#!/usr/bin/env python3
"""
Daily Briefing Script

This script gathers content from various sources (RSS feeds, sitemaps, emails, etc.),
processes the content, creates charts from financial data, and sends out an email
newsletter containing a daily briefing. Logging is set up to record events and errors.
"""

import os
import json
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from openai import OpenAI
import feedparser
from email.utils import parsedate_to_datetime
import pytz
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import imaplib
import email
from email.header import decode_header
import yfinance as yf
import matplotlib.pyplot as plt
import seaborn
import sys
import pandas as pd
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import time
import tiktoken
import random
import re
from typing import List, Optional
from pydantic import BaseModel

# Load environment variables from .env file
load_dotenv()

# Get environment variables
API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_USERNAME = os.getenv("GOOGLE_USERNAME")
GOOGLE_PASSWORD = os.getenv("GOOGLE_PASSWORD")
# Parse recipient emails into a list (split by commas)
recipient_emails_str = os.getenv("RECIPIENT_EMAILS", "")
RECIPIENT_EMAILS = [email.strip() for email in recipient_emails_str.split(",")] if recipient_emails_str else []

# Define AI model to use
AI_MODEL = "gpt-4o"

# Configure logging to log to both console and file
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_briefing.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding='utf-8')
    ]
)

# Create a custom logger for prompts and responses
prompt_logger = logging.getLogger('prompts')
prompt_logger.setLevel(logging.INFO)
# Create a separate log file for prompts and LLM outputs
PROMPT_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_response.log")
prompt_file_handler = logging.FileHandler(PROMPT_LOG_FILE, encoding='utf-8')
prompt_file_handler.setFormatter(logging.Formatter('%(asctime)s\n%(message)s\n'))
prompt_logger.addHandler(prompt_file_handler)
# Prevent prompt logs from propagating to the root logger
prompt_logger.propagate = False

# Define global headers for HTTP requests
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36')
}

# Set timezone to Eastern US
EASTERN = pytz.timezone('America/New_York')

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# OpenAI API rate limiting parameters
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 60  # seconds
MAX_TOKENS_PER_REQUEST = 25000  # Keeping well below the 30000 TPM limit
TOKEN_BUFFER = 1000  # Buffer to account for response tokens

# Initialize tokenizer for the model
def num_tokens_from_string(string, model="gpt-4"):
    """Returns the number of tokens in a text string."""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(string))
    except Exception as e:
        logging.warning(f"Error counting tokens: {e}. Using approximate count.")
        # Fallback to approximate count (1 token ≈ 4 chars for English text)
        return len(string) // 4

# Define the schema for the bullet points using Pydantic models
class ArticleBulletPoint(BaseModel):
    headline: str
    one_sentence_summary: str
    source_name: str
    url: str

class EmailBulletPoint(BaseModel):
    headline: str
    one_sentence_summary: str
    sender: str
    subject: str

class BulletPointResponse(BaseModel):
    bullet_points: List[ArticleBulletPoint] | List[EmailBulletPoint]

