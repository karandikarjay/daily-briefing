"""Verified briefing orchestration, previews, and delivery history."""
import argparse
import fcntl
import hashlib
import html
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

from anthropic import Anthropic
from openai import OpenAI
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, AI_MODEL, TEXT_FALLBACK_MODEL, SECTIONS, TEMPLATE_PATH, TIMEZONE, GOOGLE_USERNAME
from content import get_content
from content.ranking import selection_sources
from content.tavily_content import get_tavily_content
from content.freshness import Freshness, in_window, date_interval
from content.verification import select_verified, ask, FinalReview
from models.data_models import StoryBullet
from utils.api_utils import get_content_collection_timeframe
from utils.logging_setup import setup_logging
from utils.email_utils import send_email
from utils.html_utils import generate_email_html

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get('BRIEFING_STATE_DIR', str(ROOT / 'state')))


def load_history(include_rejections=False, replay_edition=False):
    path = STATE / 'history.json'
    history = json.loads(path.read_text())[-1000:] if path.exists() else []
    if replay_edition:
        _, end = get_content_collection_timeframe()
        history = [h for h in history if h.get('edition_date') != end.date().isoformat()]
    if include_rejections and (STATE / 'excluded-events.json').exists():
        start, end = get_content_collection_timeframe()
        rejected = json.loads((STATE / 'excluded-events.json').read_text())
        history += [r for r in rejected if r['window_start'] == start.isoformat() and r['window_end'] == end.isoformat()]
    return history


def remember_rejections(decisions, start, end):
    path = STATE / 'excluded-events.json'
    rejected = json.loads(path.read_text()) if path.exists() else []
    for decision in decisions:
        verdict = decision.get('verdict')
        if verdict and not verdict['accepted']:
            candidate = decision['candidate']
            rejected.append({
                'source_id': candidate['source_id'], 'title': candidate['title'],
                'event_key': verdict.get('event_key', ''), 'reason': verdict['reason'],
                'window_start': start.isoformat(), 'window_end': end.isoformat(),
                'status': 'previously_rejected_do_not_reintroduce_in_this_window',
            })
    unique = {(r['source_id'], r['window_start'], r['window_end']): r for r in rejected}
    save_json(path, list(unique.values())[-1000:])


def save_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2))
    os.chmod(temp, 0o600)
    temp.replace(path)


def display_date(value):
    interval = date_interval(value)
    if not interval:
        return value
    if interval[0] != interval[1]:
        return interval[0].strftime('%b %d, %Y')
    return interval[0].astimezone(TIMEZONE).strftime('%b %d, %Y')


def validate_stories(newsletter, verified, start, end):
    """Model-selected IDs cannot authorize an unverified source or date."""
    by_id = {n['source_id']: n for n in verified}
    topics, selected = set(), []
    for story in newsletter.stories:
        evidence = by_id.get(story.source_id)
        if not evidence or story.topic != evidence['topic'] or story.topic in topics:
            raise ValueError('Final story has an unknown source, wrong topic, or duplicate topic')
        if not in_window(evidence['published_at'], start, end):
            raise ValueError('Final source publication date is outside the window')
        topics.add(story.topic)
        selected.append(evidence)
        if evidence.get('source_link'):
            attribution = f'<a href="{html.escape(evidence["source_link"], quote=True)}">{html.escape(evidence["source_name"])}</a>'
        else:
            attribution = html.escape(f'{evidence.get("email_sender") or "FAST Email List"}: {evidence.get("email_subject") or "Announcement"}')
        attribution += f' — {html.escape(display_date(evidence["announcement_date"]))}'
        story.bullets = [b for b in story.bullets if b.label.rstrip(':').lower() != 'go deeper']
        story.bullets.append(StoryBullet(label='Go deeper', text=attribution))
    return selected


def review_stories(client, fallback, newsletter, selected):
    """A rejected final story is omitted; it cannot prevent valid topics being sent."""
    evidence = {n['source_id']: n for n in selected}
    kept, reviews = [], []
    for story in newsletter.stories:
        item = evidence[story.source_id]
        requirements = next(s['prompt'] for s in SECTIONS if s['title'] == story.topic)
        review = ask(client, fallback, FinalReview,
            "Check this story against its verified evidence and topic requirements. "
            "Approve only if every factual claim, date, number, entity and headline is "
            "supported and the central announcement is new within the verified window. "
            "Reject old events recast as new, unsupported comparisons and topic mismatches. "
            "Clearly framed analysis is allowed. Illustrations are not reporting.",
            {'story': story.model_dump(), 'verified_evidence': item, 'topic_requirements': requirements})
        reviews.append({'stage': 'final_review', 'topic': story.topic, 'source_id': story.source_id, **review.model_dump()})
        if review.approved:
            kept.append(story)
        else:
            logging.warning('Omitting final story %s: %s', story.headline, review.reason)
    newsletter.stories = kept
    refresh_summary(newsletter)
    return [evidence[s.source_id] for s in kept], {'approved': True, 'story_reviews': reviews}


