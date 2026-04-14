"""CRM database models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    """Base class for all models."""


class TypeTag(str, enum.Enum):
    """R/Q/S type tags."""

    REQUEST = "R"  # 功能请求/改进建议
    QUESTION = "Q"  # Bug/操作疑惑
    SIGNAL = "S"  # 趋势/风险/机会


class StatusTag(str, enum.Enum):
    """Status/lifecycle tags."""

    IDENTIFIED = "identified"  # 已定位/知晓
    EVALUATING = "evaluating"  # 判断中
    PENDING_FIX = "pending_fix"  # 待修复
    FIXING = "fixing"  # 修复中
    FIXED = "fixed"  # 已修复
    PENDING_REPLY = "pending_reply"  # 待回复
    REPLIED = "replied"  # 已回复
    USER_PENDING = "user_pending"  # User待回复
    USER_RESPONDED = "user_responded"  # User已反馈
    TRANSFERRED_HARDWARE = "transferred_hardware"  # 转硬件


class Product(str, enum.Enum):
    """Product lines."""

    PRODUCT_A = "Product A"
    PRODUCT_B = "Product B"
    PRODUCT_C = "Product C"
    PRODUCT_D = "Product D"
    OTHER = "Other"


class Module(str, enum.Enum):
    """Product modules."""

    NETWORK = "网络"
    STORAGE = "存储"
    UI = "UI"
    SYSTEM = "系统"
    SECURITY = "安全"
    APP_STORE = "应用商店"
    DOCKER = "Docker"
    HARDWARE = "硬件"
    OTHER = "其他"


class CRMEntry(Base):
    """CRM entry for community signals and user feedback."""

    __tablename__ = "crm_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(String(10000), nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product: Mapped[str | None] = mapped_column(String(50), nullable=True)
    module: Mapped[str | None] = mapped_column(String(50), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    type_tag: Mapped[str] = mapped_column(String(10), nullable=False, default=TypeTag.SIGNAL.value)
    status_tag: Mapped[str] = mapped_column(
        String(50), nullable=False, default=StatusTag.IDENTIFIED.value
    )

    attachments: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    knowledge_base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    github_issue_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Raw data from source (Discord/Forum message)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Source information
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # discord/forum
    source_location: Mapped[str | None] = mapped_column(String(200), nullable=True)  # channel/forum name
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<CRMEntry(id={self.id}, title={self.title[:50]}, type={self.type_tag})>"


# Database setup
def get_engine(db_path: str = "/data/crm.db"):
    """Create database engine."""
    return create_engine(f"sqlite:///{db_path}", echo=False)


def get_session_maker(engine):
    """Get session maker bound to engine."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(engine):
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


# Enable WAL mode for better concurrency
@event.listens_for(Base.metadata, "after_create")
def enable_wal(target, connection, **kw):
    """Enable WAL mode for SQLite."""
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
