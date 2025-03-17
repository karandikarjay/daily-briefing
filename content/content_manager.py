"""
Content manager module for the Daily Briefing application.

This module dispatches content retrieval requests to the appropriate modules
based on the section title.
"""

import logging
from typing import List, Dict, Any
from .rss_content import (
    get_rundown_content, get_ts_content, 
    get_vegconomist_content, get_ea_forum_content
)
from .web_content import get_axios_article, get_semafor_article
from .email_content import get_fast_email_content
from .sitemap_content import get_gq_content
from config import AXIOS_NEWSLETTERS, SEMAFOR_NEWSLETTERS

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
    elif title == "Venture Capital":
        content.append({"source_name": "Term Sheet", "content": get_ts_content(), "content_type": "articles"})
        content.append({"source_name": "Axios Pro Rata", "content": get_axios_article(AXIOS_NEWSLETTERS["Pro Rata"]), "content_type": "articles"})
        return content
    elif title == "Financial Markets":
        content.append({"source_name": "Axios Markets", "content": get_axios_article(AXIOS_NEWSLETTERS["Markets"]), "content_type": "articles"})
        content.append({"source_name": "Axios Macro", "content": get_axios_article(AXIOS_NEWSLETTERS["Macro"]), "content_type": "articles"})
        content.append({"source_name": "Axios Closer", "content": get_axios_article(AXIOS_NEWSLETTERS["Closer"]), "content_type": "articles"})
        content.append({"source_name": "Semafor Business", "content": get_semafor_article(SEMAFOR_NEWSLETTERS["Business"]), "content_type": "articles"})
        return content
    elif title == "AI":
        content.append({"source_name": "The Rundown AI", "content": get_rundown_content(), "content_type": "articles"})
        content.append({"source_name": "Axios AI+", "content": get_axios_article(AXIOS_NEWSLETTERS["AI+"]), "content_type": "articles"})
        return content
    elif title == "Politics":
        content.append({"source_name": "Axios AM", "content": get_axios_article(AXIOS_NEWSLETTERS["AM"]), "content_type": "articles"})
        content.append({"source_name": "Axios PM", "content": get_axios_article(AXIOS_NEWSLETTERS["PM"]), "content_type": "articles"})
        content.append({"source_name": "Semafor Flagship", "content": get_semafor_article(SEMAFOR_NEWSLETTERS["Flagship"]), "content_type": "articles"})
        content.append({"source_name": "Semafor Principals", "content": get_semafor_article(SEMAFOR_NEWSLETTERS["Principals"]), "content_type": "articles"})
        content.append({"source_name": "Semafor Americana", "content": get_semafor_article(SEMAFOR_NEWSLETTERS["Americana"]), "content_type": "articles"})
        return content
    elif title == "Climate":
        content.append({"source_name": "Axios Generate", "content": get_axios_article(AXIOS_NEWSLETTERS["Generate"]), "content_type": "articles"})
        content.append({"source_name": "Semafor Net Zero", "content": get_semafor_article(SEMAFOR_NEWSLETTERS["Net Zero"]), "content_type": "articles"})
        return content
    else:
        logging.warning(f"No content retrieval function defined for title: {title}")
        return content 