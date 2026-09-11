"""Regression cases for the September 11 empty alternative-protein section."""
import json
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from content.freshness import Freshness, publication_dates
from content.ranking import selection_sources, SourceRanking
from content.tavily_content import get_tavily_content
from briefing import compose_with_replacements

ET = ZoneInfo('America/New_York')
START = datetime(2026, 9, 10, 6, tzinfo=ET)
END = datetime(2026, 9, 11, 6, tzinfo=ET)
URL = 'https://example.com/announcement'


def page(published='2026-09-10T13:00:00Z'):
    return f'''<head><meta property="article:published_time" content="{published}">
    <script type="application/ld+json">{{"@type":"NewsArticle","url":"{URL}",
    "datePublished":"{published}"}}</script></head>
    <body class="active-sticky-sidebar"><article><h1>A commercial partnership</h1>
    <time class="post-published updated" datetime="{published}">Published on September 10</time>
    <time class="post-published updated" datetime="2026-09-11T00:56:23Z">Last updated September 11</time>
    <div class="entry-content">The partnership is available starting today.</div>
    <div class="related-posts"><time class="published" datetime="2022-11-07T00:00:00Z"></time></div>
    <article><time class="published" datetime="2021-11-18T00:00:00Z"></time></article>
    </article><aside><time class="published" datetime="2025-04-22T00:00:00Z"></time></aside></body>'''


class ArticleDates(unittest.TestCase):
    def inspect(self, html, **extra):
        with patch('content.freshness.safe_fetch', return_value=(URL, html)):
            return Freshness(START, END).inspect({'url': URL, **extra})

    def test_green_queen_sidebar_and_updated_byline_do_not_conflict(self):
        result = self.inspect(page())
        self.assertTrue(result['date_verified'])
        self.assertEqual(len(result['date_evidence']), 3)
        self.assertEqual(result['published_at'], '2026-09-10T13:00:00Z')

    def test_related_jsonld_is_not_this_article(self):
        html = page() + '<script type="application/ld+json">{"@type":"Article","mainEntityOfPage":{"@id":"https://example.com/old"},"datePublished":"2022-01-01T00:00:00Z"}</script>'
        self.assertTrue(self.inspect(html)['date_verified'])

    def test_real_main_article_conflict_is_still_rejected(self):
        html = page().replace('datetime="2026-09-10T13:00:00Z"', 'datetime="2026-09-09T13:00:00Z"')
        result = self.inspect(html)
        self.assertFalse(result['date_verified'])
        self.assertEqual(result['date_reason'], 'conflicting_publication_dates')

    def test_rss_conflict_is_still_rejected(self):
        result = self.inspect(page(), datetime='2026-09-09T13:00:00Z', date_kind='rss.published')
        self.assertEqual(result['date_reason'], 'conflicting_publication_dates')

    def test_publisher_calendar_resolves_matching_date_only(self):
        html = page('2026-09-11T01:00:00Z') + '<meta name="date" content="2026-09-11">'
        self.assertTrue(self.inspect(html)['date_verified'])

    def test_index_page_times_are_not_publication_proof(self):
        html = '<main><h1>Latest news</h1><article><time class="published" datetime="2026-09-10T13:00:00Z"></time></article></main>'
        self.assertEqual(publication_dates(html, URL), [])

    def test_missing_ambiguous_old_and_cutoff_reasons(self):
        for html, reason in [('<p>No date</p>', 'missing_publication_date'),
                             (page('2026-09-10T13:00:00'), 'ambiguous_publication_date'),
                             (page('2026-09-09T13:00:00Z'), 'publication_out_of_window'),
                             (page('2026-09-11T10:00:00Z'), 'publication_out_of_window')]:
            self.assertEqual(self.inspect(html)['date_reason'], reason)


