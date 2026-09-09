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


def publication_dates(html):
    soup = BeautifulSoup(html, 'html.parser')
    dates = []
    for tag in soup.find_all('meta'):
        name = (tag.get('property') or tag.get('name') or '').lower()
        if name in ('article:published_time', 'datepublished', 'date', 'pubdate', 'parsely-pub-date', 'dc.date.issued', 'citation_publication_date'):
            if tag.get('content'):
                dates.append({'value': tag['content'], 'kind': name})

    def walk(obj):
        if isinstance(obj, list):
            for child in obj:
                walk(child)
        elif isinstance(obj, dict):
            typ = obj.get('@type', [])
            typ = [typ] if isinstance(typ, str) else typ
            if any(t in ('Article', 'NewsArticle', 'BlogPosting', 'Report', 'ScholarlyArticle') for t in typ):
                if isinstance(obj.get('datePublished'), str):
                    dates.append({'value': obj['datePublished'], 'kind': 'jsonld.datePublished'})
            if '@graph' in obj:
                walk(obj['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            pass
    for tag in soup.select('time[datetime]'):
        classes = ' '.join(tag.get('class', [])).lower()
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

    def inspect(self, item):
        record = dict(item)
        record['source_id'] = source_id(record)
        record['retrieved_at'] = datetime.now(timezone.utc).isoformat()
        record['date_evidence'] = []
        if not record.get('url'):
            record['source_type'] = 'email'
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
                record['date_evidence'] = publication_dates(html)
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
        if valid:
            # Divergent original publication dates need resolution, not guessing.
            valid = max(x[0] for x in parsed) <= min(x[1] for x in parsed) + timedelta(minutes=5)
        # A precise publisher timestamp can resolve a matching date-only field.
        precise = [d['value'] for d in evidence if date_interval(d['value']) and date_interval(d['value'])[0] == date_interval(d['value'])[1]]
        chosen = precise[0] if precise else (evidence[0]['value'] if evidence else None)
        record['date_verified'] = valid and in_window(chosen, self.start, self.end) and all(in_window(v, self.start, self.end) for v in precise)
        record['published_at'] = chosen if valid else None
        record['datetime'] = record['published_at']
        return record

    def filter(self, items):
        accepted, seen = [], set()
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(self.inspect, items))
        for record in records:
            ok = record['date_verified']
            self.audit.append({'source_id': record['source_id'], 'url': record.get('url'), 'title': record.get('title', record.get('subject')), 'accepted': ok, 'reason': 'publication_in_window' if ok else 'missing_ambiguous_conflicting_or_out_of_window_date', 'date_evidence': record['date_evidence']})
            if ok and record['source_id'] not in seen:
                seen.add(record['source_id'])
                accepted.append(record)
        logging.info('Freshness: accepted %s of %s sources', len(accepted), len(items))
        return accepted


def quote_in(quote, text):
    normalize = lambda s: ' '.join(s.split()).casefold()
    return len(quote.strip()) >= 15 and normalize(quote) in normalize(text)
