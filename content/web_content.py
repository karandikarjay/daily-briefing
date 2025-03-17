"""
Web content retrieval module for the Daily Briefing application.

This module provides functions for retrieving content from web pages using
both standard requests and headless browser automation.
"""

import logging
import requests
from bs4 import BeautifulSoup
from typing import Dict
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from config import HEADERS

def get_axios_article(url: str) -> Dict[str, str]:
    """
    Uses Playwright (with stealth) to render a page and extract article content
    from specified elements. Returns a dictionary with URL and article text.
    
    Args:
        url: The URL of the Axios article to retrieve
        
    Returns:
        Dict[str, str]: A dictionary with URL and article text
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
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
        logging.exception(f"Error retrieving Axios article from {url}")
        return {"url": url, "article": ""}

def get_semafor_article(url: str) -> Dict[str, str]:
    """
    Fetches and parses an article from the given Semafor URL.
    Returns a dictionary with the URL and the extracted article text.
    
    Args:
        url: The URL of the Semafor article to retrieve
        
    Returns:
        Dict[str, str]: A dictionary with URL and article text
    """
    try:
        response = requests.get(url, headers=HEADERS)
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

        logging.info(f"Extracted article from {url}")
        return {"url": url, "article": article_text}

    except Exception as e:
        logging.exception(f"Error retrieving article from {url}")
        return {"url": url, "article": ""} 