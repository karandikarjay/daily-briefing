"""Narrative source links and email-safe warm magazine rendering."""
from html import escape
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from editor.rendering import CHART_TITLES


def linked_text(paragraph, sources):
    spans = []
    for cite in paragraph.citations:
        source = sources[cite.source_id]
        url = source.get('url')
        if not cite.link_text or not url:
            continue
        if urlparse(url).scheme not in ('https', 'http'):
            raise ValueError('Unsafe citation URL')
        lo = paragraph.text.find(cite.link_text)
        if lo < 0:
            raise ValueError('Source link text is absent from paragraph')
        hi = lo + len(cite.link_text)
        if any(lo < end and hi > start for start, end, _ in spans):
            raise ValueError('Overlapping source links')
        spans.append((lo, hi, url))
    output, previous = [], 0
    for lo, hi, url in sorted(spans):
        output.extend([escape(paragraph.text[previous:lo]),
            f'<a href="{escape(url, quote=True)}" style="color:#3c6951;text-decoration:underline;">{escape(paragraph.text[lo:hi])}</a>'])
        previous = hi
    output.append(escape(paragraph.text[previous:]))
    return ''.join(output)


def render(edition, sources, images, chart_data, template, *, placeholders=False):
    pieces = []
    if not edition.stories:
        pieces.append('<p>No new developments passed selection and verification for this edition.</p>')
    for i, story in enumerate(edition.stories, 1):
        size = '22px' if story.brief else '28px'
        pieces.append(f'<section class="story" style="margin:0 0 26px;padding:0 0 24px;border-bottom:1px solid #dcded2;">'
                      f'<h2 style="font-family:Georgia,serif;font-size:{size};line-height:1.2;font-weight:400;margin:0 0 16px;color:#262b25;">{escape(story.headline)}</h2>')
        key = f'story_image_{i}'
        if story.image_description and (key in images or placeholders):
            pieces.append(f'<img width="580" style="display:block;width:100%;max-width:580px;height:auto;border:0;" src="cid:{key}" alt="AI-generated conceptual illustration: {escape(story.headline, quote=True)}">')
            pieces.append(f'<p class="muted" style="font-size:12px;line-height:1.5;color:#606854;margin:8px 0 18px;">AI-generated illustration. {escape(story.image_caption or "Conceptual scene.")}</p>')
        for p in story.paragraphs:
            pieces.append(f'<p style="font-size:16px;line-height:1.65;margin:0 0 14px;">{linked_text(p, sources)}</p>')
        pieces.append('</section>')
    notes = {n.key: n.text for n in edition.market_notes}
    keys = [k for k in CHART_TITLES if k in images or placeholders]
    if keys:
        pieces.append('<h2 style="font-family:Georgia,serif;font-size:25px;font-weight:400;margin:0 0 22px;">Markets and prices</h2>')
    for key in keys:
        pieces.append(f'<section style="margin-bottom:26px;"><h3 style="font-size:17px;font-weight:400;margin:0 0 10px;">{escape(CHART_TITLES[key])}</h3>')
        pieces.append(f'<img width="580" style="width:100%;height:auto;display:block;" src="cid:{key}" alt="{escape(CHART_TITLES[key])} chart">')
        if key in notes:
            pieces.append(f'<p style="font-size:15px;line-height:1.6;margin:10px 0;">{escape(notes[key])}</p>')
        data = chart_data.get(key, {})
        if data.get('source_url'):
            pieces.append(f'<p class="muted" style="font-size:12px;color:#606854;margin:8px 0;">'
                          f'<a style="color:#3c6951;" href="{escape(data["source_url"], quote=True)}">{escape(data.get("source_name", "Data source"))}</a></p>')
        pieces.append('</section>')
    return template.replace('{newsletter_content}', '\n'.join(pieces))


def word_count(edition, sources, chart_data, template):
    text = BeautifulSoup(render(edition, sources, {}, chart_data, template, placeholders=True), 'html.parser').get_text(' ', strip=True)
    return len((edition.subject+' '+text).split())
