"""Write, validate and repair entire editions against frozen evidence."""
import json
from content.freshness import in_window, quote_in
from content.verification import ask
from utils.api_utils import num_tokens_from_string
from .models import Edition, Review, Repairs
from .rendering import evidence_map, word_count
from .research import historical_context


class EditionReviewError(ValueError):
    def __init__(self, reviews, draft):
        super().__init__('Edition did not pass review within the repair budget')
        self.reviews = reviews
        self.draft = draft


def evidence_context(developments, edition=None, budget=55000):
    """Keep all developments; bound long evidence while retaining quote context.

    Full documents remain in the frozen audit and in deterministic validation.
    Small pools retain their full source text. Large pools use excerpts surrounding
    both novelty evidence and any cited passages, never an uncited model summary.
    """
    material = [{k: v for k, v in d.items() if k not in ('evidence_text', 'verification_query')}
                for d in developments]
    if num_tokens_from_string(json.dumps(material)) <= budget:
        return material
    quotes = {}
    for d in developments:
        quotes.setdefault(d['evidence_source_id'], []).append(d['evidence_quote'])
    if edition:
        for story in edition.stories:
            for paragraph in story.paragraphs:
                for cite in paragraph.citations:
                    quotes.setdefault(cite.source_id, []).append(cite.quote)
    for limit in (8000, 4000, 2000, 1000):
        compact = json.loads(json.dumps(material))
        for development in compact:
            for source in development.get('evidence_sources', []):
                key = 'article' if source.get('article') else 'body'
                text = source.get(key) or ''
                if len(text) <= limit:
                    continue
                spans = [(0, limit)]
                # Match normalized whitespace just as quote validation does.
                text = ' '.join(text.split())
                for quote in quotes.get(source['source_id'], []):
                    needle = ' '.join(quote.split())
                    offset = text.casefold().find(needle.casefold())
                    if offset >= 0:
                        spans.append((max(0, offset-500), min(len(text), offset+len(needle)+500)))
                merged = []
                for lo, hi in sorted(spans):
                    if merged and lo <= merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
                    else:
                        merged.append((lo, hi))
                source[key] = '\n[... source excerpt omitted ...]\n'.join(text[lo:hi] for lo, hi in merged)
                source['excerpted'] = True
        if num_tokens_from_string(json.dumps(compact)) <= budget:
            return compact
    raise ValueError('Required evidence exceeds the composition context budget')


def empty_edition():
    return Edition(subject='Future Appetite: No verified developments',
        intro='No new developments passed selection and verification for this edition.', stories=[])


def apply_repairs(edition, repairs):
    draft = edition.model_copy(deep=True)
    for key in ('subject', 'intro', 'closing'):
        value = getattr(repairs, key)
        if value is not None:
            setattr(draft, key, value)
    try:
        for edit in repairs.headlines:
            draft.stories[edit.story_index].headline = edit.headline
        for edit in repairs.paragraphs:
            draft.stories[edit.story_index].paragraphs[edit.paragraph_index] = edit.paragraph
        for index in repairs.remove_images:
            if index < 0:
                raise IndexError('Negative image index')
            draft.stories[index].image_description = None
            draft.stories[index].image_caption = None
    except IndexError as exc:
        raise ValueError('Repair refers to an unknown paragraph or story') from exc
    draft.charts = [c for c in draft.charts if c.key not in repairs.remove_charts]
    return Edition.model_validate(draft.model_dump())


def remove_rejected_stories(edition, rejected, available):
    """Drop invalid anchors without rewriting the surviving stories."""
    draft = edition.model_copy(deep=True)
    draft.stories = [s for s in draft.stories if not set(s.development_ids) & set(rejected)]
    if not draft.stories:
        return None
    used = {sid for s in draft.stories for sid in s.development_ids}
    remaining = {d['source_id'] for d in available}
    draft.omissions = [o for o in draft.omissions if o.development_id in remaining - used]
    omitted = {o.development_id for o in draft.omissions}
    from .models import Omission
    draft.omissions.extend(Omission(development_id=sid,
        reason='Combined story removed because a related development failed review.')
        for sid in sorted(remaining - used - omitted))
    draft.charts = [c for c in draft.charts if c.development_id in used]
    # Discard references that might have depended on the removed story. Repairs
    # can supply a new introduction, but cannot resurrect an invalid anchor.
    draft.subject = draft.stories[0].headline[:100]
    draft.intro = draft.closing = ''
    return draft