class Discovery(unittest.TestCase):
    def test_rescue_uses_public_queries_and_keeps_search_dates_as_hints(self):
        audit = []
        with patch('content.tavily_content.TAVILY_API_KEY', 'test'), patch('tavily.TavilyClient') as client:
            client.return_value.search.return_value = {'results': [{'url': URL, 'title': 'Cafe partnership', 'content': 'Plant protein', 'published_date': '2026-09-10'}]}
            result = get_tavily_content('Alternative Protein', rescue=True, audit=audit, window=(START, END))
        self.assertEqual(len(result), 1)
        self.assertEqual(client.return_value.search.call_count, 6)
        calls = [call.kwargs for call in client.return_value.search.call_args_list]
        self.assertTrue(all(c['topic'] == 'general' and c['max_results'] == 8 for c in calls))
        self.assertTrue(any('cafe' in c['query'] for c in calls))
        self.assertEqual(calls[0]['start_date'], '2026-09-10')
        self.assertEqual(audit[0]['reason'], 'search_completed')

    def test_failure_and_zero_results_are_distinct(self):
        audit = []
        with patch('content.tavily_content.TAVILY_API_KEY', 'test'), patch('content.tavily_content.TAVILY_RESCUE_QUERIES', {'AI': ['one', 'two']}), patch('tavily.TavilyClient') as client:
            client.return_value.search.side_effect = [RuntimeError('unavailable'), {'results': []}]
            self.assertEqual(get_tavily_content('AI', rescue=True, audit=audit, window=(START, END)), [])
        self.assertEqual([a['reason'] for a in audit], ['search_failed', 'search_completed'])

    def test_rescue_only_for_empty_topics_and_applies_freshness(self):
        from models.data_models import AxiosNewsletterResponse, NewsStory
        from content.verification import FinalReview
        sections = [{'title': 'AI', 'prompt': 'AI'}, {'title': 'Alternative Protein', 'prompt': 'Plant protein'}]
        good = {'source_id': 'ai', 'topic': 'AI', 'title': 'AI launch', 'published_at': '2026-09-10T13:00:00Z', 'announcement_date': '2026-09-10'}
        fresh = Freshness(START, END)
        discover = MagicMock(return_value=[{'url': URL}, {'url': URL + '/old'}])
        def writer(c, f, batch):
            return AxiosNewsletterResponse(subject='', intro='', stories=[NewsStory(source_id='ai', topic='AI', headline='AI launch', bullets=[])]), ''
        def fetch(url):
            return url, page('2026-09-09T13:00:00Z') if url.endswith('/old') else page()
        with patch('briefing.SECTIONS', sections), patch('briefing.select_verified', side_effect=[([good], []), ([], []), ([], [])]) as select, patch('briefing.ask', return_value=FinalReview(approved=True, reason='Supported')), patch('content.freshness.safe_fetch', side_effect=fetch):
            newsletter, selected, _, _ = compose_with_replacements(None, None, {'AI': [good]}, fresh, [], writer, discover=discover)
        discover.assert_called_once_with('Alternative Protein')
        second_pool = select.call_args_list[-1].args[3]
        self.assertEqual([s['url'] for s in second_pool], [URL])
        self.assertEqual(len(newsletter.stories), 1)
        self.assertEqual(len(selected), 1)
        self.assertTrue(any(s['attempt'] == 2 and not s['accepted'] for s in fresh.audit))


class Ranking(unittest.TestCase):
    def test_relevant_older_article_survives_budget_and_sources_are_unchanged(self):
        sources = [{'source_id': key, 'title': key, 'article': 'evidence ' * 100,
                    'datetime': stamp, 'source_type': 'article'} for key, stamp in
                   [('noise', '2026-09-11T09:00:00Z'), ('partnership', '2026-09-10T13:01:00Z')]]
        original = json.dumps(sources)
        audit = []
        with patch('content.ranking.num_tokens_from_string', side_effect=len), patch('content.verification.ask', return_value=SourceRanking(source_ids=['partnership', 'noise'])) as ask:
            selected = selection_sources(None, None, {'title': 'Alternative Protein', 'prompt': 'Partnerships'}, sources, audit, 1, budget=1200)
        self.assertEqual([s['source_id'] for s in selected], ['partnership'])
        self.assertEqual(json.dumps(sources), original)
        self.assertEqual(audit[-1]['reason'], 'deferred_by_token_budget')
        self.assertIn('excerpt', ask.call_args.args[-1]['sources'][0])

    def test_large_pool_ranking_is_bounded_and_considers_every_source(self):
        sources = [{'source_id': str(i), 'title': 'Partnership', 'article': 'x' * 2200} for i in range(30)]
        seen = set()
        def rank(c, f, model, prompt, data):
            self.assertLessEqual(len(json.dumps(data['sources'])), 12000)
            seen.update(s['source_id'] for s in data['sources'])
            return SourceRanking(source_ids=[s['source_id'] for s in data['sources']])
        with patch('content.ranking.num_tokens_from_string', side_effect=len), patch('content.verification.ask', side_effect=rank):
            selection_sources(None, None, {'title': 'AI', 'prompt': 'AI'}, sources, [], 1, budget=5000)
        self.assertEqual(seen, {str(i) for i in range(30)})

    def test_fast_email_priority_survives_ranking(self):
        sources = [{'source_id': 'article', 'source_type': 'article', 'article': 'x' * 900},
                   {'source_id': 'email', 'source_type': 'email', 'body': 'x' * 900}]
        with patch('content.ranking.num_tokens_from_string', side_effect=len), patch('content.verification.ask', return_value=SourceRanking(source_ids=['article', 'email'])):
            selected = selection_sources(None, None, {'title': 'Vegan Movement', 'prompt': 'Advocacy'}, sources, [], 1, budget=1200)
        self.assertEqual([s['source_id'] for s in selected], ['email'])

    def test_invalid_ranking_fails_instead_of_silently_losing_sources(self):
        with patch('content.ranking.num_tokens_from_string', return_value=100), patch('content.verification.ask', return_value=SourceRanking(source_ids=['invented'])):
            with self.assertRaises(ValueError):
                selection_sources(None, None, {'title': 'AI', 'prompt': 'AI'}, [{'source_id': 'real'}], [], 1, budget=1)


if __name__ == '__main__':
    unittest.main()
