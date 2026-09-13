"""Structured editorial decisions and plain-text, source-linked newsletter blocks."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Action(StrictModel):
    tool: Literal['inspect', 'research', 'verify', 'finish']
    source_id: str = ''
    topic: Literal['Alternative Protein', 'Vegan Movement', 'AI'] = 'AI'
    reason: str = Field(max_length=1200)
    focus_quote: str = ''


class PublicQuery(StrictModel):
    query: str = Field(min_length=3, max_length=300)


class Citation(StrictModel):
    source_id: str
    quote: str = Field(min_length=15)


class Paragraph(StrictModel):
    label: str = ''
    text: str
    kind: Literal['reporting', 'analysis'] = 'reporting'
    citations: list[Citation]


class Story(StrictModel):
    development_ids: list[str] = Field(min_length=1)
    headline: str
    paragraphs: list[Paragraph] = Field(min_length=1)
    image_description: str | None = None
    image_caption: str | None = None


class Chart(StrictModel):
    key: Literal['bynd-chart', 'beyond-meat-bond-chart', 'otly-chart', 'sp500-chart', 'egg-price-chart']
    development_id: str
    reason: str


class Omission(StrictModel):
    development_id: str
    reason: str


class Edition(StrictModel):
    subject: str = Field(min_length=1, max_length=100)
    intro: str = ''
    stories: list[Story]
    closing: str = ''
    charts: list[Chart] = Field(default_factory=list)
    omissions: list[Omission] = Field(default_factory=list)


class Review(StrictModel):
    approved: bool
    issues: list[str]
    rejected_development_ids: list[str]


class HeadlineEdit(StrictModel):
    story_index: int = Field(ge=0)
    headline: str


class ParagraphEdit(StrictModel):
    story_index: int = Field(ge=0)
    paragraph_index: int = Field(ge=0)
    paragraph: Paragraph


class Repairs(StrictModel):
    subject: str | None = None
    intro: str | None = None
    closing: str | None = None
    headlines: list[HeadlineEdit] = Field(default_factory=list)
    paragraphs: list[ParagraphEdit] = Field(default_factory=list)
    remove_images: list[int] = Field(default_factory=list)
    remove_charts: list[str] = Field(default_factory=list)


class CoverageReview(StrictModel):
    adequate: bool
    reason: str
    followups: list[Action] = Field(default_factory=list, max_length=3)
