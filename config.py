#!/usr/bin/env python3
"""
Configuration module for the Daily Briefing application.

This module loads environment variables and defines configuration constants
used throughout the application.
"""

import os
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
import sys
from typing import List

# Load environment variables from .env file
load_dotenv()

# API Keys and credentials
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_USERNAME = os.getenv("GOOGLE_USERNAME")
GOOGLE_PASSWORD = os.getenv("GOOGLE_PASSWORD")

# Parse recipient emails into a list (split by commas)
recipient_emails_str = os.getenv("RECIPIENT_EMAILS", "")
RECIPIENT_EMAILS = [email.strip() for email in recipient_emails_str.split(",")] if recipient_emails_str else []

# Define AI model to use
AI_MODEL = "gpt-4o"

# Get the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# Log file paths
LOG_FILE = os.path.join(SCRIPT_DIR, "daily_briefing.log")
PROMPT_LOG_FILE = os.path.join(SCRIPT_DIR, "prompt_response.log")

# Define global headers for HTTP requests
HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36')
}

# OpenAI API rate limiting parameters
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 60  # seconds
MAX_TOKENS_PER_REQUEST = 25000  # Keeping well below the 30000 TPM limit
TOKEN_BUFFER = 1000  # Buffer to account for response tokens

# Email template path
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "template.html")

# USDA Egg Price Chart URL and path
USDA_PDF_URL = "https://www.ams.usda.gov/mnreports/ams_3725.pdf"
EGG_PRICE_CHART_PATH = os.path.join(SCRIPT_DIR, 'egg-price-chart.png')

# Beyond Meat Bond Chart URL
BEYOND_MEAT_BOND_URL = "https://markets.businessinsider.com/bonds/beyond_meat_incdl-zero_convnts_202227-bond-2027-us08862eab56"
BEYOND_MEAT_BOND_CHART_PATH = os.path.join(SCRIPT_DIR, 'beyond-meat-bond-chart.png')

# Update the chart paths dictionary
CHART_PATHS = {
    'bynd-chart.png': os.path.join(SCRIPT_DIR, 'bynd-chart.png'),
    'beyond-meat-bond-chart.png': BEYOND_MEAT_BOND_CHART_PATH,
    'otly-chart.png': os.path.join(SCRIPT_DIR, 'otly-chart.png'),
    'sp500-chart.png': os.path.join(SCRIPT_DIR, 'sp500-chart.png'),
    'egg-price-chart.png': EGG_PRICE_CHART_PATH,
}

# Update chart content IDs for email embedding
CHART_CONTENT_IDS = {
    'bynd-chart.png': '<bynd-chart>',
    'beyond-meat-bond-chart.png': '<beyond-meat-bond-chart>',
    'otly-chart.png': '<otly-chart>',
    'sp500-chart.png': '<sp500-chart>',
    'egg-price-chart.png': '<egg-price-chart>',
}

# Financial tickers configuration
TICKERS = {
    'BYND': {'filename': CHART_PATHS['bynd-chart.png'], 'display_name': 'Beyond Meat'},
    'OTLY': {'filename': CHART_PATHS['otly-chart.png'], 'display_name': 'Oatly'},
    '^GSPC': {'filename': CHART_PATHS['sp500-chart.png'], 'display_name': 'S&P 500'},
}

# User personality and preferences for personalized content
USER_PERSONALITY = "a philanthropist who donates to nonprofits working to create a vegan world and an investor in alternative protein startups. They're deeply committed to animal welfare causes and interested in the business side of plant-based foods and cultivated meat. They want comprehensive updates on the alternative protein industry for investment decisions, meaningful developments in the vegan movement to inform donation strategies, and insights from effective altruism to maximize their impact."

# Newsletter tone settings
NEWSLETTER_TONE = "conversational and engaging - like a well-informed colleague giving you updates. Include occasional light humor when appropriate, but maintain a professional tone. Use clear language that feels natural, with just a touch of lightheartedness to avoid being too serious - but avoid being silly or over-the-top with humor."

# Common prompt elements that apply to all sections
COMMON_PROMPT_ELEMENTS = (
    "Your task is to identify the most important news items "
    "from the content provided and output them in a structured format. Each news item should include a title, a detailed description, "
    "source information, and a link to the original source when available. "
    "Ensure all claims are substantiated by the sources provided."
)

# Section definitions for the daily briefing
SECTIONS = [
    {
        "title": "Alternative Protein",
        "prompt": (
            f"You are an analyst specializing in the alternative protein industry. {COMMON_PROMPT_ELEMENTS} "
            "Focus on recent developments, especially funding rounds and new product launches."
        ),
        "content_type": "articles"
    },
    {
        "title": "Vegan Movement",
        "prompt": (
            f"You are an analyst specializing in the vegan movement and animal welfare. {COMMON_PROMPT_ELEMENTS} "
            "Focus on recent accomplishments, new research, and lessons learned that would be relevant to philanthropists. "
            "Note that Farmed Animal Strategic Team (FAST) is not the name of an organization, but simply the name of an email list where people in the vegan movement share updates."
        ),
        "content_type": "emails"
    },
    {
        "title": "Effective Altruism",
        "prompt": (
            f"You are an analyst specializing in effective altruism. {COMMON_PROMPT_ELEMENTS} "
            "Focus on the latest discussions that would be relevant to philanthropists seeking to maximize their impact."
        ),
        "content_type": "articles"
    },
    {
        "title": "AI",
        "prompt": (
            f"You are an analyst specializing in artificial intelligence. {COMMON_PROMPT_ELEMENTS} "
            "Focus on new AI developments that could increase personal productivity and cutting-edge advancements from "
            "major AI companies."
        ),
        "content_type": "articles"
    }
]

# Timezone settings
TIMEZONE = ZoneInfo("America/New_York")

# Chart styling
CHART_STYLE = 'seaborn-v0_8-darkgrid'
CHART_COLOR = '#1e3d59'
GRID_COLOR = '#e0e0e0'
BACKGROUND_COLOR = '#ffffff'
CHART_DPI = 300

# Email SMTP and IMAP settings
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Source URLs
GREEN_QUEEN_SITEMAP_URL = "https://www.greenqueen.com.hk/sitemap_index.xml"
VEGCONOMIST_RSS_URL = "https://vegconomist.com/feed/"
EA_FORUM_RSS_URL = "https://forum.effectivealtruism.org/feed.xml?view=frontpage-rss&karmaThreshold=2"
RUNDOWN_RSS_URL = "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml"
FAST_EMAIL = "fast-farm-animal-strategic-team@googlegroups.com"

# Add Stability AI API key to the environment variables section
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# Add Stability AI configuration
STABILITY_API_URL = "https://api.stability.ai/v2beta/stable-image/generate/ultra"
STABILITY_IMAGE_ASPECT_RATIO = "16:9"
STABILITY_IMAGE_OUTPUT_FORMAT = "png"