# Function to make API calls with rate limiting and retries
def call_openai_api_with_backoff(client, messages, model=AI_MODEL, max_tokens=None, response_format=None):
    """
    Makes an API call to OpenAI with exponential backoff for retries.
    Handles rate limits and token limits.
    
    Args:
        client: The OpenAI client instance
        messages: List of message dictionaries to send
        model: The model to use (default: AI_MODEL)
        max_tokens: Maximum tokens for the response (optional)
        response_format: Format specification for the response (optional)
        
    Returns:
        The API response
    """
    # Count tokens in the request
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in messages)
    
    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed rate limits.")
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Prepare the API call parameters
            params = {
                "messages": messages,
                "model": model
            }
            
            # Add optional parameters if provided
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
                
            if response_format is not None:
                params["response_format"] = response_format
            
            # Make the API call
            response = client.chat.completions.create(**params)
            return response
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            if hasattr(e, 'code') and e.code == 'rate_limit_exceeded':
                logging.warning(f"Rate limit exceeded. Attempt {retry_count}/{MAX_RETRIES}")
            else:
                logging.warning(f"API error: {str(e)}. Attempt {retry_count}/{MAX_RETRIES}")
            
            if retry_count >= MAX_RETRIES:
                logging.error(f"Max retries reached. Giving up.")
                raise
            
            # Calculate backoff with jitter
            delay = min(INITIAL_RETRY_DELAY * (2 ** (retry_count - 1)) * jitter, MAX_RETRY_DELAY)
            logging.info(f"Retrying in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception("Max retries exceeded without successful API call")

def call_openai_parse_with_backoff(client, messages, response_model, model=AI_MODEL):
    """
    Makes a parse API call to OpenAI with exponential backoff for retries.
    This is specifically for structured data parsing using client.beta.chat.completions.parse
    
    Args:
        client: The OpenAI client instance
        messages: List of message dictionaries to send
        response_model: Pydantic model to parse the response into
        model: The model to use (default: AI_MODEL)
        
    Returns:
        The parsed API response
    """
    # Count tokens in the request
    total_tokens = sum(num_tokens_from_string(msg["content"]) for msg in messages)
    
    if total_tokens > MAX_TOKENS_PER_REQUEST:
        logging.warning(f"Request too large ({total_tokens} tokens). This may exceed rate limits.")
    
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Add jitter to avoid synchronized retries
            jitter = random.uniform(0.8, 1.2)
            
            # Make the parse API call
            response = client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_model
            )
            return response
        except Exception as e:
            retry_count += 1
            
            # Check if it's a rate limit error
            if hasattr(e, 'code') and e.code == 'rate_limit_exceeded':
                logging.warning(f"Rate limit exceeded. Attempt {retry_count}/{MAX_RETRIES}")
            else:
                logging.warning(f"API error: {str(e)}. Attempt {retry_count}/{MAX_RETRIES}")
            
            if retry_count >= MAX_RETRIES:
                logging.error(f"Max retries reached. Giving up.")
                raise
            
            # Calculate backoff with jitter
            delay = min(INITIAL_RETRY_DELAY * (2 ** (retry_count - 1)) * jitter, MAX_RETRY_DELAY)
            logging.info(f"Retrying in {delay:.2f} seconds...")
            time.sleep(delay)
    
    # This should not be reached due to the raise in the loop
    raise Exception("Max retries exceeded without successful API call")

def get_gq_sitemap_urls(sitemap_index_url):
    """
    Retrieves sitemap URLs from the Green Queen sitemap index.
    Filters for sitemap URLs that start with the desired pattern.
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
        logging.info("Found %d Green Queen sitemap URLs", len(urls))
        return urls
    except Exception as e:
        logging.exception("Error retrieving sitemap URLs from %s", sitemap_index_url)
        return []


def get_latest_24h_articles(sitemap_urls, source_name):
    """
    Retrieves article URLs from a list of sitemap URLs for the last 24 hours
    from the most recent article.
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
                        logging.error("Error parsing date %s: %s", lastmod_elem.text, e)
                        continue
        except Exception as e:
            logging.exception("Error processing sitemap %s", sitemap_url)
            continue

    if latest_datetime is None:
        logging.error("No valid timestamps found in sitemaps for %s", source_name)
        return []

    # Calculate the cutoff time (24 hours before the most recent article)
    cutoff_time = latest_datetime - timedelta(hours=24)
    logging.info("%s: Using articles between %s and %s", source_name, cutoff_time, latest_datetime)

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
            logging.exception("Error processing sitemap %s", sitemap_url)
            continue

    logging.info("Collected %d article URLs from %s in the last 24 hours", len(all_urls), source_name)
    return all_urls


def get_gq_article_content(urls):
    """
    Downloads and extracts article content from a list of Green Queen article URLs.
    Returns a list of dictionaries with URL, title, and article text.
    """
    articles = []
    for url in urls:
        try:
            response = requests.get(url, headers=HEADERS)
            if response.status_code != 200:
                logging.error("Failed to retrieve %s: status code %d", url, response.status_code)
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('h1', class_='single-post-title')
            title = title_tag.get_text(strip=True) if title_tag else ""
            content_tag = soup.find('div', class_='entry-content')
            article_text = content_tag.get_text(separator='\n', strip=True) if content_tag else ""
            articles.append({"url": url, "title": title, "article": article_text})
        except Exception as e:
            logging.exception("Error processing article URL: %s", url)
            continue
    logging.info("Extracted content from %d Green Queen articles", len(articles))
    return articles


def get_gq_content():
    """
    Main function to retrieve Green Queen content by:
      1. Getting the sitemap URLs.
      2. Extracting the article URLs for the last 24 hours from the most recent article.
      3. Downloading article content.
    """
    sitemap_index_url = "https://www.greenqueen.com.hk/sitemap_index.xml"
    post_sitemap_urls = get_gq_sitemap_urls(sitemap_index_url)
    article_urls = get_latest_24h_articles(post_sitemap_urls, "Green Queen")
    articles = get_gq_article_content(article_urls)
    return articles


