# Daily Briefing Project

A Python script that gathers content from various sources (RSS feeds, sitemaps, emails), processes it with OpenAI, generates images with Stability AI, and sends a personalized daily briefing email.

## Project Structure

- `main.py` - Main entry point
- `config.py` - Configuration settings
- `content/` - Content retrieval modules (RSS, email, sitemap)
- `charts/` - Financial chart generation
- `models/` - Pydantic data models
- `utils/` - Utilities for API calls, email, HTML, logging
- `template.html` - Email HTML template

## Running the Script

**Do NOT run the script with the `--send-to-everyone` flag.** This sends the briefing email to all recipients and should not be used during development or testing.

Running without the flag is safe - it sends the email only to the developer for testing:

```bash
python main.py
```

## Environment

Requires a `.env` file with API keys (see `.env.sample`).