def validate_edition(edition, developments, freshness, policy):
    by_id = {d['source_id']: d for d in developments}
    sources = evidence_map(developments)
    used, events = set(), set()
    quote_errors = []
    for story_index, story in enumerate(edition.stories):
        permitted = set()
        for sid in story.development_ids:
            if sid not in by_id or sid in used:
                raise ValueError('Unknown or repeated development')
            development = by_id[sid]
            anchor = sources.get(development['evidence_source_id'])
            if (not anchor or not anchor.get('date_verified') or
                    not in_window(anchor.get('published_at'), freshness.start, freshness.end) or
                    not quote_in(development['evidence_quote'], anchor.get('article') or anchor.get('body') or '')):
                raise ValueError('Development lacks its verified in-window anchor and exact quote')
            if development.get('topic') not in policy.topics:
                raise ValueError('Development is outside the editorial interests')
            if not in_window(development['published_at'], freshness.start, freshness.end):
                raise ValueError('Development publication is outside the reporting window')
            if not freshness.start.date().isoformat() <= development['announcement_date'] <= freshness.end.date().isoformat():
                raise ValueError('Development announcement is outside the reporting window')
            event = development['event_key'].casefold()
            if event in events:
                raise ValueError('Repeated underlying event')
            used.add(sid)
            events.add(event)
            permitted.update(s['source_id'] for s in development.get('evidence_sources', []))
        for paragraph_index, paragraph in enumerate(story.paragraphs):
            if not paragraph.text.strip() or not paragraph.citations:
                raise ValueError('Each paragraph needs text and evidence, including analysis premises')
            for citation in paragraph.citations:
                source = sources.get(citation.source_id)
                if not source or citation.source_id not in permitted:
                    raise ValueError('Citation is outside this story evidence')
                if not (in_window(source.get('published_at'), freshness.start, freshness.end)
                        or historical_context(source, freshness.end)):
                    raise ValueError('Citation has ambiguous dates or post-cutoff evidence')
                if not quote_in(citation.quote, source.get('article') or source.get('body') or ''):
                    quote_errors.append(f'story {story_index}, paragraph {paragraph_index}, '
                                        f'source {citation.source_id}: {citation.quote[:300]}')
    if quote_errors:
        raise ValueError('Citation quotes are not verbatim; correct all listed quotes:\n' + '\n'.join(quote_errors))
    omitted = [o.development_id for o in edition.omissions]
    if len(omitted) != len(set(omitted)) or set(omitted) != set(by_id) - used:
        raise ValueError('Explain every omitted verified development exactly once')
    if any(not o.reason.strip() for o in edition.omissions):
        raise ValueError('Omission reasons cannot be empty')
    if sum(bool(s.image_description) for s in edition.stories) > policy.max_images:
        raise ValueError('Illustration budget exceeded')
    if len(edition.charts) > policy.max_charts or len({c.key for c in edition.charts}) != len(edition.charts):
        raise ValueError('Chart budget exceeded or repeated chart')
    if any(c.development_id not in used or not c.reason.strip() for c in edition.charts):
        raise ValueError('Charts must explain a selected development')
    if word_count(edition, developments) > policy.max_words:
        raise ValueError('Edition exceeds the five-minute word limit')
    return [by_id[sid] for story in edition.stories for sid in story.development_ids]


