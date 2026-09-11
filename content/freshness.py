"""Source-grounded publication dates. Discovery dates never authorize a story."""
import hashlib
import ipaddress
import json
import logging
import re
import socket
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, urljoin, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup
from config import HEADERS, TIMEZONE


def canonical_url(url):
    p = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith('utm_') and k not in ('fbclid', 'gclid')]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), '', urlencode(query), ''))


def source_id(item):
    key = canonical_url(item['url']) if item.get('url') else '|'.join(str(item.get(k, '')) for k in ('message_id', 'subject', 'datetime', 'body'))
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def date_interval(value):
    """Do not invent midnight or a timezone for imprecise timestamps."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            lo = datetime.fromisoformat(value).replace(tzinfo=TIMEZONE)
            return lo, lo + timedelta(days=1)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        return None
    return dt, dt


def in_window(value, start, end):
    interval = date_interval(value)
    if not interval:
        return False
    lo, hi = interval
    # Half-open windows prevent the 06:00 boundary appearing twice.
    return start <= lo < end and hi <= end


def publication_dates(html, url=None):
    soup = BeautifulSoup(html, 'html.parser')
    dates = []
    for tag in soup.find_all('meta'):
        name = (tag.get('property') or tag.get('name') or '').lower()
        if name in ('article:published_time', 'datepublished', 'date', 'pubdate', 'parsely-pub-date', 'dc.date.issued', 'citation_publication_date'):
            if tag.get('content'):
                dates.append({'value': tag['content'], 'kind': name})

    def belongs_to_page(obj):
        if not url:
            return True
        identity = obj.get('mainEntityOfPage') or obj.get('url') or obj.get('@id')
        if isinstance(identity, dict):
            identity = identity.get('@id') or identity.get('url')
        return not isinstance(identity, str) or canonical_url(urljoin(url, identity)) == canonical_url(url)

    def walk(obj):
        if isinstance(obj, list):
            for child in obj:
                walk(child)
        elif isinstance(obj, dict):
            typ = obj.get('@type', [])
            typ = [typ] if isinstance(typ, str) else typ
            if any(t in ('Article', 'NewsArticle', 'BlogPosting', 'Report', 'ScholarlyArticle') for t in typ):
                if belongs_to_page(obj) and isinstance(obj.get('datePublished'), str):
                    dates.append({'value': obj['datePublished'], 'kind': 'jsonld.datePublished'})
            if '@graph' in obj:
                walk(obj['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            pass
    # Only the main article's byline dates belong to this URL. Related cards,
    # navigation and sidebars routinely contain unrelated publication dates.
    heading = soup.find('h1')
    scope = heading.find_parent('article') if heading else None
    if scope is None and heading:
        scope = heading.find_parent('main')
    if scope:
        for tag in scope.select('time[datetime]'):
            if tag.find_parent(['aside', 'nav', 'footer']):
                continue
            ancestors = []
            for parent in tag.parents:
                if parent is scope:
                    break
                ancestors.append(parent)
            if any(re.search(r'related|sidebar|recommend|newsletter|comment',
                             ' '.join(parent.get('class', [])), re.I) for parent in ancestors):
                continue
            owner = tag.find_parent('article')
            if owner is not None and owner is not scope:
                continue
            classes = ' '.join(tag.get('class', [])).lower()
            label = tag.get_text(' ', strip=True).lower()
            if tag.get('itemprop') == 'dateModified' or re.search(r'last updated|modified|updated on', label):
                continue
            if tag.get('itemprop') == 'datePublished' or 'published' in classes:
                dates.append({'value': tag['datetime'], 'kind': 'visible.time.published'})
    return dates


def safe_fetch(url):
    """Bound requests and redirects; article URLs cannot target private services."""
    for _ in range(5):
        p = urlparse(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            raise ValueError('Invalid public article URL')
        for addr in socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80)):
            if not ipaddress.ip_address(addr[4][0]).is_global:
                raise ValueError('Non-public article address')
        with requests.get(url, headers=HEADERS, timeout=(8, 15), allow_redirects=False, stream=True) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            response.raise_for_status()
            if 'html' not in response.headers.get('Content-Type', '').lower():
                raise ValueError('Not an HTML article')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 3_000_000:
                    raise ValueError('Article exceeds size limit')
                chunks.append(chunk)
            return url, b''.join(chunks).decode(response.encoding or 'utf-8', errors='replace')
    raise ValueError('Too many redirects')


class Freshness:
    def __init__(self, start, end):
        self.start, self.end = start, end
        self.cache = {}
        self.audit = []
        self.pipeline_audit = []

    def inspect(self, item):
        record = dict(item)
        record['source_id'] = source_id(record)
        record['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        record['date_evidence'] = []
        if not record.get('url'):
            record['source_type'] = 'email'
            body = record.get('body', '')
            if re.search(r'<[A-Za-z!/][^>]*>', body):
                record['body'] = BeautifulSoup(body, 'html.parser').get_text(' ', strip=True)
            record['received_at'] = record.get('datetime')
            # This only validates receipt; event verification still checks novelty.
            record['date_evidence'] = [{'value': record.get('datetime'), 'kind': 'email.received'}]
        else:
            record['source_type'] = 'article'
            url = canonical_url(record['url'])
            if url not in self.cache:
                try:
                    self.cache[url] = safe_fetch(url)
                except Exception as exc:
                    self.cache[url] = None
                    logging.info('Date fetch unavailable %s: %s', url, type(exc).__name__)
            fetched = self.cache[url]
            if fetched:
                final_url, html = fetched
                record['url'] = canonical_url(final_url)
                record['source_id'] = source_id(record)
                record['date_evidence'] = publication_dates(html, final_url)
                soup = BeautifulSoup(html, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer']):
                    tag.decompose()
                article = soup.find('article') or soup.find('main') or soup.body or soup
                record['article'] = article.get_text(' ', strip=True)[:24000]
            # RSS publication dates are publisher-provided; search/lastmod are not.
            if record.get('date_kind') == 'rss.published':
                record['date_evidence'].append({'value': record.get('datetime'), 'kind': 'rss.published'})
        evidence = record['date_evidence']
        parsed = [date_interval(d['value']) for d in evidence]
        valid = bool(evidence) and all(parsed)
        precise = [d['value'] for d, interval in zip(evidence, parsed)
                   if interval and interval[0] == interval[1]]
        precise_dates = [date_interval(value)[0] for value in precise]
        reason = 'missing_publication_date' if not evidence else 'ambiguous_publication_date'
        if valid:
            if precise_dates:
                valid = max(precise_dates) - min(precise_dates) <= timedelta(minutes=5)
                # Date-only fields use the publisher's calendar, not an invented
                # midnight in New York. Precise, offset-aware dates resolve them.
                calendars = {d.date().isoformat() for d in precise_dates}
                calendars.update(d.astimezone(TIMEZONE).date().isoformat() for d in precise_dates)
                valid = valid and all(d['value'] in calendars for d, interval in zip(evidence, parsed)
                                      if interval[0] != interval[1])
            else:
                valid = len({x[0] for x in parsed}) == 1
            reason = 'conflicting_publication_dates'
        chosen = precise[0] if precise else (evidence[0]['value'] if evidence else None)
        record['date_verified'] = bool(valid and in_window(chosen, self.start, self.end)
                                       and all(in_window(v, self.start, self.end) for v in precise))
        record['date_reason'] = ('publication_in_window' if record['date_verified'] else
                                 'publication_out_of_window' if valid else reason)
        record['published_at'] = chosen if valid else None
        record['datetime'] = record['published_at']
        return record

    def filter(self, items, topic=None, attempt=1):
        accepted, seen = [], set()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(self.inspect, items))
        for record in records:
            ok = record['date_verified']
            self.audit.append({'source_id': record['source_id'], 'url': record.get('url'), 'title': record.get('title', record.get('subject')), 'accepted': ok, 'stage': 'publication', 'topic': topic, 'attempt': attempt, 'reason': record['date_reason'], 'date_evidence': record['date_evidence']})
            if ok and record['source_id'] not in seen:
                seen.add(record['source_id'])
                accepted.append(record)
        logging.info('Freshness: accepted %s of %s sources', len(accepted), len(items))
        return accepted


def quote_in(quote, text):
    normalize = lambda s: ' '.join(s.split()).casefold()
    return len(quote.strip()) >= 15 and normalize(quote) in normalize(text)
