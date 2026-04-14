"""Pydantic schemas for CRM."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from crm.models import Module, Product, StatusTag, TypeTag


class CRMEntryBase(BaseModel):
    """Base schema for CRM entries."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    source_url: str | None = Field(default=None, max_length=1000)
    user_id: str | None = Field(default=None, max_length=100)
    product: str | None = Field(default=None, max_length=50)
    module: str | None = Field(default=None, max_length=50)
    version: str | None = Field(default=None, max_length=50)
    assignee: str | None = Field(default=None, max_length=100)
    type_tag: str = Field(default=TypeTag.SIGNAL.value, max_length=10)
    status_tag: str = Field(default=StatusTag.IDENTIFIED.value, max_length=50)
    attachments: list[str] = Field(default_factory=list)
    knowledge_base_url: str | None = Field(default=None, max_length=1000)
    github_issue_url: str | None = Field(default=None, max_length=1000)


class CRMEntryCreate(CRMEntryBase):
    """Schema for creating a new entry."""

    raw_data: dict[str, Any] | None = None
    source_type: str | None = None
    source_location: str | None = None
    message_id: str | None = None


class CRMEntryUpdate(BaseModel):
    """Schema for updating an entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=1000)
    user_id: str | None = Field(default=None, max_length=100)
    product: str | None = Field(default=None, max_length=50)
    module: str | None = Field(default=None, max_length=50)
    version: str | None = Field(default=None, max_length=50)
    assignee: str | None = Field(default=None, max_length=100)
    type_tag: str | None = Field(default=None, max_length=10)
    status_tag: str | None = Field(default=None, max_length=50)
    attachments: list[str] | None = None
    knowledge_base_url: str | None = Field(default=None, max_length=1000)
    github_issue_url: str | None = Field(default=None, max_length=1000)
    replied_at: datetime | None = None
    resolved_at: datetime | None = None


class CRMEntryResponse(CRMEntryBase):
    """Schema for entry response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    replied_at: datetime | None
    resolved_at: datetime | None
    raw_data: dict[str, Any] | None
    source_type: str | None
    source_location: str | None
    message_id: str | None


class CRMEntryList(BaseModel):
    """Schema for list response."""

    items: list[CRMEntryResponse]
    total: int
    page: int
    page_size: int


class EntryFilterParams(BaseModel):
    """Filter parameters for entries."""

    model_config = ConfigDict(str_strip_whitespace=True)

    q: str | None = Field(default=None, description="Search in title and description")
    type_tag: str | None = Field(default=None, description="R/Q/S type filter")
    status_tag: str | None = Field(default=None, description="Status filter")
    product: str | None = Field(default=None, description="Product filter")
    module: str | None = Field(default=None, description="Module filter")
    version: str | None = Field(default=None, description="Version filter")
    assignee: str | None = Field(default=None, description="Assignee filter")
    user_id: str | None = Field(default=None, description="User ID filter")
    date_from: datetime | None = Field(default=None, description="Created from date")
    date_to: datetime | None = Field(default=None, description="Created to date")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class DashboardStats(BaseModel):
    """Dashboard statistics."""

    total_entries: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    by_product: dict[str, int]
    recent_entries: list[CRMEntryResponse]
