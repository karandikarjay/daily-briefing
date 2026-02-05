"""
Tavily web search content retrieval module for the Daily Briefing application.

This module uses the Tavily Search API to discover recent news articles
across configured topic areas.
"""

import logging
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse

from config import TAVILY_API_KEY, TAVILY_QUERIES, TAVILY_MAX_RAW_CONTENT_CHARS, TIMEZONE
from utils.api_utils import get_content_collection_timeframe


def _get_search_days() -> int:
    """Calculate the number of days to search based on the content collection timeframe."""
    start_time, end_time = get_content_collection_timeframe()
    delta = end_time - start_time
    # Round up to at least 1 day
    return max(1, delta.days + (1 if delta.seconds > 0 else 0))


def _extract_domain(url: str) -> str:
    """Extract a clean domain name from a URL (e.g. 'reuters.com')."""
    try:
        hostname = urlparse(url).hostname or ""
        # Strip leading 'www.'
        if hostname.startswith("www."):
            hostname = hostname[4:]
        return hostname
    except Exception:
        return "unknown"


def get_tavily_content(section_title: str) -> List[Dict[str, str]]:
    """
    Retrieve recent news articles for a section using Tavily web search.

    Args:
        section_title: One of the keys in TAVILY_QUERIES (e.g. "Alternative Protein")

    Returns:
        List of dicts with keys: url, title, article, datetime, source_name
    """
    if not TAVILY_API_KEY:
        logging.warning("TAVILY_API_KEY not set — skipping Tavily search")
        return []

    queries = TAVILY_QUERIES.get(section_title)
    if not queries:
        logging.warning(f"No Tavily queries configured for section: {section_title}")
        return []

    try:
        from tavily import TavilyClient
    except ImportError:
        logging.error("tavily-python package not installed. Run: pip install tavily-python")
        return []

    client = TavilyClient(api_key=TAVILY_API_KEY)
    days = _get_search_days()
    start_time, end_time = get_content_collection_timeframe()
    seen_urls: set = set()
    results: List[Dict[str, str]] = []

    logging.info(f"Tavily [{section_title}]: filtering articles from {start_time} to {end_time}")

    for query in queries:
        try:
            logging.info(f"Tavily search [{section_title}]: '{query}' (days={days})")
            response = client.search(
                query=query,
                topic="news",
                search_depth="advanced",
                include_raw_content=True,
                days=days,
                max_results=5,
            )

            for item in response.get("results", []):
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                raw_content = item.get("raw_content") or item.get("content", "")
                if TAVILY_MAX_RAW_CONTENT_CHARS and len(raw_content) > TAVILY_MAX_RAW_CONTENT_CHARS:
                    raw_content = raw_content[:TAVILY_MAX_RAW_CONTENT_CHARS]

                # Parse published_date and filter against the exact timeframe
                published = item.get("published_date")
                dt = None
                if published:
                    try:
                        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                        dt = dt.astimezone(TIMEZONE)
                    except (ValueError, TypeError):
                        dt = None

                if dt and not (start_time <= dt <= end_time):
                    logging.info(
                        f"Tavily [{section_title}]: skipping '{item.get('title', '')[:60]}' "
                        f"— published {dt.isoformat()} is outside timeframe"
                    )
                    continue

                dt_str = dt.isoformat() if dt else datetime.now(TIMEZONE).isoformat()

                results.append({
                    "url": url,
                    "title": item.get("title", ""),
                    "article": raw_content,
                    "datetime": dt_str,
                    "source_name": _extract_domain(url),
                })

        except Exception:
            logging.exception(f"Tavily search failed for query '{query}' in [{section_title}]")
            continue

    logging.info(f"Tavily [{section_title}]: collected {len(results)} unique articles from {len(queries)} queries")
    return results
