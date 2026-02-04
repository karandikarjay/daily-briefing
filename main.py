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
from datetime import datetime
from openai import OpenAI
from anthropic import Anthropic
from typing import Dict, List

# Import configuration
from config import (
    OPENAI_API_KEY, ANTHROPIC_API_KEY, AI_MODEL, SECTIONS, TEMPLATE_PATH,
    USER_PERSONALITY, NEWSLETTER_TONE
)

# Import utilities
from utils.logging_setup import setup_logging, log_section_prompt, log_section_response, log_newsletter
from utils.api_utils import num_tokens_from_string, call_openai_parse_with_backoff, call_openai_api_with_backoff, call_openai_image_generation
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
    AxiosNewsletterResponse,
    NewsItem,
    ContentElement,
    NewsStory
)

def main():
    """Main function to run the daily briefing process."""
    # Check for the --send-to-everyone flag
    send_to_everyone = "--send-to-everyone" in sys.argv

    # Set up logging
    logger, prompt_logger = setup_logging()

    # Initialize Anthropic client for text generation (Claude)
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    # Initialize OpenAI client for image generation
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
        # Generate Axios-style newsletter with a final API call
        if all_news_items:
            axios_response, email_subject = generate_cohesive_newsletter(client, all_news_items, prompt_logger)

            # Generate images for each story using OpenAI's gpt-image-1.5
            image_paths = generate_images(openai_client, axios_response)

            # Read the HTML newsletter template
            with open(TEMPLATE_PATH, "r", encoding="utf-8") as file:
                template = file.read()

            # Generate the HTML for the newsletter using the template and Axios response
            newsletter = generate_email_html(template, axios_response, image_paths)

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

def generate_images(client: OpenAI, axios_response: AxiosNewsletterResponse) -> Dict[str, str]:
    """
    Generates images using OpenAI's gpt-image-1.5 for each story's image_description.

    Args:
        client: The OpenAI client instance
        axios_response: The Axios-style newsletter response with stories

    Returns:
        Dict[str, str]: Dictionary mapping image_id to file path
    """
    image_paths = {}

    for i, story in enumerate(axios_response.stories):
        if story.image_description:
            image_id = f"story_image_{i + 1}"

            try:
                logging.info(f"Generating image for story {i + 1}: {story.headline[:50]}...")

                # Get the prompt (image_description)
                prompt = story.image_description

                # Log the image prompt to the prompt logger
                logging.getLogger('prompts').info(
                    f"\n{'='*80}\nIMAGE GENERATION PROMPT {image_id}\n{'='*80}\n"
                    f"Story: {story.headline}\n"
                    f"Prompt: {prompt}\n"
                    f"{'='*80}\n"
                )

                # Create a temporary directory if it doesn't exist
                temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_images")
                os.makedirs(temp_dir, exist_ok=True)

                # Define the output image path
                image_path = os.path.join(temp_dir, f"{image_id}.png")

                # Generate the image using OpenAI's gpt-image-1.5
                image_data = call_openai_image_generation(client, prompt)

                # Save the image
                with open(image_path, 'wb') as file:
                    file.write(image_data)

                # Add the image path to the dictionary
                image_paths[image_id] = image_path

                logging.info(f"Image saved to {image_path}")

            except Exception as e:
                logging.exception(f"Error generating image for story {i + 1}: {e}")

    return image_paths

