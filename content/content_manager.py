"""
Content manager module for the Daily Briefing application.

This module dispatches content retrieval requests to the appropriate modules
based on the section title.
"""

import logging
import json
from typing import List, Dict, Any
from .tavily_content import get_tavily_content
from .email_content import get_fast_email_content
from .sitemap_content import get_gq_content
from .rss_content import get_vegconomist_content
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
    content.sort(key=lambda x: x.get("datetime") or "")
    
    # Calculate total tokens based on the JSON string that will be used in the prompt
    total_tokens = num_tokens_from_string(json.dumps(content))
    logging.info(f"{section_title}: Initial collection has {len(content)} items with {total_tokens} tokens")
    
    # Remove oldest items until we're under the token limit
    while total_tokens > max_tokens and len(content) > 1:
        # Remove the oldest item (first in the list since we sorted by datetime)
        removed_item = content.pop(0)
        item_type = "email" if "subject" in removed_item else "article"
        item_title = removed_item.get("subject", "") if item_type == "email" else removed_item.get("title", "untitled")
        logging.info(f"{section_title}: Removed {item_type} '{item_title}' from {removed_item.get('source_name', 'unknown source')} to reduce token count")
        
        # Recalculate token count
        total_tokens = num_tokens_from_string(json.dumps(content))
        logging.info(f"{section_title}: After removal, {len(content)} items with {total_tokens} tokens remain")
    
    return content

def get_content(title: str, max_tokens: int = 20000) -> List[Dict[str, Any]]:
    """
    Returns content based on the provided title.
    Dispatches to different content-retrieval functions and limits total tokens.
    
    Args:
        title: The title of the section to retrieve content for
        max_tokens: Maximum token limit for all content in this section
        
    Returns:
        List[Dict[str, Any]]: A list of content items
    """
    all_content = []

    if title == "Alternative Protein":
        all_content.extend(get_gq_content())
        all_content.extend(get_vegconomist_content())
        all_content.extend(get_tavily_content("Alternative Protein"))
    elif title == "Vegan Movement":
        # FAST emails are the primary source — reserve token budget for them
        fast_content = get_fast_email_content()
        tavily_content = get_tavily_content("Vegan Movement")
        fast_tokens = num_tokens_from_string(json.dumps(fast_content)) if fast_content else 0
        tavily_budget = max(0, max_tokens - fast_tokens)
        if tavily_content:
            tavily_content = limit_content_by_tokens(tavily_content, tavily_budget, f"{title} (Tavily)")
        all_content.extend(fast_content)
        all_content.extend(tavily_content)
        return all_content
    elif title == "AI":
        all_content.extend(get_tavily_content("AI"))
    else:
        logging.warning(f"No content retrieval function defined for title: {title}")
        return all_content

    # Apply token limit to the combined content
    if all_content:
        all_content = limit_content_by_tokens(all_content, max_tokens, title)

    return all_content