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

# Load environment variables from .env file (override=True ensures .env takes precedence)
load_dotenv(override=True)

# API Keys and credentials
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GOOGLE_USERNAME = os.getenv("GOOGLE_USERNAME")
GOOGLE_PASSWORD = os.getenv("GOOGLE_PASSWORD")

# Parse recipient emails into a list (split by commas)
recipient_emails_str = os.getenv("RECIPIENT_EMAILS", "")
RECIPIENT_EMAILS = [email.strip() for email in recipient_emails_str.split(",")] if recipient_emails_str else []

# Define AI model to use (Claude Opus 4.5)
AI_MODEL = "claude-opus-4-5"

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

# API rate limiting parameters
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 60  # seconds
MAX_TOKENS_PER_REQUEST = 100000  # Claude supports much larger context
TOKEN_BUFFER = 1000  # Buffer to account for response tokens
MAX_OUTPUT_TOKENS = 8192  # Maximum output tokens for Claude

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
USER_PERSONALITY = "a philanthropist who donates to nonprofits working to create a vegan world and an investor in alternative protein startups. They are excited about the potential of AI to supercharge their efforts"

# Newsletter tone settings
NEWSLETTER_TONE = "conversational and engaging - like a well-informed colleague, who has experienced the ups and downs of market cycles and overhyped startups and doesn't easily get excited, giving you updates. Avoid the the gratuitous use of similes and metaphors."

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

# Tavily web search configuration
TAVILY_QUERIES = {
    "Alternative Protein": [
        "alternative protein industry news",
        "cultivated meat cellular agriculture",
        "plant-based meat dairy funding startup",
    ],
    "Vegan Movement": [
        "vegan movement animal welfare policy",
        "animal rights legislation advocacy",
    ],
    "AI": [
        "artificial intelligence breakthrough news",
        "AI tools productivity enterprise",
        "OpenAI Anthropic Google AI launch",
    ],
}
TAVILY_MAX_RAW_CONTENT_CHARS = 8000

FAST_EMAILS = [
    "fast-farm-animal-strategic-team@googlegroups.com",
    "list@fastcommunity.org"
]

# OpenAI Image Generation configuration (using gpt-image-1.5)
IMAGE_MODEL = "gpt-image-1.5"
IMAGE_SIZE = "1536x1024"  # Landscape format for newsletter
IMAGE_QUALITY = "medium"  # Balance between quality and cost
IMAGE_OUTPUT_FORMAT = "png"