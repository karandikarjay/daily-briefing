#!/usr/bin/env python3
"""
Daily Briefing Script

This script gathers content from various sources (RSS feeds, sitemaps, emails, etc.),
processes the content, creates charts from financial data, and sends out an email
newsletter containing a daily briefing.
"""

import sys
import json
import logging
from openai import OpenAI
from typing import Dict, List

# Import configuration
from config import (
    OPENAI_API_KEY, AI_MODEL, SECTIONS, TEMPLATE_PATH
)

# Import utilities
from utils.logging_setup import setup_logging, log_section_prompt, log_section_response, log_newsletter
from utils.api_utils import num_tokens_from_string, call_openai_parse_with_backoff
from utils.html_utils import generate_email_html
from utils.email_utils import send_email

# Import content retrieval
from content import get_content

# Import chart generation
from charts import create_charts

# Import models
from models.data_models import (
    ArticleBulletPointsResponse,
    EmailBulletPointsResponse
)

def main():
    """Main function to run the daily briefing process."""
    # Check for the --send-to-everyone flag
    send_to_everyone = "--send-to-everyone" in sys.argv

    # Set up logging
    logger, prompt_logger = setup_logging()
    
    # Initialize OpenAI client
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Dictionary to store bullet points for each section
    sections_data = {}

    # Process each section and gather its bullet points
    for section in SECTIONS:
        content = get_content(section["title"])
        
        # Convert content to a clean string representation to reduce token usage
        content_str = json.dumps(content)
        
        prompt = section["prompt"]
        user_content = f"<content>{content_str}</content>"

        try:
            # Log the prompt
            log_section_prompt(prompt_logger, section["title"], prompt, user_content)
            
            # Count tokens in the prompt including the XML tags
            token_count = num_tokens_from_string(prompt) + num_tokens_from_string(user_content)
            logging.info(f"Prompt for {section['title']} has {token_count} tokens")
            
            # Prepare messages for the API call
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content}
            ]
            
            # Create the appropriate Pydantic response model based on content type
            if section["content_type"] == "articles":
                response_model = ArticleBulletPointsResponse
            else:  # for emails
                response_model = EmailBulletPointsResponse
            
            # Make API call with structured output using call_openai_parse_with_backoff
            response = call_openai_parse_with_backoff(
                client,
                messages,
                response_model,
                model=AI_MODEL
            )
            
            # Convert Pydantic models to dictionaries before serializing to JSON
            serializable_bullet_points = [bullet.model_dump() for bullet in response.choices[0].message.parsed.bullet_points]
            # Store the bullet points in the sections_data dictionary
            sections_data[section["title"]] = serializable_bullet_points
            
            # Log the response for debugging
            bullet_points_json = json.dumps(serializable_bullet_points)
            log_section_response(prompt_logger, section["title"], bullet_points_json)
            
        except Exception as e:
            logging.exception(f"Error obtaining response for section: {section['title']}")
            sections_data[section["title"]] = []  # Empty array as fallback
    
    try:
        # Read the HTML newsletter template
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as file:
            template = file.read()
            
        # Generate the HTML for the newsletter using the template and bullet points
        newsletter = generate_email_html(template, sections_data)
        
        # Log the generated newsletter for debugging
        log_newsletter(prompt_logger, newsletter)
        
    except Exception as e:
        logging.exception("Error generating newsletter HTML")
        # Fallback to a simple HTML message
        newsletter = "<html><body><h1>Daily Briefing</h1><p>There was an error generating the newsletter content.</p></body></html>"

    # Create financial charts and send the email newsletter
    create_charts()
    send_email(newsletter, send_to_everyone)
    logging.info("Daily briefing process completed successfully.")

if __name__ == "__main__":
    main() 