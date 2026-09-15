"""Behavioral contracts for the skill-led pipeline and delivery boundary."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from content.freshness import Freshness
from editor.policy import load_policy
from codex_pipeline.models import Draft, Research
from codex_pipeline.runtime import validate
from codex_pipeline.rendering import render
from codex_pipeline.agent import strict_schema
import briefing


class CodexPipelineTests(unittest.TestCase):
    def setUp(self):
        tz = ZoneInfo('America/New_York')
        self.fresh = Freshness(datetime(2026,9,14,6,tzinfo=tz),datetime(2026,9,15,6,tzinfo=tz))
        self.sources = {'a': {'source_id':'a','published_at':'2026-09-14T12:00:00-04:00',
            'date_verified':True, 'url':'https://example.org/study',
            'article':'Researchers reported an eighteen percent decrease in beef purchases.'}}
        self.draft = Draft.model_validate({'edition': {'subject':'Hospital study', 'stories': [{
            'development_ids':['event-a'], 'headline':'New hospital study', 'brief':False,
            'image_description':'Conceptual hospital dining room', 'image_caption':'Conceptual scene.',
            'paragraphs':[{'text':'The researchers reported a decrease in purchases.', 'kind':'reporting',
                'citations':[{'source_id':'a','quote':'Researchers reported an eighteen percent decrease', 'link_text':'researchers'}]}]}],
            'market_notes':[]}, 'developments':[{'source_id':'event-a','evidence_source_id':'a',
                'evidence_quote':'Researchers reported an eighteen percent decrease', 'announcement_date':'2026-09-14',
                'event_key':'hospital-study-2026', 'title':'Hospital study', 'topic':'Vegan Movement'}], 'omissions':[]})

    def check(self, **kw):
        return validate(self.draft, self.sources, ['a'], kw.get('history',[]), self.fresh, load_policy(),kw.get('chart_data',{}))

    def test_group_history_blocks_event_but_no_personal_history(self):
        self.assertGreater(self.check(), 0)
        with self.assertRaisesRegex(ValueError,'group-delivered'):
            self.check(history=[{'event_key':'HOSPITAL-STUDY-2026'}])

    def test_dates_quotes_and_links_are_enforced(self):
        self.sources['a']['published_at']='2026-09-15T06:00:00-04:00'
        with self.assertRaisesRegex(ValueError,'outside'):
            self.check()
        self.sources['a']['published_at']='2026-09-14T12:00:00-04:00'
        self.draft.edition.stories[0].paragraphs[0].citations[0].quote='An invented source quotation'
        with self.assertRaisesRegex(ValueError,'Quotation'):
            self.check()

    def test_chart_commentary_counts_toward_total(self):
        self.draft.edition.market_notes=[{'key':'bynd-chart','text':'word '*900}]
        self.draft=Draft.model_validate(self.draft.model_dump())
        with self.assertRaisesRegex(ValueError,'words'):
            self.check(chart_data={'bynd-chart':{}})

    def test_missing_chart_commentary_rejected(self):
        with self.assertRaisesRegex(ValueError,'each available chart'):
            self.check(chart_data={'bynd-chart':{}})

    def test_narrative_links_escape_text_and_preserve_url(self):
        self.draft.edition.stories[0].headline='<script>alert(1)</script>'
        html=render(self.draft.edition,self.sources,{}, {},'{newsletter_content}')
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertIn('href="https://example.org/study"',html)
        self.assertNotIn('Why it matters',html)

    def test_wire_schema_has_all_required_fields(self):
        schema=strict_schema(Draft)
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertFalse(schema['additionalProperties'])

    def test_personal_send_never_updates_group_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); state=root/'state';state.mkdir(); preview=root/'preview';preview.mkdir()
            (state/'history.json').write_text('[]')
            html='Approved newsletter'
            (preview/'newsletter.html').write_text(html)
            review=json.dumps({'approved':True}).encode()
            (preview/'final-review.json').write_bytes(review)
            payload={'pipeline':'codex','subject':'Hospital study','selected':[{'event_key':'hospital-study-2026'}],
                     'images':{},'html_sha256':hashlib.sha256(html.encode()).hexdigest(),
                     'review_sha256':hashlib.sha256(review).hexdigest(),'edition_date':'2026-09-15'}
            (preview/'delivery.json').write_text(json.dumps(payload))
            with patch.object(briefing,'STATE',state),patch.object(briefing,'GOOGLE_USERNAME','jay@example.org'),patch.object(briefing,'send_email',return_value=True) as send:
                briefing.deliver(preview,everyone=False)
                self.assertEqual(json.loads((state/'history.json').read_text()),[])
                self.assertFalse(send.call_args.args[2])
                briefing.deliver(preview,everyone=True)
                self.assertEqual(briefing.load_history()[0]['event_key'],'hospital-study-2026')
                with self.assertRaises(ValueError):
                    briefing.deliver(preview,everyone=True)

    def test_unavailable_research_does_not_become_empty_news(self):
        from codex_pipeline.runtime import collect_public
        with tempfile.TemporaryDirectory() as tmp, patch('codex_pipeline.runtime.run_agent', return_value=Research(research_completed=False, leads=[], coverage_note='Tools unavailable')):
            with self.assertRaisesRegex(RuntimeError,'could not complete'):
                collect_public(self.fresh,load_policy(),Path(tmp))

    def test_default_generation_never_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('sys.argv',['main.py','--pipeline','codex']), patch.object(briefing,'ROOT',root), patch.object(briefing,'STATE',root/'state'), patch.object(briefing,'setup_logging'), patch('codex_pipeline.runtime.make_preview') as make, patch.object(briefing,'deliver') as send:
                briefing.setup_logging.return_value=(None,None)
                briefing.run()
                make.assert_called_once()
                send.assert_not_called()

    def test_changed_review_cannot_authorize_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'delivery.json').write_text(json.dumps({'pipeline':'codex','review_sha256':'wrong'}))
            (p/'final-review.json').write_text('{"approved":true}')
            with patch.object(briefing,'send_email') as send, self.assertRaises(ValueError):
                briefing.deliver(p)
            send.assert_not_called()


if __name__=='__main__':
    unittest.main()
