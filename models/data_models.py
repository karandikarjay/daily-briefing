"""
Data models for the Daily Briefing application.

This module defines Pydantic models used for structured data throughout the application.
"""

from typing import List, Optional
from pydantic import BaseModel

class ArticleBulletPoint(BaseModel):
    """Model for article-based bullet points."""
    headline: str
    one_sentence_summary: str
    source_name: str
    url: str

class EmailBulletPoint(BaseModel):
    """Model for email-based bullet points."""
    headline: str
    one_sentence_summary: str
    sender: str
    subject: str

class ArticleBulletPointsResponse(BaseModel):
    """Response model for article-based bullet points."""
    bullet_points: List[ArticleBulletPoint]

class EmailBulletPointsResponse(BaseModel):
    """Response model for email-based bullet points."""
    bullet_points: List[EmailBulletPoint]

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