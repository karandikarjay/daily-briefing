"""Editorial degradation and delivery watchdog regressions; no external calls."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from test_editor import edition, development, Freshness, START, END, ET, load_policy
from editor.models import ImageEdit, Repairs, Review, ReviewIssue, Omission, ParagraphEdit, StoryEdit
from editor.composition import apply_repairs, compose_edition, EditionReviewError, validate_edition, CitationReviewError
from editor.runtime import compose_with_recovery
from editor.salvage import shorten_failed_draft
from check_delivery import check_delivery
from run_status import ProductionRun


def finding(field='paragraph', index=0, category='factual'):
    return ReviewIssue(id='issue-1', field=field, story_index=index,
                       paragraph_index=0 if field == 'paragraph' else None,
                       category=category, detail='Unsupported claim')


def rejected(issue):
    return Review(approved=False, issues=[issue.detail], findings=[issue], rejected_development_ids=[])


def failed(draft, issue):
    return EditionReviewError([{'stage': 'edition_review', **rejected(issue).model_dump()}], draft.model_dump())


class EditorialResilience(unittest.TestCase):
    def test_caption_can_be_repaired_without_changing_story(self):
        draft = edition()
        draft.stories[0].image_caption = 'Unsupported organization description'
        result = apply_repairs(draft, Repairs(images=[ImageEdit(story_index=0,
            image_caption='Conceptual illustration.', image_description='Abstract shapes')]))
        self.assertEqual(result.stories[0].image_caption, 'Conceptual illustration.')
        self.assertEqual(result.stories[0].paragraphs, draft.stories[0].paragraphs)
        self.assertEqual(draft.stories[0].image_caption, 'Unsupported organization description')

    def test_noop_repair_does_not_spend_independent_review_call(self):
        policy = load_policy().model_copy(update={'max_repairs': 1})
        with patch('editor.composition.ask', side_effect=[edition(), rejected(finding()),
                Repairs(addressed_issue_ids=['issue-1'])]) as ask:
            with self.assertRaises(EditionReviewError) as caught:
                compose_edition(None, None, [development()], Freshness(START, END), policy)
        self.assertEqual(ask.call_count, 3)
        self.assertEqual(caught.exception.reviews[-1]['stage'], 'repair_check')

    def test_pruning_preserves_good_story_and_requires_independent_approval(self):
        bad = failed(edition('a', 'b'), finding())
        with tempfile.TemporaryDirectory() as tmp, patch('editor.runtime.compose_edition',
                side_effect=[bad, bad, (edition('b'), [development('b')], {'approved': True, 'reviews': []})]) as compose:
            result, selected, review = compose_with_recovery(None, None, [development(), development('b')],
                Freshness(START, END), load_policy(), [], Path(tmp))
        salvaged = compose.call_args.kwargs['initial_draft']
        self.assertEqual([s.development_ids for s in salvaged.stories], [['b']])
        self.assertEqual(salvaged.stories[0].paragraphs, edition('b').stories[0].paragraphs)
        self.assertEqual([o.development_id for o in salvaged.omissions], ['a'])
        self.assertTrue(compose.call_args.kwargs['salvage'])
        self.assertEqual(compose.call_args.args[4].max_repairs, 0)
        self.assertTrue(review['approved'])
        self.assertEqual(review['delivery_kind'], 'shortened')

    def test_pruned_draft_cannot_bypass_rejection(self):
        bad = failed(edition('a', 'b'), finding())
        remaining = failed(edition('b'), finding())
        with tempfile.TemporaryDirectory() as tmp, patch('editor.runtime.compose_edition',
                side_effect=[bad, bad, remaining]):
            result, selected, review = compose_with_recovery(None, None, [development(), development('b')],
                Freshness(START, END), load_policy(), [], Path(tmp))
        self.assertFalse(review['approved'])
        self.assertTrue(review['service_notice'])
        self.assertEqual(selected, [])
        self.assertEqual(result.stories, [])

    def test_unlocalized_or_global_issues_cannot_be_silently_pruned(self):
        for reviews in ([{'issues': ['Unsupported'], 'stage': 'edition_review'}],
                        [{'issues': ['Missing caveat'], 'stage': 'edition_review',
                          'findings': [finding('edition', None).model_dump()]}]):
            self.assertIsNone(shorten_failed_draft(edition().model_dump(), reviews, [development()], set()))

    def test_caption_only_failure_keeps_story_with_neutral_caption(self):
        failure = failed(edition(), finding('image_caption'))
        draft = shorten_failed_draft(failure.draft, failure.reviews, [development()], set())
        self.assertEqual(len(draft.stories), 1)
        self.assertEqual(draft.stories[0].image_caption, 'Conceptual illustration.')

    def test_bad_quotes_withhold_only_the_affected_story(self):
        draft = edition('a', 'b')
        draft.stories[0].paragraphs[0].citations[0].quote = 'A quotation that does not occur in the evidence.'
        with self.assertRaises(CitationReviewError) as caught:
            validate_edition(draft, [development(), development('b')], Freshness(START, END), load_policy())
        review = {'stage': 'structural_review', 'issues': [str(caught.exception)],
                  'findings': [f.model_dump() for f in caught.exception.findings]}
        shortened = shorten_failed_draft(draft.model_dump(), [review], [development(), development('b')], set())
        self.assertEqual([s.development_ids for s in shortened.stories], [['b']])

    def test_quote_repair_does_not_reopen_already_changed_semantic_fields(self):
        draft = edition()
        draft.intro = 'Unsupported intro'
        intro_issue = ReviewIssue(id='intro', field='intro', category='factual', detail='Remove intro')
        bad_paragraph = draft.stories[0].paragraphs[0].model_copy(deep=True)
        bad_paragraph.citations[0].quote = 'A fabricated quote, not present in the evidence.'
        with patch('editor.composition.ask', side_effect=[draft, rejected(intro_issue),
                Repairs(intro='', paragraphs=[ParagraphEdit(story_index=0, paragraph_index=0,
                         paragraph=bad_paragraph)], addressed_issue_ids=['intro']),
                Repairs(paragraphs=[ParagraphEdit(story_index=0, paragraph_index=0,
                         paragraph=edition().stories[0].paragraphs[0])], addressed_issue_ids=['citation-0-0']),
                Review(approved=True, issues=[], rejected_development_ids=[])]):
            result, _, review = compose_edition(None, None, [development()], Freshness(START, END), load_policy())
        self.assertEqual(result.intro, '')
        self.assertTrue(review['approved'])

    def test_deadline_never_approves_unreviewed_copy(self):
        with patch('editor.composition.ask') as ask:
            with self.assertRaises(EditionReviewError):
                compose_edition(None, None, [development()], Freshness(START, END),
                                load_policy(), deadline=0)
        ask.assert_not_called()

    def test_initial_shortened_draft_goes_directly_to_independent_review(self):
        with patch('editor.composition.ask', return_value=Review(approved=True, issues=[],
                rejected_development_ids=[])) as ask:
            result, selected, review = compose_edition(None, None, [development()],
                Freshness(START, END), load_policy().model_copy(update={'max_repairs': 0}),
                initial_draft=edition(), salvage=True)
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(ask.call_args.kwargs['independent'])
        self.assertIn('Fallback presentation policy', ask.call_args.args[3])
        self.assertTrue(review['approved'])

    def test_partial_repairs_preserve_progress_for_next_attempt(self):
        draft = edition()
        draft.intro, draft.closing = 'Unsupported intro', 'Unsupported closing'
        issues = [ReviewIssue(id='intro', field='intro', category='factual', detail='Fix intro'),
                  ReviewIssue(id='closing', field='closing', category='factual', detail='Fix closing')]
        with patch('editor.composition.ask', side_effect=[draft,
                Review(approved=False, issues=['Fix intro', 'Fix closing'], findings=issues,
                       rejected_development_ids=[]),
                Repairs(intro='', addressed_issue_ids=['intro']),
                Repairs(closing='', addressed_issue_ids=['closing']),
                Review(approved=True, issues=[], rejected_development_ids=[])]) as ask:
            result, _, review = compose_edition(None, None, [development()],
                                               Freshness(START, END), load_policy())
        self.assertEqual(result.intro, '')
        self.assertEqual(result.closing, '')
        self.assertEqual(ask.call_args_list[3].args[-1]['draft']['intro'], '')
        self.assertEqual([f['id'] for f in ask.call_args_list[3].args[-1]['findings']], ['closing'])

    def test_restore_only_previously_omitted_developments(self):
        draft = edition('a')
        draft.omissions = [Omission(development_id='b', reason='Combined story removed because a related development failed review.')]
        repaired = apply_repairs(draft, Repairs(restore_stories=edition('b').stories))
        self.assertEqual([s.development_ids for s in repaired.stories], [['a'], ['b']])
        self.assertEqual(repaired.omissions, [])
        self.assertEqual(repaired.stories[0], draft.stories[0])
        for sid in ('a', 'unavailable'):
            with self.assertRaisesRegex(ValueError, 'previously omitted'):
                apply_repairs(draft, Repairs(restore_stories=edition(sid).stories))

    def test_whole_story_repair_can_add_paragraphs_without_changing_other_stories(self):
        draft = edition('a', 'b')
        replacement = draft.stories[0].model_copy(deep=True)
        replacement.paragraphs.append(replacement.paragraphs[0].model_copy(update={'text': 'A qualification.'}))
        repaired = apply_repairs(draft, Repairs(stories=[StoryEdit(story_index=0, story=replacement)]))
        self.assertEqual(len(repaired.stories[0].paragraphs), 2)
        self.assertEqual(repaired.stories[1], draft.stories[1])
        with self.assertRaisesRegex(ValueError, 'preserve development IDs'):
            apply_repairs(draft, Repairs(stories=[StoryEdit(story_index=0, story=edition('b').stories[0])]))

    def test_invalid_repair_consumes_budget_and_can_recover(self):
        edits = [Repairs(restore_stories=edition('unknown').stories),
                 Repairs(paragraphs=[ParagraphEdit(story_index=0, paragraph_index=5,
                                                   paragraph=edition().stories[0].paragraphs[0])])]
        for edit in edits:
            with self.subTest(edit=edit), patch('editor.composition.ask',
                    side_effect=[edition(), rejected(finding()), edit]):
                with self.assertRaises(EditionReviewError) as caught:
                    compose_edition(None, None, [development()], Freshness(START, END),
                                    load_policy().model_copy(update={'max_repairs': 1}))
                self.assertIn('Invalid repair', caught.exception.reviews[-1]['issues'][0])

    def test_only_review_related_coverage_omissions_qualify_for_salvage(self):
        draft = edition('a')
        issue = ReviewIssue(id='coverage', field='edition', category='coverage',
                            detail='Restore b', development_ids=['b'])
        for reason, expected in [('Combined story removed because a related development failed review.', True),
                                 ('Not enough space', False)]:
            draft.omissions = [Omission(development_id='b', reason=reason)]
            failure = failed(draft, issue)
            result = shorten_failed_draft(failure.draft, failure.reviews,
                                          [development(), development('b')], set())
            self.assertEqual(result is not None, expected)


class Watchdog(unittest.TestCase):
    now = datetime(2026, 9, 15, 6, 46, tzinfo=ET)

    def write_delivery(self, root, kind='full', status='smtp_accepted', personal=False,
                       replay=False, date='2026-09-15', approved=True):
        directory = root / 'previews' / 'run'
        directory.mkdir(parents=True, exist_ok=True)
        marker = 'personal-send-attempt.json' if personal else 'group-send-attempt.json'
        (directory / marker).write_text(json.dumps({'at': self.now.isoformat(),
                                                  'status': status, 'group': not personal}))
        (directory / 'delivery.json').write_text(json.dumps({'edition_date': date,
            'delivery_kind': kind, 'service_notice': kind == 'service_notice', 'replay_only': replay}))
        (directory / 'final-review.json').write_text(json.dumps({'approved': approved}))

    def test_outcomes_distinguish_notice_shortened_and_full(self):
        for kind, alert in [('full', False), ('shortened', False), ('service_notice', True)]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_delivery(root, kind)
                result = check_delivery(root, self.now)
                self.assertEqual(result['outcome'], kind)
                self.assertEqual(result['alert'], alert)

    def test_personal_replay_old_unapproved_or_uncertain_cannot_count_as_success(self):
        for kwargs in ({'personal': True}, {'replay': True}, {'date': '2026-09-14'},
                       {'approved': False}, {'status': 'started'}, {'status': 'failed_or_uncertain_do_not_retry'}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.write_delivery(root, **kwargs)
                self.assertTrue(check_delivery(root, self.now)['alert'])

    def test_missing_delivery_and_crash_stage_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(RuntimeError):
                with ProductionRun(True, root / 'state') as status:
                    status.stage('composing')
                    raise RuntimeError('sensitive error text')
            record = json.loads((root / 'state' / 'production-run.json').read_text())
            self.assertEqual(record['failed_stage'], 'composing')
            self.assertNotIn('sensitive', json.dumps(record))
            self.assertTrue(check_delivery(root, self.now)['alert'])

    def test_before_deadline_and_weekends_are_not_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            for now in [self.now.replace(hour=6, minute=44), self.now.replace(day=19)]:
                self.assertEqual(check_delivery(Path(tmp), now)['outcome'], 'not_due')

    def test_dry_run_does_not_overwrite_production_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ProductionRun(False, Path(tmp)) as status:
                status.stage('composing')
            self.assertFalse((Path(tmp) / 'production-run.json').exists())