def refresh_summary(newsletter):
    # Derive the intro/subject from approved headlines so removed facts cannot linger.
    kept = newsletter.stories
    if kept:
        newsletter.subject = kept[0].headline[:50]
        newsletter.intro = '<strong>' + datetime.now(TIMEZONE).strftime('Happy %A!') + '</strong> In this edition: ' + '; '.join(html.escape(s.headline) for s in kept) + '.'
    else:
        newsletter.subject = 'Future Appetite: Quiet news day'
        newsletter.intro = 'No verified new developments met the freshness checks for this edition.'


def compose_with_replacements(client, fallback, sources_by_topic, freshness, history, writer, discover=None):
    """Try another shortlist after a failed selection or final review, at most twice/topic."""
    from models.data_models import AxiosNewsletterResponse
    newsletter = AxiosNewsletterResponse(subject='', intro='', stories=[])
    selected, decisions, reviews = [], [], []
    attempted = set()
    sources_by_topic = {topic: list(items) for topic, items in sources_by_topic.items()}
    for attempt in range(2):
        present = {story.topic for story in newsletter.stories}
        batch = []
        for section in SECTIONS:
            if section['title'] in present:
                continue
            topic = section['title']
            if attempt == 1 and discover is not None:
                additions = freshness.filter(discover(topic), topic=topic, attempt=2)
                known = {s['source_id'] for s in sources_by_topic.get(topic, [])}
                sources_by_topic.setdefault(topic, []).extend(s for s in additions if s['source_id'] not in known)
            remaining = []
            for source in sources_by_topic.get(topic, []):
                reason = ('already_attempted' if source['source_id'] in attempted else
                          'previously_covered_or_rejected' if any(source['source_id'] == h.get('source_id') for h in history) else None)
                if reason:
                    freshness.pipeline_audit.append({'stage': 'history', 'topic': topic, 'attempt': attempt + 1,
                                                     'source_id': source['source_id'], 'accepted': False, 'reason': reason})
                else:
                    remaining.append(source)
            available = selection_sources(client, fallback, section, remaining, freshness.pipeline_audit, attempt + 1)
            verified, audit = select_verified(client, fallback, section, available, freshness, history)
            shortlisted = {d['candidate']['source_id'] for d in audit}
            for source in available:
                freshness.pipeline_audit.append({'stage': 'shortlist', 'topic': topic, 'attempt': attempt + 1,
                                                 'source_id': source['source_id'], 'accepted': source['source_id'] in shortlisted,
                                                 'reason': 'verification_attempted' if source['source_id'] in shortlisted else 'not_verified_in_shortlist'})
            for decision in audit:
                decision.update({'stage': 'verification', 'topic': topic, 'attempt': attempt + 1})
            attempted.update(d['candidate']['source_id'] for d in audit)
            attempted.update(n['source_id'] for n in verified)
            decisions.extend(audit)
            batch.extend(verified)
        if not batch:
            continue
        draft, _ = writer(client, fallback, batch)
        approved = validate_stories(draft, batch, freshness.start, freshness.end)
        approved, review = review_stories(client, fallback, draft, approved)
        selected.extend(approved)
        newsletter.stories.extend(draft.stories)
        reviews.extend(review['story_reviews'])
    order = {section['title']: i for i, section in enumerate(SECTIONS)}
    newsletter.stories.sort(key=lambda story: order[story.topic])
    refresh_summary(newsletter)
    return newsletter, selected, decisions, {'approved': True, 'story_reviews': reviews}


