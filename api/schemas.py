"""Pydantic schemas for the ADB v2 API surface."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

CategoryOrder = Literal["sales_volume", "alphabetical"]


class ConnectRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ConnectResponse(BaseModel):
    session_token: str
    username:      str
    expires_at:    float
    industries_count: int = 0
    # Lines captured during the SSO flow (Selenium prints). Surfaced to
    # the frontend so a failing connect has a diagnosable trail.
    logs: List[str] = Field(default_factory=list)


class IndustryOut(BaseModel):
    slug: str
    label: str
    pipeline: Literal["adb", "fs"]


class LevelsOut(BaseModel):
    """Per-industry level filter options for the ADB pipeline. Empty for
    foodservice industries (the FS pipeline doesn't use these dropdowns)."""
    level1_options: List[str] = Field(default_factory=list)
    level_cols:     List[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    industry:        str            = Field(..., description="Industry slug (see /api/industries)")
    year:            int
    quarter:         Literal["Q1", "Q2", "Q3", "Q4"]
    release_date:    str            = Field(..., description="mm/yyyy")
    category_order:  CategoryOrder  = "sales_volume"
    level1_filter:   Optional[str]  = None
    analysis_level:  Optional[str]  = None


class RunStatus(BaseModel):
    run_id:    str
    state:     Literal["queued", "running", "done", "error", "cancelled"]
    step:      Optional[str] = None
    message:   Optional[str] = None
    elapsed_s: float = 0.0
    # Populated only while state == "queued"; null once the run has a slot.
    queue_position: Optional[int]   = None
    queue_depth:    Optional[int]   = None
    eta_seconds:    Optional[float] = None
    # Last N log lines from the pipeline. Frontend can show these live.
    logs: List[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    run_id:       str
    download_url: Optional[str] = None
