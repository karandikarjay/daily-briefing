"""
HTML utilities for the Daily Briefing application.

This module provides functions for generating HTML content for the email newsletter.
"""

import re
import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Union
from models.data_models import ContentElement, AxiosNewsletterResponse


def generate_email_html(template: str, newsletter_content: Union[List[ContentElement], AxiosNewsletterResponse], image_paths: Optional[Dict[str, str]] = None) -> str:
    """
    Generates HTML for the email newsletter using the template and newsletter content.

    Args:
        template (str): HTML template string
        newsletter_content: Either List[ContentElement] (legacy) or AxiosNewsletterResponse (new format)
        image_paths (Dict[str, str], optional): Dictionary of image IDs to file paths

    Returns:
        str: Generated HTML content for the email
    """
    # Check if we're using the new Axios format
    if isinstance(newsletter_content, AxiosNewsletterResponse):
        return _generate_axios_html(template, newsletter_content, image_paths)
    else:
        # Legacy format with ContentElement list
        return _generate_legacy_html(template, newsletter_content, image_paths)


def _generate_axios_html(template: str, axios_response: AxiosNewsletterResponse, image_paths: Optional[Dict[str, str]] = None) -> str:
    """
    Generates HTML for Axios-style newsletter with clean, minimal formatting.

    Args:
        template: HTML template string
        axios_response: The Axios newsletter response with stories
        image_paths: Dictionary of image IDs to file paths

    Returns:
        str: Generated HTML content
    """
    newsletter_html = ""

    # Add intro paragraph with bold lead-in
    if axios_response.intro:
        newsletter_html += f'<p class="intro-text">{axios_response.intro}</p>\n'

    # Generate HTML for each story
    for i, story in enumerate(axios_response.stories):
        story_html = '<div class="story-section">\n'

        # Story header with consistent numbering: "1. Headline", "2. Headline", "3. Headline"
        story_html += f'  <h2 class="story-header"><span class="story-number">{i + 1}.</span> {story.headline}</h2>\n'

        # Add image right after headline (like Axios)
        image_id = f"story_image_{i + 1}"
        if image_paths and image_id in image_paths:
            story_html += f'  <img class="story-image" src="cid:{image_id}" alt="{story.headline}">\n'
            if story.image_caption:
                story_html += f'  <p class="image-caption">{story.image_caption}</p>\n'

        story_html += '  <div class="story-content">\n'

        # Convert bullets to flowing paragraphs with bold lead-ins
        for bullet in story.bullets:
            # Clean up label - remove trailing colon if present for cleaner look
            label = bullet.label.rstrip(':')

            # All bullets become paragraphs with bold lead-ins
            story_html += f'    <p><strong>{label}:</strong> {bullet.text}</p>\n'

        story_html += '  </div>\n'
        story_html += '</div>\n'
        newsletter_html += story_html

    # Add closing if present
    if axios_response.closing:
        newsletter_html += f'<p style="margin-top: 24px;">{axios_response.closing}</p>\n'

    # Replace the newsletter content placeholder
    html = template.replace("{newsletter_content}", newsletter_html)
    return html


def _generate_legacy_html(template: str, newsletter_elements: List[ContentElement], image_paths: Optional[Dict[str, str]] = None) -> str:
    """
    Generates HTML using the legacy ContentElement format.

    Args:
        template: HTML template string
        newsletter_elements: List of ContentElement objects
        image_paths: Dictionary of image IDs to file paths

    Returns:
        str: Generated HTML content
    """
    newsletter_html = ""

    for element in newsletter_elements:
        if element.type == "heading":
            newsletter_html += f"<h2>{element.content}</h2>\n"
        elif element.type == "paragraph":
            newsletter_html += f"<p>{element.content}</p>\n"
        elif element.type == "image_description":
            # For image descriptions, we'll add a div with the image
            image_id = element.content

            # Check if there's a caption
            caption_html = ""
            if element.caption:
                caption_html = f'<p class="image-caption"><em>{element.caption}</em></p>'

            newsletter_html += f'<div class="generated-image"><img src="cid:{image_id}" alt="Generated image related to newsletter content" style="width:100%;max-width:800px;height:auto;margin:15px auto;display:block;border-radius:8px;">{caption_html}</div>\n'

    # Replace the newsletter content placeholder with the actual newsletter text
    html = template.replace("{newsletter_content}", newsletter_html)
    return html

def clean_html_content(html_content: str) -> str:
    """
    Cleans HTML content to reduce token usage while preserving meaningful content.
    Removes unnecessary tags, attributes, and whitespace.
    
    Args:
        html_content: The HTML content to clean
        
    Returns:
        str: The cleaned text content
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
        
        return text.strip()
    except Exception as e:
        logging.warning(f"Error cleaning HTML content: {e}")
        # Fall back to a simpler approach
        return re.sub(r'<[^>]*>', ' ', html_content).strip() 