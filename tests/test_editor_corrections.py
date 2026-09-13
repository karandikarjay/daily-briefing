import unittest
from unittest.mock import patch
from test_editor import source, development, edition, START, END, QUOTE
from content.freshness import Freshness
from content.verification import select_verified, Selection, Candidate, QuoteRepair, Verdict, Verdicts
from editor.models import Action, CoverageReview, Review
from editor.policy import load_policy
from editor.research import review_coverage
from editor.composition import compose_edition
from editor.rendering import render_edition, CHART_TITLES


class Corrections(unittest.TestCase):
    def candidate(self, quote=QUOTE):
        return Candidate(source_id='a', title='New evaluation', description=QUOTE,
                         evidence_quote=quote, event_key='evaluation-a', verification_query='public report')

    def verdict(self):
        return Verdicts(verdicts=[Verdict(candidate_source_id='a', accepted=True, topic_matches=True,
            evidence_source_id='a', evidence_quote=QUOTE, announcement_date='2026-09-07',
            event_key='evaluation-a', reason='New firsthand report')])

    def test_quote_repair_preserves_event_and_strict_validation(self):
        replies=[Selection(news_items=[self.candidate('A paraphrase of the announcement')], reason='Relevant'),
                 QuoteRepair(quote=QUOTE, reason='Exact source sentence'), self.verdict()]
        with patch('content.verification.ask', side_effect=replies) as ask:
            selected, audit=select_verified(None,None,{'title':'Vegan Movement','prompt':'advocacy'},
                [source(private=True)],Freshness(START,END),[],focus_quote=QUOTE)
        self.assertEqual(selected[0]['event_key'],'evaluation-a')
        self.assertEqual(ask.call_args.args[4]['intended_development_quote'],QUOTE)
        self.assertTrue(any(d['reason']=='quote_repair' for d in audit))
        replies[1]=QuoteRepair(quote='Still an invented quotation',reason='bad')
        with patch('content.verification.ask',side_effect=replies):
            selected,audit=select_verified(None,None,{'title':'Vegan Movement','prompt':'advocacy'},
                [source(private=True)],Freshness(START,END),[],focus_quote=QUOTE)
        self.assertFalse(selected)
        self.assertEqual(audit[-1]['reason'],'invalid_source_or_quote')

    def test_empty_selection_rechecked_with_explanation(self):
        with patch('content.verification.ask',side_effect=[Selection(news_items=[],reason='Missed report'),
                Selection(news_items=[self.candidate()],reason='New report found'),self.verdict()]):
            selected,audit=select_verified(None,None,{'title':'Vegan Movement','prompt':'advocacy'},
                [source(private=True)],Freshness(START,END),[],focus_quote='')
        self.assertEqual(len(selected),1)
        self.assertEqual(audit[1]['reason'],'selection_recheck')

    def test_private_focus_cannot_enter_public_verification(self):
        with patch('content.verification.ask') as ask:
            selected,audit=select_verified(None,None,{'title':'AI','prompt':'AI'},[source()],
                Freshness(START,END),[],focus_quote='SECRET private email context')
        ask.assert_not_called()
        self.assertEqual(audit[0]['reason'],'invalid_focus_quote')

    def test_coverage_recovers_candidate_without_exporting_private_reason(self):
        fresh=Freshness(START,END)
        review=CoverageReview(adequate=False,reason='Missed candidate',followups=[
            Action(tool='verify',source_id='a',topic='AI',reason='SECRET private email',focus_quote=QUOTE)])
        with patch('editor.research.ask',return_value=review), patch('editor.research.select_verified',
                return_value=([development(topic='AI')],[])) as verify:
            extra,_=review_coverage(None,None,{'a':source()},[],fresh,
                [{'title':'SECRET private email'}],load_policy(),[],[])
        self.assertEqual(len(extra),1)
        self.assertNotIn('SECRET',str(verify.call_args))
        self.assertTrue(any(d['stage']=='coverage_outcome' for d in fresh.pipeline_audit))

    def test_missing_image_prompt_restored_before_review(self):
        with patch('editor.composition.ask',side_effect=[edition(),Review(approved=True,issues=[],rejected_development_ids=[])]):
            draft,_,_=compose_edition(None,None,[development()],Freshness(START,END),load_policy())
        self.assertTrue(draft.stories[0].image_description)

    def test_regular_footer_independent_of_editor_chart_choices(self):
        html=render_edition('<html>{newsletter_content}</html>',edition(),[development()],
                            {k:'image.png' for k in CHART_TITLES})
        for k in CHART_TITLES:
            self.assertIn('cid:'+k,html)
        self.assertIn('Markets and prices',html)
