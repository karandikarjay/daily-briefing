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
from config import API_KEY, GOOGLE_USERNAME, GOOGLE_PASSWORD

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
    for all articles published in the last 24 hours from the most recent post.
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

        # Calculate the cutoff time (24 hours before the most recent post)
        cutoff_time = latest_datetime - timedelta(hours=24)
        logging.info("EA Forum: Using posts between %s and %s", cutoff_time, latest_datetime)

        # Second pass: collect posts within the 24-hour window
        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            desc_elem = item.find("description")
            pub_date_elem = item.find("pubDate")
            
            if not (title_elem is not None and link_elem is not None and pub_date_elem is not None):
                continue

            title = title_elem.text.strip() if title_elem.text else ""
            url = link_elem.text.strip() if link_elem.text else ""
            article = desc_elem.text.strip() if (desc_elem is not None and desc_elem.text) else ""
            pub_date_str = pub_date_elem.text.strip()
            
            try:
                dt = datetime.strptime(pub_date_str, "%a, %d %b %Y %H:%M:%S GMT")
                dt = dt.replace(tzinfo=timezone.utc)
                dt_est = dt.astimezone(ZoneInfo("America/New_York"))
                
                if cutoff_time <= dt_est <= latest_datetime:
                    entries.append({
                        "url": url,
                        "title": title,
                        "article": article
                    })
            except Exception:
                logging.warning("Error parsing date for item: %s", title)
                continue
        
        logging.info("Extracted %d articles from EA Forum in the last 24 hours", len(entries))
        return entries

    except Exception as e:
        logging.exception("Error retrieving content from EA Forum RSS feed")
        return []


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
        content.append({"source_name": "Green Queen", "articles": get_gq_content()})
        content.append({"source_name": "Vegconomist", "articles": get_vegconomist_content()})
        return content
    elif title == "Vegan Movement":
        content = get_fast_email_content()
        return content
    elif title == "Effective Altruism":
        content.append({"source_name": "EA Forum", "articles": get_ea_forum_content()})
        return content
    elif title == "Venture Capital":
        content.append({"source_name": "Term Sheet", "articles": get_ts_content()})
        content.append({"source_name": "Axios Pro Rata", "articles": get_axios_article("https://www.axios.com/newsletters/axios-pro-rata")})
        return content
    elif title == "Financial Markets":
        content.append({"source_name": "Short Squeez", "articles": get_ss_content()})
        content.append({"source_name": "Axios Markets", "articles": get_axios_article("https://www.axios.com/newsletters/axios-markets")})
        content.append({"source_name": "Axios Macro", "articles": get_axios_article("https://www.axios.com/newsletters/axios-macro")})
        content.append({"source_name": "Axios Closer", "articles": get_axios_article("https://www.axios.com/newsletters/axios-closer")})
        content.append({"source_name": "Semafor Business", "articles": get_semafor_article("https://www.semafor.com/newsletters/business/latest")})
        return content
    elif title == "AI":
        content.append({"source_name": "The Rundown AI", "articles": get_rundown_content()})
        content.append({"source_name": "Axios AI+", "articles": get_axios_article("https://www.axios.com/newsletters/axios-ai-plus")})
        return content
    elif title == "Politics":
        content.append({"source_name": "Axios AM", "articles": get_axios_article("https://www.axios.com/newsletters/axios-am")})
        content.append({"source_name": "Axios PM", "articles": get_axios_article("https://www.axios.com/newsletters/axios-pm")})
        content.append({"source_name": "Semafor Flagship", "articles": get_semafor_article("https://www.semafor.com/newsletters/flagship/latest")})
        content.append({"source_name": "Semafor Principals", "articles": get_semafor_article("https://www.semafor.com/newsletters/principals/latest")})
        content.append({"source_name": "Semafor Americana", "articles": get_semafor_article("https://www.semafor.com/newsletters/americana/latest")})
        return content
    elif title == "Climate":
        content.append({"source_name": "Axios Generate", "articles": get_axios_article("https://www.axios.com/newsletters/axios-generate")})
        content.append({"source_name": "Semafor Net Zero", "articles": get_semafor_article("https://www.semafor.com/newsletters/netzero/latest")})
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

    if send_to_everyone:
        receiver_emails.append("robert@alwyncapital.com")

    message = MIMEMultipart("related")
    message["Subject"] = "Daily Briefing"
    message["From"] = sender_email
    message["To"] = ", ".join(receiver_emails)

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
            server.sendmail(sender_email, receiver_emails, message.as_string())
        logging.info("Email sent successfully to %s", ", ".join(receiver_emails))
    except Exception as e:
        logging.exception("Error sending email")


