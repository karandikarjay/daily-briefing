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

- **AI-Powered Content Processing**: Uses Claude Opus 5 (Anthropic) to:
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
  - Up to 3 verified stories with photorealistic AI-generated images
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
- Anthropic API key (for Claude Opus 5 text generation)
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

2. **Content Processing**: For each section, the collected content is processed using Claude Opus 5 to extract the most important news items.

3. **Newsletter Generation**: Claude selects up to 3 verified stories and generates an Axios-style newsletter with Smart Brevity principles.

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

- Anthropic for providing Claude Opus 5
- OpenAI for providing gpt-image-1.5 image generation
- yfinance for financial data
- All the content sources that make this briefing possible

## Verified news pipeline

Text defaults to `claude-opus-5`, adaptive thinking with medium effort. The existing
`gpt-5.6-sol` fallback is retained. Model usage is logged for cost measurement.

All collectors share one frozen, half-open Eastern-time window: 06:00 yesterday
to 06:00 today, with Monday covering Friday onward. Early/manual runs use the
most recent completed scheduled window. Search recency and sitemap modification
dates are discovery hints, never publication proof. Article metadata/RSS publication
dates must agree and fall inside the window. Ambiguous dates are excluded.

Up to three candidates per topic are considered in order. An unrestricted search
looks for the original announcement and prior coverage. A grounded novelty review
must confirm the central announcement is new; a date, source ID and exact supporting
quote are retained. Unknown dates, recycled events, failed verification and repeated
events are excluded. An independent final review checks the newsletter against its
evidence. Empty topics get an explicit quiet-news notice. API/writer failures abort
instead of sending an error disguised as a successful briefing.

`python main.py --dry-run` saves a full HTML/image preview without sending.
`python main.py --send-preview /absolute/path/to/previews/RUN` sends that validated
preview only to the configured sender's +list address. `python main.py` also sends
only to that address. Only production cron uses `--send-to-everyone`.

Private audit evidence and previews live in ignored `previews/`; delivered-event
history lives in ignored `state/history.json`. Personal previews do not change group
history. Each preview has an exclusive send-attempt marker. If delivery is uncertain,
inspect Sent before taking any further action; do not remove the marker and retry
blindly. Tests: `python -m unittest discover -s tests -v`.

Publication metadata can be wrong, and semantic verification is probabilistic.
The deliberate tradeoff is to omit uncertain stories, sometimes producing a shorter
edition, rather than treat discovery dates or a model's unsupported assertion as proof.
