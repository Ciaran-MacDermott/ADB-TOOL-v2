"""Pydantic schemas for the ADB v2 API surface."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

CategoryOrder = Literal["sales_volume", "alphabetical"]


class ConnectRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ConnectResponse(BaseModel):
    session_token: str
    username:      str
    expires_at:    float


class IndustryOut(BaseModel):
    slug: str
    label: str
    pipeline: Literal["adb", "fs"]


class RunRequest(BaseModel):
    industry:        str            = Field(..., description="Industry slug (see /api/industries)")
    year:            int
    quarter:         Literal["Q1", "Q2", "Q3", "Q4"]
    release_date:    str            = Field(..., description="mm/yyyy")
    category_order:  CategoryOrder  = "sales_volume"
    level1_filter:   Optional[str]  = None
    analysis_level:  Optional[str]  = None
    npd_username:    Optional[str]  = None
    npd_password:    Optional[str]  = None


class RunStatus(BaseModel):
    run_id:    str
    state:     Literal["pending", "running", "done", "error", "cancelled"]
    step:      Optional[str] = None
    message:   Optional[str] = None
    elapsed_s: float = 0.0


class RunResponse(BaseModel):
    run_id:       str
    download_url: Optional[str] = None
