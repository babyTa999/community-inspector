"""CRUD operations for CRM entries."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from crm.models import CRMEntry, StatusTag, TypeTag
from crm.schemas import CRMEntryCreate, CRMEntryUpdate


def create_entry(db: Session, entry: CRMEntryCreate) -> CRMEntry:
    """Create a new CRM entry."""
    db_entry = CRMEntry(**entry.model_dump())
    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def get_entry(db: Session, entry_id: str) -> CRMEntry | None:
    """Get entry by ID."""
    return db.query(CRMEntry).filter(CRMEntry.id == entry_id).first()


def get_entry_by_message_id(db: Session, message_id: str) -> CRMEntry | None:
    """Get entry by message ID."""
    return db.query(CRMEntry).filter(CRMEntry.message_id == message_id).first()


def update_entry(db: Session, entry_id: str, update: CRMEntryUpdate) -> CRMEntry | None:
    """Update an existing entry."""
    db_entry = get_entry(db, entry_id)
    if not db_entry:
        return None

    update_data = update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_entry, field, value)

    db.commit()
    db.refresh(db_entry)
    return db_entry


def delete_entry(db: Session, entry_id: str) -> bool:
    """Delete an entry."""
    db_entry = get_entry(db, entry_id)
    if not db_entry:
        return False

    db.delete(db_entry)
    db.commit()
    return True


def get_entries(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    order_by: str = "created_at",
    desc: bool = True,
) -> list[CRMEntry]:
    """Get entries with pagination."""
    query = db.query(CRMEntry)

    # Apply ordering
    order_column = getattr(CRMEntry, order_by, CRMEntry.created_at)
    if desc:
        order_column = order_column.desc()
    query = query.order_by(order_column)

    return query.offset(skip).limit(limit).all()


def count_entries(db: Session) -> int:
    """Count total entries."""
    return db.query(CRMEntry).count()


def create_entry_from_digest(
    db: Session,
    *,
    message_id: str,
    title: str,
    description: str,
    source_url: str,
    user_id: str,
    source_type: str,
    source_location: str,
    category: str,  # Problem, Signal, UGC
    translated_zh: str,
    has_reply: bool | None = None,
    solved: bool | None = None,
    known_status: str = "n/a",
    known_source: str = "",
    thread_title: str = "",
    raw_data: dict[str, Any] | None = None,
) -> CRMEntry | None:
    """Create entry from bot digest item.

    Maps bot classification to CRM schema:
    - Problem -> Q (Question)
    - Signal -> S (Signal)
    - UGC -> S (Signal) or can be filtered out
    """
    # Check if entry already exists
    existing = get_entry_by_message_id(db, message_id)
    if existing:
        return existing

    # Map category to type tag
    type_tag_map = {
        "Problem": TypeTag.QUESTION.value,
        "Signal": TypeTag.SIGNAL.value,
        "UGC": TypeTag.SIGNAL.value,
    }
    type_tag = type_tag_map.get(category, TypeTag.SIGNAL.value)

    # Determine initial status
    if category == "Problem":
        if solved:
            status_tag = StatusTag.FIXED.value
        elif has_reply:
            status_tag = StatusTag.REPLIED.value
        else:
            status_tag = StatusTag.IDENTIFIED.value
    else:
        status_tag = StatusTag.IDENTIFIED.value

    # Build title from thread title or translated content
    final_title = thread_title or translated_zh[:100]
    if len(final_title) > 200:
        final_title = final_title[:200] + "..."

    entry_create = CRMEntryCreate(
        title=final_title,
        description=description or translated_zh,
        source_url=source_url,
        user_id=user_id,
        type_tag=type_tag,
        status_tag=status_tag,
        source_type=source_type,
        source_location=source_location,
        message_id=message_id,
        knowledge_base_url=known_source if known_status == "known" else None,
        raw_data=raw_data,
    )

    return create_entry(db, entry_create)


def get_stats(db: Session) -> dict[str, Any]:
    """Get dashboard statistics."""
    from sqlalchemy import func

    total = db.query(CRMEntry).count()

    # Count by type
    by_type = {}
    for type_tag, count in (
        db.query(CRMEntry.type_tag, func.count(CRMEntry.id)).group_by(CRMEntry.type_tag).all()
    ):
        by_type[type_tag] = count

    # Count by status
    by_status = {}
    for status_tag, count in (
        db.query(CRMEntry.status_tag, func.count(CRMEntry.id)).group_by(CRMEntry.status_tag).all()
    ):
        by_status[status_tag] = count

    # Count by product
    by_product = {}
    for product, count in (
        db.query(CRMEntry.product, func.count(CRMEntry.id))
        .filter(CRMEntry.product.isnot(None))
        .group_by(CRMEntry.product)
        .all()
    ):
        by_product[product] = count

    # Recent entries
    recent = (
        db.query(CRMEntry).order_by(CRMEntry.created_at.desc()).limit(10).all()
    )

    return {
        "total_entries": total,
        "by_type": by_type,
        "by_status": by_status,
        "by_product": by_product,
        "recent_entries": recent,
    }
