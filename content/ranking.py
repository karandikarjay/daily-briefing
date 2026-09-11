"""Rank compact excerpts before allocating the full-evidence selection budget."""
import json
from pydantic import BaseModel
from utils.api_utils import num_tokens_from_string


class SourceRanking(BaseModel):
    source_ids: list[str]


def selection_sources(client, fallback, section, sources, audit, attempt, budget=20000):
    if not sources:
        return []
    ranked = sources
    if num_tokens_from_string(json.dumps(sources)) > budget:
        from .verification import ask
        cards = [{k: (s.get(k) or '')[:300] for k in ('source_id', 'title', 'subject', 'source_name', 'published_at', 'source_type')}
                 | {'excerpt': (s.get('article') or s.get('body', ''))[:1800]} for s in sources]
        # Bound ranking prompts as well as selection prompts. Every source gets
        # considered; a long article cannot evict another before relevance review.
        def batches_for(cards):
            batches, batch = [], []
            for card in cards:
                if batch and num_tokens_from_string(json.dumps(batch + [card])) > 12000:
                    batches.append(batch)
                    batch = []
                batch.append(card)
            if batch:
                batches.append(batch)
            return batches

        def rank(cards):
            result = ask(client, fallback, SourceRanking,
                'Rank ALL supplied source_ids by relevance and importance to the topic requirements, best first. '
                'Use the title and compact excerpt; these are discovery summaries, not verified announcements. '
                'Prefer concrete commercial developments over generic market reports and unrelated coverage. '
                'Include every ID exactly once. Do not invent IDs.',
                {'topic_requirements': section['prompt'], 'sources': cards})
            expected = {c['source_id'] for c in cards}
            if len(result.source_ids) != len(expected) or set(result.source_ids) != expected:
                raise ValueError('Source ranking returned missing, duplicate or unknown IDs')
            by_id = {c['source_id']: c for c in cards}
            return [by_id[key] for key in result.source_ids]

        batches = batches_for(cards)
        while True:
            ranked_batches = [rank(batch) for batch in batches]
            if len(ranked_batches) == 1:
                ordered = ranked_batches[0]
                break
            # Compare batch leaders in bounded prompts, reducing the pool each
            # round. Other sources stay available below them and on retries.
            finalists = [card for batch in ranked_batches
                         for card in batch[:min(6, max(1, len(batch) // 2))]]
            batches = batches_for(finalists)
        by_id = {s['source_id']: s for s in sources}
        ranked = [by_id[card['source_id']] for card in ordered]
        ranked_ids = {s['source_id'] for s in ranked}
        ranked += [s for s in sources if s['source_id'] not in ranked_ids]
    if section['title'] == 'Vegan Movement':
        # Preserve the established preference for firsthand FAST announcements.
        ranked = sorted(ranked, key=lambda s: s.get('source_type') != 'email')
    selected = []
    for position, source in enumerate(ranked, 1):
        fits = num_tokens_from_string(json.dumps(selected + [source])) <= budget
        if fits:
            selected.append(source)
        audit.append({'stage': 'selection_budget', 'topic': section['title'], 'attempt': attempt,
                      'source_id': source['source_id'], 'rank': position, 'accepted': fits,
                      'reason': 'included_for_selection' if fits else 'deferred_by_token_budget'})
    return selected
