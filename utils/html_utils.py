"""
HTML utilities for the Daily Briefing application.

This module provides functions for generating HTML content for the email newsletter.
"""

import re
import logging
from bs4 import BeautifulSoup

def generate_email_html(template: str, sections_data: dict) -> str:
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
            # Make section title lowercase and replace spaces with underscores for use in placeholders
            section_key = section_title.lower().replace(' ', '_')
            
            # Remove all list items for this section since there are no bullet points
            for i in range(1, 4):  # Handle all 3 possible bullet points
                # Define generic pattern to find list items with the section's placeholders
                pattern = r'<li><strong>{' + section_key + f'_headline_{i}' + r'}:.*?</li>'
                # Use re.sub to remove the list item containing the placeholders
                html = re.sub(pattern, '', html)
            
            continue
            
        # Make section title lowercase and replace spaces with underscores for use in placeholders
        section_key = section_title.lower().replace(' ', '_')
        
        # Replace placeholders for each bullet point that exists
        for i, bullet in enumerate(bullet_points, 1):
            if i > 3:  # Only process up to 3 bullet points
                break
                
            # Replace headline and summary
            html = html.replace(f"{{{section_key}_headline_{i}}}", bullet.get("headline", ""))
            html = html.replace(f"{{{section_key}_one_sentence_summary_{i}}}", bullet.get("one_sentence_summary", ""))
            
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
            if bullet_points and "source_name" in bullet_points[0] and "url" in bullet_points[0]:
                # For article-type sections
                pattern = r'<li><strong>{' + section_key + f'_headline_{i}' + r'}:</strong> {' + section_key + f'_one_sentence_summary_{i}' + r'} <a href="{' + section_key + f'_url_{i}' + r'}">{' + section_key + f'_source_name_{i}' + r'}</a></li>'
            elif bullet_points and "sender" in bullet_points[0] and "subject" in bullet_points[0]:
                # For email-type sections
                pattern = r'<li><strong>{' + section_key + f'_headline_{i}' + r'}:</strong> {' + section_key + f'_one_sentence_summary_{i}' + r'} \(Email from {' + section_key + f'_sender_{i}' + r'} with subject "{' + section_key + f'_subject_{i}' + r'}"\)</li>'
            else:
                # For sections with unknown structure, use a more generic pattern
                pattern = r'<li><strong>{' + section_key + f'_headline_{i}' + r'}:.*?</li>'
                
            # Use re.sub to remove the list item containing the placeholders
            html = re.sub(pattern, '', html)
    
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