"""CRM database models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""


class TypeTag(str, enum.Enum):
    """R/Q/S type tags."""

    REQUEST = "R"  # 功能请求/改进建议
    QUESTION = "Q"  # Bug/操作疑惑
    SIGNAL = "S"  # 趋势/风险/机会
    TIPS = "Tips"  # 技巧/教程


class StatusTag(str, enum.Enum):
    """Status/lifecycle tags - matching Feishu format."""

    IDENTIFIED = "已定位/知晓"
    EVALUATING = "待/判断/中"
    PENDING_FIX = "待修复"
    FIXING = "修复中"
    FIXED = "已解决"
    PENDING_REPLY = "待回复"
    REPLIED = "已回复"
    IMPORTANT = "重要"


class FeatureModule(str, enum.Enum):
    """Feature modules from Feishu 描述性tag."""

    FILES = "Files"
    APP_STORE = "App Store"
    DOCKER = "Docker"
    VM = "虚拟机"
    RAID = "RAID"
    BACKUP = "备份"
    NETWORK = "网络"
    STORAGE = "存储"
    UI = "UI/UX"
    SYSTEM = "系统"
    SECURITY = "安全"
    SEARCH = "搜索"
    SMB = "Samba/SMB"
    CLOUD_DRIVE = "云盘"
    GPU = "GPU"
    UPS = "UPS"
    MONITORING = "监控/小组件"
    PERMISSIONS = "权限/账户"
    ENCRYPTION = "文件加密"
    MIGRATION = "迁移"
    DRIVERS = "驱动"
    MOBILE = "移动端"
    DESKTOP = "桌面端"
    EXPERIENCE = "体验优化"
    THIRD_PARTY = "第三方集成"
    OTHER = "其他"


class SourceType(str, enum.Enum):
    """Source of the issue - where it came from."""

    DISCORD = "Discord"
    REDDIT = "Reddit"
    GITHUB = "GitHub"
    EMAIL = "Email"
    INTERCOM = "Intercom"
    FORUM = "Forum"
    INTERNAL = "内部"
    OTHER = "其他"


class Priority(str, enum.Enum):
    """Priority levels for issues."""

    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"
    CRITICAL = "紧急"


class User(Base):
    """User model for tracking who made changes."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    edits: Mapped[list["EditHistory"]] = relationship("EditHistory", back_populates="user")

    def __repr__(self) -> str:
        return f"<User(username={self.username})>"


class CRMEntry(Base):
    """CRM entry matching Feishu多维表格 format."""

    __tablename__ = "crm_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 问题/需求描述 (标题)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # 分析和todo + 社区todo (完整描述)
    analysis_todo: Mapped[str | None] = mapped_column(Text, nullable=True)
    community_todo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 链接
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 相关人员 (追踪人)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # tag (状态标签)
    status_tag: Mapped[str] = mapped_column(
        String(50), nullable=False, default=StatusTag.IDENTIFIED.value
    )

    # 描述性tag (功能模块)
    feature_module: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 名字 (用户)
    user_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 声量
    volume: Mapped[int] = mapped_column(Integer, default=1)

    # 更新记录日期
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # 备注
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 父记录 (关联的其他记录)
    parent_record: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 类型标签 (R/Q/S/Tips)
    type_tag: Mapped[str] = mapped_column(String(10), nullable=False, default=TypeTag.SIGNAL.value)

    # 附件 (图片文件名列表)
    attachments: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)

    # 知识库链接
    knowledge_base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # GitHub Issue 链接
    github_issue_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 来源类型 (Discord/Reddit/GitHub/Email等)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 来源原始链接
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 优先级
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True, default=Priority.MEDIUM.value)

    # 父问题ID (用于子问题关联)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("crm_entries.id"), nullable=True)

    # 解决时间 (用于统计解决时长)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    children: Mapped[list["CRMEntry"]] = relationship(
        "CRMEntry",
        back_populates="parent",
        remote_side=["CRMEntry.id"],
        foreign_keys="[CRMEntry.parent_id]"
    )
    parent: Mapped["CRMEntry" | None] = relationship(
        "CRMEntry",
        back_populates="children",
        remote_side=["CRMEntry.id"],
        foreign_keys="[CRMEntry.parent_id]"
    )

    # Optimistic locking - version number for conflict detection
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Last editor tracking
    last_edited_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Is currently being edited (for real-time collaboration)
    is_being_edited: Mapped[bool] = mapped_column(default=False)
    edited_by_session: Mapped[str | None] = mapped_column(String(100), nullable=True)
    edit_session_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    history: Mapped[list["EditHistory"]] = relationship(
        "EditHistory",
        back_populates="entry",
        order_by="desc(EditHistory.created_at)"
    )

    def __repr__(self) -> str:
        return f"<CRMEntry(id={self.id}, title={self.title[:50]}, type={self.type_tag})>"


class EditHistory(Base):
    """Track edit history for each entry."""

    __tablename__ = "edit_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    entry_id: Mapped[str] = mapped_column(ForeignKey("crm_entries.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # What changed
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Snapshot of full entry at this point (optional, for rollback)
    entry_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    entry: Mapped[CRMEntry] = relationship("CRMEntry", back_populates="history")
    user: Mapped[User | None] = relationship("User", back_populates="edits")

    def __repr__(self) -> str:
        return f"<EditHistory(entry={self.entry_id}, field={self.field_name})>"


class RealTimeSession(Base):
    """Track active WebSocket sessions for real-time collaboration."""

    __tablename__ = "realtime_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    entry_id: Mapped[str | None] = mapped_column(ForeignKey("crm_entries.id"), nullable=True)

    # Session metadata
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    is_active: Mapped[bool] = mapped_column(default=True)

    def __repr__(self) -> str:
        return f"<RealTimeSession(session={self.session_id}, user={self.username})>"


class KnowledgeBase(Base):
    """Knowledge base articles for issue resolution."""

    __tablename__ = "knowledge_base"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 标题
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # 内容
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 标签
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)

    # 关联的原始问题ID
    source_issue_id: Mapped[str | None] = mapped_column(ForeignKey("crm_entries.id"), nullable=True)

    # 被引用次数
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    # 向量ID (用于Qdrant检索)
    vector_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    source_issue: Mapped[CRMEntry | None] = relationship("CRMEntry", foreign_keys=[source_issue_id])

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, title={self.title[:50]})>"
