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
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from utils.html_utils import clean_html_content
from utils.api_utils import num_tokens_from_string
from config import HEADERS, RUNDOWN_RSS_URL, SHORT_SQUEEZ_RSS_URL, TERM_SHEET_URL, VEGCONOMIST_RSS_URL, EA_FORUM_RSS_URL
import time

def get_rundown_content() -> Optional[Dict[str, str]]:
    """
    Retrieves the most recent content from The Rundown RSS feed.
    Extracts the article text from the linked page.
    
    Returns:
        Optional[Dict[str, str]]: A dictionary with URL and article text, or None if retrieval fails
    """
    rss_url = RUNDOWN_RSS_URL
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        logging.warning("No entries found in The Rundown RSS feed")
        return None

    entries_sorted = sorted(feed.entries, key=lambda entry: entry.published_parsed, reverse=True)
    most_recent_link = entries_sorted[0].link

    try:
        response = requests.get(most_recent_link, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        content = soup.find('div', id='content-blocks')
        if content:
            article_text = content.get_text(separator="\n", strip=True)
            return {"url": most_recent_link, "article": article_text}
        else:
            logging.error("Content container not found in The Rundown article")
            return None
    except Exception as e:
        logging.exception(f"Error retrieving The Rundown content from {most_recent_link}")
        return None

def get_ss_content() -> Optional[Dict[str, str]]:
    """
    Retrieves the most recent content from the Short Squeez RSS feed.
    Extracts the article text from the linked page.
    
    Returns:
        Optional[Dict[str, str]]: A dictionary with URL and article text, or None if retrieval fails
    """
    rss_url = SHORT_SQUEEZ_RSS_URL
    feed = feedparser.parse(rss_url)
    if not feed.entries:
        logging.warning("No entries found in the Short Squeez RSS feed")
        return None

    entries_sorted = sorted(feed.entries, key=lambda entry: entry.published_parsed, reverse=True)
    most_recent_link = entries_sorted[0].link

    try:
        response = requests.get(most_recent_link, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        content = soup.find('div', id='content-blocks')
        if content:
            article_text = content.get_text(separator="\n", strip=True)
            return {"url": most_recent_link, "article": article_text}
        else:
            logging.error("Content container not found in Short Squeez article")
            return None
    except Exception as e:
        logging.exception(f"Error retrieving Short Squeez content from {most_recent_link}")
        return None

def get_ts_content() -> Dict[str, str]:
    """
    Retrieves content from the Term Sheet page.
    Extracts article text from table cells with the class 'bodyContent'.
    
    Returns:
        Dict[str, str]: A dictionary with URL and article text
    """
    url = TERM_SHEET_URL
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        body_contents = soup.find_all("td", class_="bodyContent")
        if not body_contents:
            raise ValueError("No elements with class 'bodyContent' found.")
        article_text = "\n\n".join(
            section.get_text(separator="\n", strip=True) for section in body_contents
        )
        return {"url": url, "article": article_text}
    except Exception as e:
        logging.exception(f"Error retrieving Term Sheet content from {url}")
        raise

def get_vegconomist_content() -> List[Dict[str, str]]:
    """
    Retrieves content from Vegconomist's RSS feed for the last 24 hours
    from the most recent article.
    
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL, title, and article text
    """
    articles = []
    latest_datetime = None

    try:
        # Parse the RSS feed
        feed = feedparser.parse(VEGCONOMIST_RSS_URL)
        
        # First pass: find the most recent article timestamp
        for entry in feed.entries:
            try:
                # Use feedparser's built-in parsed date instead of manual parsing
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    # Convert time tuple to datetime
                    pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    
                    if latest_datetime is None or pub_date > latest_datetime:
                        latest_datetime = pub_date
            except Exception as e:
                logging.exception("Error processing RSS entry timestamp")
                continue

        if latest_datetime is None:
            logging.error("No valid timestamps found in Vegconomist feed")
            return []

        # Calculate the cutoff time (24 hours before the most recent article)
        cutoff_time = latest_datetime - timedelta(hours=24)
        logging.info(f"Vegconomist: Using articles between {cutoff_time} and {latest_datetime}")
        
        # Second pass: process each entry within the 24-hour window
        for entry in feed.entries:
            try:
                # Use the same date parsing approach as above for consistency
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    
                    if cutoff_time <= pub_date <= latest_datetime:
                        content = entry.content[0].value if 'content' in entry else entry.description
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        for div in soup.find_all('div', class_='wp-caption'):
                            div.decompose()
                        
                        article_text = soup.get_text(separator='\n', strip=True)
                        
                        articles.append({
                            "url": entry.link,
                            "title": entry.title,
                            "article": article_text
                        })
                
            except Exception as e:
                logging.exception(f"Error processing RSS entry: {entry.link if 'link' in entry else 'unknown'}")
                continue
                
        logging.info(f"Extracted content from {len(articles)} Vegconomist articles in the last 24 hours")
        return articles
        
    except Exception as e:
        logging.exception("Error retrieving content from Vegconomist RSS feed")
        return []

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
        entries = []
        latest_datetime = None
        
        # First pass: find the most recent post timestamp
        for item in items:
            pub_date_elem = item.find("pubDate")
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    pub_date_str = pub_date_elem.text.strip()
                    dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S GMT")
                    dt = dt.replace(tzinfo=timezone.utc)
                    dt_est = dt.astimezone(ZoneInfo("America/New_York"))
                    
                    if latest_datetime is None or dt_est > latest_datetime:
                        latest_datetime = dt_est
                except Exception:
                    logging.warning(f"Error parsing date: {pub_date_str}")
                    continue

        if latest_datetime is None:
            logging.error("No valid timestamps found in EA Forum feed")
            return []

        # Calculate the cutoff time (48 hours before the most recent post)
        cutoff_time = latest_datetime - timedelta(hours=48)
        logging.info(f"EA Forum: Using posts between {cutoff_time} and {latest_datetime}")

        # Second pass: collect posts within the 48-hour window
        articles_with_dates = []
        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pub_date_elem = item.find("pubDate")
            
            if not (title_elem is not None and link_elem is not None and pub_date_elem is not None):
                continue

            title = title_elem.text.strip() if title_elem.text else ""
            url = link_elem.text.strip() if link_elem.text else ""
            article_html = desc_elem.text.strip() if (desc_elem is not None and desc_elem.text) else ""
            pub_date_str = pub_date_elem.text.strip()
            
            try:
                dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S GMT")
                dt = dt.replace(tzinfo=timezone.utc)
                dt_est = dt.astimezone(ZoneInfo("America/New_York"))
                
                if cutoff_time <= dt_est <= latest_datetime:
                    # Clean HTML content to reduce token usage
                    article_text = clean_html_content(article_html)
                    
                    article_entry = {
                        "url": url,
                        "title": title,
                        "article": article_text,
                        "datetime": dt_est  # Store the datetime for sorting
                    }
                    articles_with_dates.append(article_entry)
            except Exception:
                logging.warning(f"Error parsing date for item: {title}")
                continue
        
        # Sort articles by date (oldest first)
        articles_with_dates.sort(key=lambda x: x["datetime"])
        
        # Create entries list without the datetime field
        entries = [{k: v for k, v in article.items() if k != "datetime"} for article in articles_with_dates]
        
        # Check token count and remove oldest articles if needed
        total_tokens = sum(num_tokens_from_string(json.dumps(entry)) for entry in entries)
        logging.info(f"EA Forum: Initial collection has {len(entries)} articles with {total_tokens} tokens")
        
        while total_tokens > 20000 and len(entries) > 1:
            # Remove the oldest article (first in the list since we sorted by date)
            removed_article = entries.pop(0)
            logging.info(f"EA Forum: Removed article '{removed_article['title']}' to reduce token count")
            
            # Recalculate token count
            total_tokens = sum(num_tokens_from_string(json.dumps(entry)) for entry in entries)
            logging.info(f"EA Forum: After removal, {len(entries)} articles with {total_tokens} tokens remain")
        
        logging.info(f"Extracted {len(entries)} articles from EA Forum in the last 48 hours (after token limit applied)")
        return entries

    except Exception as e:
        logging.exception("Error retrieving content from EA Forum RSS feed")
        return [] 