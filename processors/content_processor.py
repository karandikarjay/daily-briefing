#!/usr/bin/env python3
"""
Content Processor Module

This module contains functions for processing content from various sources,
including filtering articles by date and providing common prompts for the API.
"""

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests
from typing import List, Dict, Any, Optional, Union

from config import HEADERS
from models import ArticleBulletPoint, EmailBulletPoint, BulletPointResponse
from utils.api_utils import call_openai_parse_with_backoff, num_tokens_from_string

# Common instructions for all bullet point generation
COMMON_BULLET_POINT_INSTRUCTIONS = (
    "The value corresponding to the 'headline' key should be a headline in title case that captures the main point of the bullet point. "
    "The value corresponding to the 'one_sentence_summary' key should be a one-sentence summary of the bullet point. "
    "The output should be in valid JSON format without any surrounding markdown code block markers. "
)

# Unified format for all sections
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

# Base instructions for all sections
BASE_INSTRUCTIONS = (
    "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
    "Give me the bullet points only without anything before or after. "
    "Make sure that there are exactly 3 bullet points (no more, no fewer). "
    "Make sure that any claims you make are substantiated by the text of the sources you reference. "
)


def get_latest_24h_articles(sitemap_urls: List[str], source_name: str) -> List[str]:
    """
    Retrieves article URLs from a list of sitemap URLs for the last 24 hours
    from the most recent article.
    
    Args:
        sitemap_urls (List[str]): List of sitemap URLs to search
        source_name (str): Name of the source for logging purposes
        
    Returns:
        List[str]: List of article URLs from the last 24 hours
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


def get_section_prompt(section_title: str) -> str:
    """
    Returns the appropriate prompt for a given section.
    
    Args:
        section_title (str): The title of the section
        
    Returns:
        str: The prompt for the section
    """
    prompts = {
        "Alternative Protein": (
            "I am an investor in alternative protein startups. I want to be aware of recent developments in the alternative protein industry "
            "(especially recent funding rounds and new product launches) so that I can invest wisely. "
            + BASE_INSTRUCTIONS
        ),
        "Vegan Movement": (
            "I am a philanthropist who donates to the vegan movement. I want to stay up to date on what's going on in the vegan movement "
            "(particularly recent accomplishments, new research, and lessons learned) so that I can make better philanthropic decisions when we're pitched by vegan nonprofits. "
            "Note that Farmed Animal Strategic Team (FAST) is not the name of an organization, but simply the name of an email list where people in the vegan movement share updates. "
            + BASE_INSTRUCTIONS
        ),
        "Effective Altruism": (
            "I am a philanthropist. I want to be aware of the latest discussions in the effective altruism community so that I can make donations effectively. "
            + BASE_INSTRUCTIONS
        ),
        "Venture Capital": (
            "I am a venture capitalist. I want to know what's going on in the venture capital ecosystem, such as any major deals and broader market trends. "
            + BASE_INSTRUCTIONS
        ),
        "Financial Markets": (
            "I am an investor at a hedge fund. I want to know what's going on in the financial markets, particularly the performance of the markets as a whole, any significant economic news releases, and any major deals. "
            + BASE_INSTRUCTIONS
        ),
        "AI": (
            "I want to know what new developments are going on in the world of AI tools so that I can increase my personal productivity and I also want to know what the cutting-edge AI companies are doing since they are likely to have a significant impact on the world. "
            + BASE_INSTRUCTIONS
        ),
        "Politics": (
            "I want to know what's going on in the world of politics so that I can be well-informed in case any recent developments come up in conversation. "
            + BASE_INSTRUCTIONS
        ),
        "Climate": (
            "I want to know what's going on with regard to climate change, including how startups and venture capitalists are addressing the issue, "
            "how policymakers are responding, what climate philanthropists are doing, what strategies the environmental movement is pursuing, and any updates to climate science. "
            + BASE_INSTRUCTIONS
        )
    }
    
    return prompts.get(section_title, BASE_INSTRUCTIONS)


def process_content_with_llm(client, section_title: str, content: List[Dict], model: str) -> List[Dict]:
    """
    Process content for a section through the OpenAI API.
    
    Args:
        client: OpenAI client instance
        section_title (str): Title of the section
        content (List[Dict]): Content to process
        model (str): AI model to use
        
    Returns:
        List[Dict]: List of bullet points for the section
    """
    # Create prompt and user content
    prompt = get_section_prompt(section_title)
    user_content = f"<content>{json.dumps(content)}</content>"
    
    # Get content type (articles or emails)
    content_type = content[0].get("content_type") if content else "articles"
    
    try:
        # Log the prompt
        logging.getLogger('prompts').info(
            f"\n{'='*80}\nPROMPT FOR {section_title}\n{'='*80}\n"
            f"SYSTEM: {prompt}\n\nUSER: {user_content}\n{'='*80}\n"
        )
        
        # Count tokens in the prompt including the XML tags
        token_count = num_tokens_from_string(prompt) + num_tokens_from_string(user_content)
        logging.info(f"Prompt for {section_title} has {token_count} tokens")
        
        # Prepare messages for the API call
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content}
        ]
        
        # Create the appropriate response model based on content type
        if content_type == "articles":
            from models import ArticleBulletPointsResponse
            response_model = ArticleBulletPointsResponse
        else:  # for emails
            from models import EmailBulletPointsResponse
            response_model = EmailBulletPointsResponse
        
        # Make API call with structured output
        response = call_openai_parse_with_backoff(
            client,
            messages,
            response_model,
            model=model
        )
        
        # Convert Pydantic models to dictionaries before serializing to JSON
        serializable_bullet_points = [bullet.model_dump() for bullet in response.choices[0].message.parsed.bullet_points]
        
        # Log the response for debugging
        bullet_points_json = json.dumps(serializable_bullet_points)
        logging.getLogger('prompts').info(
            f"\n{'='*80}\nRESPONSE FOR {section_title}\n{'='*80}\n"
            f"{bullet_points_json}\n{'='*80}\n"
        )
        
        return serializable_bullet_points
        
    except Exception as e:
        logging.exception("Error obtaining response for section: %s", section_title)
        return []  # Empty array as fallback


def process_structured_content(client, content_by_section: Dict[str, List[Dict]], model: str) -> Dict[str, List[Dict]]:
    """
    Process all sections and extract key points.
    
    Args:
        client: OpenAI client instance
        content_by_section (Dict[str, List[Dict]]): Content organized by section
        model (str): AI model to use
        
    Returns:
        Dict[str, List[Dict]]: Dictionary mapping section titles to their bullet points
    """
    sections_data = {}
    
    # Process each section and gather its bullet points
    for section_title, content in content_by_section.items():
        if not content:
            logging.warning(f"No content for section: {section_title}")
            sections_data[section_title] = []
            continue
            
        sections_data[section_title] = process_content_with_llm(client, section_title, content, model)
    
    return sections_data