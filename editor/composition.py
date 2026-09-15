"""Write, validate and repair entire editions against frozen evidence."""
import json
import time
from content.freshness import in_window, quote_in
from content.verification import ask
from utils.api_utils import num_tokens_from_string
from .models import Edition, Review, Repairs, ReviewIssue
from .rendering import evidence_map, word_count
from .research import historical_context


class EditionReviewError(ValueError):
    def __init__(self, reviews, draft):
        super().__init__('Edition did not pass review within the repair budget')
        self.reviews = reviews
        self.draft = draft


class CitationReviewError(ValueError):
    def __init__(self, message, findings):
        super().__init__(message)
        self.findings = findings


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
        replaced = set()
        for edit in repairs.stories:
            if edit.story_index in replaced:
                raise ValueError('Repeated whole-story repair')
            if edit.story.development_ids != draft.stories[edit.story_index].development_ids:
                raise ValueError('Whole-story repairs must preserve development IDs')
            replaced.add(edit.story_index)
            draft.stories[edit.story_index] = edit.story.model_copy(deep=True)
        if any(edit.story_index in replaced for edit in repairs.paragraphs):
            raise ValueError('Do not combine whole-story and paragraph repairs on the same story')
        for edit in repairs.headlines:
            draft.stories[edit.story_index].headline = edit.headline
        for edit in repairs.paragraphs:
            draft.stories[edit.story_index].paragraphs[edit.paragraph_index] = edit.paragraph
        for edit in repairs.images:
            draft.stories[edit.story_index].image_caption = edit.image_caption
            draft.stories[edit.story_index].image_description = edit.image_description
        for index in repairs.remove_images:
            if index < 0:
                raise IndexError('Negative image index')
            draft.stories[index].image_description = None
            draft.stories[index].image_caption = None
    except IndexError as exc:
        raise ValueError('Repair refers to an unknown paragraph or story') from exc
    draft.charts = [c for c in draft.charts if c.key not in repairs.remove_charts]
    if repairs.restore_stories:
        omitted = {o.development_id for o in draft.omissions}
        restored = [sid for story in repairs.restore_stories for sid in story.development_ids]
        if not set(restored) <= omitted or len(restored) != len(set(restored)):
            raise ValueError('Restored stories must use distinct, previously omitted developments')
        draft.stories.extend(s.model_copy(deep=True) for s in repairs.restore_stories)
        draft.omissions = [o for o in draft.omissions if o.development_id not in restored]
    return Edition.model_validate(draft.model_dump())


def issue_value(edition, issue):
    """Resolve a review location strictly; malformed findings never authorize pruning."""
    if issue.field in ('subject', 'intro', 'closing'):
        if issue.story_index is not None or issue.paragraph_index is not None:
            raise ValueError('Global review issue has story coordinates')
        return getattr(edition, issue.field)
    if issue.field == 'edition':
        return edition.model_dump()
    if issue.story_index is None or issue.story_index >= len(edition.stories):
        raise ValueError('Review issue refers to an unknown story')
    story = edition.stories[issue.story_index]
    if issue.field == 'paragraph':
        if issue.paragraph_index is None or issue.paragraph_index >= len(story.paragraphs):
            raise ValueError('Review issue refers to an unknown paragraph')
        return story.paragraphs[issue.paragraph_index].model_dump()
    return story.model_dump() if issue.field == 'story' else getattr(story, issue.field)


def repair_gaps(before, after, findings, edits):
    addressed = set(edits.addressed_issue_ids)
    gaps = []
    for issue in findings:
        # A whole-story rewrite may remove a flagged paragraph or shift its index.
        # Moving the same unchanged paragraph elsewhere is not a correction.
        replaced = any(e.story_index == issue.story_index for e in edits.stories)
        if replaced and issue.field == 'paragraph':
            old = before.stories[issue.story_index].paragraphs[issue.paragraph_index]
            changed = old not in after.stories[issue.story_index].paragraphs
        else:
            changed = issue_value(before, issue) != issue_value(after, issue)
        if issue.id not in addressed or not changed:
            gaps.append(f'{issue.id}: repair did not address or change {issue.field}: {issue.detail}')
    return gaps


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
    quote_findings = {}
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
                    quote_findings[(story_index, paragraph_index)] = ReviewIssue(
                        id=f'citation-{story_index}-{paragraph_index}', field='paragraph',
                        story_index=story_index, paragraph_index=paragraph_index, category='factual',
                        detail='Replace nonverbatim supporting quotations with exact evidence quotes.')
    if quote_errors:
        raise CitationReviewError('Citation quotes are not verbatim; correct all listed quotes:\n'
                                  + '\n'.join(quote_errors), list(quote_findings.values()))
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
    words = word_count(edition, developments)
    if words > policy.max_words:
        raise ValueError(f'Edition exceeds the five-minute word limit: {words} rendered words '
                         f'versus {policy.max_words} allowed, including sources, captions and '
                         f'chart headings. Cut at least {words - policy.max_words} words.')
    return [by_id[sid] for story in edition.stories for sid in story.development_ids]