if __name__ == "__main__":
    # Check for the --send-to-everyone flag
    send_to_everyone = "--send-to-everyone" in sys.argv

    # Define common instructions for bullet points
    COMMON_BULLET_POINT_INSTRUCTIONS = (
        "The value corresponding to the 'headline' key should be a headline in title case that captures the main point of the bullet point. "
        "The value corresponding to the 'one_sentence_summary' key should be a one-sentence summary of the bullet point. "
        "The output should be in valid JSON format without any surrounding markdown code block markers. "
    )

    # Define specific formats for different sections
    GENERAL_FORMAT = (
        "Return the bullet points in JSON format as an array of 3 objects with the keys 'headline', 'one_sentence_summary', 'source_name', and 'url'. " +
        "The value corresponding to the 'source_name' key should be the name of the source that provided the information for the bullet point. " +
        "Make sure that the source_name is one of the values corresponding to the key 'source_name' in the data that I have provided. " +
        "The value corresponding to the 'url' key should be the URL of the source that provided the information for the bullet point. " +
        "Make sure that the URL is one of the values corresponding to the key 'url' in the data that I have provided. " +
        COMMON_BULLET_POINT_INSTRUCTIONS
    )

    EA_FORMAT = (
        "Return the bullet points in JSON format as an array of 3 objects with the keys 'headline', 'one_sentence_summary', and 'url'. " +
        "The value corresponding to the 'url' key should be the URL of the source that provided the information for the bullet point. " +
        "Make sure that the URL is one of the values corresponding to the key 'url' in the data that I have provided. " +
        COMMON_BULLET_POINT_INSTRUCTIONS
    )

    EMAIL_FORMAT = (
        "Return the bullet points in JSON format as an array of 3 objects with the keys 'headline', 'one_sentence_summary', 'sender', and 'subject'. " +
        "The value corresponding to the 'sender' key should be the name of the sender of the email that provided the information for the bullet point. " +
        "The value corresponding to the 'subject' key should be the subject of the email that provided the information for the bullet point. " +
        COMMON_BULLET_POINT_INSTRUCTIONS
    )

    # Define sections for the daily briefing with their prompts
    BASE_INSTRUCTIONS = (
        "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
        "Give me the 3 bullet points only without anything before or after. "
        "Make sure that any claims you make are substantiated by the text of the sources you reference. "
    )

    sections = [
        {
            "title": "Alternative Protein",
            "prompt": (
                "I am an investor in alternative protein startups. I want to be aware of recent developments in the alternative protein industry "
                "(especially recent funding rounds and new product launches) so that I can invest wisely. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
        },
        {
            "title": "Vegan Movement",
            "prompt": (
                "I am a philanthropist who donates to the vegan movement. I want to stay up to date on what's going on in the vegan movement "
                "(particularly recent accomplishments, new research, and lessons learned) so that I can make better philanthropic decisions when we're pitched by vegan nonprofits. "
                "Note that Farmed Animal Strategic Team (FAST) is not the name of an organization, but simply the name of an email list where people in the vegan movement share updates. "
                + BASE_INSTRUCTIONS +
                EMAIL_FORMAT
            )
        },
        {
            "title": "Effective Altruism",
            "prompt": (
                "I am a philanthropist. I want to be aware of the latest discussions in the effective altruism community so that I can make donations effectively. "
                + BASE_INSTRUCTIONS +
                EA_FORMAT
            )
        },
        {
            "title": "Venture Capital",
            "prompt": (
                "I am a venture capitalist. I want to know what's going on in the venture capital ecosystem, such as any major deals and broader market trends. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
        },
        {
            "title": "Financial Markets",
            "prompt": (
                "I am an investor at a hedge fund. I want to know what's going on in the financial markets, particularly the performance of the markets as a whole, any significant economic news releases, and any major deals. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
        },
        {
            "title": "AI",
            "prompt": (
                "I want to know what new developments are going on in the world of AI tools so that I can increase my personal productivity and I also want to know what the cutting-edge AI companies are doing since they are likely to have a significant impact on the world. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
        },
        {
            "title": "Politics",
            "prompt": (
                "I want to know what's going on in the world of politics so that I can be well-informed in case any recent developments come up in conversation. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
        },
        {
            "title": "Climate",
            "prompt": (
                "I want to know what's going on with regard to climate change, including how startups and venture capitalists are addressing the issue, "
                "how policymakers are responding, what climate philanthropists are doing, what strategies the environmental movement is pursuing, and any updates to climate science. "
                + BASE_INSTRUCTIONS +
                GENERAL_FORMAT
            )
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

    main_prompt = ("Write a daily briefing. I have provided the sections that I want below. "
                   "Give the response in HTML format that would be suitable for an email newsletter. "
                   "The output should be in valid HTML format without any surrounding markdown code block markers. I have provided an HTML template for the newsletter below. "
                   "Do not include a copyright notice at the bottom.\n"
                   f"<template>{template}</template>")

    client = OpenAI(api_key=API_KEY)

    # Process each section and append its bullet points to the main prompt
    for section in sections:
        content = get_content(section["title"])
        prompt = section["prompt"] + f"<content>{content}</content>"

        try:
            # Log the prompt
            prompt_logger.info(f"\n{'='*80}\nPROMPT FOR {section['title']}\n{'='*80}\n{prompt}\n{'='*80}\n")
            
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="o1-mini",
            )
            bullet_points = response.choices[0].message.content
            
            # Log the response
            prompt_logger.info(f"\n{'='*80}\nRESPONSE FOR {section['title']}\n{'='*80}\n{bullet_points}\n{'='*80}\n")
            
        except Exception as e:
            logging.exception("Error obtaining response for section: %s", section["title"])
            bullet_points = ""
        
        title = section["title"]
        main_prompt += f"\n<section><title>{title}</title><bullet_points>{bullet_points}</bullet_points></section>"

    try:
        # Log the main prompt
        prompt_logger.info(f"\n{'='*80}\nMAIN PROMPT\n{'='*80}\n{main_prompt}\n{'='*80}\n")
        
        newsletter_response = client.chat.completions.create(
            messages=[{"role": "user", "content": main_prompt}],
            model="o1-mini",
        )
        newsletter = newsletter_response.choices[0].message.content
        
        # Log the newsletter response
        prompt_logger.info(f"\n{'='*80}\nNEWSLETTER RESPONSE\n{'='*80}\n{newsletter}\n{'='*80}\n")
        
    except Exception as e:
        logging.exception("Error generating final newsletter")
        newsletter = ""

    # Create financial charts and send the email newsletter
    create_charts()
    send_email(newsletter, send_to_everyone)
    logging.info("Daily briefing process completed successfully.")
