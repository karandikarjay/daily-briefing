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
from content.content_manager import limit_content_by_tokens
from content.freshness import Freshness, in_window, date_interval
from content.verification import select_verified, ask, FinalReview
from models.data_models import StoryBullet
from utils.api_utils import get_content_collection_timeframe, num_tokens_from_string
from utils.logging_setup import setup_logging
from utils.email_utils import send_email
from utils.html_utils import generate_email_html

ROOT = Path(__file__).resolve().parent
STATE = Path(os.environ.get('BRIEFING_STATE_DIR', str(ROOT / 'state')))


def load_history():
    path = STATE / 'history.json'
    if not path.exists():
        return []
    history = json.loads(path.read_text())
    return history[-1000:]


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
    return interval[0].astimezone(TIMEZONE).strftime('%b %d, %Y, %I:%M %p %Z')


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
            label = 'Published'
        else:
            attribution = html.escape(f'{evidence.get("email_sender") or "FAST Email List"}: {evidence.get("email_subject") or "Announcement"}')
            label = 'Email received'
        attribution += f' — {label}: {html.escape(display_date(evidence["published_at"]))}; announcement: {html.escape(display_date(evidence["announcement_date"]))}'
        story.bullets = [b for b in story.bullets if b.label.rstrip(':').lower() != 'go deeper']
        story.bullets.append(StoryBullet(label='Go deeper', text=attribution))
    return selected


def deliver(directory, everyone=False):
    payload = json.loads((directory / 'delivery.json').read_text())
    newsletter = (directory / 'newsletter.html').read_text()
    if hashlib.sha256(newsletter.encode()).hexdigest() != payload['html_sha256']:
        raise ValueError('Preview changed since validation; regenerate before sending')
    # Exclusive marker prevents blind retries after an uncertain SMTP outcome.
    marker = directory / ('group-send-attempt.json' if everyone else 'personal-send-attempt.json')
    local, domain = GOOGLE_USERNAME.split('@')
    with marker.open('x') as f:
        json.dump({'status': 'started', 'at': datetime.now(TIMEZONE).isoformat(), 'personal_to': f'{local}+list@{domain}', 'group': everyone}, f)
    os.chmod(marker, 0o600)
    subject = payload['subject'] if everyone else '[Preview] ' + payload['subject']
    success = send_email(newsletter, subject, everyone, payload['images'])
    save_json(marker, {'status': 'smtp_accepted' if success else 'failed_or_uncertain_do_not_retry', 'at': datetime.now(TIMEZONE).isoformat(), 'group': everyone, 'subject': subject})
    if not success:
        raise RuntimeError('SMTP did not confirm full delivery; inspect Sent before retrying')
    # Personal tests must not suppress stories for the regular group edition.
    if everyone:
        history = load_history()
        history.extend({k: n.get(k) for k in ('source_id', 'event_key', 'announcement_date', 'source_link', 'title', 'topic')} for n in payload['selected'])
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
        history = load_history()
        all_news, decisions = [], []
        for section in SECTIONS:
            sources = freshness.filter(get_content(section['title']))
            sources = [s for s in sources if not any(s['source_id'] == h.get('source_id') for h in history)]
            if section['title'] == 'Vegan Movement':
                # Preserve the established priority for firsthand FAST announcements.
                emails = limit_content_by_tokens([s for s in sources if s['source_type'] == 'email'], 20000, 'FAST')
                budget = max(0, 20000 - num_tokens_from_string(json.dumps(emails)))
                articles = limit_content_by_tokens([s for s in sources if s['source_type'] == 'article'], budget, 'Vegan Movement articles')
                sources = emails + articles
            else:
                sources = limit_content_by_tokens(sources, 20000, section['title'])
            verified, audit = select_verified(client, fallback, section, sources, freshness, history)
            all_news.extend(verified)
            decisions.extend(audit)
        stamp = datetime.now(TIMEZONE).strftime('%Y%m%d-%H%M%S')
        directory = ROOT / 'previews' / stamp
        directory.mkdir(parents=True, mode=0o700)
        save_json(directory / 'audit.json', {'window_start': start.isoformat(), 'window_end_exclusive': end.isoformat(), 'model': AI_MODEL, 'sources': freshness.audit, 'decisions': decisions})
        if all_news:
            newsletter, subject = generate_cohesive_newsletter(client, fallback, all_news, prompt_logger)
            selected = validate_stories(newsletter, all_news, start, end)
            if not selected:
                raise ValueError('Writer returned no stories despite verified inputs')
            review = ask(client, fallback, FinalReview, '''
Check the drafted newsletter against the supplied verified evidence and topic requirements. Approve only
if every factual claim is supported, each headline/What describes the verified new
announcement, and no historical fact is recast as current. 'Why it matters' may offer
clearly framed analysis, but must not invent facts or current comparisons. Ignore
illustration descriptions. Check source IDs, quoted numbers, dates, and entities.
Reject substantive unsupported claims. Return a short reason.
''', {'newsletter': newsletter.model_dump(), 'verified_evidence': selected, 'topic_requirements': {s['title']: s['prompt'] for s in SECTIONS}})
            save_json(directory / 'final-review.json', review.model_dump())
            if not review.approved:
                raise ValueError('Final factual review rejected newsletter: ' + review.reason)
        else:
            from models.data_models import AxiosNewsletterResponse
            newsletter = AxiosNewsletterResponse(subject='Future Appetite: Quiet news day', intro='No verified new developments met the freshness checks for this edition.', stories=[])
            subject, selected = newsletter.subject, []
        present = {n['topic'] for n in selected}
        quiet = [s['title'] for s in SECTIONS if s['title'] not in present]
        newsletter.closing = ' '.join(f'{topic}: No verified new developments in this window.' for topic in quiet) or None
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
        rendered = generate_email_html(Path(TEMPLATE_PATH).read_text(), newsletter, saved_images)
        rendered = rendered.replace('</body>', f'<p style="font-size:12px;color:#777">News window: {html.escape(display_date(start.isoformat()))} to {html.escape(display_date(end.isoformat()))} (exclusive).</p></body>')
        (directory / 'newsletter.html').write_text(rendered)
        save_json(directory / 'delivery.json', {'subject': subject, 'selected': selected, 'images': saved_images, 'html_sha256': hashlib.sha256(rendered.encode()).hexdigest()})
        logging.info('Validated preview saved to %s', directory)
        if not args.dry_run:
            deliver(directory, everyone=args.send_to_everyone)


if __name__ == '__main__':
    run()
