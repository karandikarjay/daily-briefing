#!/usr/bin/env python3
"""Compare saved editions locally; never calls APIs or sends email."""
import argparse
import json
from pathlib import Path
from bs4 import BeautifulSoup


def summarize(directory):
    directory = Path(directory)
    delivery = json.loads((directory / 'delivery.json').read_text())
    review = json.loads((directory / 'final-review.json').read_text())
    soup = BeautifulSoup((directory / 'newsletter.html').read_text(), 'html.parser')
    content = soup.select_one('.content') or soup.body or soup
    audit = json.loads((directory / 'audit.json').read_text())
    result = {'directory': str(directory.resolve()), 'subject': delivery['subject'],
        'edition_date': delivery.get('edition_date'), 'pipeline': delivery.get('pipeline', 'legacy'),
        'headlines': [h.get_text(' ', strip=True) for h in soup.select('.story-header')],
        'words': len(content.get_text(' ', strip=True).split()),
        'selected_topics': [s['topic'] for s in delivery['selected']],
        'selected_events': [s['event_key'] for s in delivery['selected']],
        'approved': review['approved'], 'review_attempts': len(review.get('reviews', [])),
        'research_budget': [r for r in audit.get('pipeline', []) if r.get('stage') == 'research_budget'],
        'text_usage': audit.get('text_usage', [])}
    edition_path = directory / 'edition.json'
    if edition_path.exists():
        result['omissions'] = json.loads(edition_path.read_text()).get('omissions', [])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previews', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps([summarize(p) for p in args.previews], indent=2))
