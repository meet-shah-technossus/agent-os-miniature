"""Pydantic models for prompt generation inputs and review feedback."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FileVerdict(str, Enum):
    ACCEPT = "accept"
    PATCH = "patch"
    REGENERATE = "regenerate"


class FileReview(BaseModel):
    """Review verdict for a single file from the code reviewer."""
    file_path: str
    verdict: FileVerdict = FileVerdict.ACCEPT
    comments: list[str] = Field(default_factory=list)


class ReviewFeedback(BaseModel):
    """Aggregated review feedback from a prior iteration."""
    iteration: int = 0
    files: list[FileReview] = Field(default_factory=list)
    summary: str = ""
