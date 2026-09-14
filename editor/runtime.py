"""Preview orchestration and optional media, separate from SMTP delivery."""
import hashlib
import logging
import shutil
import time
from pathlib import Path

from config import CHART_PATHS, AI_MODEL
from utils.api_utils import TEXT_USAGE
from .composition import compose_edition, EditionReviewError
from .research import research_developments
from .rendering import render_edition, CHART_TITLES, word_count
from .models import Edition, Omission


def compose_with_recovery(client, fallback, developments, freshness, policy, history, directory):
    """Retry rejected copy once from scratch; never send an unapproved draft."""
    reviews, rejected, issues = [], set(), []
    for phase in ('normal', 'recovery'):
        available = [d for d in developments if d['source_id'] not in rejected]
        try:
            kwargs = {} if phase == 'normal' else {'recovery_issues': issues}
            brief = policy if phase == 'normal' else policy.model_copy(
                update={'target_words': min(policy.target_words, 400)})
            edition, selected, review = compose_edition(
                client, fallback, available, freshness, brief, history, **kwargs)
            review['reviews'] = reviews + [dict(r, phase=phase) for r in review.get('reviews', [])]
            review['removed_developments'] = sorted(rejected | set(review.get('removed_developments', [])))
            review['recovery_used'] = phase == 'recovery'
            return edition, selected, review
        except EditionReviewError as exc:
            from briefing import save_json
            logging.warning('%s edition exhausted review repairs', phase)
            save_json(directory / f'{phase}-rejected-draft.json', exc.draft)
            reviews.extend(dict(r, phase=phase) for r in exc.reviews)
            issues.extend(issue for r in exc.reviews for issue in r.get('issues', []))
            rejected.update(sid for r in exc.reviews for sid in r.get('rejected_development_ids', []))
    # This fixed operational message makes no news claims and needs no model call.
    # A rejected newsletter is not an approved edition or an empty news window.
    notice = Edition(subject='Future Appetite: Today’s briefing is unavailable',
        intro='Today’s briefing could not be completed to our editorial standards. '
              'We’re withholding the unapproved stories. This does not mean there were no newsworthy developments.',
        stories=[], omissions=[Omission(development_id=d['source_id'],
            reason='Edition withheld after normal and recovery review budgets were exhausted.')
            for d in developments])
    logging.error('Sending service notice: normal and recovery editions failed review')
    return notice, [], {'approved': False, 'service_notice': True, 'recovery_used': True,
                        'reviews': reviews, 'word_count': word_count(notice, developments)}


def generate_media(client, edition, directory):
    from main import generate_images
    from charts import create_charts, get_beyond_meat_bond_chart, extract_egg_price_chart
    generated = generate_images(client, edition)
    chosen = set(CHART_TITLES)
    started = time.time_ns()
    jobs = []
    if chosen & {'bynd-chart', 'otly-chart', 'sp500-chart'}:
        jobs.append(create_charts)
    if 'beyond-meat-bond-chart' in chosen:
        jobs.append(get_beyond_meat_bond_chart)
    if 'egg-price-chart' in chosen:
        jobs.append(extract_egg_price_chart)
    for job in jobs:
        try:
            job()
        except Exception:
            logging.exception('Optional chart generation failed')
    for key in chosen:
        path = Path(CHART_PATHS[key + '.png'])
        if path.exists() and path.stat().st_mtime_ns >= started:
            generated[key] = str(path)
        else:
            logging.warning('Omitting unavailable or stale optional chart %s', key)
    saved = {}
    for key, path in generated.items():
        destination = directory / (key + '.png')
        shutil.copyfile(path, destination)
        saved[key] = str(destination)
    return saved


def make_preview(client, fallback, sources_by_topic, freshness, history, policy,
                 directory, template, *, replay=None):
    from briefing import save_json, remember_rejections
    directory.mkdir(parents=True, mode=0o700)
    usage_start = len(TEXT_USAGE)
    base = {'window_start': freshness.start.isoformat(),
            'window_end_exclusive': freshness.end.isoformat(), 'policy': policy.model_dump()}
    save_json(directory / 'research-input.json', {**base, 'sources_by_topic': sources_by_topic,
                                                'history': history})
    decisions, developments, final_reviews = [], [], []
    try:
        if replay is None:
            developments, decisions = research_developments(client, fallback, sources_by_topic,
                                                            freshness, history, policy)
        else:
            developments = replay
        save_json(directory / 'developments.json', {**base, 'developments': developments, 'history': history})
        edition, selected, review = compose_with_recovery(
            client, fallback, developments, freshness, policy, history, directory)
        final_reviews = review.get('reviews', [])
        save_json(directory / 'edition.json', edition.model_dump())
        save_json(directory / 'final-review.json', review)
        # Frozen-evidence comparisons exercise writing/review without live media data.
        images = generate_media(fallback, edition, directory) if replay is None and not review.get('service_notice') else {}
        markup = render_edition(template, edition, developments, images)
        (directory / 'newsletter.html').write_text(markup)
        save_json(directory / 'delivery.json', {
            'pipeline': 'editor', 'replay_only': replay is not None,
            'service_notice': review.get('service_notice', False),
            'edition_date': freshness.end.date().isoformat(), 'subject': edition.subject,
            'selected': selected, 'images': images,
            'image_sha256': {key: hashlib.sha256(Path(path).read_bytes()).hexdigest() for key, path in images.items()},
            'html_sha256': hashlib.sha256(markup.encode()).hexdigest()})
    except EditionReviewError as exc:
        final_reviews = exc.reviews
        save_json(directory / 'final-review.json', {'approved': False, 'reviews': exc.reviews})
        save_json(directory / 'rejected-draft.json', exc.draft)
        raise
    finally:
        decisions = [d for d in freshness.pipeline_audit if d.get('stage') == 'verification'] or decisions
        by_id = {d['source_id']: d for d in developments}
        for review in final_reviews:
            for sid in review.get('rejected_development_ids', []):
                if sid in by_id:
                    decision = {'stage': 'final_review_rejection',
                        'candidate': {'source_id': sid, 'title': by_id[sid]['title']},
                        'verdict': {'accepted': False, 'event_key': by_id[sid]['event_key'],
                                    'reason': '; '.join(review.get('issues', []))}}
                    decisions.append(decision)
                    freshness.pipeline_audit.append(decision)
        if replay is None:
            remember_rejections(decisions, freshness.start, freshness.end)
        save_json(directory / 'audit.json', {**base, 'sources': freshness.audit,
            'pipeline': freshness.pipeline_audit, 'decisions': decisions,
            'model': AI_MODEL, 'text_usage': TEXT_USAGE[usage_start:]})
    return decisions
