"""
HTML utilities for the Daily Briefing application.

This module provides functions for generating HTML content for the email newsletter.
"""

import re
import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
from models.data_models import ContentElement

def generate_email_html(template: str, newsletter_elements: List[ContentElement], image_paths: Optional[Dict[str, str]] = None) -> str:
    """
    Generates HTML for the email newsletter using the template and newsletter elements.
    
    Args:
        template (str): HTML template string
        newsletter_elements (List[ContentElement]): List of newsletter content elements
        image_paths (Dict[str, str], optional): Dictionary of image IDs to file paths
        
    Returns:
        str: Generated HTML content for the email
    """
    # Generate HTML from the content elements
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
        
        # Remove "Published on..." prefix that appears in many EA Forum posts
        text = re.sub(r'^Published on [A-Za-z]+ \d+, \d+ \d+:\d+ [AP]M [A-Z]+\s*', '', text)
        
        # Remove "Discuss" suffix that appears in many EA Forum posts
        text = re.sub(r'\s*Discuss$', '', text)
        
        return text.strip()
    except Exception as e:
        logging.warning(f"Error cleaning HTML content: {e}")
        # Fall back to a simpler approach
        return re.sub(r'<[^>]*>', ' ', html_content).strip() 