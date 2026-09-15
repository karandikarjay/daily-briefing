"""Editorial behavior, privacy boundaries, evidence repairs and delivery regressions."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from content.freshness import Freshness
from editor.composition import compose_edition, validate_edition, evidence_context, apply_repairs
from editor.models import Action, Citation, Edition, Omission, Paragraph, PublicQuery, Review, Story, Chart, Repairs, ParagraphEdit
from editor.policy import load_policy
from editor.rendering import render_edition, word_count, source_label
from editor.research import public_research, research_developments

ET = ZoneInfo('America/New_York')
START = datetime(2026, 9, 7, 6, tzinfo=ET)
END = datetime(2026, 9, 8, 6, tzinfo=ET)
QUOTE = 'The organization published its new intervention evaluation today.'


def source(sid='a', private=False):
    return {'source_id': sid, 'source_type': 'email' if private else 'article',
            'title': 'Evaluation published', 'subject': 'Private evaluation' if private else '',
            'source_name': 'Example', 'url': None if private else 'https://example.com/' + sid,
            'article': '' if private else QUOTE, 'body': QUOTE if private else '',
            'date_verified': True, 'date_reason': 'publication_in_window', 'date_evidence': [],
            'published_at': '2026-09-07T12:00:00Z'}


def development(sid='a', private=False, topic='Vegan Movement'):
    return {'source_id': sid, 'evidence_source_id': sid, 'event_key': 'evaluation-' + sid,
            'title': 'New evaluation', 'description': QUOTE, 'topic': topic,
            'published_at': '2026-09-07T12:00:00Z', 'announcement_date': '2026-09-07',
            'source_name': 'Example', 'source_type': 'email' if private else 'article',
            'source_link': None if private else 'https://example.com/' + sid,
            'evidence_quote': QUOTE, 'evidence_text': QUOTE,
            'evidence_sources': [source(sid, private)]}


def story(sid='a'):
    return Story(development_ids=[sid], headline='New intervention evaluation',
        paragraphs=[Paragraph(label='What changed', text=QUOTE,
                    citations=[Citation(source_id=sid, quote=QUOTE)])])


def edition(*ids):
    return Edition(subject='New evidence on interventions', stories=[story(sid) for sid in (ids or ('a',))])


class Recovery(unittest.TestCase):
    def test_recovery_rewrites_with_all_feedback_and_excludes_rejected_events(self):
        from editor.runtime import compose_with_recovery
        from editor.composition import EditionReviewError
        failed = EditionReviewError([
            {'issues': ['Old event'], 'rejected_development_ids': ['a']},
            {'issues': ['Attribute headline'], 'rejected_development_ids': []}], edition().model_dump())
        with tempfile.TemporaryDirectory() as tmp, patch('editor.runtime.compose_edition', side_effect=[
                failed, (edition('b'), [development('b')], {'approved': True, 'reviews': []})]) as compose:
            result, selected, review = compose_with_recovery(None, None,
                [development(), development('b')], Freshness(START, END), load_policy(), [], Path(tmp))
            self.assertTrue((Path(tmp) / 'normal-rejected-draft.json').exists())
        self.assertEqual([d['source_id'] for d in compose.call_args.args[2]], ['b'])
        self.assertEqual(compose.call_args.kwargs['recovery_issues'], ['Old event', 'Attribute headline'])
        self.assertEqual(compose.call_args.args[4].target_words, 400)
        self.assertEqual(review['removed_developments'], ['a'])
        self.assertTrue(review['approved'])
        self.assertTrue(review['recovery_used'])
        self.assertEqual(selected[0]['source_id'], 'b')

    def test_persistent_rejection_delivers_only_notice_and_preserves_history(self):
        from editor.runtime import make_preview
        from briefing import deliver
        policy = load_policy().model_copy(update={'max_repairs': 0})
        rejection = Review(approved=False, issues=['Unsupported reporting'], rejected_development_ids=[])
        with tempfile.TemporaryDirectory() as tmp:
            root, fresh = Path(tmp), Freshness(START, END)
            preview = root / 'preview'
            history = [{'event_key': 'previously-delivered'}]
            (root / 'history.json').write_text(json.dumps(history))
            with patch('editor.runtime.research_developments', return_value=([development()], [])), \
                    patch('editor.composition.ask', side_effect=[edition(), rejection, edition(), rejection]) as ask, \
                    patch('editor.runtime.generate_media') as media, patch('briefing.STATE', root), \
                    patch('briefing.GOOGLE_USERNAME', 'sender@example.com'), \
                    patch('briefing.send_email', return_value=True) as smtp:
                make_preview(None, None, {}, fresh, history, policy, preview, '{newsletter_content}')
                deliver(preview, everyone=True)
                self.assertEqual(ask.call_count, 4)
                media.assert_not_called()
                sent_html = smtp.call_args.args[0]
                self.assertIn('could not be completed', sent_html)
                self.assertNotIn(QUOTE, sent_html)
                self.assertEqual(json.loads((root / 'history.json').read_text()), history)
            payload = json.loads((preview / 'delivery.json').read_text())
            self.assertTrue(payload['service_notice'])
            self.assertEqual(payload['selected'], [])
            review = json.loads((preview / 'final-review.json').read_text())
            self.assertFalse(review['approved'])
            self.assertEqual([r['phase'] for r in review['reviews']], ['normal', 'recovery'])
            self.assertTrue((preview / 'recovery-rejected-draft.json').exists())

    def test_recovery_is_independently_reviewed_before_delivery(self):
        from editor.runtime import compose_with_recovery
        policy = load_policy().model_copy(update={'max_repairs': 0})
        with tempfile.TemporaryDirectory() as tmp, patch('editor.composition.ask', side_effect=[
                edition(), Review(approved=False, issues=['Fix headline'], rejected_development_ids=[]),
                edition(), Review(approved=True, issues=[], rejected_development_ids=[])]) as ask:
            _, selected, review = compose_with_recovery(None, None, [development()],
                Freshness(START, END), policy, [], Path(tmp))
        self.assertTrue(ask.call_args.kwargs['independent'])
        self.assertTrue(review['approved'])
        self.assertEqual(len(review['reviews']), 2)
        self.assertEqual(len(selected), 1)


class Composition(unittest.TestCase):
    def setUp(self):
        self.fresh = Freshness(START, END)
        self.policy = load_policy()

    def test_multiple_same_topic_stories_keep_editor_order(self):
        items = [development('a'), development('b')]
        result = validate_edition(edition('b', 'a'), items, self.fresh, self.policy)
        self.assertEqual([i['source_id'] for i in result], ['b', 'a'])

    def test_unknown_sources_and_fabricated_quotes_fail(self):
        for sid, quote in [('unknown', QUOTE), ('a', 'The organization saved a million animals today.')]:
            draft = edition()
            draft.stories[0].paragraphs[0].citations = [Citation(source_id=sid, quote=quote)]
            with self.assertRaises(ValueError):
                validate_edition(draft, [development()], self.fresh, self.policy)

    def test_all_invalid_quotes_reported_in_one_repair(self):
        draft = edition('a', 'b')
        for item in draft.stories:
            item.paragraphs[0].citations[0].quote = 'A fabricated quote, not found in the source.'
        with self.assertRaises(ValueError) as exc:
            validate_edition(draft, [development(), development('b')], self.fresh, self.policy)
        self.assertIn('story 0, paragraph 0', str(exc.exception))
        self.assertIn('story 1, paragraph 0', str(exc.exception))

    def test_cannot_cite_an_unrelated_developments_evidence(self):
        draft = edition('a', 'b')
        draft.stories[0].paragraphs[0].citations[0].source_id = 'b'
        with self.assertRaises(ValueError):
            validate_edition(draft, [development('a'), development('b')], self.fresh, self.policy)

    def test_history_context_allowed_but_future_context_blocked(self):
        item = development()
        old = source('old') | {'published_at': '2025-01-01T12:00:00Z', 'date_verified': False,
                               'date_reason': 'publication_out_of_window'}
        item['evidence_sources'].append(old)
        draft = edition()
        draft.stories[0].paragraphs[0].citations = [Citation(source_id='old', quote=QUOTE)]
        validate_edition(draft, [item], self.fresh, self.policy)
        old['published_at'] = '2026-09-09T12:00:00Z'
        with self.assertRaises(ValueError):
            validate_edition(draft, [item], self.fresh, self.policy)

    def test_old_development_and_duplicate_events_blocked(self):
        old = development() | {'published_at': '2025-01-01T12:00:00Z'}
        with self.assertRaises(ValueError):
            validate_edition(edition(), [old], self.fresh, self.policy)
        with self.assertRaises(ValueError):
            validate_edition(edition('a', 'b'), [development(), development('b') | {'event_key': 'evaluation-a'}], self.fresh, self.policy)

    def test_missing_verified_anchor_cannot_be_replaced_by_context(self):
        item = development()
        item['evidence_source_id'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'anchor'):
            validate_edition(edition(), [item], self.fresh, self.policy)

    def test_large_evidence_keeps_citation_context_and_original_snapshot(self):
        item = development()
        item['evidence_sources'][0]['article'] = 'Background. ' * 5000 + QUOTE + ' Closing. ' * 5000
        original = json.dumps(item)
        with patch('editor.composition.num_tokens_from_string', side_effect=len):
            compact = evidence_context([item], edition(), budget=12000)
        self.assertLess(len(json.dumps(compact)), 12000)
        self.assertIn(QUOTE, compact[0]['evidence_sources'][0]['article'])
        self.assertTrue(compact[0]['evidence_sources'][0]['excerpted'])
        self.assertEqual(json.dumps(item), original)

    def test_word_ceiling_includes_intro_captions_and_sources(self):
        draft = edition()
        draft.intro = 'word ' * 800
        self.assertGreater(word_count(draft, [development()]), 800)
        with self.assertRaises(ValueError):
            validate_edition(draft, [development()], self.fresh, self.policy)

    def test_every_omission_explained_and_media_tied_to_selected_news(self):
        items = [development(), development('b')]
        draft = edition()
        with self.assertRaises(ValueError):
            validate_edition(draft, items, self.fresh, self.policy)
        draft.omissions = [Omission(development_id='b', reason='Less consequential')]
        validate_edition(draft, items, self.fresh, self.policy)
        draft.charts = [Chart(key='bynd-chart', development_id='b', reason='Related')]
        with self.assertRaises(ValueError):
            validate_edition(draft, items, self.fresh, self.policy)

    def test_entire_edition_review_repairs_intro_without_formula(self):
        bad, good = edition(), edition()
        bad.intro = 'Unsupported claim'
        good.intro = 'New evidence on intervention effectiveness.'
        with patch('editor.composition.ask', side_effect=[bad,
                Review(approved=False, issues=['Unsupported intro'], rejected_development_ids=[]), Repairs(intro=good.intro),
                Review(approved=True, issues=[], rejected_development_ids=[])]) as ask:
            result, selected, review = compose_edition(None, None, [development()], self.fresh, self.policy)
        self.assertEqual(result.intro, good.intro)
        self.assertEqual(len(review['reviews']), 2)
        self.assertIn('Unsupported intro', ask.call_args_list[2].args[-1]['issues'])
        self.assertEqual(len(selected), 1)

    def test_targeted_repairs_preserve_untouched_stories_and_original(self):
        original = edition('a', 'b')
        changed = story('a').paragraphs[0].model_copy(update={'text': 'A corrected description.'})
        repaired = apply_repairs(original, Repairs(paragraphs=[ParagraphEdit(story_index=0, paragraph_index=0, paragraph=changed)]))
        self.assertEqual(repaired.stories[1].model_dump(), original.stories[1].model_dump())
        self.assertEqual(original.stories[0].paragraphs[0].text, QUOTE)
        self.assertEqual(repaired.stories[0].paragraphs[0].text, 'A corrected description.')

    def test_rejected_event_removed_and_survivor_rewritten(self):
        with patch('editor.composition.ask', side_effect=[edition('a', 'b'),
                Review(approved=False, issues=['a is an old event'], rejected_development_ids=['a']), Repairs(),
                Review(approved=True, issues=[], rejected_development_ids=[])]):
            result, selected, review = compose_edition(None, None, [development(), development('b')], self.fresh, self.policy)
        self.assertEqual([s['source_id'] for s in selected], ['b'])
        self.assertEqual(review['removed_developments'], ['a'])

    def test_persistent_review_failure_aborts(self):
        self.policy.max_repairs = 1
        with patch('editor.composition.ask', side_effect=[edition(), Review(approved=False, issues=['Unsupported'], rejected_development_ids=[]), Repairs(), Review(approved=False, issues=['Unsupported'], rejected_development_ids=[])]):
            with self.assertRaisesRegex(ValueError, 'repair budget'):
                compose_edition(None, None, [development()], self.fresh, self.policy)

    def test_structural_failure_repaired_before_semantic_review(self):
        bad = edition()
        bad.stories[0].paragraphs[0].citations[0].quote = 'This fabricated quote is not in the evidence.'
        repairs = Repairs(paragraphs=[ParagraphEdit(story_index=0, paragraph_index=0, paragraph=story().paragraphs[0])],
                          addressed_issue_ids=['citation-0-0'])
        with patch('editor.composition.ask', side_effect=[bad, repairs, Review(approved=True, issues=[], rejected_development_ids=[])]):
            _, _, review = compose_edition(None, None, [development()], self.fresh, self.policy)
        self.assertEqual(review['reviews'][0]['stage'], 'structural_review')

    def test_render_escapes_model_html_omits_empty_sections_and_market_footer(self):
        draft = edition()
        draft.intro = '<script>bad()</script>'
        output = render_edition('<html>{newsletter_content}<div class="financial-section">Markets</div></html>', draft, [development()], {})
        self.assertNotIn('<script>', output)
        self.assertIn('&lt;script&gt;', output)
        self.assertNotIn('Markets', output)
        self.assertNotIn('Alternative Protein', output)
        self.assertIn('Sep 07, 2026', output)
        self.assertNotIn('12:00', output)

    def test_private_attribution_decodes_email_headers(self):
        label = source_label({'source_type': 'email', 'email_sender': '=?UTF-8?Q?Eva_Hemmerov=C3=A1_via_FAST?= <list@example.com>', 'subject': 'New evaluation'})
        self.assertEqual(label, 'Eva Hemmerová via FAST: New evaluation')


class Research(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy()
        self.fresh = Freshness(START, END)
        self.policy.coverage_followups = 0

    def test_private_research_request_blocked_and_budget_enforced(self):
        self.policy.max_actions = 2
        with patch('editor.research.ask', return_value=Action(tool='research', source_id='private', reason='Search private details')), patch('editor.research.public_research') as search:
            selected, _ = research_developments(None, None, {'Vegan Movement': [source('private', True)]}, self.fresh, [], self.policy)
        search.assert_not_called()
        self.assertEqual(selected, [])
        self.assertTrue(any(t.get('reason') == 'action_budget_exhausted' for t in self.fresh.pipeline_audit))

    def test_public_query_context_excludes_editor_reason_and_private_history(self):
        self.policy.max_actions = 1
        with patch('editor.research.ask', return_value=Action(tool='research', source_id='public', topic='AI', reason='SECRET private content')), \
             patch('editor.research.public_research', return_value=([], {'query': 'public query', 'reason': 'search_completed', 'result_count': 0})) as search:
            research_developments(None, None, {'AI': [source('public')], 'Vegan Movement': [source('private', True)]}, self.fresh,
                                  [{'source_id': 'history', 'title': 'SECRET private content'}], self.policy)
        self.assertNotIn('SECRET', str(search.call_args))
        self.assertNotIn('private', str(search.call_args))

    def test_verification_gets_public_history_only(self):
        actions = [Action(tool='verify', source_id='public', topic='AI', reason='Important'), Action(tool='finish', reason='Enough')]
        with patch('editor.research.ask', side_effect=actions), patch('editor.research.select_verified', return_value=([development('public', topic='AI')], [])) as verify:
            items, _ = research_developments(None, None, {'AI': [source('public')]}, self.fresh,
                [{'source_id': 'old', 'title': 'SECRET email', 'source_link': None}], self.policy)
        self.assertEqual(verify.call_args.args[5], [])
        self.assertEqual(len(items), 1)

    def test_two_same_topic_candidates_can_be_verified(self):
        actions = [Action(tool='verify', source_id=sid, topic='AI', reason='Important') for sid in ('a', 'b')]
        actions.append(Action(tool='finish', reason='Enough'))
        with patch('editor.research.ask', side_effect=actions), patch('editor.research.select_verified', side_effect=[([development('a', topic='AI')], []), ([development('b', topic='AI')], [])]):
            items, _ = research_developments(None, None, {'AI': [source('a'), source('b')]}, self.fresh, [], self.policy)
        self.assertEqual(len(items), 2)

    def test_same_event_coverage_merges_supporting_sources(self):
        actions = [Action(tool='verify', source_id=sid, reason='Important') for sid in ('a', 'b')]
        actions.append(Action(tool='finish', reason='Enough'))
        second = development('b') | {'event_key': 'evaluation-a'}
        with patch('editor.research.ask', side_effect=actions), patch('editor.research.select_verified', side_effect=[([development()], []), ([second], [])]):
            items, _ = research_developments(None, None, {'AI': [source('a'), source('b')]}, self.fresh, [], self.policy)
        self.assertEqual(len(items), 1)
        self.assertEqual({s['source_id'] for s in items[0]['evidence_sources']}, {'a', 'b'})

    def test_research_after_verification_retains_conflicting_old_evidence(self):
        actions = [Action(tool='verify', source_id='a', reason='Important'),
                   Action(tool='research', source_id='a', reason='Check limitations'),
                   Action(tool='finish', reason='Enough')]
        old = source('old') | {'date_verified': False, 'date_reason': 'publication_out_of_window',
                               'published_at': '2025-01-01T12:00:00Z'}
        with patch('editor.research.ask', side_effect=actions), patch('editor.research.select_verified', return_value=([development()], [])), patch('editor.research.public_research', return_value=([old], {'query': 'original report', 'reason': 'search_completed', 'result_count': 1})):
            items, _ = research_developments(None, None, {'AI': [source()]}, self.fresh, [], self.policy)
        self.assertIn('old', {s['source_id'] for s in items[0]['evidence_sources']})

    def test_verification_and_wall_time_budgets_stop_work(self):
        self.policy.max_actions = 2
        self.policy.max_verifications = 1
        actions = [Action(tool='verify', source_id=sid, reason='Important') for sid in ('a', 'b')]
        with patch('editor.research.ask', side_effect=actions), patch('editor.research.select_verified', return_value=([], [])) as verify:
            research_developments(None, None, {'AI': [source('a'), source('b')]}, self.fresh, [], self.policy)
        self.assertEqual(verify.call_count, 1)
        with patch('editor.research.time.monotonic', side_effect=[0, 901, 902]), patch('editor.research.ask') as ask:
            research_developments(None, None, {}, Freshness(START, END), [], self.policy)
        ask.assert_not_called()

    def test_search_budget_and_failures_are_visible(self):
        self.policy.max_actions = 3
        self.policy.max_searches = 1
        with patch('editor.research.ask', return_value=Action(tool='research', topic='AI', reason='Investigate')), \
             patch('editor.research.public_research', return_value=([], {'query': 'q', 'reason': 'search_failed', 'result_count': 0})) as search:
            research_developments(None, None, {}, self.fresh, [], self.policy)
        self.assertEqual(search.call_count, 1)
        self.assertTrue(any(t.get('result') == 'search_budget_exhausted' for t in self.fresh.pipeline_audit))

    def test_no_public_search_when_verifying_private_email(self):
        with self.assertRaises(ValueError):
            public_research(None, None, 'AI', source('mail', True), self.policy, self.fresh, [])

    def test_public_research_fetches_and_checks_publisher_dates(self):
        with patch('editor.research.ask', return_value=PublicQuery(query='new evaluation')), patch('editor.research.TAVILY_API_KEY', 'test'), patch('tavily.TavilyClient') as search, patch.object(self.fresh, 'inspect', return_value=source()) as inspect:
            search.return_value.search.return_value = {'results': [{'url': 'https://example.com/a', 'content': QUOTE}]}
            records, audit = public_research(None, None, 'Vegan Movement', None, self.policy, self.fresh, [])
        inspect.assert_called_once()
        self.assertTrue(records[0]['date_verified'])
        self.assertEqual(audit['reason'], 'search_completed')


class Runtime(unittest.TestCase):
    def test_independent_review_uses_alternate_provider_without_primary_call(self):
        from types import SimpleNamespace
        from content.verification import ask
        primary, alternate = MagicMock(), MagicMock()
        verdict = Review(approved=True, issues=[], rejected_development_ids=[])
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=verdict))])
        with patch('content.verification.call_openai_structured', return_value=response) as call:
            result = ask(primary, alternate, Review, 'Check evidence', {'evidence': 'Göttingen: €2.6 million'}, independent=True)
        self.assertIs(call.call_args.args[0], alternate)
        primary.messages.create.assert_not_called()
        self.assertTrue(result.approved)
        self.assertIn('Göttingen: €2.6 million', call.call_args.args[1][1]['content'])
        self.assertNotIn('\\u20ac', call.call_args.args[1][1]['content'])

    def test_regular_charts_generated_and_stale_chart_omitted(self):
        from editor.runtime import generate_media
        from editor.rendering import CHART_TITLES
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {k + '.png': str(root / (k + '.png')) for k in CHART_TITLES}
            for path in paths.values():
                Path(path).write_bytes(b'old')
                os.utime(path, (1, 1))
            with patch('main.generate_images', return_value={}), patch('charts.create_charts') as charts, patch('charts.get_beyond_meat_bond_chart') as bond, patch('charts.extract_egg_price_chart') as egg, patch('editor.runtime.CHART_PATHS', paths):
                self.assertEqual(generate_media(None, edition(), root), {})
                charts.assert_called_once()
                bond.assert_called_once()
                egg.assert_called_once()

    def test_editor_models_use_native_json_schema_and_keep_local_constraints(self):
        from types import SimpleNamespace
        from utils.api_utils import call_claude_parse_with_backoff
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type='text', text='{"tool":"finish","reason":"Enough"}')],
            stop_reason='end_turn', usage=SimpleNamespace(input_tokens=10, output_tokens=5))
        result = call_claude_parse_with_backoff(client, [{'role': 'user', 'content': 'test'}], Action)
        self.assertEqual(result.choices[0].message.parsed.tool, 'finish')
        config = client.messages.create.call_args.kwargs['output_config']
        self.assertEqual(config['format']['type'], 'json_schema')
        self.assertFalse(config['format']['schema']['additionalProperties'])
        self.assertNotIn('maxLength', config['format']['schema']['properties']['reason'])
        client.messages.create.return_value.content[0].text = json.dumps({'tool': 'finish', 'reason': 'x' * 1201})
        with self.assertRaises(ValueError):
            call_claude_parse_with_backoff(client, [{'role': 'user', 'content': 'test'}], Action)

    def test_default_editor_dry_run_never_sends_or_updates_delivery_history(self):
        import briefing
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / 'template.html'
            template.write_text('<html>{newsletter_content}</html>')
            with patch('sys.argv', ['main.py', '--dry-run']), patch('briefing.ROOT', root), patch('briefing.STATE', root / 'state'), patch('briefing.TEMPLATE_PATH', str(template)), patch('briefing.setup_logging', return_value=(MagicMock(), MagicMock())), patch('briefing.get_content', return_value=[]), patch('briefing.Anthropic'), patch('briefing.OpenAI'), patch('editor.runtime.research_developments', return_value=([], [])), patch('editor.runtime.generate_media', return_value={}), patch('briefing.send_email') as send:
                briefing.run()
            send.assert_not_called()
            output = next((root / 'previews').glob('*/newsletter.html')).read_text()
            self.assertNotIn('class="story-header"', output)
            self.assertIn('passed selection', output)
            self.assertFalse((root / 'state/history.json').exists())

    def test_replay_cannot_be_sent_and_modified_image_blocks_delivery(self):
        from briefing import deliver
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'delivery.json').write_text(json.dumps({'replay_only': True}))
            with self.assertRaisesRegex(ValueError, 'cannot be sent'):
                deliver(path)
            image = path / 'image.png'
            image.write_bytes(b'changed')
            (path / 'delivery.json').write_text(json.dumps({'images': {'a': str(image)}, 'image_sha256': {'a': hashlib.sha256(b'original').hexdigest()}}))
            with self.assertRaisesRegex(ValueError, 'image changed'):
                deliver(path)

    def test_replay_requires_explicit_dry_run(self):
        from briefing import run
        with patch('sys.argv', ['main.py', '--replay-evidence', '/tmp/evidence.json']):
            with self.assertRaises(SystemExit):
                run()

    def test_failure_saves_private_audit_without_sendable_payload(self):
        from editor.runtime import make_preview
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('editor.runtime.research_developments', return_value=([development()], [])), patch('editor.runtime.compose_edition', side_effect=ValueError('review failed')), patch('briefing.STATE', root):
                with self.assertRaises(ValueError):
                    make_preview(None, None, {}, Freshness(START, END), [], load_policy(), root / 'preview', '{newsletter_content}')
            self.assertTrue((root / 'preview/audit.json').exists())
            self.assertFalse((root / 'preview/delivery.json').exists())

    def test_final_rejections_persist_but_evidence_replay_does_not_write_state(self):
        from editor.runtime import make_preview
        from editor.composition import empty_edition
        verdict = {'approved': True, 'reviews': [{'rejected_development_ids': ['a'], 'issues': ['Outside scope']}], 'word_count': 0}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('editor.runtime.research_developments', return_value=([development()], [])), patch('editor.runtime.compose_edition', return_value=(empty_edition(), [], verdict)), patch('editor.runtime.generate_media', return_value={}), patch('briefing.remember_rejections') as remember:
                decisions = make_preview(None, None, {}, Freshness(START, END), [], load_policy(), root / 'live', '{newsletter_content}')
                self.assertEqual(decisions[-1]['stage'], 'final_review_rejection')
                self.assertEqual(remember.call_args.args[0][-1]['candidate']['source_id'], 'a')
                remember.reset_mock()
                make_preview(None, None, {}, Freshness(START, END), [], load_policy(), root / 'replay', '{newsletter_content}', replay=[development()])
                remember.assert_not_called()


if __name__ == '__main__':
    unittest.main()