def get_rundown_content():
    """
    Retrieves the most recent content from The Rundown RSS feed.
    Extracts the article text from the linked page.
    """
    rss_url = "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml"
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
        logging.exception("Error retrieving The Rundown content from %s", most_recent_link)
        return None


def get_ss_content():
    """
    Retrieves the most recent content from the Short Squeez RSS feed.
    Extracts the article text from the linked page.
    """
    rss_url = "https://rss.beehiiv.com/feeds/uuk5kg8PFC.xml"
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
        logging.exception("Error retrieving Short Squeez content from %s", most_recent_link)
        return None


def get_ts_content():
    """
    Retrieves content from the Term Sheet page.
    Extracts article text from table cells with the class 'bodyContent'.
    """
    url = "https://content.fortune.com/newsletter/termsheet/"
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
        logging.exception("Error retrieving Term Sheet content from %s", url)
        raise


def get_axios_article(url):
    """
    Uses Playwright (with stealth) to render a page and extract article content
    from specified elements. Returns a dictionary with URL and article text.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            stealth_sync(page)
            page.goto(url, wait_until='networkidle')
            page.wait_for_timeout(5000)
            html_content = page.content()
            browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        article_elements = soup.find_all(class_=['DraftjsBlocks_draftjs__fm3S2', 'StoryImage_caption__HRtkC'])
        article_content = []
        for element in article_elements:
            text_parts = [t for t in element.stripped_strings]
            article_content.append(" ".join(text_parts))
        return {"url": url, "article": "\n".join(article_content)}
    except Exception as e:
        logging.exception("Error retrieving Axios article from %s", url)
        return {"url": url, "article": ""}


def get_fast_email_content():
    """
    Connects to the Gmail IMAP server and retrieves emails that include the specified email
    (FAST email list) in any "to" or "from" field for the last 24 hours from the most recent email.
    Returns a list of email contents.
    """
    IMAP_SERVER = "imap.gmail.com"
    IMAP_PORT = 993
    search_email = "fast-farm-animal-strategic-team@googlegroups.com"

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(GOOGLE_USERNAME, GOOGLE_PASSWORD)
        mail.select("inbox")

        # Calculate the date two weeks ago (for initial search)
        two_weeks_ago = (datetime.now(EASTERN) - timedelta(weeks=2)).strftime("%d-%b-%Y")

        # Search for emails that include the specified email in any "to" or "from" field within the past two weeks
        status, data = mail.search(None, f'(OR (TO "{search_email}" SINCE {two_weeks_ago}) (FROM "{search_email}" SINCE {two_weeks_ago}))')
        email_ids = data[0].split()

        latest_datetime = None
        email_dates = []

        # First pass: find the most recent email timestamp
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(BODY.PEEK[HEADER])")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    date_tuple = parsedate_to_datetime(msg["Date"])
                    if latest_datetime is None or date_tuple > latest_datetime:
                        latest_datetime = date_tuple

        if latest_datetime is None:
            logging.error("No valid timestamps found in FAST emails")
            return []

        # Calculate the cutoff time (24 hours before the most recent email)
        cutoff_time = latest_datetime - timedelta(hours=24)
        logging.info("FAST: Using emails between %s and %s", cutoff_time, latest_datetime)

        emails_content = []

        # Second pass: fetch emails within the 24-hour window
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    date_tuple = parsedate_to_datetime(msg["Date"])
                    
                    if cutoff_time <= date_tuple <= latest_datetime:
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding if encoding else "utf-8")

                        # Remove 'FAST ♞ ' from the subject if present
                        subject = subject.replace('FAST ♞ ', '')

                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                if content_type == "text/plain":
                                    body = part.get_payload(decode=True).decode()
                                    emails_content.append({"subject": subject, "body": body})
                        else:
                            body = msg.get_payload(decode=True).decode()
                            emails_content.append({"subject": subject, "body": body})

        mail.logout()
        logging.info("Retrieved %d FAST emails in the last 24 hours", len(emails_content))
        return emails_content

    except Exception as e:
        logging.exception("Error retrieving FAST email content")
        return []


def get_vegconomist_content():
    """
    Retrieves content from Vegconomist's RSS feed for the last 24 hours
    from the most recent article.
    """
    articles = []
    latest_datetime = None

    try:
        # Parse the RSS feed
        feed = feedparser.parse('https://vegconomist.com/feed/')
        
        # First pass: find the most recent article timestamp
        for entry in feed.entries:
            try:
                pub_date = datetime.fromtimestamp(
                    email.utils.mktime_tz(email.utils.parsedate_tz(entry.published))
                ).replace(tzinfo=timezone.utc)
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
        logging.info("Vegconomist: Using articles between %s and %s", cutoff_time, latest_datetime)
        
        # Second pass: process each entry within the 24-hour window
        for entry in feed.entries:
            try:
                pub_date = datetime.fromtimestamp(
                    email.utils.mktime_tz(email.utils.parsedate_tz(entry.published))
                ).replace(tzinfo=timezone.utc)
                
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
                logging.exception("Error processing RSS entry: %s", entry.link if 'link' in entry else 'unknown')
                continue
                
        logging.info("Extracted content from %d Vegconomist articles in the last 24 hours", len(articles))
        return articles
        
    except Exception as e:
        logging.exception("Error retrieving content from Vegconomist RSS feed")
        return []


def get_ea_forum_content():
    """
    Fetches the RSS feed from Effective Altruism Forum and returns a list of dictionaries
    for all articles published in the last 48 hours from the most recent post.
    Each dictionary contains the keys: "url", "title", and "article".
    """
    feed_url = "https://forum.effectivealtruism.org/feed.xml?view=frontpage-rss&karmaThreshold=2"
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
                    logging.warning("Error parsing date: %s", pub_date_str)
                    continue

        if latest_datetime is None:
            logging.error("No valid timestamps found in EA Forum feed")
            return []

        # Calculate the cutoff time (48 hours before the most recent post)
        cutoff_time = latest_datetime - timedelta(hours=48)
        logging.info("EA Forum: Using posts between %s and %s", cutoff_time, latest_datetime)

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
                logging.warning("Error parsing date for item: %s", title)
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
        
        logging.info("Extracted %d articles from EA Forum in the last 48 hours (after token limit applied)", len(entries))
        return entries

    except Exception as e:
        logging.exception("Error retrieving content from EA Forum RSS feed")
        return []


def clean_html_content(html_content):
    """
    Cleans HTML content to reduce token usage while preserving meaningful content.
    Removes unnecessary tags, attributes, and whitespace.
    """
    if not html_content:
        return ""
    
    try:
        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove unnecessary tags completely
        for tag in soup.find_all(['style', 'script', 'svg', 'iframe']):
            tag.decompose()
        
        # Remove all class, id, and style attributes
        for tag in soup.find_all(True):
            if tag.has_attr('class'):
                del tag['class']
            if tag.has_attr('id'):
                del tag['id']
            if tag.has_attr('style'):
                del tag['style']
        
        # Get text with minimal formatting
        text = soup.get_text(separator=' ', strip=True)
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove "Published on..." prefix that appears in many EA Forum posts
        text = re.sub(r'^Published on [A-Za-z]+ \d+, \d+ \d+:\d+ [AP]M [A-Z]+\s*', '', text)
        
        # Remove "Discuss" suffix that appears in many EA Forum posts
        text = re.sub(r'\s*Discuss$', '', text)
        
        return text.strip()
    except Exception as e:
        logging.warning(f"Error cleaning HTML content: {e}")
        # Fall back to a simpler approach
        return re.sub(r'<[^>]*>', ' ', html_content).strip()


def get_semafor_article(url):
    """
    Fetches and parses an article from the given Semafor URL.
    Returns a dictionary with the URL and the extracted article text.
    """
    try:
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(f"Failed to fetch {url}: Status code {response.status_code}")

        # Parse the HTML content
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Try to find the main article container.
        # First, try an <article> tag.
        article_tag = soup.find("article")
        if article_tag:
            article_text = article_tag.get_text(separator="\n").strip()
        else:
            # If no <article> tag is found, try a container by known class name (this may vary).
            main_container = soup.find("div", class_="styles_container__kVu6N")
            if main_container:
                article_text = main_container.get_text(separator="\n").strip()
            else:
                # Fallback: extract all text from the <body>
                if soup.body:
                    article_text = soup.body.get_text(separator="\n").strip()
                else:
                    article_text = soup.get_text(separator="\n").strip()

        logging.info("Extracted article from %s", url)
        return {"url": url, "article": article_text}

    except Exception as e:
        logging.exception("Error retrieving article from %s", url)
        return {"url": url, "article": ""}


def get_content(title):
    """
    Returns content based on the provided title.
    Dispatches to different content-retrieval functions.
    """
    content = []
    if title == "Alternative Protein":
        content.append({"source_name": "Green Queen", "content": get_gq_content(), "content_type": "articles"})
        content.append({"source_name": "Vegconomist", "content": get_vegconomist_content(), "content_type": "articles"})
        return content
    elif title == "Vegan Movement":
        content.append({"source_name": "FAST Email List", "content": get_fast_email_content(), "content_type": "emails"})
        return content
    elif title == "Effective Altruism":
        content.append({"source_name": "EA Forum", "content": get_ea_forum_content(), "content_type": "articles"})
        return content
    elif title == "Venture Capital":
        content.append({"source_name": "Term Sheet", "content": get_ts_content(), "content_type": "articles"})
        content.append({"source_name": "Axios Pro Rata", "content": get_axios_article("https://www.axios.com/newsletters/axios-pro-rata"), "content_type": "articles"})
        return content
    elif title == "Financial Markets":
        content.append({"source_name": "Short Squeez", "content": get_ss_content(), "content_type": "articles"})
        content.append({"source_name": "Axios Markets", "content": get_axios_article("https://www.axios.com/newsletters/axios-markets"), "content_type": "articles"})
        content.append({"source_name": "Axios Macro", "content": get_axios_article("https://www.axios.com/newsletters/axios-macro"), "content_type": "articles"})
        content.append({"source_name": "Axios Closer", "content": get_axios_article("https://www.axios.com/newsletters/axios-closer"), "content_type": "articles"})
        content.append({"source_name": "Semafor Business", "content": get_semafor_article("https://www.semafor.com/newsletters/business/latest"), "content_type": "articles"})
        return content
    elif title == "AI":
        content.append({"source_name": "The Rundown AI", "content": get_rundown_content(), "content_type": "articles"})
        content.append({"source_name": "Axios AI+", "content": get_axios_article("https://www.axios.com/newsletters/axios-ai-plus"), "content_type": "articles"})
        return content
    elif title == "Politics":
        content.append({"source_name": "Axios AM", "content": get_axios_article("https://www.axios.com/newsletters/axios-am"), "content_type": "articles"})
        content.append({"source_name": "Axios PM", "content": get_axios_article("https://www.axios.com/newsletters/axios-pm"), "content_type": "articles"})
        content.append({"source_name": "Semafor Flagship", "content": get_semafor_article("https://www.semafor.com/newsletters/flagship/latest"), "content_type": "articles"})
        content.append({"source_name": "Semafor Principals", "content": get_semafor_article("https://www.semafor.com/newsletters/principals/latest"), "content_type": "articles"})
        content.append({"source_name": "Semafor Americana", "content": get_semafor_article("https://www.semafor.com/newsletters/americana/latest"), "content_type": "articles"})
        return content
    elif title == "Climate":
        content.append({"source_name": "Axios Generate", "content": get_axios_article("https://www.axios.com/newsletters/axios-generate"), "content_type": "articles"})
        content.append({"source_name": "Semafor Net Zero", "content": get_semafor_article("https://www.semafor.com/newsletters/netzero/latest"), "content_type": "articles"})
        return content
    else:
        logging.warning("No content retrieval function defined for title: %s", title)
        return content


def create_charts():
    """
    Creates charts for a set of financial tickers using yfinance data.
    Saves the charts as image files.
    """
    plt.style.use('seaborn-v0_8-darkgrid')
    chart_color = '#1e3d59'
    grid_color = '#e0e0e0'
    background_color = '#ffffff'
    tickers = {
        'BYND': {'filename': os.path.join(SCRIPT_DIR, 'bynd-chart.png'), 'display_name': 'Beyond Meat'},
        'OTLY': {'filename': os.path.join(SCRIPT_DIR, 'otly-chart.png'), 'display_name': 'Oatly'},
        '^GSPC': {'filename': os.path.join(SCRIPT_DIR, 'sp500-chart.png'), 'display_name': 'S&P 500'},
        '^TNX': {'filename': os.path.join(SCRIPT_DIR, '10y-yield-chart.png'), 'display_name': '10-Year Treasury'},
        '^VIX': {'filename': os.path.join(SCRIPT_DIR, 'vix-chart.png'), 'display_name': 'VIX'}
    }

    for ticker, info in tickers.items():
        logging.info("Downloading data for %s...", info['display_name'])
        data = yf.download(ticker, period="1y")
        if data.empty:
            logging.warning("No data found for %s. Skipping chart creation.", info['display_name'])
            continue

        logging.info("Plotting chart for %s...", info['display_name'])
        plt.figure(figsize=(10, 6), facecolor=background_color)
        ax = plt.gca()
        ax.set_facecolor(background_color)
        plt.plot(data.index, data['Close'],
                 label='Close Price' if ticker != '^TNX' else 'Yield',
                 color=chart_color, linewidth=2)
        plt.grid(True, linestyle='--', alpha=0.7, color=grid_color)
        
        # Annotate the most recent price
        latest_date = data.index[-1]
        latest_price = data['Close'].iloc[-1][ticker]
        plt.annotate(f'{latest_price:.2f}',
                     xy=(latest_date, latest_price),
                     xytext=(latest_date + pd.Timedelta(days=2), latest_price),
                     fontsize=14, color=chart_color,
                     ha='left', va='center')

        # Customize title based on ticker
        if ticker == '^TNX':
            title = f"{info['display_name']} Yield"
        else:
            title = f"{info['display_name']}"
            
        plt.title(title, color=chart_color, fontsize=18, pad=20, fontweight='bold')
        
        ax.tick_params(colors=chart_color, labelsize=12)
        plt.tight_layout()
        plt.savefig(info['filename'], dpi=300, bbox_inches='tight', facecolor=background_color)
        plt.close()
        logging.info("Saved chart: %s", info['filename'])


def send_email(body, send_to_everyone=False):
    """
    Sends an email with the provided HTML body and attaches chart images.
    Uses Gmail's SMTP server for sending.
    """
    sender_email = GOOGLE_USERNAME
    receiver_emails = [GOOGLE_USERNAME]
    bcc_emails = []

    if send_to_everyone and RECIPIENT_EMAILS:
        bcc_emails = RECIPIENT_EMAILS

    message = MIMEMultipart("related")
    message["Subject"] = "Daily Briefing"
    message["From"] = sender_email
    message["To"] = sender_email
    if bcc_emails:
        message["Bcc"] = ", ".join(bcc_emails)

    # Attach the HTML content
    part = MIMEText(body, "html")
    message.attach(part)

    # Attach chart images
    image_files = {
        'bynd-chart.png': '<bynd-chart>',
        'otly-chart.png': '<otly-chart>',
        'sp500-chart.png': '<sp500-chart>',
        '10y-yield-chart.png': '<10y-yield-chart>',
        'vix-chart.png': '<vix-chart>'
    }
    for filename, content_id in image_files.items():
        image_path = os.path.join(SCRIPT_DIR, filename)
        try:
            with open(image_path, 'rb') as img_file:
                img = MIMEImage(img_file.read())
                img.add_header('Content-ID', content_id)
                message.attach(img)
        except Exception as e:
            logging.exception("Error attaching image %s", image_path)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Secure the connection
            server.login(sender_email, GOOGLE_PASSWORD)
            # Include all recipients (To + Bcc) in the sendmail recipients list
            all_recipients = [sender_email] + bcc_emails
            server.sendmail(sender_email, all_recipients, message.as_string())
        
        if bcc_emails:
            logging.info("Email sent successfully to %s and BCC to %d recipients", sender_email, len(bcc_emails))
        else:
            logging.info("Email sent successfully to %s", sender_email)
    except Exception as e:
        logging.exception("Error sending email")


# Function to generate HTML email from template and bullet points
def generate_email_html(template, sections_data):
    """
    Generates HTML for the email newsletter using the template and bullet points data.
    
    Args:
        template (str): HTML template string
        sections_data (dict): Dictionary mapping section titles to their bullet points
        
    Returns:
        str: Generated HTML content for the email
    """
    # Create a copy of the template to modify
    html = template
    
    # Process each section
    for section_title, bullet_points in sections_data.items():
        # Skip if no bullet points
        if not bullet_points or len(bullet_points) == 0:
            continue
            
        # Make section title lowercase and replace spaces with underscores for use in placeholders
        section_key = section_title.lower().replace(' ', '_')
        
        # Replace placeholders for each bullet point that exists
        for i, bullet in enumerate(bullet_points, 1):
            if i > 3:  # Only process up to 3 bullet points
                break
                
            # Replace headline and summary
            html = html.replace(f"{{{section_key}_headline_{i}}}", bullet.get("headline", ""))
            html = html.replace(f"{{{section_key}_one_sentence__summary_{i}}}", bullet.get("one_sentence_summary", ""))
            
            # Replace source-specific placeholders
            if "source_name" in bullet and "url" in bullet:
                # For article-type content
                html = html.replace(f"{{{section_key}_source_name_{i}}}", bullet.get("source_name", ""))
                html = html.replace(f"{{{section_key}_url_{i}}}", bullet.get("url", "#"))
            elif "sender" in bullet and "subject" in bullet:
                # For email-type content
                html = html.replace(f"{{{section_key}_sender_{i}}}", bullet.get("sender", ""))
                html = html.replace(f"{{{section_key}_subject_{i}}}", bullet.get("subject", ""))
        
        # Remove list items for missing bullet points (if fewer than 3 were returned)
        for i in range(len(bullet_points) + 1, 4):  # Start from the first missing index up to 3
            # Define regex patterns to find list items with the missing placeholders
            # The patterns look for <li> tags containing the specific placeholder patterns
            if "source_name" in bullet_points[0] and "url" in bullet_points[0]:
                # For article-type sections
                pattern = rf'<li><strong>\{{{section_key}_headline_{i}\}}:</strong> \{{{section_key}_one_sentence__summary_{i}\}} <a href="\{{{section_key}_url_{i}\}}">\{{{section_key}_source_name_{i}\}}</a></li>'
            elif "sender" in bullet_points[0] and "subject" in bullet_points[0]:
                # For email-type sections
                pattern = rf'<li><strong>\{{{section_key}_headline_{i}\}}:</strong> \{{{section_key}_one_sentence__summary_{i}\}} \(Email from \{{{section_key}_sender_{i}\}} with subject "\{{{section_key}_subject_{i}\}}"\)</li>'
            else:
                # For sections with unknown structure, use a more generic pattern
                pattern = rf'<li><strong>\{{{section_key}_headline_{i}\}}:.*?</li>'
                
            # Use re.sub to remove the list item containing the placeholders
            import re
            html = re.sub(pattern, '', html)
    
    return html


if __name__ == "__main__":
    # Check for the --send-to-everyone flag
    send_to_everyone = "--send-to-everyone" in sys.argv

    # Define common instructions for bullet points
    COMMON_BULLET_POINT_INSTRUCTIONS = (
        "The value corresponding to the 'headline' key should be a headline in title case that captures the main point of the bullet point. "
        "The value corresponding to the 'one_sentence_summary' key should be a one-sentence summary of the bullet point. "
        "The output should be in valid JSON format without any surrounding markdown code block markers. "
    )

    # Define a unified format for all sections
    UNIFIED_FORMAT = (
        "Return the bullet points in JSON format as an array of 3 objects with the keys 'headline' and 'one_sentence_summary'. "
        "If the content_type is 'articles', also include the keys 'source_name' and 'url'. "
        "The value corresponding to the 'source_name' key should be the name of the source that provided the information for the bullet point. "
        "Make sure that the source_name is one of the values corresponding to the key 'source_name' in the data that I have provided. "
        "The value corresponding to the 'url' key should be the URL of the source that provided the information for the bullet point. "
        "Make sure that the URL is one of the values corresponding to the key 'url' in the data that I have provided. "
        "If the content_type is 'emails', also include the keys 'sender' and 'subject'. "
        "The value corresponding to the 'sender' key should be the name of the sender of the email that provided the information for the bullet point. "
        "The value corresponding to the 'subject' key should be the subject of the email that provided the information for the bullet point. "
        + COMMON_BULLET_POINT_INSTRUCTIONS
    )

    # Define sections for the daily briefing with their prompts
    BASE_INSTRUCTIONS = (
        "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
        "Give me the bullet points only without anything before or after. "
        "Make sure that there are exactly 3 bullet points (no more, no fewer). "
        "Make sure that any claims you make are substantiated by the text of the sources you reference. "
    )

    sections = [
        {
            "title": "Alternative Protein",
            "prompt": (
                "I am an investor in alternative protein startups. I want to be aware of recent developments in the alternative protein industry "
                "(especially recent funding rounds and new product launches) so that I can invest wisely. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "Vegan Movement",
            "prompt": (
                "I am a philanthropist who donates to the vegan movement. I want to stay up to date on what's going on in the vegan movement "
                "(particularly recent accomplishments, new research, and lessons learned) so that I can make better philanthropic decisions when we're pitched by vegan nonprofits. "
                "Note that Farmed Animal Strategic Team (FAST) is not the name of an organization, but simply the name of an email list where people in the vegan movement share updates. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "emails"
        },
        {
            "title": "Effective Altruism",
            "prompt": (
                "I am a philanthropist. I want to be aware of the latest discussions in the effective altruism community so that I can make donations effectively. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "Venture Capital",
            "prompt": (
                "I am a venture capitalist. I want to know what's going on in the venture capital ecosystem, such as any major deals and broader market trends. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "Financial Markets",
            "prompt": (
                "I am an investor at a hedge fund. I want to know what's going on in the financial markets, particularly the performance of the markets as a whole, any significant economic news releases, and any major deals. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "AI",
            "prompt": (
                "I want to know what new developments are going on in the world of AI tools so that I can increase my personal productivity and I also want to know what the cutting-edge AI companies are doing since they are likely to have a significant impact on the world. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "Politics",
            "prompt": (
                "I want to know what's going on in the world of politics so that I can be well-informed in case any recent developments come up in conversation. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        },
        {
            "title": "Climate",
            "prompt": (
                "I want to know what's going on with regard to climate change, including how startups and venture capitalists are addressing the issue, "
                "how policymakers are responding, what climate philanthropists are doing, what strategies the environmental movement is pursuing, and any updates to climate science. "
                + BASE_INSTRUCTIONS
            ),
            "content_type": "articles"
        }
    ]

    # Read the HTML newsletter template
    try:
        template_path = os.path.join(SCRIPT_DIR, "template.html")
        with open(template_path, "r", encoding="utf-8") as file:
            template = file.read()
    except Exception as e:
        logging.exception("Error reading HTML template")
        raise

    client = OpenAI(api_key=API_KEY)
    
    # Dictionary to store bullet points for each section
    sections_data = {}

    # Process each section and gather its bullet points
    for section in sections:
        content = get_content(section["title"])
        
        # Convert content to a clean string representation to reduce token usage
        content_str = json.dumps(content)
        
        prompt = section["prompt"]
        user_content = f"<content>{content_str}</content>"

        try:
            # Log the prompt
            prompt_logger.info(f"\n{'='*80}\nPROMPT FOR {section['title']}\n{'='*80}\nSYSTEM: {prompt}\n\nUSER: {user_content}\n{'='*80}\n")
            
            # Count tokens in the prompt including the XML tags
            token_count = num_tokens_from_string(prompt) + num_tokens_from_string(user_content)
            logging.info(f"Prompt for {section['title']} has {token_count} tokens")
            
            # Prepare messages for the API call
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content}
            ]
            
            # Create the appropriate Pydantic response model based on content type
            if section["content_type"] == "articles":
                # Create a new class with proper type annotation for bullet_points
                class ArticleBulletPointsResponse(BaseModel):
                    bullet_points: List[ArticleBulletPoint]
                response_model = ArticleBulletPointsResponse
            else:  # for emails
                # Create a new class with proper type annotation for bullet_points
                class EmailBulletPointsResponse(BaseModel):
                    bullet_points: List[EmailBulletPoint]
                response_model = EmailBulletPointsResponse
            
            # Make API call with structured output using call_openai_parse_with_backoff
            response = call_openai_parse_with_backoff(
                client,
                messages,
                response_model,
                model=AI_MODEL
            )
            
            # Convert Pydantic models to dictionaries before serializing to JSON
            serializable_bullet_points = [bullet.model_dump() for bullet in response.choices[0].message.parsed.bullet_points]
            # Store the bullet points in the sections_data dictionary
            sections_data[section["title"]] = serializable_bullet_points
            
            # Log the response for debugging
            bullet_points_json = json.dumps(serializable_bullet_points)
            prompt_logger.info(f"\n{'='*80}\nRESPONSE FOR {section['title']}\n{'='*80}\n{bullet_points_json}\n{'='*80}\n")
            
        except Exception as e:
            logging.exception("Error obtaining response for section: %s", section["title"])
            sections_data[section["title"]] = []  # Empty array as fallback
    
    try:
        # Generate the HTML for the newsletter using the template and bullet points
        newsletter = generate_email_html(template, sections_data)
        
        # Log the generated newsletter for debugging
        prompt_logger.info(f"\n{'='*80}\nGENERATED NEWSLETTER\n{'='*80}\n{newsletter}\n{'='*80}\n")
        
    except Exception as e:
        logging.exception("Error generating newsletter HTML")
        # Fallback to a simple HTML message
        newsletter = "<html><body><h1>Daily Briefing</h1><p>There was an error generating the newsletter content.</p></body></html>"

    # Create financial charts and send the email newsletter
    create_charts()
    send_email(newsletter, send_to_everyone)
    logging.info("Daily briefing process completed successfully.")
