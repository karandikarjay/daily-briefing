#!/usr/bin/env python3
"""
Daily Briefing Script

This script gathers insights from various sources (RSS feeds, sitemaps, emails, etc.),
processes the content, creates visualizations from financial data, and delivers a
personalized email newsletter containing your daily briefing.
"""

import sys
import json
import logging
import os
from openai import OpenAI
from typing import Dict, List, Optional
import requests

# Import configuration
from config import (
    OPENAI_API_KEY, AI_MODEL, SECTIONS, TEMPLATE_PATH,
    USER_PERSONALITY, NEWSLETTER_TONE,
    STABILITY_API_KEY, STABILITY_API_URL, STABILITY_IMAGE_ASPECT_RATIO, STABILITY_IMAGE_OUTPUT_FORMAT
)

# Import utilities
from utils.logging_setup import setup_logging, log_section_prompt, log_section_response, log_newsletter
from utils.api_utils import num_tokens_from_string, call_openai_parse_with_backoff, call_openai_api_with_backoff, call_stability_api_with_backoff
from utils.html_utils import generate_email_html
from utils.email_utils import send_email

# Import content retrieval
from content import get_content

# Import chart generation
from charts import create_charts, extract_egg_price_chart, get_beyond_meat_bond_chart

# Import models
from models.data_models import (
    TopicNewsResponse,
    CohesiveNewsletterResponse,
    NewsItem,
    ContentElement
)

def main():
    """Main function to run the daily briefing process."""
    # Check for the --send-to-everyone flag
    send_to_everyone = "--send-to-everyone" in sys.argv

    # Set up logging
    logger, prompt_logger = setup_logging()
    
    # Initialize OpenAI client
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Dictionary to store news items for each section
    all_news_items = []

    # Process each section and gather its news items
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
            
            # Make API call with structured output
            response = call_openai_parse_with_backoff(
                client,
                messages,
                TopicNewsResponse,
                model=AI_MODEL
            )
            
            # Add news items from this section to the overall list
            section_news_items = response.choices[0].message.parsed.news_items
            for item in section_news_items:
                # Add the section title to each news item for reference
                item_dict = item.model_dump()
                item_dict["topic"] = section["title"]
                all_news_items.append(item_dict)
            
            # Log the response for debugging
            news_items_json = json.dumps([item.model_dump() for item in section_news_items])
            log_section_response(prompt_logger, section["title"], news_items_json)
            
        except Exception as e:
            logging.exception(f"Error obtaining response for section: {section['title']}")
    
    try:
        # Generate cohesive newsletter text with a final API call
        if all_news_items:
            newsletter_elements, email_subject = generate_cohesive_newsletter(client, all_news_items, prompt_logger)
            
            # Generate images for any image descriptions using Stability AI
            image_paths = generate_stability_images(newsletter_elements)
            
            # Read the HTML newsletter template
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as file:
                template = file.read()
                
            # Generate the HTML for the newsletter using the template and cohesive text
            newsletter = generate_email_html(template, newsletter_elements, image_paths)
            
            # Log the generated newsletter for debugging
            log_newsletter(prompt_logger, newsletter)
        else:
            logging.error("No news items collected. Cannot generate newsletter.")
            newsletter = "<html><body><h1>Daily Briefing</h1><p>There was an error generating the newsletter content.</p></body></html>"
            email_subject = None
            image_paths = {}
            
    except Exception as e:
        logging.exception("Error generating newsletter HTML")
        # Fallback to a simple HTML message
        newsletter = "<html><body><h1>Daily Briefing</h1><p>There was an error generating the newsletter content.</p></body></html>"
        email_subject = None
        image_paths = {}

    # Create financial charts, beyond meat bond chart, egg price chart, then send the email newsletter
    create_charts()
    get_beyond_meat_bond_chart()
    extract_egg_price_chart()
    send_email(newsletter, email_subject, send_to_everyone, image_paths)
    logging.info("Daily briefing process completed successfully.")

