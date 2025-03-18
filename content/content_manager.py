"""
Content manager module for the Daily Briefing application.

This module dispatches content retrieval requests to the appropriate modules
based on the section title.
"""

import logging
from typing import List, Dict, Any
from .rss_content import (
    get_rundown_content, get_vegconomist_content, get_ea_forum_content
)
from .email_content import get_fast_email_content
from .sitemap_content import get_gq_content

def get_content(title: str) -> List[Dict[str, Any]]:
    """
    Returns content based on the provided title.
    Dispatches to different content-retrieval functions.
    
    Args:
        title: The title of the section to retrieve content for
        
    Returns:
        List[Dict[str, Any]]: A list of content sources with their retrieved content
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
    elif title == "AI":
        content.append({"source_name": "The Rundown AI", "content": get_rundown_content(), "content_type": "articles"})
        # Remove the Axios AI+ content line
        # content.append({"source_name": "Axios AI+", "content": get_axios_article(AXIOS_NEWSLETTERS["AI+"]), "content_type": "articles"})
        return content
    else:
        logging.warning(f"No content retrieval function defined for title: {title}")
        return content 