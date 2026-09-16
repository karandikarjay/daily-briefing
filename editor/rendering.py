"""Controlled HTML for flexible editions; model text is always escaped."""
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr
from html import escape
from urllib.parse import urlparse
from bs4 import BeautifulSoup

CHART_TITLES = {
    'bynd-chart': 'Beyond Meat stock', 'beyond-meat-bond-chart': 'Beyond Meat bond',
    'otly-chart': 'Oatly stock', 'sp500-chart': 'S&P 500', 'egg-price-chart': 'US egg prices',
}


def evidence_map(developments):
    result = {}
    for item in developments:
        for source in item.get('evidence_sources', []):
            result[source['source_id']] = source
    return result


def source_label(source):
    name = source.get('source_name') or 'Source'
    if source.get('source_type') == 'email':
        def decoded(value):
            try:
                return str(make_header(decode_header(value)))
            except (LookupError, UnicodeError):
                return value
        sender = decoded(source.get('email_sender') or name)
        sender = parseaddr(sender)[0] or sender
        name = f"{sender}: {decoded(source.get('subject') or 'Announcement')}"
    return name


def attribution(source, date=None):
    label = escape(source_label(source))
    url = source.get('url')
    if url and urlparse(url).scheme in ('http', 'https'):
        label = f'<a href="{escape(url, quote=True)}">{label}</a>'
    value = date or (source.get('published_at') or '')[:10]
    if value:
        value = datetime.fromisoformat(value).strftime('%b %d, %Y')
        label += ' — ' + escape(value)
    return label


def render_content(edition, developments, images=None, *, placeholders=False):
    images = images or {}
    sources = evidence_map(developments)
    by_id = {d['source_id']: d for d in developments}
    pieces = []
    if edition.intro:
        pieces.append(f'<p class="intro-text">{escape(edition.intro)}</p>')
    for index, story in enumerate(edition.stories, 1):
        pieces.append(f'<div class="story-section"><h2 class="story-header">{escape(story.headline)}</h2>')
        image_id = f'story_image_{index}'
        if story.image_description and (image_id in images or placeholders):
            pieces.append(f'<img class="story-image" src="cid:{image_id}" alt="AI-generated illustration: {escape(story.headline, quote=True)}">')
            caption = story.image_caption or 'Illustration'
            pieces.append(f'<p class="image-caption">{escape(caption)}</p>')
        pieces.append('<div class="story-content">')
        cited = []
        for paragraph in story.paragraphs:
            label = paragraph.label or ('The implication' if paragraph.kind == 'analysis' else '')
            prefix = f'<strong>{escape(label.rstrip(":"))}:</strong> ' if label else ''
            pieces.append(f'<p>{prefix}{escape(paragraph.text)}</p>')
            cited.extend(c.source_id for c in paragraph.citations)
        anchor_dates = {by_id[sid]['evidence_source_id']: by_id[sid]['announcement_date']
                        for sid in story.development_ids if sid in by_id}
        cited = list(dict.fromkeys(list(anchor_dates) + cited))
        links = [attribution(sources[sid], anchor_dates.get(sid)) for sid in cited if sid in sources]
        if links:
            pieces.append('<p class="go-deeper"><strong>Sources:</strong> ' + ' · '.join(links) + '</p>')
        pieces.append('</div></div>')
    if edition.closing:
        pieces.append(f'<p>{escape(edition.closing)}</p>')
    charts = [key for key in CHART_TITLES if key in images or placeholders]
    if charts:
        pieces.append('<div class="financial-section"><h2>Markets and prices</h2>')
        for key in charts:
            pieces.append(f'<div class="chart-item"><h3>{CHART_TITLES[key]}</h3>'
                          f'<img style="width:100%;height:auto" src="cid:{key}" alt="{CHART_TITLES[key]}"></div>')
        pieces.append('</div>')
    return '\n'.join(pieces)


def word_count(edition, developments):
    text = BeautifulSoup(render_content(edition, developments, placeholders=True), 'html.parser').get_text(' ', strip=True)
    return len((edition.subject + ' ' + text).split())


def render_edition(template, edition, developments, images):
    # The legacy renderer still uses the permanent chart section during rollback.
    soup = BeautifulSoup(template, 'html.parser')
    for block in soup.select('.financial-section'):
        block.decompose()
    return str(soup).replace('{newsletter_content}', render_content(edition, developments, images))