def deliver(directory, everyone=False):
    payload = json.loads((directory / 'delivery.json').read_text())
    newsletter = (directory / 'newsletter.html').read_bytes().decode('utf-8')
    if hashlib.sha256(newsletter.encode()).hexdigest() != payload['html_sha256']:
        raise ValueError('Preview changed since validation; regenerate before sending')
    # Exclusive marker prevents blind retries after an uncertain SMTP outcome.
    marker = directory / ('group-send-attempt.json' if everyone else 'personal-send-attempt.json')
    local, domain = GOOGLE_USERNAME.split('@')
    with marker.open('x') as f:
        json.dump({'status': 'started', 'at': datetime.now(TIMEZONE).isoformat(), 'personal_to': f'{local}+list@{domain}', 'group': everyone}, f)
    os.chmod(marker, 0o600)
    subject = payload['subject'] if everyone else '[Preview] ' + payload['subject']
    success = send_email(newsletter, subject, everyone, payload['images'], cleanup_images=False)
    save_json(marker, {'status': 'smtp_accepted' if success else 'failed_or_uncertain_do_not_retry', 'at': datetime.now(TIMEZONE).isoformat(), 'group': everyone, 'subject': subject})
    if not success:
        raise RuntimeError('SMTP did not confirm full delivery; inspect Sent before retrying')
    # Personal tests must not suppress stories for the regular group edition.
    if everyone:
        history = load_history()
        history.extend({**{k: n.get(k) for k in ('source_id', 'event_key', 'announcement_date', 'source_link', 'title', 'topic')}, 'edition_date': payload.get('edition_date')} for n in payload['selected'])
        save_json(STATE / 'history.json', history[-1000:])
    logging.info('Delivery completed: %s', marker)


def run():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true', help='Save a complete preview; never send email')
    modes.add_argument('--send-to-everyone', action='store_true', help='Production group delivery')
    modes.add_argument('--send-preview', type=Path, help='Send a previously validated preview only to the sender')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / 'run.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger, prompt_logger = setup_logging()
        if args.send_preview:
            deliver(args.send_preview.resolve(), everyone=False)
            return
        from main import generate_cohesive_newsletter, generate_images
        from charts import create_charts, extract_egg_price_chart, get_beyond_meat_bond_chart
        start, end = get_content_collection_timeframe()
        freshness = Freshness(start, end)
        client = Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=0)
        fallback = OpenAI(api_key=OPENAI_API_KEY, max_retries=0)
        logging.info('Verified briefing window [%s, %s); primary=%s fallback=%s', start, end, AI_MODEL, TEXT_FALLBACK_MODEL)
        history = load_history(include_rejections=True, replay_edition=not args.send_to_everyone)
        sources_by_topic = {}
        for section in SECTIONS:
            sources_by_topic[section['title']] = freshness.filter(
                get_content(section['title'], audit=freshness.pipeline_audit), topic=section['title'])
        newsletter, selected, decisions, review = compose_with_replacements(
            client, fallback, sources_by_topic, freshness, history,
            lambda c, f, items: generate_cohesive_newsletter(c, f, items, prompt_logger),
            discover=lambda topic: get_tavily_content(topic, rescue=True, audit=freshness.pipeline_audit,
                                                     window=(start, end)))
        remember_rejections(decisions, start, end)
        stamp = datetime.now(TIMEZONE).strftime('%Y%m%d-%H%M%S')
        directory = ROOT / 'previews' / stamp
        directory.mkdir(parents=True, mode=0o700)
        save_json(directory / 'audit.json', {'window_start': start.isoformat(), 'window_end_exclusive': end.isoformat(), 'model': AI_MODEL, 'sources': freshness.audit, 'pipeline': freshness.pipeline_audit, 'decisions': decisions})
        save_json(directory / 'final-review.json', review)
        subject = newsletter.subject
        present = {n['topic'] for n in selected}
        notices = {s['title']: 'No story passed selection and verification for this edition.' for s in SECTIONS if s['title'] not in present}
        newsletter.closing = None
        images = generate_images(fallback, newsletter)
        # Copy story images into the immutable preview before SMTP cleanup.
        import shutil
        saved_images = {}
        for key, path in images.items():
            destination = directory / (key + '.png')
            shutil.copyfile(path, destination)
            saved_images[key] = str(destination)
        create_charts()
        get_beyond_meat_bond_chart()
        extract_egg_price_chart()
        rendered = generate_email_html(Path(TEMPLATE_PATH).read_text(), newsletter, saved_images, section_notices=notices)
        (directory / 'newsletter.html').write_text(rendered)
        save_json(directory / 'delivery.json', {'edition_date': end.date().isoformat(), 'subject': subject, 'selected': selected, 'images': saved_images, 'html_sha256': hashlib.sha256(rendered.encode()).hexdigest()})
        logging.info('Validated preview saved to %s', directory)
        if not args.dry_run:
            deliver(directory, everyone=args.send_to_everyone)


if __name__ == '__main__':
    run()
