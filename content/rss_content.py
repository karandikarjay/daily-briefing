"""
RSS content retrieval module for the Daily Briefing application.

This module provides functions for retrieving content from RSS feeds.
"""

import logging
import requests
import feedparser
import xml.etree.ElementTree as ET
import re
import json
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Callable
from zoneinfo import ZoneInfo
from utils.html_utils import clean_html_content
from utils.api_utils import num_tokens_from_string
from config import HEADERS, RUNDOWN_RSS_URL, VEGCONOMIST_RSS_URL, EA_FORUM_RSS_URL
import time

def fetch_and_parse_rss(rss_url: str) -> Optional[feedparser.FeedParserDict]:
    """
    Fetches and parses an RSS feed.
    
    Args:
        rss_url: URL of the RSS feed
        
    Returns:
        Parsed feed or None if retrieval fails
    """
    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            logging.warning(f"No entries found in RSS feed: {rss_url}")
            return None
        return feed
    except Exception as e:
        logging.exception(f"Error fetching or parsing RSS feed: {rss_url}")
        return None

def get_most_recent_entry(feed: feedparser.FeedParserDict) -> Optional[Dict]:
    """
    Gets the most recent entry from a parsed feed.
    
    Args:
        feed: Parsed feed
        
    Returns:
        Most recent entry or None if no entries
    """
    if not feed or not feed.entries:
        return None
    
    entries_sorted = sorted(feed.entries, key=lambda entry: entry.published_parsed, reverse=True)
    return entries_sorted[0]

def fetch_article_content(url: str, content_selector: str) -> Optional[str]:
    """
    Fetches and extracts article content from a URL.
    
    Args:
        url: Article URL
        content_selector: CSS selector for the content container
        
    Returns:
        Extracted article text or None if retrieval fails
    """
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Split the selector into tag and id parts
        tag, selector_value = content_selector.split(':', 1)
        
        # Find the content using the tag and explicit id parameter
        content = soup.find(tag, id=selector_value)
        
        if content:
            article_text = content.get_text(separator="\n", strip=True)
            return article_text
        else:
            logging.error(f"Content container '{content_selector}' not found in article: {url}")
            return None
    except Exception as e:
        logging.exception(f"Error retrieving content from {url}")
        return None

def get_single_article_from_rss(rss_url: str, content_selector: str, source_name: str) -> Optional[Dict[str, str]]:
    """
    Retrieves the most recent article from an RSS feed.
    
    Args:
        rss_url: URL of the RSS feed
        content_selector: CSS selector for the content container
        source_name: Name of the source for logging
        
    Returns:
        Dictionary with URL and article text, or None if retrieval fails
    """
    feed = fetch_and_parse_rss(rss_url)
    if not feed:
        return None
    
    most_recent = get_most_recent_entry(feed)
    if not most_recent:
        return None
    
    article_url = most_recent.link
    article_text = fetch_article_content(article_url, content_selector)
    
    if article_text:
        return {"url": article_url, "article": article_text}
    else:
        logging.error(f"Failed to extract content from {source_name} article: {article_url}")
        return None

def get_rundown_content() -> Optional[Dict[str, str]]:
    """
    Retrieves the most recent content from The Rundown RSS feed.
    
    Returns:
        Optional[Dict[str, str]]: A dictionary with URL and article text, or None if retrieval fails
    """
    return get_single_article_from_rss(RUNDOWN_RSS_URL, "div:content-blocks", "The Rundown")

def get_articles_within_timeframe(
    feed_data: Any, 
    hours_window: int,
    extract_datetime_fn: Callable,
    extract_content_fn: Callable,
    source_name: str,
    max_tokens: Optional[int] = None
) -> List[Dict[str, str]]:
    """
    Generic function to extract articles within a time window from a feed.
    
    Args:
        feed_data: The feed data (could be feedparser result or XML)
        hours_window: Number of hours to look back from the most recent article
        extract_datetime_fn: Function to extract datetime from an entry
        extract_content_fn: Function to extract content from an entry
        source_name: Name of the source for logging
        max_tokens: Maximum token limit (optional)
        
    Returns:
        List of article dictionaries
    """
    articles_with_dates = []
    latest_datetime = None
    
    # First pass: find the most recent article timestamp
    try:
        entries = feed_data.entries if hasattr(feed_data, 'entries') else feed_data
        
        for entry in entries:
            try:
                pub_date = extract_datetime_fn(entry)
                if pub_date and (latest_datetime is None or pub_date > latest_datetime):
                    latest_datetime = pub_date
            except Exception as e:
                logging.exception(f"Error processing {source_name} entry timestamp")
                continue

        if latest_datetime is None:
            logging.error(f"No valid timestamps found in {source_name} feed")
            return []

        # Calculate the cutoff time
        cutoff_time = latest_datetime - timedelta(hours=hours_window)
        logging.info(f"{source_name}: Using articles between {cutoff_time} and {latest_datetime}")
        
        # Second pass: process each entry within the time window
        for entry in entries:
            try:
                pub_date = extract_datetime_fn(entry)
                
                if pub_date and cutoff_time <= pub_date <= latest_datetime:
                    article_data = extract_content_fn(entry)
                    if article_data:
                        article_data["datetime"] = pub_date  # Store for sorting
                        articles_with_dates.append(article_data)
            except Exception as e:
                entry_id = getattr(entry, 'link', 'unknown') if hasattr(entry, 'link') else 'unknown'
                logging.exception(f"Error processing {source_name} entry: {entry_id}")
                continue
                
        # Sort articles by date (oldest first)
        articles_with_dates.sort(key=lambda x: x["datetime"])
        
        # Create entries list without the datetime field
        articles = [{k: v for k, v in article.items() if k != "datetime"} for article in articles_with_dates]
        
        # Apply token limit if specified
        if max_tokens:
            articles = limit_articles_by_tokens(articles, max_tokens, source_name)
        
        logging.info(f"Extracted content from {len(articles)} {source_name} articles in the last {hours_window} hours")
        return articles
        
    except Exception as e:
        logging.exception(f"Error retrieving content from {source_name}")
        return []