def compose_edition(client, fallback, developments, freshness, policy, history=None):
    if not developments:
        return empty_edition(), [], {'approved': True, 'reviews': [], 'word_count': 0}
    available = list(developments)
    previous, feedback, reviews, removed = None, [], [], []
    repair_draft = None
    prompt = '''Write Future Appetite using the editorial brief and verified developments.
Choose the most important material across topics, order freely, and allocate space by
importance. There is no minimum length, topic quota, required order, or fixed set of
paragraph labels. Aim for target_words; max_words includes headlines, intro, closing,
captions and source attribution. Write a concise, engaging Axios-style edition.
Use plain text only, no HTML or Markdown. Subject and optional intro/closing must be
supported by the selected stories. Do not add a generic greeting or forced theme.
Do not narrate verification, selection, reporting windows, or email-list mechanics
in reader copy. Source attribution handles provenance. Prefer concise headlines
and short paragraphs, usually two or three sentences, to dense blocks of detail.
Each story has one or more development_ids referring to source_id in the supplied
developments. Group related coverage, but never repeat an underlying event. Each
paragraph needs citations with exact source_id and verbatim supporting quotes from
that development's evidence_sources. Quotes support factual claims or the premises
of clearly framed analysis; the separate reviewer checks entailment. Every statement,
comparison and implication must be grounded. Dates on old contextual evidence must
be explicit. New research is not necessarily causal or generalizable. State limitations
when relevant; do not manufacture an actionable takeaway or recommendation.
Each story must lead with the verified new development, not old contextual facts.
Respect the evidence's limits: an email summary is not the full study. Missing
outcomes or methods in a summary do not prove the full study did not measure or
report them. Attribute organizational claims; do not call an intervention cheap,
effective or replicable unless the supplied evidence establishes that conclusion.
Use reporting or analysis paragraph kinds. Labels are optional and should be useful.
Explain why each unselected verified development was omitted in omissions (private audit).
Illustrations are optional, at most max_images: only request one when it adds value,
avoid depictions implying actual news photography, and describe a conceptual illustration.
Charts are optional, at most max_charts: use only when a selected development warrants
one of the available market series, give its development_id and reason. Chart data will
be generated separately; do not invent prices, returns, or patterns absent from evidence.
If feedback is provided, repair the cited problems while retaining sound reporting.
'''
    for attempt in range(policy.max_repairs + 1):
        if repair_draft is not None:
            edits = ask(client, fallback, Repairs,
                'Make surgical corrections to the reviewer issues, using zero-based story '
                'and paragraph indexes. Return only fields or paragraphs that need changes. '
                'Prefer deleting an unsupported phrase or substituting the simplest sourced '
                'wording. Do not introduce new comparisons, generalizations, or analysis. '
                'Keep unaffected language verbatim within edited paragraphs. Preserve valid '
                'citations, adding exact evidence quotes only if necessary. Leave unchanged '
                'subject, intro and closing null. To remove an unsupported intro or closing, '
                'set it to an empty string. Remove a problematic optional image/chart if '
                'needed. You cannot add stories or change their development IDs.',
                {'brief': policy.model_dump(), 'draft': repair_draft.model_dump(),
                 'issues': feedback, 'evidence': evidence_context(available, repair_draft)})
            edition = apply_repairs(repair_draft, edits)
        else:
            edition = ask(client, fallback, Edition, prompt,
                {'brief': policy.model_dump(), 'window_start': freshness.start.isoformat(),
                 'window_end': freshness.end.isoformat(), 'developments': evidence_context(available),
                 'previous_draft': previous, 'feedback': feedback})
        try:
            selected = validate_edition(edition, available, freshness, policy)
        except ValueError as exc:
            feedback = [str(exc)]
            reviews.append({'attempt': attempt+1, 'stage': 'structural_review', 'approved': False, 'issues': feedback})
            previous = edition.model_dump()
            repair_draft = edition if str(exc).startswith('Citation quote') else None
            continue
        review = ask(client, fallback, Review,
            'Independently review the COMPLETE newsletter: subject, intro, headlines, '
            'paragraphs, transitions, closing, image captions, and chart choices. Check '
            'every fact, number, date, comparison, causal inference and implication against '
            'the evidence. Exact quotes alone do not establish entailment. Plausible background '
            'knowledge is not evidence. Factual assertions inside analysis paragraphs need '
            'support too; a hedged implication cannot rely on invented premises. Check novelty '
            'against the reporting window and prior coverage, including semantic duplicates. '
            'Only new developments may anchor stories. Older evidence is dated context. '
            'Check each development against its assigned topic scope in the brief. '
            'A shared technology or speculative relevance alone does not establish fit. '
            'Analysis must be clearly framed and follow from evidence without overstating '
            'causality, transferability or certainty. Evaluate importance for the audience '
            'and useful implications, avoiding generic hype. Do not impose topic quotas. '
            'Reject material omissions of stronger verified news. Images must be clearly '
            'illustrative, not purported event photographs. Charts must be relevant. '
            'List concrete repair issues. rejected_development_ids is ONLY for developments '
            'that cannot anchor a story (old, repeated, outside scope or invalid evidence), '
            'not merely flawed prose. Do not reject for harmless stylistic preferences. '
            'Approve only if no material issues remain.',
            {'brief': policy.model_dump(), 'edition': edition.model_dump(),
             'verified_developments': evidence_context(available, edition), 'previously_covered': history or [],
             'window_start': freshness.start.isoformat(), 'window_end': freshness.end.isoformat()}, independent=True)
        reviews.append({'attempt': attempt+1, 'stage': 'edition_review', **review.model_dump()})
        if not set(review.rejected_development_ids) <= {d['source_id'] for d in available}:
            raise ValueError('Reviewer rejected an unknown development')
        if review.approved and not review.issues and not review.rejected_development_ids:
            return edition, selected, {'approved': True, 'reviews': reviews,
                'removed_developments': removed, 'word_count': word_count(edition, available)}
        feedback = review.issues or ['Resolve the rejected development(s) and rewrite affected text.']
        removed.extend(review.rejected_development_ids)
        available = [d for d in available if d['source_id'] not in review.rejected_development_ids]
        if not available:
            return empty_edition(), [], {'approved': True, 'reviews': reviews,
                                        'removed_developments': removed, 'word_count': 0}
        previous = edition.model_dump()
        repair_draft = (remove_rejected_stories(edition, review.rejected_development_ids, available)
                        if review.rejected_development_ids else edition)
    raise EditionReviewError(reviews, previous)
