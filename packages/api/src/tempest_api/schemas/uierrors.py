"""UI-error shapes (HANDOFF-WORLD-CLASS §1.1): the webview's crash reports."""

from pydantic import BaseModel, Field


class UiErrorReport(BaseModel):
    message: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)  # "window.error" | "unhandledrejection"
    stack: str | None = None


class UiErrorRecorded(BaseModel):
    recorded: bool