def compose_edition(client, fallback, developments, freshness, policy, history=None, *,
                    recovery_issues=None, initial_draft=None, deadline=None, salvage=False,
                    prior_review_context=None):
    if not developments:
        return empty_edition(), [], {'approved': True, 'reviews': [], 'word_count': 0}
    available = list(developments)
    previous, feedback, reviews, removed = None, list(recovery_issues or []), [], []
    repair_draft, findings = None, []
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
Provide a conceptual AI illustration description and concise caption for EVERY story,
up to max_images. Do not imply actual news photography or invent event details.
The regular five market charts are added separately; leave charts empty. Do not
invent prices, returns, or trends. Their headings count toward the word budget.
If feedback is provided, repair the cited problems while retaining sound reporting.
'''
    if recovery_issues is not None:
        prompt += '''Recovery edition: start again from the evidence and resolve ALL supplied
review issues. Write brief, attributed factual reporting; omit optional analysis and
transitions that introduce unsupported implications. Retain important news and its
limitations. Use explicit, factual headlines. Account for omissions as usual.
'''
    for attempt in range(policy.max_repairs + 1):
        if deadline is not None and time.monotonic() >= deadline:
            if reviews:
                reviews[-1]['deadline_exhausted'] = True
            else:
                reviews.append({'stage': 'deadline', 'approved': False,
                                'issues': ['Composition deadline exhausted.']})
            break
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
                'needed. Use images to correct captions and illustration descriptions directly. '
                'Use paragraphs ONLY to replace existing paragraph indexes. To add, delete or '
                'reorganize paragraphs, use stories to replace the complete story, keeping its '
                'development IDs exactly unchanged. Do not mix stories and paragraphs edits '
                'for the same story. '
                'Return addressed_issue_ids for every supplied finding you address. '
                'Do not change development IDs on existing stories. If review requests '
                'restoring an omitted verified development, use restore_stories to append '
                'a standalone story drawn ONLY from the available evidence. Never restore '
                'a rejected development or modify unrelated stories.',
                {'brief': policy.model_dump(), 'draft': repair_draft.model_dump(),
                 'issues': feedback, 'findings': [f.model_dump() for f in findings],
                 'evidence': evidence_context(available, repair_draft)})
            try:
                edition = apply_repairs(repair_draft, edits)
            except ValueError as exc:
                feedback = [f'Invalid repair: {exc}'] + feedback
                reviews.append({'attempt': attempt+1, 'stage': 'repair_check', 'approved': False,
                                'issues': feedback, 'findings': [f.model_dump() for f in findings]})
                previous = repair_draft.model_dump()
                continue
            gaps = repair_gaps(repair_draft, edition, findings, edits)
            if not findings and not removed and edition == repair_draft:
                gaps = ['Repair made no changes to the rejected draft.']
            if gaps:
                feedback = gaps
                if edits.stories:
                    # Failed acknowledgments on a structural rewrite: keep the original
                    # coordinates rather than attaching stale findings to rearranged text.
                    edition = repair_draft
                else:
                    findings = [f for f in findings if f.id not in edits.addressed_issue_ids
                                or issue_value(repair_draft, f) == issue_value(edition, f)]
                reviews.append({'attempt': attempt+1, 'stage': 'repair_check', 'approved': False,
                                'issues': gaps, 'findings': [f.model_dump() for f in findings]})
                # Field edits do not shift coordinates. Retain progress, but never approve
                # these changes without the subsequent complete independent review.
                repair_draft = edition
                previous = edition.model_dump()
                continue
        elif initial_draft is not None:
            edition, initial_draft = initial_draft.model_copy(deep=True), None
        else:
            edition = ask(client, fallback, Edition, prompt,
                {'brief': policy.model_dump(), 'window_start': freshness.start.isoformat(),
                 'window_end': freshness.end.isoformat(), 'developments': evidence_context(available),
                 'previous_draft': previous, 'feedback': feedback})
        # Subsequent structural feedback concerns this updated draft. Earlier semantic
        # issues remain in prior_reviews, but must not force already changed fields to
        # change again during a quotation-only repair.
        findings = []
        # Visuals are part of the product, not an editorial opt-out. A neutral
        # conceptual fallback avoids a missing prompt silently dropping a story image.
        for story in edition.stories:
            if not story.image_description:
                story.image_description = ('Create an editorial conceptual illustration of this topic: '
                    + story.headline + '. Symbolic composition, no text, logos, identifiable people, '
                    'or reconstruction of a real event. Clearly illustrative rather than documentary.')
                story.image_caption = 'Conceptual illustration.'
            if recovery_issues is not None:
                story.image_caption = 'Conceptual illustration.'
        if recovery_issues is not None:
            edition.subject = 'Future Appetite: Today’s briefing'
            edition.intro = edition.closing = ''
        try:
            selected = validate_edition(edition, available, freshness, policy)
        except ValueError as exc:
            feedback = [str(exc)]
            findings = getattr(exc, 'findings', [])
            reviews.append({'attempt': attempt+1, 'stage': 'structural_review', 'approved': False,
                            'issues': feedback, 'findings': [f.model_dump() for f in findings]})
            previous = edition.model_dump()
            repair_draft = edition if str(exc).startswith('Citation quote') else None
            continue
        if deadline is not None and time.monotonic() >= deadline:
            previous = edition.model_dump()
            reviews.append({'stage': 'deadline', 'approved': False,
                            'issues': ['Composition deadline exhausted before independent review.']})
            break
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
            'List ALL material repair issues in this pass, including subject and headlines. '
            'Use prior reviews to check repairs consistently; do not reopen resolved issues '
            'without identifying a remaining material error. '
            'List concrete repair issues. rejected_development_ids is ONLY for developments '
            'that cannot anchor a story (old, repeated, outside scope or invalid evidence), '
            'not merely flawed prose. Do not list harmless stylistic preferences as issues '
            'or findings. optional_presentation is for materially misleading optional '
            'content, not requests for more engaging copy. '
            'Return one finding for EACH issue, with a unique id, exact zero-based location, '
            'category and actionable detail. Use field=edition only for genuinely global '
            'issues such as material omissions. For omitted news, use category=coverage '
            'and list the omitted development_ids. Never use coverage for unsupported '
            'claims or missing essential qualifications. Do not classify missing essential caveats '
            'as optional presentation. Approve only if no material issues remain.'
            + (' Fallback presentation policy: the neutral subject "Future Appetite: Today’s briefing", '
               'an empty intro/closing, and fixed conceptual-illustration captions are intentional '
               'and permitted. Do not reject them for being generic or require specific news claims '
               'in these fields, even if an earlier review requested that. This permission applies '
               'only to presentation; all factual and evidence checks remain required. '
               'Brief attributed factual reporting with essential qualifications is sufficient '
               'for fallback delivery. Optional analysis, recommendations, and separate "so what" '
               'paragraphs are not required, even if earlier reviews requested them.'
               if salvage or recovery_issues is not None else '')
            + (' This is a shortened fallback. Evidence/review-related omissions are permitted; '
               'do not demand reinstating withheld stories. Check that pruning did not remove '
               'essential qualifications or make remaining reporting misleading.' if salvage else ''),
            {'brief': policy.model_dump(), 'edition': edition.model_dump(),
             'prior_reviews': list(prior_review_context or []) + reviews,
             'verified_developments': evidence_context(available, edition), 'previously_covered': history or [],
             'window_start': freshness.start.isoformat(), 'window_end': freshness.end.isoformat()}, independent=True)
        if len({f.id for f in review.findings}) != len(review.findings):
            raise ValueError('Duplicate review issue IDs')
        for finding in review.findings:
            issue_value(edition, finding)
        reviews.append({'attempt': attempt+1, 'stage': 'edition_review', **review.model_dump()})
        if not set(review.rejected_development_ids) <= {d['source_id'] for d in available}:
            raise ValueError('Reviewer rejected an unknown development')
        if review.approved and not review.issues and not review.findings and not review.rejected_development_ids:
            return edition, selected, {'approved': True, 'reviews': reviews,
                'removed_developments': removed, 'word_count': word_count(edition, available)}
        feedback = review.issues or [f.detail for f in review.findings] or ['Resolve the rejected development(s) and rewrite affected text.']
        findings = review.findings
        removed.extend(review.rejected_development_ids)
        available = [d for d in available if d['source_id'] not in review.rejected_development_ids]
        if not available:
            return empty_edition(), [], {'approved': True, 'reviews': reviews,
                                        'removed_developments': removed, 'word_count': 0}
        previous = edition.model_dump()
        repair_draft = (remove_rejected_stories(edition, review.rejected_development_ids, available)
                        if review.rejected_development_ids else edition)
        # Removal shifts indexes. Remap surviving findings to the new draft.
        if review.rejected_development_ids and repair_draft is not None:
            positions = {tuple(s.development_ids): i for i, s in enumerate(repair_draft.stories)}
            remapped = []
            for finding in findings:
                if finding.story_index is None:
                    if (finding.field in ('subject', 'intro', 'closing')
                            and issue_value(edition, finding) != issue_value(repair_draft, finding)):
                        continue  # Removal already reset this field; full review still follows.
                    remapped.append(finding)
                else:
                    key = tuple(edition.stories[finding.story_index].development_ids)
                    if key in positions:
                        remapped.append(finding.model_copy(update={'story_index': positions[key]}))
            findings = remapped
    raise EditionReviewError(reviews, previous)
