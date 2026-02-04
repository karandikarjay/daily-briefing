# Future Appetite

A Python application that automatically generates and delivers a personalized daily briefing email newsletter with curated content from various sources including news sites, RSS feeds, emails, and financial data.

## Overview

Future Appetite collects content from multiple sources, processes it using AI to extract the most relevant information, generates photorealistic images and financial charts, and sends a formatted Axios-style email newsletter. The application is designed to provide a comprehensive overview of various topics including:

- Alternative Protein
- Vegan Movement
- AI

## Features

- **Content Aggregation**: Collects content from multiple sources including:
  - RSS feeds (Vegconomist, The Rundown AI)
  - Website sitemaps (Green Queen)
  - Email lists (FAST)

- **AI-Powered Content Processing**: Uses Claude Opus 4.5 (Anthropic) to:
  - Extract the most important news items from each source
  - Select the top 3 stories across all topics
  - Generate an Axios-style newsletter with Smart Brevity principles
  - Create scannable content with "What", "Why it matters", and "Go deeper" sections

- **AI Image Generation**: Uses OpenAI's gpt-image-1.5 to generate photorealistic images for each story

- **Financial Charts**: Generates visual charts for financial data including:
  - Beyond Meat (BYND) stock price
  - Beyond Meat bond price
  - Oatly (OTLY) stock price
  - S&P 500
  - USDA egg prices

- **Email Delivery**: Sends a formatted HTML email with:
  - Clean, minimal Axios-style design
  - Top 3 stories with photorealistic AI-generated images
  - Embedded financial charts
  - Links to original sources
  - Option to send to a single recipient or a distribution list

## Project Structure

```
daily-briefing/
├── charts/                  # Financial chart generation
│   ├── __init__.py
│   └── financial_charts.py
├── content/                 # Content retrieval from various sources
│   ├── __init__.py
│   ├── content_manager.py
│   ├── email_content.py
│   ├── rss_content.py
│   ├── sitemap_content.py
│   └── web_content.py
├── models/                  # Data models for structured content
│   ├── __init__.py
│   └── data_models.py
├── utils/                   # Utility functions
│   ├── __init__.py
│   ├── api_utils.py
│   ├── html_utils.py
│   ├── email_utils.py
│   └── logging_setup.py
├── config.py                # Configuration settings
├── main.py                  # Main application entry point
├── template.html            # Email template
└── README.md                # This file
```

## Requirements

- Python 3.9+
- Anthropic API key (for Claude Opus 4.5 text generation)
- OpenAI API key (for gpt-image-1.5 image generation)
- Gmail account (for sending emails)
- Required Python packages (see requirements.txt)

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/daily-briefing.git
   cd daily-briefing
   ```

2. Install required packages:
   ```
   pip install -r requirements.txt
   ```

3. Create a `.env` file with the following variables:
   ```
   ANTHROPIC_API_KEY=your_anthropic_api_key
   OPENAI_API_KEY=your_openai_api_key
   GOOGLE_USERNAME=your_gmail_address
   GOOGLE_PASSWORD=your_gmail_app_password
   RECIPIENT_EMAILS=email1@example.com,email2@example.com
   ```

   Note: For Gmail, you'll need to use an App Password rather than your regular password. See [Google's documentation](https://support.google.com/accounts/answer/185833) for details.

## Usage

### Basic Usage

Run the script to generate and send the daily briefing to yourself:

```
python main.py
```

### Send to All Recipients

To send the briefing to all email addresses in your RECIPIENT_EMAILS list:

```
python main.py --send-to-everyone
```

## Configuration

The application is configured through the `config.py` file, which includes:

- API keys and credentials
- Email settings
- Content source URLs
- Section definitions
- Chart styling options
- Rate limiting parameters

## How It Works

1. **Content Collection**: The application retrieves content from various sources defined in the configuration.

2. **Content Processing**: For each section, the collected content is processed using Claude Opus 4.5 to extract the most important news items.

3. **Newsletter Generation**: Claude selects the top 3 stories and generates an Axios-style newsletter with Smart Brevity principles.

4. **Image Generation**: OpenAI's gpt-image-1.5 generates photorealistic images for each story.

5. **Chart Generation**: Financial charts are created using matplotlib and yfinance data.

6. **Email Generation**: An HTML email is generated using the template with the Axios-style content, images, and charts.

7. **Email Delivery**: The email is sent to the specified recipients.

## Content Collection Logic

The application collects content based on the following time windows:

- If today is Saturday, Sunday, or Monday: Content from 6am ET Friday to 6am ET today
- For all other days: Content from 6am ET yesterday to 6am ET today

This ensures that you get a comprehensive update after weekends while maintaining daily relevance during the work week.

## Logging

The application generates two log files:

- `daily_briefing.log`: General application logs
- `prompt_response.log`: Detailed logs of prompts sent to the AI and responses received

## Extending the Application

### Adding New Content Sources

To add a new content source:

1. Create a new function in the appropriate content module (e.g., `rss_content.py` for RSS feeds)
2. Update the `content_manager.py` file to include your new source
3. Add any necessary configuration to `config.py`

### Adding New Sections

To add a new section to the briefing:

1. Add a new section definition to the `SECTIONS` list in `config.py`
2. Update the email template (`template.html`) to include the new section
3. Update the content manager to retrieve content for the new section

## Acknowledgements

- Anthropic for providing Claude Opus 4.5
- OpenAI for providing gpt-image-1.5 image generation
- yfinance for financial data
- All the content sources that make this briefing possible