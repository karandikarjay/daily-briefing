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


class ReviewIssue(StrictModel):
    id: str = Field(min_length=1)
    field: Literal['subject', 'intro', 'closing', 'headline', 'paragraph',
                   'image_caption', 'image_description', 'story', 'edition']
    story_index: int | None = Field(default=None, ge=0)
    paragraph_index: int | None = Field(default=None, ge=0)
    category: Literal['factual', 'invalid_development', 'optional_presentation', 'coverage']
    detail: str = Field(min_length=1)
    development_ids: list[str] = Field(default_factory=list)


class Review(StrictModel):
    approved: bool
    issues: list[str]
    rejected_development_ids: list[str]
    findings: list[ReviewIssue] = Field(default_factory=list)


class HeadlineEdit(StrictModel):
    story_index: int = Field(ge=0)
    headline: str


class ParagraphEdit(StrictModel):
    story_index: int = Field(ge=0)
    paragraph_index: int = Field(ge=0)
    paragraph: Paragraph


class ImageEdit(StrictModel):
    story_index: int = Field(ge=0)
    image_caption: str
    image_description: str


class StoryEdit(StrictModel):
    story_index: int = Field(ge=0)
    story: Story


class Repairs(StrictModel):
    subject: str | None = None
    intro: str | None = None
    closing: str | None = None
    headlines: list[HeadlineEdit] = Field(default_factory=list)
    paragraphs: list[ParagraphEdit] = Field(default_factory=list)
    images: list[ImageEdit] = Field(default_factory=list)
    addressed_issue_ids: list[str] = Field(default_factory=list)
    restore_stories: list[Story] = Field(default_factory=list)
    stories: list[StoryEdit] = Field(default_factory=list)
    remove_images: list[int] = Field(default_factory=list)
    remove_charts: list[str] = Field(default_factory=list)

    @classmethod
    def model_json_schema(cls, *args, **kwargs):
        # Many independently optional edit fields exceeded the provider's grammar
        # complexity limit. Explicit nulls/empty lists keep the same local defaults
        # while greatly reducing optional branches in the wire schema.
        schema = super().model_json_schema(*args, **kwargs)

        def require_fields(node):
            if isinstance(node, dict):
                node.pop('default', None)
                if 'properties' in node:
                    node['required'] = list(node['properties'])
                for value in node.values():
                    require_fields(value)
            elif isinstance(node, list):
                for value in node:
                    require_fields(value)

        require_fields(schema)
        return schema


class CoverageReview(StrictModel):
    adequate: bool
    reason: str
    followups: list[Action] = Field(default_factory=list, max_length=3)