def generate_stability_images(newsletter_elements: List[ContentElement]) -> Dict[str, str]:
    """
    Generates images using Stability AI for any image_description elements.
    
    Args:
        newsletter_elements: List of newsletter content elements
        
    Returns:
        Dict[str, str]: Dictionary mapping image_id to file path
    """
    image_paths = {}
    image_counter = 1
    
    for i, element in enumerate(newsletter_elements):
        if element.type == "image_description":
            image_id = f"generated_image_{image_counter}"
            image_counter += 1
            
            try:
                logging.info(f"Generating Stability AI image for: {element.content[:50]}...")
                
                # Get the prompt (content) and save the caption
                prompt = element.content
                
                # Log the Stability AI prompt to the prompt logger
                logging.getLogger('prompts').info(
                    f"\n{'='*80}\nSTABILITY AI PROMPT {image_id}\n{'='*80}\n"
                    f"{prompt}\n"
                    f"{'='*80}\n"
                )
                
                # Create a temporary directory if it doesn't exist
                temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_images")
                os.makedirs(temp_dir, exist_ok=True)
                
                # Define the output image path
                image_path = os.path.join(temp_dir, f"{image_id}.png")
                
                # Prepare the API call function for Stability AI
                def make_stability_api_call():
                    return requests.post(
                        STABILITY_API_URL,
                        headers={
                            "authorization": f"Bearer {STABILITY_API_KEY}",
                            "accept": "image/*"
                        },
                        files={"none": ''},
                        data={
                            "prompt": prompt,
                            "output_format": STABILITY_IMAGE_OUTPUT_FORMAT,
                            "aspect_ratio": STABILITY_IMAGE_ASPECT_RATIO,
                        },
                    )
                
                # Make the API request with backoff
                response = call_stability_api_with_backoff(
                    api_call=make_stability_api_call,
                    resource_type="stability_image"
                )
                
                # Save the image
                with open(image_path, 'wb') as file:
                    file.write(response.content)
                    
                # Add the image path to the dictionary
                image_paths[image_id] = image_path
                
                logging.info(f"Stability AI image saved to {image_path}")
                
                # Update the element content to include the image ID for reference
                element.content = image_id
                    
            except Exception as e:
                logging.exception(f"Error generating Stability AI image: {e}")
    
    return image_paths