def generate_cohesive_newsletter(client: Anthropic, news_items: List[Dict], prompt_logger) -> tuple:
    """
    Generates an Axios-style newsletter with top 3 stories from the collected news items.

    Args:
        client: The Anthropic client (Claude)
        news_items: List of news items from all sections
        prompt_logger: Logger for prompts and responses

    Returns:
        tuple: (AxiosNewsletterResponse, email_subject)
    """
    # Create the prompt for generating Axios-style newsletter
    system_prompt = (
        f"You are writing 'Future Appetite' - a daily newsletter for {USER_PERSONALITY}. "
        f"Create a sharp, scannable newsletter highlighting the TOP 3 stories using Smart Brevity principles. "

        "\n\n=== SMART BREVITY WRITING STYLE ==="
        "\nEvery word must earn its place. Write like a sharp, well-informed colleague."
        "\n"
        "\n• Lead with the news, not background"
        "\n• Short sentences (under 20 words)"
        "\n• Active voice: 'Company launched X' not 'X was launched'"
        "\n• Specific details: numbers, names, dates"
        "\n• Skip hype: if source says 'revolutionary,' you say 'new'"
        "\n• No throat-clearing phrases"
        "\n• Skeptical but fair"

        "\n\n=== STORY SELECTION (exactly 3) ==="
        "\nPick stories that are:"
        "\n• Actionable - affects investment, donation, or work decisions"
        "\n• Timely - happened in the last 24 hours"
        "\n• Surprising or significant"
        "\n"
        "\nAim for variety: alt-protein, vegan movement, AI tools."

        "\n\n=== FORMAT FOR EACH STORY ==="
        "\n"
        "\n1. HEADLINE: 5-8 words, convey the core news"
        "\n"
        "\n2. THREE BULLETS with these exact labels:"
        "\n   • 'What' - The news in 1-2 crisp sentences"
        "\n   • 'Why it matters' - The 'so what' for this reader"
        "\n   • 'Go deeper' - Source attribution with link (or email sender/subject)"
        "\n"
        "\n3. IMAGE DESCRIPTION: For AI image generation"
        "\n"
        "\n4. CAPTION: One line for the image"

        "\n\n=== INTRO ==="
        f"\nToday is {datetime.now().strftime('%A, %B %d, %Y')}."
        "\nStart with a bold greeting using the current day like '<strong>Happy Tuesday!</strong>' or similar."
        "\nThen one sentence teasing what's in this edition."
        "\nExample: '<strong>Happy Tuesday!</strong> Big retail moves in alt-protein today, plus an AI tool worth knowing.'"

        "\n\n=== SUBJECT LINE ==="
        "\nHighlight your top story. Under 50 characters."
        "\nGood: 'Oatly Stock Hits 52-Week Low'"
        "\nBad: 'Your Daily Update: News and More'"

        "\n\n=== LINK FORMATTING ==="
        "\nUse HTML: <a href=\"URL\">source name</a>"
        "\nFor emails: mention sender and subject (no link needed)"

        "\n\n=== IMAGE GUIDELINES ==="
        "\nCreate photorealistic image descriptions (2-3 sentences)."
        "\n• Write prompts that produce images looking like real photographs"
        "\n• Include specific details: lighting, angle, setting, subjects"
        "\n• Think: professional news photography, documentary style"
        "\n• Describe realistic scenes with natural compositions"
        "\n• AVOID: text, logos, charts, obvious AI artifacts"
        "\n• Caption: brief, written as if describing a real photo"
    )

    # Convert news items to a string for the API call
    news_items_str = json.dumps(news_items)
    user_content = f"<news_items>{news_items_str}</news_items>"

    # Log the final prompt
    log_section_prompt(prompt_logger, "AXIOS NEWSLETTER", system_prompt, user_content)

    # Prepare messages for the API call
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    try:
        # Make API call with Axios-style response model
        response = call_openai_parse_with_backoff(
            client,
            messages,
            AxiosNewsletterResponse,
            model=AI_MODEL
        )

        # Extract the parsed response
        axios_response = response.choices[0].message.parsed
        email_subject = axios_response.subject

        # Log the response
        log_section_response(prompt_logger, "AXIOS NEWSLETTER",
                            f"Subject: {email_subject}\n\nIntro: {axios_response.intro}\n\nStories:\n{json.dumps([story.model_dump() for story in axios_response.stories])}")

        return axios_response, email_subject
    except Exception as e:
        logging.exception("Error generating Axios-style newsletter")
        # Return a minimal fallback response
        from models.data_models import StoryBullet
        fallback_story = NewsStory(
            headline="Error generating newsletter",
            bullets=[StoryBullet(label="What:", text="There was an error generating the newsletter content.")],
            image_description=None,
            image_caption=None
        )
        fallback_response = AxiosNewsletterResponse(
            subject="Daily Briefing",
            intro="There was an error generating today's briefing.",
            stories=[fallback_story]
        )
        return fallback_response, None

if __name__ == "__main__":
    main() 