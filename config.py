#!/usr/bin/env python3
"""
Configuration module for the Daily Briefing application.

This module loads environment variables and defines configuration constants
used throughout the application.
"""

import os
import pytz
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

# Chart file paths
CHART_PATHS = {
    'bynd-chart.png': os.path.join(SCRIPT_DIR, 'bynd-chart.png'),
    'otly-chart.png': os.path.join(SCRIPT_DIR, 'otly-chart.png'),
    'sp500-chart.png': os.path.join(SCRIPT_DIR, 'sp500-chart.png'),
    '10y-yield-chart.png': os.path.join(SCRIPT_DIR, '10y-yield-chart.png'),
    'vix-chart.png': os.path.join(SCRIPT_DIR, 'vix-chart.png')
}

# Chart content IDs for email embedding
CHART_CONTENT_IDS = {
    'bynd-chart.png': '<bynd-chart>',
    'otly-chart.png': '<otly-chart>',
    'sp500-chart.png': '<sp500-chart>',
    '10y-yield-chart.png': '<10y-yield-chart>',
    'vix-chart.png': '<vix-chart>'
}

# Financial tickers configuration
TICKERS = {
    'BYND': {'filename': CHART_PATHS['bynd-chart.png'], 'display_name': 'Beyond Meat'},
    'OTLY': {'filename': CHART_PATHS['otly-chart.png'], 'display_name': 'Oatly'},
    '^GSPC': {'filename': CHART_PATHS['sp500-chart.png'], 'display_name': 'S&P 500'},
    '^TNX': {'filename': CHART_PATHS['10y-yield-chart.png'], 'display_name': '10-Year Treasury'},
    '^VIX': {'filename': CHART_PATHS['vix-chart.png'], 'display_name': 'VIX'}
}

# Section definitions for the daily briefing
SECTIONS = [
    {
        "title": "Alternative Protein",
        "prompt": (
            "I am an investor in alternative protein startups. I want to be aware of recent developments in the alternative protein industry "
            "(especially recent funding rounds and new product launches) so that I can invest wisely. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "Vegan Movement",
        "prompt": (
            "I am a philanthropist who donates to the vegan movement. I want to stay up to date on what's going on in the vegan movement "
            "(particularly recent accomplishments, new research, and lessons learned) so that I can make better philanthropic decisions when we're pitched by vegan nonprofits. "
            "Note that Farmed Animal Strategic Team (FAST) is not the name of an organization, but simply the name of an email list where people in the vegan movement share updates. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "emails"
    },
    {
        "title": "Effective Altruism",
        "prompt": (
            "I am a philanthropist. I want to be aware of the latest discussions in the effective altruism community so that I can make donations effectively. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "Venture Capital",
        "prompt": (
            "I am a venture capitalist. I want to know what's going on in the venture capital ecosystem, such as any major deals and broader market trends. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "Financial Markets",
        "prompt": (
            "I am an investor at a hedge fund. I want to know what's going on in the financial markets, particularly the performance of the markets as a whole, any significant economic news releases, and any major deals. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "AI",
        "prompt": (
            "I want to know what new developments are going on in the world of AI tools so that I can increase my personal productivity and I also want to know what the cutting-edge AI companies are doing since they are likely to have a significant impact on the world. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "Politics",
        "prompt": (
            "I want to know what's going on in the world of politics so that I can be well-informed in case any recent developments come up in conversation. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    },
    {
        "title": "Climate",
        "prompt": (
            "I want to know what's going on with regard to climate change, including how startups and venture capitalists are addressing the issue, "
            "how policymakers are responding, what climate philanthropists are doing, what strategies the environmental movement is pursuing, and any updates to climate science. "
            "Give me the 3 most important bullet points to be aware of from the content I have provided below. "
            "Give me the bullet points only without anything before or after. "
            "Make sure that there are exactly 3 bullet points (no more, no fewer). "
            "Make sure that any claims you make are substantiated by the text of the sources you reference. "
        ),
        "content_type": "articles"
    }
]

# Timezone settings
EASTERN_ZONE = ZoneInfo("America/New_York")

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
SHORT_SQUEEZ_RSS_URL = "https://rss.beehiiv.com/feeds/uuk5kg8PFC.xml"
TERM_SHEET_URL = "https://content.fortune.com/newsletter/termsheet/"
FAST_EMAIL = "fast-farm-animal-strategic-team@googlegroups.com"

# APIs and sources configuration
AXIOS_NEWSLETTERS = {
    "Pro Rata": "https://www.axios.com/newsletters/axios-pro-rata",
    "Markets": "https://www.axios.com/newsletters/axios-markets",
    "Macro": "https://www.axios.com/newsletters/axios-macro",
    "Closer": "https://www.axios.com/newsletters/axios-closer",
    "AM": "https://www.axios.com/newsletters/axios-am",
    "PM": "https://www.axios.com/newsletters/axios-pm",
    "Generate": "https://www.axios.com/newsletters/axios-generate",
    "AI+": "https://www.axios.com/newsletters/axios-ai-plus"
}

SEMAFOR_NEWSLETTERS = {
    "Business": "https://www.semafor.com/newsletters/business/latest",
    "Flagship": "https://www.semafor.com/newsletters/flagship/latest",
    "Principals": "https://www.semafor.com/newsletters/principals/latest",
    "Americana": "https://www.semafor.com/newsletters/americana/latest",
    "Net Zero": "https://www.semafor.com/newsletters/netzero/latest"
}