"""
Content manager module for the Daily Briefing application.

This module dispatches content retrieval requests to the appropriate modules
based on the section title.
"""

import logging
import json
from typing import List, Dict, Any
from .rss_content import (
    get_rundown_content, get_vegconomist_content, get_ea_forum_content
)
from .email_content import get_fast_email_content
from .sitemap_content import get_gq_content
from utils.api_utils import num_tokens_from_string

def limit_content_by_tokens(content_list: List[Dict[str, Any]], max_tokens: int, section_title: str) -> List[Dict[str, Any]]:
    """
    Limits the content items to stay under a token limit.
    Removes oldest items first, sorting by the datetime field.
    
    Args:
        content_list: List of content items with datetime field
        max_tokens: Maximum token limit
        section_title: Name of the section for logging
        
    Returns:
        List[Dict[str, Any]]: Limited list of content items
    """
    if not content_list:
        return content_list
    
    # Make a copy to avoid modifying the original list
    content = content_list.copy()
    
    # Sort content by datetime (oldest first)
    content.sort(key=lambda x: x.get("datetime", ""))
    
    # Helper function to serialize datetime objects for token counting
    def serialize_for_token_count(item):
        # Create a copy to avoid modifying the original item
        item_copy = item.copy()
        
        # Convert datetime to string if present
        if "datetime" in item_copy and hasattr(item_copy["datetime"], "isoformat"):
            item_copy["datetime"] = item_copy["datetime"].isoformat()
            
        return json.dumps(item_copy)
    
    # Calculate total tokens
    total_tokens = sum(num_tokens_from_string(serialize_for_token_count(item)) for item in content)
    logging.info(f"{section_title}: Initial collection has {len(content)} items with {total_tokens} tokens")
    
    # Remove oldest items until we're under the token limit
    while total_tokens > max_tokens and len(content) > 1:
        # Remove the oldest item (first in the list since we sorted by datetime)
        removed_item = content.pop(0)
        item_type = "email" if "subject" in removed_item else "article"
        item_title = removed_item.get("subject", "") if item_type == "email" else removed_item.get("title", "untitled")
        logging.info(f"{section_title}: Removed {item_type} '{item_title}' to reduce token count")
        
        # Recalculate token count
        total_tokens = sum(num_tokens_from_string(serialize_for_token_count(item)) for item in content)
        logging.info(f"{section_title}: After removal, {len(content)} items with {total_tokens} tokens remain")
    
    # Convert all datetime objects to strings for JSON serialization before returning
    for item in content:
        if "datetime" in item and hasattr(item["datetime"], "isoformat"):
            item["datetime"] = item["datetime"].isoformat()
    
    return content

def get_content(title: str, max_tokens: int = 20000) -> List[Dict[str, Any]]:
    """
    Returns content based on the provided title.
    Dispatches to different content-retrieval functions and limits total tokens.
    
    Args:
        title: The title of the section to retrieve content for
        max_tokens: Maximum token limit for all content in this section
        
    Returns:
        List[Dict[str, Any]]: A list of content sources with their retrieved content
    """
    all_content = []
    
    if title == "Alternative Protein":
        all_content.append({"source_name": "Green Queen", "content": get_gq_content(), "content_type": "articles"})
        all_content.append({"source_name": "Vegconomist", "content": get_vegconomist_content(), "content_type": "articles"})
    elif title == "Vegan Movement":
        all_content.append({"source_name": "FAST Email List", "content": get_fast_email_content(), "content_type": "emails"})
    elif title == "Effective Altruism":
        all_content.append({"source_name": "EA Forum", "content": get_ea_forum_content(), "content_type": "articles"})
    elif title == "AI":
        all_content.append({"source_name": "The Rundown AI", "content": get_rundown_content(), "content_type": "articles"})
    else:
        logging.warning(f"No content retrieval function defined for title: {title}")
        return all_content
    
    # Combine all content from different sources for token limiting
    combined_content = []
    for source in all_content:
        combined_content.extend(source["content"])
    
    # Apply token limit to the combined content
    if combined_content:
        limited_content = limit_content_by_tokens(combined_content, max_tokens, title)
        
        # Update each source with only its filtered content
        for source in all_content:
            source_name = source["source_name"]
            content_type = source["content_type"]
            
            # Filter the limited content to only include items from this source
            source["content"] = [
                item for item in limited_content 
                if (content_type == "emails" and "subject" in item) or 
                   (content_type == "articles" and "url" in item)
            ]
            
            logging.info(f"{title} - {source_name}: Final content count: {len(source['content'])}")
    
    return all_content