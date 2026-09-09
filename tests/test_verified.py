import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

from content.freshness import Freshness, publication_dates, in_window, canonical_url
from content.verification import Candidate, Verdict, validate_verdict
from models.data_models import AxiosNewsletterResponse, NewsStory, StoryBullet, TopicNewsResponse
from briefing import validate_stories
from utils.api_utils import call_claude_parse_with_backoff, call_openai_parse_with_backoff, get_content_collection_timeframe
from utils.email_utils import send_email

ET = ZoneInfo('America/New_York')
START = datetime(2026, 9, 7, 6, tzinfo=ET)
END = datetime(2026, 9, 8, 6, tzinfo=ET)


class Dates(unittest.TestCase):
    def test_boundaries_and_ambiguity(self):
        self.assertTrue(in_window('2026-09-07T10:00:00Z', START, END))
        self.assertFalse(in_window('2026-09-08T10:00:00Z', START, END))
        self.assertFalse(in_window('2026-09-08', START, END))
        self.assertFalse(in_window('2026-09-07T12:00:00', START, END))
        self.assertFalse(in_window('garbage', START, END))

    def test_wildtype_undated_instagram_regression(self):
        with patch('content.freshness.safe_fetch', side_effect=ValueError('unavailable')):
            fresh = Freshness(START, END)
            result = fresh.filter([{'url': 'https://www.instagram.com/p/Dc_f1esjynR', 'title': 'Did you know?', 'article': "Cargill invested in Wildtype's $100 million Series B funding round, alongside investors including Bezos Expeditions and Temasek.", 'datetime': None}])
            self.assertEqual(result, [])

    def test_modified_old_article_rejected(self):
        page = '<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2022-02-23T12:00:00Z","dateModified":"2026-09-07T12:00:00Z"}</script>'
        with patch('content.freshness.safe_fetch', return_value=('https://example.com/funding', page)):
            record = Freshness(START, END).inspect({'url': 'https://example.com/funding', 'datetime': '2026-09-07T12:00:00Z', 'date_kind': 'sitemap.modified'})
        self.assertFalse(record['date_verified'])
        self.assertEqual(record['published_at'], '2022-02-23T12:00:00Z')

    def test_conflicting_dates_rejected(self):
        page = '<meta property="article:published_time" content="2026-09-07T12:00:00Z"><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2022-02-23T12:00:00Z"}</script>'
        with patch('content.freshness.safe_fetch', return_value=('https://example.com/a', page)):
            self.assertFalse(Freshness(START, END).inspect({'url': 'https://example.com/a'})['date_verified'])

    def test_matching_date_only_can_be_resolved(self):
        page = '<meta name="date" content="2026-09-07"><meta property="article:published_time" content="2026-09-07T12:00:00Z">'
        with patch('content.freshness.safe_fetch', return_value=('https://example.com/a', page)):
            self.assertTrue(Freshness(START, END).inspect({'url': 'https://example.com/a'})['date_verified'])

    def test_search_timestamp_is_not_proof_but_rss_is(self):
        item = {'url': 'https://example.com/a', 'datetime': '2026-09-07T12:00:00Z'}
        with patch('content.freshness.safe_fetch', side_effect=ValueError('unavailable')):
            self.assertFalse(Freshness(START, END).inspect(item)['date_verified'])
            self.assertTrue(Freshness(START, END).inspect({**item, 'date_kind': 'rss.published'})['date_verified'])

    def test_modified_alone_never_counts(self):
        self.assertEqual(publication_dates('<meta property="article:modified_time" content="2026-09-07T12:00:00Z">'), [])

    def test_html_email_is_normalized_before_quote_checks(self):
        from content.freshness import quote_in
        item = {'subject': 'Round 3', 'datetime': '2026-09-08T02:00:00Z', 'body': "<p>Applications for <b>Round 3</b> of <b>MFA&#39;s project</b> are now open!</p>"}
        source = Freshness(START, END).inspect(item)
        self.assertTrue(source['date_verified'])
        self.assertTrue(quote_in("Applications for Round 3 of MFA's project are now open!", source['body']))

    def test_canonical_url(self):
        self.assertEqual(canonical_url('https://example.com/news/?utm_source=x#fragment'), 'https://example.com/news')

    def test_monday_dst_and_early_runs(self):
        class Clock(datetime):
            current = datetime(2026, 3, 9, 6, 5, tzinfo=ET)
            @classmethod
            def now(cls, tz=None):
                return cls.current
        with patch('utils.api_utils.datetime', Clock):
            get_content_collection_timeframe.cache_clear()
            start, end = get_content_collection_timeframe()
            self.assertEqual(start, datetime(2026, 3, 6, 6, tzinfo=ET))
            self.assertEqual((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds(), 71 * 3600)
            Clock.current = datetime(2026, 9, 8, 5, tzinfo=ET)
            get_content_collection_timeframe.cache_clear()
            start, end = get_content_collection_timeframe()
            self.assertEqual(end, datetime(2026, 9, 7, 6, tzinfo=ET))
            self.assertEqual(start, datetime(2026, 9, 4, 6, tzinfo=ET))
        get_content_collection_timeframe.cache_clear()


class Verification(unittest.TestCase):
    def setUp(self):
        self.candidate = Candidate(source_id='a', title='New launch', description='A product launches', evidence_quote='The company launched its new product today.', event_key='company-product-2026', verification_query='company product launch announcement')
        self.proof = {'a': {'date_verified': True, 'published_at': '2026-09-07T12:00:00Z', 'article': self.candidate.evidence_quote}}
        self.verdict = Verdict(candidate_source_id='a', accepted=True, topic_matches=True, evidence_source_id='a', evidence_quote=self.candidate.evidence_quote, announcement_date='2026-09-07', event_key='company-product-2026', reason='First launch confirmed')

    def test_valid_evidence(self):
        self.assertTrue(validate_verdict(self.verdict, self.candidate, self.proof, START, END))

    def test_wrong_topic_is_rejected(self):
        self.verdict.topic_matches = False
        self.assertFalse(validate_verdict(self.verdict, self.candidate, self.proof, START, END))

    def test_fabricated_quote_rejected(self):
        self.verdict.evidence_quote = 'The company raised a billion dollars today.'
        self.assertFalse(validate_verdict(self.verdict, self.candidate, self.proof, START, END))

    def test_recent_repost_of_old_event_rejected(self):
        self.verdict.announcement_date = '2022-02-23'
        self.assertFalse(validate_verdict(self.verdict, self.candidate, self.proof, START, END))

    def test_unknown_evidence_rejected(self):
        self.verdict.evidence_source_id = 'invented'
        self.assertFalse(validate_verdict(self.verdict, self.candidate, self.proof, START, END))

    def test_final_cannot_introduce_unverified_story(self):
        newsletter = AxiosNewsletterResponse(subject='Test', intro='Hello', stories=[NewsStory(source_id='invented', topic='AI', headline='New thing', bullets=[])])
        with self.assertRaises(ValueError):
            validate_stories(newsletter, [], START, END)

    def test_empty_newsletter_allowed(self):
        newsletter = AxiosNewsletterResponse(subject='Quiet', intro='No news', stories=[])
        self.assertEqual(validate_stories(newsletter, [], START, END), [])


class ModelAndDelivery(unittest.TestCase):
    def test_opus_thinking_blocks_are_skipped(self):
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type='thinking'), SimpleNamespace(type='text', text='{"news_items":[]}')], stop_reason='end_turn', usage=SimpleNamespace(input_tokens=10, output_tokens=20))
        result = call_claude_parse_with_backoff(client, [{'role': 'user', 'content': 'test'}], TopicNewsResponse)
        self.assertEqual(result.choices[0].message.parsed.news_items, [])
        self.assertEqual(client.messages.create.call_args.kwargs['output_config'], {'effort': 'medium'})

    def test_existing_fallback_retained(self):
        fallback = MagicMock()
        with patch('utils.api_utils.call_claude_parse_with_backoff', side_effect=ValueError('failure')):
            call_openai_parse_with_backoff(MagicMock(), [], TopicNewsResponse, fallback_client=fallback)
        self.assertEqual(fallback.beta.chat.completions.parse.call_args.kwargs['model'], 'gpt-5.6-sol')

    def test_personal_send_has_no_group_recipients(self):
        with patch('utils.email_utils.smtplib.SMTP') as smtp, patch('utils.email_utils.GOOGLE_USERNAME', 'jay@example.com'), patch('utils.email_utils.RECIPIENT_EMAILS', ['group@example.com']), patch('utils.email_utils.CHART_CONTENT_IDS', {}):
            smtp.return_value.sendmail.return_value = {}
            self.assertTrue(send_email('<p>Preview</p>', 'Test', False))
            args = smtp.return_value.sendmail.call_args.args
            self.assertEqual(args[1], ['jay+list@example.com'])
            self.assertNotIn('group@example.com', args[2])

    def test_duplicate_preview_send_blocked(self):
        from briefing import deliver
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'newsletter.html').write_text('hello')
            (path / 'delivery.json').write_text(json.dumps({'html_sha256': hashlib.sha256(b'hello').hexdigest(), 'subject': 'Test', 'images': {}, 'selected': []}))
            with patch('briefing.send_email', return_value=True) as send:
                deliver(path)
                with self.assertRaises(FileExistsError):
                    deliver(path)
                self.assertEqual(send.call_count, 1)

    def test_dry_run_cannot_send_or_write_delivery_history(self):
        import briefing
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / 'template.html'
            template.write_text('<html><body>{newsletter_content}</body></html>')
            with patch('sys.argv', ['main.py', '--dry-run']), patch('briefing.ROOT', root), patch('briefing.STATE', root / 'state'), patch('briefing.TEMPLATE_PATH', str(template)), patch('briefing.setup_logging', return_value=(MagicMock(), MagicMock())), patch('briefing.get_content', return_value=[]), patch('briefing.Anthropic'), patch('briefing.OpenAI'), patch('main.generate_images', return_value={}), patch('charts.create_charts'), patch('charts.get_beyond_meat_bond_chart'), patch('charts.extract_egg_price_chart'), patch('briefing.send_email') as send:
                briefing.run()
                send.assert_not_called()
                previews = list((root / 'previews').glob('*/newsletter.html'))
                self.assertEqual(len(previews), 1)
                self.assertIn('No verified new developments', previews[0].read_text())
                self.assertFalse((root / 'state' / 'history.json').exists())

    def test_private_email_is_not_submitted_to_public_search(self):
        from content.verification import select_verified, Candidates, Verdicts
        from config import SECTIONS
        candidate = Candidate(source_id='mail', title='New study', description='New results', evidence_quote='We published our new effectiveness study today.', event_key='new-study-2026', verification_query='private unreleased data')
        source = {'source_id': 'mail', 'source_type': 'email', 'date_verified': True, 'published_at': '2026-09-08T02:00:00Z', 'datetime': '2026-09-08T02:00:00Z', 'body': candidate.evidence_quote, 'date_evidence': [], 'subject': 'New study', 'source_name': 'FAST'}
        verdict = Verdict(candidate_source_id='mail', accepted=True, topic_matches=True, evidence_source_id='mail', evidence_quote=candidate.evidence_quote, announcement_date='2026-09-07', event_key='new-study-2026', reason='Firsthand new report')
        with patch('content.verification.ask', side_effect=[Candidates(news_items=[candidate]), Verdicts(verdicts=[verdict])]), patch('tavily.TavilyClient') as search:
            selected, audit = select_verified(MagicMock(), MagicMock(), SECTIONS[1], [source], Freshness(START, END), [])
            search.assert_not_called()
            self.assertEqual(len(selected), 1)

    def test_billing_failure_uses_fallback_once_per_run(self):
        class BillingError(Exception):
            status_code = 400
        fallback = MagicMock()
        with patch('utils.api_utils._claude_unavailable', False), patch('utils.api_utils.call_claude_parse_with_backoff', side_effect=BillingError('credit balance is too low')) as claude:
            for _ in range(2):
                call_openai_parse_with_backoff(MagicMock(), [], TopicNewsResponse, fallback_client=fallback)
            self.assertEqual(claude.call_count, 1)
            self.assertEqual(fallback.beta.chat.completions.parse.call_count, 2)


if __name__ == '__main__':
    unittest.main()