def generate_cohesive_newsletter(client: OpenAI, news_items: List[Dict], prompt_logger) -> tuple:
    """
    Generates a cohesive newsletter from the collected news items.
    
    Args:
        client: The OpenAI client
        news_items: List of news items from all sections
        prompt_logger: Logger for prompts and responses
        
    Returns:
        tuple: (newsletter_elements, email_subject)
    """
    # Create the prompt for generating cohesive text
    system_prompt = (
        f"You are writing a personalized daily briefing for {USER_PERSONALITY}. "
        f"Create a cohesive daily briefing with a custom subject line and content elements from the news items provided. "
        f"The tone should be {NEWSLETTER_TONE}. "
        "\n\nThe primary goal of this briefing is to keep the reader informed about:"
        "\n1. Developments in the alternative protein industry that might affect investment decisions"
        "\n2. Updates in the vegan movement that could influence donation strategies"
        "\n3. Current discussions in the effective altruism community"
        "\n4. Recent AI developments, especially new tools that could be useful for work"
        "\n\nThe text should flow naturally between topics, with smooth transitions. "
        "Include all important information from each news item. "
        "Ensure you include citations to sources for each piece of information. "
        "IMPORTANT: Create hyperlinks to original sources using HTML anchor tags. For each news item, include at least one link to the source_link when available. "
        "IMPORTANT: Seamlessly integrate citations within the text flow. Instead of using parentheses, use phrases like 'according to <a href=\"source_link\">source_name</a>', 'as reported by <a href=\"source_link\">source_name</a>', 'in a recent article from <a href=\"source_link\">source_name</a>', etc."
        "For emails, mention the sender name and subject line naturally in the text."
        
        # Add specific guidance about tempering enthusiastic claims
        "\n\nIMPORTANT: Maintain a measured, thoughtful tone even when reporting on enthusiastic or bold claims from the sources. "
        "When sources make ambitious projections or strong claims:"
        "\n- Present these with appropriate context and qualification"
        "\n- Use phrases like 'aims to,' 'is working toward,' or 'the company suggests that' rather than stating projections as certainties"
        "\n- If a source uses particularly hyperbolic language, tone it down while preserving the core information"
        "\n- Distinguish between factual developments (funding secured, products launched) and speculative claims or forecasts"
        "\n- Where appropriate, note that certain statements reflect the source's perspective rather than established facts"
        "\n- Use language like 'according to the announcement' or 'in their report' to attribute claims to their sources"
        "\nThe goal is to present information faithfully but with appropriate nuance and critical distance."
        
        "\n\nIMPORTANT: Your output will be formatted as follows:"
        "\n1. A custom email subject line that captures the essence of today's briefing"
        "\n2. A list of content elements, each marked as either 'paragraph', 'heading', or 'image_description'"
        "\n\nFor content that would be enclosed in <p> tags, mark it as 'paragraph'."
        "\nFor content that would be enclosed in <h2> tags, mark it as 'heading'."
        "\nFor visual prompts that would be used to generate images with Stability AI, mark as 'image_description'. "
        
        "\n\nFor image descriptions:"
        "\n- Include 3-4 image descriptions throughout the newsletter at appropriate points"
        "\n- Make each image description HIGHLY SPECIFIC to the actual news items you just mentioned in the preceding paragraphs"
        "\n- Base each image directly on the most visually interesting or important news item from that section"
        "\n- Create detailed, vivid descriptions (1-3 sentences) focusing on visual elements that would enhance understanding of the news item"
        "\n- Position image descriptions after discussing the relevant news item, not before"
        "\n- IMPORTANT: Avoid requesting infographics, charts, diagrams, or any form of text in the images"
        "\n- IMPORTANT: Focus on photorealistic scenes, objects, or environments rather than data visualizations"
        "\n- IMPORTANT: Describe imagery that can be purely visual without relying on text to convey meaning"
        "\n- Use a photorealistic style unless specifically noting otherwise"
        "\n- For each image description, also create a brief caption (1-2 sentences) that will appear below the image"
        "\n- The caption should explain what the image represents"
        "\n- Do NOT make the caption sound like it's describing a real photograph or actual event"
        
        "\n\nDO include HTML formatting in the content text itself as needed (e.g., <a> tags for links, <strong>, <em>, etc.)."
        "\nDO NOT include the structural <p> and <h2> tags - we will add those programmatically based on your type markers."
        "\n\nEnsure all citations are woven naturally into the flow of the appropriate paragraph."
    )
    
    # Convert news items to a string for the API call
    news_items_str = json.dumps(news_items)
    user_content = f"<news_items>{news_items_str}</news_items>"
    
    # Log the final prompt
    log_section_prompt(prompt_logger, "COHESIVE NEWSLETTER", system_prompt, user_content)
    
    # Prepare messages for the API call
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
    
    try:
        # Make API call
        response = call_openai_parse_with_backoff(
            client,
            messages,
            CohesiveNewsletterResponse,
            model=AI_MODEL
        )
        
        # Extract the subject and content elements
        email_subject = response.choices[0].message.parsed.subject
        content_elements = response.choices[0].message.parsed.content_elements
        
        # Log the response
        log_section_response(prompt_logger, "COHESIVE NEWSLETTER", 
                            f"Subject: {email_subject}\n\nContent:\n{json.dumps([elem.model_dump() for elem in content_elements])}")
        
        return content_elements, email_subject
    except Exception as e:
        logging.exception("Error generating cohesive newsletter text")
        return [ContentElement(type="paragraph", content="Error generating newsletter content.")], None

if __name__ == "__main__":
    main() 