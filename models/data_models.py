"""
Data models for the Daily Briefing application.

This module defines Pydantic models used for structured data throughout the application.
"""

from typing import List, Optional, Dict, Union
from pydantic import BaseModel

class NewsItem(BaseModel):
    """Model for a single news item."""
    title: str
    description: str
    source_name: str
    source_link: Optional[str] = None  # URL or None for emails
    source_type: str  # "article" or "email"
    email_sender: Optional[str] = None
    email_subject: Optional[str] = None

class TopicNewsResponse(BaseModel):
    """Response model for news items by topic."""
    news_items: List[NewsItem]

class ContentElement(BaseModel):
    """Model for a content element in the newsletter."""
    type: str  # "paragraph", "heading", or "image_description"
    content: str  # Raw text without HTML tags
    caption: Optional[str] = None  # Caption for image_description elements


class StoryBullet(BaseModel):
    """Model for a bullet point within a story."""
    label: str  # Bold label like "What:", "Why it matters:", "Go deeper:"
    text: str  # The content after the label (can include HTML links)


class NewsStory(BaseModel):
    """Model for a single news story in Axios style."""
    headline: str  # Short, punchy headline for the story
    bullets: List[StoryBullet]  # List of bullet points (what, why, source)
    image_description: Optional[str] = None  # Description for AI image generation
    image_caption: Optional[str] = None  # Caption for the generated image


class AxiosNewsletterResponse(BaseModel):
    """Response model for Axios-style newsletter with top 3 stories."""
    subject: str  # Email subject line highlighting the top story
    intro: str  # Brief intro paragraph
    stories: List[NewsStory]  # Exactly 3 top stories
    closing: Optional[str] = None  # Optional closing remarks


class CohesiveNewsletterResponse(BaseModel):
    """Response model for the final cohesive newsletter (legacy)."""
    subject: str  # Custom email subject
    content_elements: List[ContentElement]  # List of paragraphs, headings, and image descriptions

class ArticleContent(BaseModel):
    """Model for article content."""
    url: str
    title: Optional[str] = ""
    article: str

class EmailContent(BaseModel):
    """Model for email content."""
    subject: str
    body: str

class ContentSource(BaseModel):
    """Model for content sources."""
    source_name: str
    content: List[ArticleContent] | List[EmailContent] | ArticleContent | EmailContent | None
    content_type: str 