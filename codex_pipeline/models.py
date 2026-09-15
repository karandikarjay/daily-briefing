"""Small artifact contract between autonomous research, writing, and publishing."""
from typing import Literal
from pydantic import Field
from editor.models import StrictModel

ChartKey = Literal['bynd-chart', 'otly-chart', 'sp500-chart', 'beyond-meat-bond-chart', 'egg-price-chart']
Topic = Literal['Alternative Protein', 'Vegan Movement', 'AI']


class Lead(StrictModel):
    url: str
    title: str
    topic: Topic
    significance: str
    prior_coverage_query: str
    context_urls: list[str]


class Research(StrictModel):
    research_completed: bool
    leads: list[Lead] = Field(max_length=18)
    coverage_note: str


class Citation(StrictModel):
    source_id: str
    quote: str = Field(min_length=15)
    link_text: str  # Exact substring of paragraph text; empty for non-public evidence.


class Paragraph(StrictModel):
    text: str
    kind: Literal['reporting', 'analysis']
    citations: list[Citation] = Field(min_length=1)


class Story(StrictModel):
    development_ids: list[str] = Field(min_length=1)
    headline: str
    paragraphs: list[Paragraph] = Field(min_length=1)
    brief: bool
    image_description: str | None
    image_caption: str | None


class Note(StrictModel):
    key: ChartKey
    text: str


class Edition(StrictModel):
    subject: str = Field(min_length=1, max_length=100)
    stories: list[Story]
    market_notes: list[Note]


class Development(StrictModel):
    source_id: str  # Unique event ID selected by editor.
    evidence_source_id: str  # Retained source ID supplied by runner.
    evidence_quote: str = Field(min_length=15)
    announcement_date: str
    event_key: str
    title: str
    topic: Topic


class Omitted(StrictModel):
    source_id: str
    reason: str


class Draft(StrictModel):
    edition: Edition
    developments: list[Development]
    omissions: list[Omitted]


class Review(StrictModel):
    approved: bool
    issues: list[str]
