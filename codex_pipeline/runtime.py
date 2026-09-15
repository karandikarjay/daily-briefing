"""Skill-led newsletter: autonomous research, private writing, controlled delivery artifacts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlparse

from content.freshness import canonical_url, in_window, quote_in
from editor.rendering import CHART_TITLES
from .agent import run_agent, ROOT
from .models import Research, Draft, Review, Edition
from .rendering import render, word_count

TEMPLATE = Path(__file__).with_name('template.html')
SERVICE_NOTICE = ('Today’s briefing could not be completed to our editorial standards. '
                  'We’re withholding the unapproved stories. This does not mean there were no newsworthy developments.')


def private_json(path, data):
    from briefing import save_json
    save_json(path, data)


def collect_public(freshness, policy, directory):
    from config import TAVILY_API_KEY
    from tavily import TavilyClient
    research = run_agent('public researcher', Research, {
        'topics': policy.topics, 'selection': policy.selection,
        'window_start': freshness.start.isoformat(), 'window_end_exclusive': freshness.end.isoformat(),
        'assignment': 'Search globally across these interests for consequential new developments. '
        'Open primary pages and search prior coverage. Return up to 18 strong leads with precise article '
        'URLs (not homepages), public context URLs and a prior_coverage_query identifying each event '
        'without restricting dates. Search each interest, then prioritize by significance. Do not '
        'fill slots or use out-of-window stories. Aim for a useful pool of 8-12 leads when news warrants it.',
    }, directory, web=True, seconds=policy.research_seconds)
    private_json(directory / 'research.json', research.model_dump())
    if research.leads and not TAVILY_API_KEY:
        raise RuntimeError('TAVILY_API_KEY required for independent original-announcement searches')

    def retain(lead):
        record = freshness.inspect({'url': lead.url, 'title': lead.title,
                                    'source_name': urlparse(lead.url).hostname, 'topic': lead.topic})
        report = {'url': lead.url, 'reason': record['date_reason'], 'accepted': False}
        if not record['date_verified']:
            return None, [], report
        try:
            response = TavilyClient(api_key=TAVILY_API_KEY).search(
                query=lead.prior_coverage_query, topic='general', search_depth='advanced',
                include_raw_content=True, max_results=4, timeout=30)
        except Exception as exc:
            report.update(reason='prior_coverage_search_failed', error_type=type(exc).__name__)
            return None, [], report
        results = response.get('results', [])
        report.update(accepted=True, prior_coverage_query=lead.prior_coverage_query,
                      search_results=results, significance=lead.significance)
        context = []
        urls = list(dict.fromkeys(lead.context_urls + [r['url'] for r in results if r.get('url')]))[:4]
        for url in urls:
            if canonical_url(url) == canonical_url(record['url']):
                continue
            item = freshness.inspect({'url': url, 'title': '', 'source_name': urlparse(url).hostname})
            # Unknown and post-cutoff context cannot support claims. Earlier pages may disprove novelty.
            if item.get('published_at') and (item['date_verified'] or
                    (item['date_reason'] == 'publication_out_of_window' and
                     not_after_cutoff(item['published_at'], freshness.end))):
                context.append(item)
        record['novelty_check'] = {'prior_coverage_query': lead.prior_coverage_query,
            'search_results': [{k: r.get(k) for k in ('url', 'title', 'content', 'published_date')} for r in results]}
        record['research_significance'] = lead.significance
        return record, context, report
    with ThreadPoolExecutor(max_workers=4) as pool:
        collected = list(pool.map(retain, research.leads))
    sources, anchors, audit = {}, [], []
    for record, context, report in collected:
        audit.append(report)
        if record:
            sources[record['source_id']] = record
            anchors.append(record['source_id'])
            for source in context:
                sources.setdefault(source['source_id'], source)
    private_json(directory / 'discovery-audit.json', audit)
    return sources, list(dict.fromkeys(anchors))


def not_after_cutoff(value, end):
    from content.freshness import date_interval
    interval = date_interval(value)
    return bool(interval and interval[0] < end and interval[1] <= end)


def collect_charts(directory):
    from charts import create_charts, get_beyond_meat_bond_chart, extract_egg_price_chart
    from config import CHART_PATHS
    images, observations, failures = {}, {}, []
    for job in (create_charts, get_beyond_meat_bond_chart, extract_egg_price_chart):
        started = time.time_ns()
        try:
            data = job() or {}
            for key, item in data.items():
                source = Path(CHART_PATHS[key + '.png'])
                if source.exists() and source.stat().st_mtime_ns >= started:
                    destination = directory / f'{key}.png'
                    shutil.copyfile(source, destination)
                    images[key] = str(destination.resolve())
                    observations[key] = dict(item, retrieved_at=datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            logging.exception('Chart job failed: %s', job.__name__)
            failures.append({'job': job.__name__, 'error_type': type(exc).__name__})
    private_json(directory / 'chart-data.json', observations)
    private_json(directory / 'chart-failures.json', {'failures': failures,
        'missing': [key for key in CHART_TITLES if key not in images]})
    return images, observations


def validate(draft, sources, anchors, history, freshness, policy, chart_data):
    developments, events, selected_sources = {}, set(), set()
    old_events = {str(h.get('event_key') or '').casefold() for h in history}
    for d in draft.developments:
        if d.source_id in developments or not d.event_key.strip():
            raise ValueError('Repeated development ID or empty event key')
        source = sources.get(d.evidence_source_id)
        if not source or d.evidence_source_id not in anchors or not source.get('date_verified'):
            raise ValueError('Development must use a retained in-window candidate source')
        if not in_window(source.get('published_at'), freshness.start, freshness.end):
            raise ValueError('Source outside reporting window')
        if not quote_in(d.evidence_quote, source.get('article') or source.get('body', '')):
            raise ValueError('Development quote not found in retained source')
        try:
            day = datetime.strptime(d.announcement_date, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('Announcement date must be YYYY-MM-DD')
        if not freshness.start.date() <= day <= freshness.end.date():
            raise ValueError('Announcement date outside reporting window')
        if d.topic not in policy.topics:
            raise ValueError('Unknown topic')
        event = d.event_key.strip().casefold()
        if event in old_events or event in events:
            raise ValueError('Repeated or previously group-delivered event')
        events.add(event)
        selected_sources.add(d.evidence_source_id)
        developments[d.source_id] = d
    used = set()
    for story in draft.edition.stories:
        if not story.brief and not story.image_description:
            raise ValueError('Substantial stories require an illustration prompt')
        for sid in story.development_ids:
            if sid not in developments or sid in used:
                raise ValueError('Unknown or repeated story development')
            used.add(sid)
        public_link = False
        for paragraph in story.paragraphs:
            for cite in paragraph.citations:
                source = sources.get(cite.source_id)
                if not source or not not_after_cutoff(source.get('published_at'), freshness.end):
                    raise ValueError('Unknown, undated or post-cutoff citation')
                if not quote_in(cite.quote, source.get('article') or source.get('body', '')):
                    raise ValueError(f'Quotation not found in source {cite.source_id}: {cite.quote[:120]}')
                if cite.link_text and source.get('url'):
                    if cite.link_text not in paragraph.text:
                        raise ValueError('Link text must be an exact paragraph substring')
                    public_link = True
        if any(sources[developments[sid].evidence_source_id].get('url') for sid in story.development_ids) and not public_link:
            raise ValueError('Public stories need narrative source links')
    if used != set(developments):
        raise ValueError('Every selected development must appear in a story')
    omissions = [o.source_id for o in draft.omissions]
    if len(omissions) != len(set(omissions)) or set(omissions) != set(anchors) - selected_sources:
        raise ValueError('Account for every unselected candidate source exactly once in omissions')
    if any(not o.reason.strip() for o in draft.omissions):
        raise ValueError('Empty omission reason')
    keys = [n.key for n in draft.edition.market_notes]
    if len(keys) != len(set(keys)) or set(keys) != set(chart_data):
        raise ValueError('Provide exactly one commentary for each available chart')
    if any(not n.text.strip() for n in draft.edition.market_notes):
        raise ValueError('Empty chart commentary')
    if sum(bool(s.image_description) for s in draft.edition.stories) > policy.max_images:
        raise ValueError('Too many illustrations')
    words = word_count(draft.edition, sources, chart_data, TEMPLATE.read_text())
    if words > policy.max_words:
        raise ValueError(f'Edition has {words} words including ALL chart commentary and captions; limit {policy.max_words}')
    # Rendering also validates link overlaps and URL schemes.
    render(draft.edition, sources, {}, chart_data, TEMPLATE.read_text())
    return words


def make_preview(freshness, history, policy, directory, *, status=None, replay=None):
    from config import OPENAI_API_KEY
    from openai import OpenAI
    from main import generate_images
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    base = {'window_start': freshness.start.isoformat(), 'window_end_exclusive': freshness.end.isoformat(),
            'policy': policy.model_dump(), 'history': history, 'pipeline': 'codex'}
    private_json(directory / 'audit.json', dict(base, status='started'))
    if status:
        status.stage('researching', preview=str(directory))
    if replay is not None:
        sources, anchors, chart_data = replay['sources'], replay['anchors'], replay['chart_data']
        images = {}
    else:
        sources, anchors = collect_public(freshness, policy, directory)
        # No private data was accessible to the public researcher above. Private
        # editing starts only now and has neither web nor shell tools.
        from content.email_content import get_fast_email_content
        for source in freshness.filter(get_fast_email_content(), topic='Vegan Movement'):
            source['topic'] = 'Vegan Movement'
            sources[source['source_id']] = source
            anchors.append(source['source_id'])
        anchors = list(dict.fromkeys(anchors))
        if status:
            status.stage('media', preview=str(directory))
        images, chart_data = collect_charts(directory)
    frozen = dict(base, sources=sources, anchors=anchors, chart_data=chart_data)
    private_json(directory / 'evidence.json', frozen)
    if status:
        status.stage('composing', preview=str(directory))
    feedback, reviews, previous = [], [], None
    draft = None
    deadline = time.monotonic() + policy.composition_seconds
    for attempt in range(policy.max_repairs + 1):
        if deadline-time.monotonic() < 30:
            break
        if attempt == policy.max_repairs and feedback:
            feedback = feedback + ['Final repair: prefer a shorter edition; remove unsupported claims or stories and keep essential qualifications.']
        draft = run_agent(f'editor-{attempt+1}', Draft, dict(frozen,
            assignment='Act as the private editor. Select only truly new events, compare to GROUP history '
            'semantically even when titles or event keys differ. Write coherent narratives with no intro '
            'or closing. Use short updates as appropriate. For each selected development give a unique '
            'source_id event identifier and its evidence_source_id from sources. Give exact quotes. '
            'All paragraph citations use retained source IDs, with link_text exactly matching a phrase '
            'in that paragraph, or empty for private email. Identify who did research. For each '
            'unselected anchor give a source_id and omission reason. Consider the unrestricted prior '
            'coverage results; old context never makes an old event new. Chart data is an exception '
            'to story freshness: report its actual observation date, never pretend monthly data is daily. '
            'Write 450-550 words of news and reserve roughly 100-150 for the five chart notes. '
            'Avoid unsupported claims in illustration captions too.',
            feedback=feedback, previous_draft=previous), directory,
            seconds=max(1, int(deadline-time.monotonic())))
        previous = draft.model_dump()
        try:
            words = validate(draft, sources, anchors, history, freshness, policy, chart_data)
        except ValueError as exc:
            feedback = [str(exc)]
            reviews.append({'approved': False, 'stage': 'validation', 'issues': feedback})
            continue
        if deadline-time.monotonic() < 30:
            break
        review = run_agent(f'reviewer-{attempt+1}', Review, dict(frozen, draft=previous,
            assignment='Act as an independent reviewer with fresh context. Verify every claim and '
            'implication against retained evidence, including chart notes, subject, and image captions. '
            'Check actual novelty using prior-coverage results and GROUP history, not just new article '
            'dates or different event keys. New firsthand organizational announcements qualify with '
            'attribution; email receipt alone does not make forwarded old news new. Check research '
            'attribution, methods and essential qualifications. Require no unsupported causal claims '
            'about chart movements. Flag important coverage omissions from available candidates, but '
            'do not demand quotas, evergreen content or more than the word budget. Check source links '
            'support their surrounding claims. Be proportionate: style preferences do not block an '
            'accurate useful edition. Approve only with an empty issues list. If no stories were '
            'selected, independently check that the omissions justify an empty edition.'), directory,
            seconds=max(1, int(deadline-time.monotonic())))
        reviews.append(dict(review.model_dump(), stage='independent_review'))
        private_json(directory / 'final-review.json', {'approved': False, 'reviews': reviews})
        if review.approved and not review.issues:
            break
        feedback = review.issues or ['Review did not approve; simplify or omit unsupported material.']
    approved = bool(reviews and reviews[-1]['stage'] == 'independent_review' and
                    reviews[-1]['approved'] and not reviews[-1]['issues'])
    if not approved:
        private_json(directory / 'final-review.json', {'approved': False, 'reviews': reviews})
        # A fixed service notice is explicitly not an approved news edition. API
        # exceptions still propagate and never become notices.
        draft = Draft(edition=Edition(subject='Future Appetite: Today’s briefing is unavailable',
                      stories=[], market_notes=[]), developments=[], omissions=[])
        images, chart_data = {}, {}
        words = len((draft.edition.subject + ' ' + SERVICE_NOTICE).split())
    private_json(directory / 'edition.json', draft.edition.model_dump())
    private_json(directory / 'developments.json', dict(frozen, developments=[d.model_dump() for d in draft.developments]))
    if replay is None and approved:
        if status:
            status.stage('illustrating', preview=str(directory))
        generated = generate_images(OpenAI(api_key=OPENAI_API_KEY, timeout=180), draft.edition)
        for key, source in generated.items():
            destination = directory / (key + '.png')
            shutil.copyfile(source, destination)
            images[key] = str(destination)
    markup = render(draft.edition, sources, images, chart_data, TEMPLATE.read_text())
    if not approved:
        markup = markup.replace('No new developments passed selection and verification for this edition.', SERVICE_NOTICE)
    (directory / 'newsletter.html').write_text(markup)
    selected = [dict(d.model_dump(), published_at=sources[d.evidence_source_id]['published_at'],
                     source_link=sources[d.evidence_source_id].get('url')) for d in draft.developments]
    private_json(directory / 'final-review.json', {'approved': approved, 'service_notice': not approved, 'word_count': words, 'reviews': reviews})
    private_json(directory / 'delivery.json', {
        'pipeline': 'codex', 'replay_only': replay is not None, 'service_notice': not approved,
        'delivery_kind': 'full' if approved else 'service_notice', 'edition_date': freshness.end.date().isoformat(),
        'subject': draft.edition.subject, 'selected': selected, 'images': images,
        'image_sha256': {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k,v in images.items()},
        'html_sha256': hashlib.sha256(markup.encode()).hexdigest(),
        'review_sha256': hashlib.sha256((directory / 'final-review.json').read_bytes()).hexdigest(),
    })
    private_json(directory / 'audit.json', dict(base, status='approved' if approved else 'service_notice',
        commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        codex_model=os.environ.get('CODEX_MODEL', 'gpt-5.6-sol'),
        text_usage=[json.loads(p.read_text()) for p in sorted(directory.glob('*-usage.json'))],
        omissions=[o.model_dump() for o in draft.omissions], word_count=words))
    logging.info('Validated Codex preview saved to %s (%s words)', directory, words)
    return directory
