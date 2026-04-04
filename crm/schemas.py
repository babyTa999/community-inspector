"""Pydantic schemas for CRM."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CRMEntryBase(BaseModel):
    """Base schema for CRM entries - matching Feishu format."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # 问题/需求描述
    title: str = Field(..., min_length=1, max_length=500)

    # 分析和todo
    analysis_todo: str | None = Field(default=None, max_length=10000)

    # 社区todo
    community_todo: str | None = Field(default=None, max_length=10000)

    # 链接
    source_url: str | None = Field(default=None, max_length=1000)

    # 相关人员
    assignee: str | None = Field(default=None, max_length=100)

    # tag (状态)
    status_tag: str = Field(default="已定位/知晓", max_length=50)

    # 描述性tag (功能模块)
    feature_module: str | None = Field(default=None, max_length=50)

    # 名字 (用户)
    user_name: str | None = Field(default=None, max_length=100)

    # 声量
    volume: int = Field(default=1, ge=0)

    # 备注
    notes: str | None = Field(default=None, max_length=5000)

    # 父记录
    parent_record: str | None = Field(default=None, max_length=500)

    # 类型标签
    type_tag: str = Field(default="S", max_length=10)

    # 知识库链接
    knowledge_base_url: str | None = Field(default=None, max_length=1000)

    # GitHub Issue 链接
    github_issue_url: str | None = Field(default=None, max_length=1000)

    # 来源类型
    source_type: str | None = Field(default=None, max_length=50)


class CRMEntryCreate(CRMEntryBase):
    """Schema for creating a new entry."""

    attachments: list[str] = Field(default_factory=list)
    # Optional user tracking
    created_by: str | None = Field(default=None, max_length=100)


class CRMEntryUpdate(BaseModel):
    """Schema for updating an entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    analysis_todo: str | None = Field(default=None, max_length=10000)
    community_todo: str | None = Field(default=None, max_length=10000)
    source_url: str | None = Field(default=None, max_length=1000)
    assignee: str | None = Field(default=None, max_length=100)
    status_tag: str | None = Field(default=None, max_length=50)
    feature_module: str | None = Field(default=None, max_length=50)
    user_name: str | None = Field(default=None, max_length=100)
    volume: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=5000)
    parent_record: str | None = Field(default=None, max_length=500)
    type_tag: str | None = Field(default=None, max_length=10)
    attachments: list[str] | None = None
    knowledge_base_url: str | None = Field(default=None, max_length=1000)
    github_issue_url: str | None = Field(default=None, max_length=1000)
    source_type: str | None = Field(default=None, max_length=50)

    # Optimistic locking - must provide current version
    version: int | None = Field(default=None, description="Current version for optimistic locking")
    # User tracking
    edited_by: str | None = Field(default=None, max_length=100)


class EditHistoryResponse(BaseModel):
    """Schema for edit history entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    field_name: str
    old_value: str | None
    new_value: str | None
    created_at: datetime
    username: str | None = None


class CRMEntryResponse(CRMEntryBase):
    """Schema for entry response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    attachments: list[str] | None
    created_at: datetime
    updated_at: datetime

    # Collaboration fields
    version: int
    last_edited_by: str | None
    last_edited_at: datetime | None
    is_being_edited: bool
    edited_by_session: str | None


class CRMEntryList(BaseModel):
    """Schema for list response."""

    items: list[CRMEntryResponse]
    total: int
    page: int
    page_size: int


class EntryFilterParams(BaseModel):
    """Filter parameters for entries."""

    model_config = ConfigDict(str_strip_whitespace=True)

    q: str | None = Field(default=None, description="Search in title")
    type_tag: str | None = Field(default=None, description="R/Q/S/Tips type filter")
    status_tag: str | None = Field(default=None, description="Status filter")
    feature_module: str | None = Field(default=None, description="Feature module filter")
    assignee: str | None = Field(default=None, description="Assignee filter")
    user_name: str | None = Field(default=None, description="User name filter")
    date_from: str | None = Field(default=None, description="Created from date (YYYY-MM-DD)")
    date_to: str | None = Field(default=None, description="Created to date (YYYY-MM-DD)")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class DashboardStats(BaseModel):
    """Dashboard statistics."""

    total_entries: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    by_feature_module: dict[str, int]
    recent_entries: list[CRMEntryResponse]


# Real-time collaboration schemas

class UserBase(BaseModel):
    """Base user schema."""

    username: str = Field(..., min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)


class UserCreate(UserBase):
    """Schema for creating a user."""

    pass


class UserResponse(UserBase):
    """Schema for user response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime


class RealTimeMessage(BaseModel):
    """Base schema for WebSocket messages."""

    type: str = Field(..., description="Message type: edit_start, edit_end, update, cursor, presence")
    entry_id: str | None = Field(default=None)
    username: str
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: dict | None = Field(default=None)


class EditStartMessage(RealTimeMessage):
    """Message sent when user starts editing."""

    type: str = "edit_start"
    entry_id: str


class EditEndMessage(RealTimeMessage):
    """Message sent when user finishes editing."""

    type: str = "edit_end"
    entry_id: str


class EntryUpdateMessage(RealTimeMessage):
    """Message sent when entry is updated."""

    type: str = "entry_update"
    entry_id: str
    data: dict  # Changed fields
    version: int  # New version number


class CursorPositionMessage(RealTimeMessage):
    """Message for cursor position during collaborative editing."""

    type: str = "cursor"
    entry_id: str
    data: dict = Field(..., description="{field: str, position: int}")


class PresenceMessage(RealTimeMessage):
    """Message for user presence (join/leave)."""

    type: str = "presence"
    data: dict = Field(..., description="{status: 'online'|'offline', entries: [entry_ids]}")


class ConflictResponse(BaseModel):
    """Response when optimistic locking detects a conflict."""

    error: str = "Conflict detected"
    current_version: int
    your_version: int
    current_data: CRMEntryResponse
    changes_made_by: str | None
    changes_made_at: datetime | None
