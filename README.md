# Daily Briefing

A Python application that automatically generates and delivers a personalized daily briefing email with curated content from various sources including news sites, RSS feeds, emails, and financial data.

## Overview

The Daily Briefing application collects content from multiple sources, processes it using AI to extract the most relevant information, generates financial charts, and sends a formatted email newsletter. The application is designed to provide a comprehensive overview of various topics including:

- Alternative Protein
- Vegan Movement
- AI

## Features

- **Content Aggregation**: Collects content from multiple sources including:
  - RSS feeds (Vegconomist, The Rundown AI)
  - Website sitemaps (Green Queen)
  - Email lists (FAST)

- **AI-Powered Content Processing**: Uses OpenAI's GPT models to:
  - Extract the most important information from each source
  - Generate concise bullet points for each section
  - Create summaries that highlight key developments

- **AI Image Generation**: Uses Stability AI to generate relevant images for newsletter content

- **Financial Charts**: Generates visual charts for financial data including:
  - Beyond Meat (BYND) stock price
  - Beyond Meat bond price
  - Oatly (OTLY) stock price
  - S&P 500
  - USDA egg prices

- **Email Delivery**: Sends a formatted HTML email with:
  - Organized sections for different topics
  - AI-generated images
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
- OpenAI API key
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

2. **Content Processing**: For each section, the collected content is processed using OpenAI's API to extract the most important information and generate bullet points.

3. **Chart Generation**: Financial charts are created using matplotlib and yfinance data.

4. **Email Generation**: An HTML email is generated using the template and populated with the processed content and charts.

5. **Email Delivery**: The email is sent to the specified recipients.

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

- OpenAI for providing the GPT models
- yfinance for financial data
- All the content sources that make this briefing possible