"""
Sitemap content retrieval module for the Daily Briefing application.

This module provides functions for retrieving content from website sitemaps.
"""

import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from typing import List, Dict
from config import HEADERS, GREEN_QUEEN_SITEMAP_URL

def get_gq_sitemap_urls(sitemap_index_url: str) -> List[str]:
    """
    Retrieves sitemap URLs from the Green Queen sitemap index.
    Filters for sitemap URLs that start with the desired pattern.
    
    Args:
        sitemap_index_url: The URL of the sitemap index
        
    Returns:
        List[str]: A list of sitemap URLs
    """
    try:
        response = requests.get(sitemap_index_url, headers=HEADERS)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for sitemap in root.findall("ns:sitemap", ns):
            loc = sitemap.find("ns:loc", ns)
            if loc is not None:
                url_text = loc.text.strip()
                if url_text.startswith("https://www.greenqueen.com.hk/post-sitemap"):
                    urls.append(url_text)
        logging.info(f"Found {len(urls)} Green Queen sitemap URLs")
        return urls
    except Exception as e:
        logging.exception(f"Error retrieving sitemap URLs from {sitemap_index_url}")
        return []

def get_latest_24h_articles(sitemap_urls: List[str], source_name: str) -> List[str]:
    """
    Retrieves article URLs from a list of sitemap URLs for the last 24 hours
    from the most recent article.
    
    Args:
        sitemap_urls: A list of sitemap URLs to process
        source_name: The name of the source (for logging)
        
    Returns:
        List[str]: A list of article URLs
    """
    all_urls = []
    latest_datetime = None
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    # First pass: find the most recent article timestamp
    for sitemap_url in sitemap_urls:
        try:
            response = requests.get(sitemap_url, headers=HEADERS)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for url_elem in root.findall("ns:url", ns):
                lastmod_elem = url_elem.find("ns:lastmod", ns)
                if lastmod_elem is not None:
                    try:
                        lastmod_dt = datetime.fromisoformat(lastmod_elem.text)
                        if lastmod_dt.tzinfo is None:
                            lastmod_dt = lastmod_dt.replace(tzinfo=timezone.utc)
                        if latest_datetime is None or lastmod_dt > latest_datetime:
                            latest_datetime = lastmod_dt
                    except Exception as e:
                        logging.error(f"Error parsing date {lastmod_elem.text}: {e}")
                        continue
        except Exception as e:
            logging.exception(f"Error processing sitemap {sitemap_url}")
            continue

    if latest_datetime is None:
        logging.error(f"No valid timestamps found in sitemaps for {source_name}")
        return []

    # Calculate the cutoff time (24 hours before the most recent article)
    cutoff_time = latest_datetime - timedelta(hours=24)
    logging.info(f"{source_name}: Using articles between {cutoff_time} and {latest_datetime}")

    # Second pass: collect articles within the 24-hour window
    for sitemap_url in sitemap_urls:
        try:
            response = requests.get(sitemap_url, headers=HEADERS)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for url_elem in root.findall("ns:url", ns):
                loc_elem = url_elem.find("ns:loc", ns)
                lastmod_elem = url_elem.find("ns:lastmod", ns)
                if loc_elem is not None and lastmod_elem is not None:
                    lastmod_dt = datetime.fromisoformat(lastmod_elem.text)
                    if lastmod_dt.tzinfo is None:
                        lastmod_dt = lastmod_dt.replace(tzinfo=timezone.utc)

                    if cutoff_time <= lastmod_dt <= latest_datetime:
                        all_urls.append(loc_elem.text)
        except Exception as e:
            logging.exception(f"Error processing sitemap {sitemap_url}")
            continue

    logging.info(f"Collected {len(all_urls)} article URLs from {source_name} in the last 24 hours")
    return all_urls

def get_gq_article_content(urls: List[str]) -> List[Dict[str, str]]:
    """
    Downloads and extracts article content from a list of Green Queen article URLs.
    
    Args:
        urls: A list of article URLs to process
        
    Returns:
        List[Dict[str, str]]: A list of dictionaries with URL, title, and article text
    """
    articles = []
    for url in urls:
        try:
            response = requests.get(url, headers=HEADERS)
            if response.status_code != 200:
                logging.error(f"Failed to retrieve {url}: status code {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('h1', class_='single-post-title')
            title = title_tag.get_text(strip=True) if title_tag else ""
            content_tag = soup.find('div', class_='entry-content')
            article_text = content_tag.get_text(separator='\n', strip=True) if content_tag else ""
            articles.append({"url": url, "title": title, "article": article_text})
        except Exception as e:
            logging.exception(f"Error processing article URL: {url}")
            continue
    logging.info(f"Extracted content from {len(articles)} Green Queen articles")
    return articles

def get_gq_content() -> List[Dict[str, str]]:
    """
    Main function to retrieve Green Queen content by:
      1. Getting the sitemap URLs.
      2. Extracting the article URLs for the last 24 hours from the most recent article.
      3. Downloading article content.
      
    Returns:
        List[Dict[str, str]]: A list of dictionaries with article content
    """
    sitemap_index_url = GREEN_QUEEN_SITEMAP_URL
    post_sitemap_urls = get_gq_sitemap_urls(sitemap_index_url)
    article_urls = get_latest_24h_articles(post_sitemap_urls, "Green Queen")
    articles = get_gq_article_content(article_urls)
    return articles 