"""Editable reader preferences, with validated operational ceilings."""
import json
from pathlib import Path
from pydantic import Field
from .models import StrictModel


class Policy(StrictModel):
    audience: str
    purpose: str
    voice: str
    selection: str
    freshness: str
    analysis: str
    topics: dict[str, str]
    target_words: int = Field(default=650, ge=100, le=800)
    max_words: int = Field(default=800, ge=100, le=800)
    max_actions: int = Field(default=32, ge=1, le=40)
    max_searches: int = Field(default=4, ge=0, le=8)
    coverage_followups: int = Field(default=3, ge=0, le=3)
    max_verifications: int = Field(default=10, ge=1, le=20)
    research_seconds: int = Field(default=900, ge=1, le=1800)
    max_repairs: int = Field(default=2, ge=0, le=3)
    max_images: int = Field(default=8, ge=0, le=12)
    max_charts: int = Field(default=5, ge=0, le=5)


def load_policy(path=None):
    path = Path(path) if path else Path(__file__).resolve().parents[1] / 'editorial.json'
    policy = Policy.model_validate(json.loads(path.read_text()))
    if policy.target_words > policy.max_words:
        raise ValueError('Target words must not exceed the reading limit')
    if set(policy.topics) != {'Alternative Protein', 'Vegan Movement', 'AI'}:
        raise ValueError('Editorial topics must match the supported collection interests')
    return policy