def limit_articles_by_tokens(articles: List[Dict[str, str]], max_tokens: int, source_name: str) -> List[Dict[str, str]]:
    """
    Limits the number of articles to stay under a token limit.
    Removes oldest articles first.
    
    Args:
        articles: List of article dictionaries
        max_tokens: Maximum token limit
        source_name: Name of the source for logging
        
    Returns:
        Limited list of articles
    """
    total_tokens = sum(num_tokens_from_string(json.dumps(entry)) for entry in articles)
    logging.info(f"{source_name}: Initial collection has {len(articles)} articles with {total_tokens} tokens")
    
    while total_tokens > max_tokens and len(articles) > 1:
        # Remove the oldest article (first in the list since we sorted by date)
        removed_article = articles.pop(0)
        logging.info(f"{source_name}: Removed article '{removed_article.get('title', 'untitled')}' to reduce token count")
        
        # Recalculate token count
        total_tokens = sum(num_tokens_from_string(json.dumps(entry)) for entry in articles)
        logging.info(f"{source_name}: After removal, {len(articles)} articles with {total_tokens} tokens remain")
    
    return articles

def get_vegconomist_content() -> List[Dict[str, str]]:
    """
    Retrieves content from Vegconomist's RSS feed for the last 24 hours
    from the most recent article.
    
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL, title, and article text
    """
    feed = fetch_and_parse_rss(VEGCONOMIST_RSS_URL)
    if not feed:
        return []
    
    def extract_datetime(entry):
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            return pub_date.replace(tzinfo=timezone.utc)
        return None
    
    def extract_content(entry):
        content = entry.content[0].value if 'content' in entry else entry.description
        soup = BeautifulSoup(content, 'html.parser')
        
        for div in soup.find_all('div', class_='wp-caption'):
            div.decompose()
        
        article_text = soup.get_text(separator='\n', strip=True)
        
        return {
            "url": entry.link,
            "title": entry.title,
            "article": article_text
        }
    
    return get_articles_within_timeframe(
        feed_data=feed,
        hours_window=24,
        extract_datetime_fn=extract_datetime,
        extract_content_fn=extract_content,
        source_name="Vegconomist"
    )

def get_ea_forum_content() -> List[Dict[str, str]]:
    """
    Fetches the RSS feed from Effective Altruism Forum and returns a list of dictionaries
    for all articles published in the last 48 hours from the most recent post.
    
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL, title, and article text
    """
    feed_url = EA_FORUM_RSS_URL
    try:
        response = requests.get(feed_url)
        response.raise_for_status()
        xml_content = response.text

        # Parse the XML content
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        if channel is None:
            logging.warning("No channel found in EA Forum feed")
            return []

        # Extract all <item> elements
        items = channel.findall("item")
        
        def extract_datetime(item):
            pub_date_elem = item.find("pubDate")
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    pub_date_str = pub_date_elem.text.strip()
                    dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S GMT")
                    dt = dt.replace(tzinfo=timezone.utc)
                    return dt.astimezone(ZoneInfo("America/New_York"))
                except Exception:
                    logging.warning(f"Error parsing date: {pub_date_str}")
            return None
        
        def extract_content(item):
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            
            if not (title_elem is not None and link_elem is not None):
                return None

            title = title_elem.text.strip() if title_elem.text else ""
            url = link_elem.text.strip() if link_elem.text else ""
            article_html = desc_elem.text.strip() if (desc_elem is not None and desc_elem.text) else ""
            
            # Clean HTML content to reduce token usage
            article_text = clean_html_content(article_html)
            
            return {
                "url": url,
                "title": title,
                "article": article_text
            }
        
        return get_articles_within_timeframe(
            feed_data=items,
            hours_window=48,
            extract_datetime_fn=extract_datetime,
            extract_content_fn=extract_content,
            source_name="EA Forum",
            max_tokens=20000
        )

    except Exception as e:
        logging.exception("Error retrieving content from EA Forum RSS feed")
        return [] 