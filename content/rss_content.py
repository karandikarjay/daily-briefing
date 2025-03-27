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
from utils.api_utils import num_tokens_from_string, get_content_collection_timeframe
from config import HEADERS, RUNDOWN_RSS_URL, VEGCONOMIST_RSS_URL, EA_FORUM_RSS_URL, TIMEZONE
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

def get_rundown_content() -> List[Dict[str, str]]:
    """
    Retrieves content from The Rundown AI RSS feed within the configured time window.
    
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL and article text
    """
    feed = fetch_and_parse_rss(RUNDOWN_RSS_URL)
    if not feed:
        return []
    
    def extract_datetime(entry):
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            pub_date = pub_date.replace(tzinfo=timezone.utc)
            return pub_date.astimezone(TIMEZONE)
        return None
    
    def extract_content(entry):
        content = entry.content[0].value if 'content' in entry and entry.content else entry.description
        soup = BeautifulSoup(content, 'html.parser')
        article_text = soup.get_text(separator='\n', strip=True)
        
        # Get full article content if available
        article_url = entry.link
        try:
            full_article = fetch_article_content(article_url, "div:content-blocks")
            if full_article:
                article_text = full_article
        except Exception as e:
            logging.warning(f"Error getting full The Rundown AI article content: {e}")
        
        return {
            "url": article_url,
            "title": entry.title,
            "article": article_text,
            "datetime": extract_datetime(entry),
            "source_name": "The Rundown AI"
        }
    
    return get_articles_within_timeframe(
        feed_data=feed,
        extract_datetime_fn=extract_datetime,
        extract_content_fn=extract_content,
        source_name="The Rundown AI"
    )

def get_articles_within_timeframe(
    feed_data: Any, 
    extract_datetime_fn: Callable,
    extract_content_fn: Callable,
    source_name: str
) -> List[Dict[str, str]]:
    """
    Generic function to extract articles within the configured time window from a feed.
    
    Args:
        feed_data: The feed data (could be feedparser result or XML)
        extract_datetime_fn: Function to extract datetime from an entry
        extract_content_fn: Function to extract content from an entry
        source_name: Name of the source for logging
        
    Returns:
        List of article dictionaries
    """
    articles_with_dates = []
    
    try:
        from utils.api_utils import get_content_collection_timeframe
        start_time, end_time = get_content_collection_timeframe()
        
        logging.info(f"{source_name}: Retrieving articles from {start_time} to {end_time}")
        
        entries = feed_data.entries if hasattr(feed_data, 'entries') else feed_data
        
        # Process each entry within the time window
        for entry in entries:
            try:
                pub_date = extract_datetime_fn(entry)
                
                if pub_date and start_time <= pub_date <= end_time:
                    article_data = extract_content_fn(entry)
                    if article_data:
                        # Convert datetime to string only at the end before returning
                        if article_data["datetime"] and isinstance(article_data["datetime"], datetime):
                            article_data["datetime"] = article_data["datetime"].isoformat()
                        articles_with_dates.append(article_data)
            except Exception as e:
                entry_id = getattr(entry, 'link', 'unknown') if hasattr(entry, 'link') else 'unknown'
                logging.exception(f"Error processing {source_name} entry: {entry_id}")
                continue
        
        logging.info(f"Extracted content from {len(articles_with_dates)} {source_name} articles in the configured time window")
        return articles_with_dates
        
    except Exception as e:
        logging.exception(f"Error retrieving content from {source_name}")
        return []

def get_vegconomist_content() -> List[Dict[str, str]]:
    """
    Retrieves content from Vegconomist's RSS feed within the configured time window.
    
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL, title, and article text
    """
    feed = fetch_and_parse_rss(VEGCONOMIST_RSS_URL)
    if not feed:
        return []
    
    def extract_datetime(entry):
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
            pub_date = pub_date.replace(tzinfo=timezone.utc)
            return pub_date.astimezone(TIMEZONE)
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
            "article": article_text,
            "datetime": extract_datetime(entry),
            "source_name": "Vegconomist"
        }
    
    return get_articles_within_timeframe(
        feed_data=feed,
        extract_datetime_fn=extract_datetime,
        extract_content_fn=extract_content,
        source_name="Vegconomist"
    )

def get_ea_forum_content() -> List[Dict[str, str]]:
    """
    Fetches the RSS feed from Effective Altruism Forum and returns articles
    published within the configured time window.
    
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
                    return dt.astimezone(TIMEZONE)
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
                "article": article_text,
                "datetime": extract_datetime(item),
                "source_name": "EA Forum"
            }
        
        return get_articles_within_timeframe(
            feed_data=items,
            extract_datetime_fn=extract_datetime,
            extract_content_fn=extract_content,
            source_name="EA Forum"
        )

    except Exception as e:
        logging.exception("Error retrieving content from EA Forum RSS feed")
        return [] 