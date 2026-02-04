# Future Appetite - Daily Briefing Project

A Python script that gathers content from various sources (RSS feeds, sitemaps, emails), processes it with Claude Opus 4.5, generates photorealistic images with OpenAI's gpt-image-1.5, and sends a personalized Axios-style daily briefing email.

## Project Structure

- `main.py` - Main entry point
- `config.py` - Configuration settings (API keys, model settings, content sources)
- `content/` - Content retrieval modules (RSS, email, sitemap)
- `charts/` - Financial chart generation (stock charts, bond chart, egg prices)
- `models/` - Pydantic data models for structured AI responses
- `utils/` - Utilities for API calls, email, HTML, logging
- `template.html` - Email HTML template (Axios-style design)

## AI Stack

- **Text Generation**: Claude Opus 4.5 (Anthropic) - extracts news items and generates the newsletter
- **Image Generation**: gpt-image-1.5 (OpenAI) - creates photorealistic images for each story

## Running the Script

**Do NOT run the script with the `--send-to-everyone` flag.** This sends the briefing email to all recipients and should not be used during development or testing.

Running without the flag is safe - it sends the email only to the developer for testing:

```bash
cd "/Users/jay/Tresorit/Jay's tresor/Code/daily-briefing"
source venv/bin/activate
python main.py
```

## Environment

Requires a `.env` file with:
- `ANTHROPIC_API_KEY` - For Claude Opus 4.5 text generation
- `OPENAI_API_KEY` - For gpt-image-1.5 image generation
- `GOOGLE_USERNAME` - Gmail address for sending
- `GOOGLE_PASSWORD` - Gmail app password
- `RECIPIENT_EMAILS` - Comma-separated list of recipients

## Newsletter Format

The newsletter follows Axios-style "Smart Brevity" principles:
- Top 3 stories selected from all content sources
- Each story has: headline, "What", "Why it matters", "Go deeper" sections
- Photorealistic AI-generated image for each story
- Financial charts section at the bottom
