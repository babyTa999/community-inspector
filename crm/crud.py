"""CRUD operations for CRM entries."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.orm import Session

try:
    from crm.models import CRMEntry, EditHistory, User
    from crm.schemas import CRMEntryCreate, CRMEntryUpdate
except ImportError:
    from models import CRMEntry, EditHistory, User
    from schemas import CRMEntryCreate, CRMEntryUpdate


class ConflictError(Exception):
    """Raised when optimistic locking detects a conflict."""

    def __init__(self, current_version: int, your_version: int, current_entry: CRMEntry):
        self.current_version = current_version
        self.your_version = your_version
        self.current_entry = current_entry
        super().__init__(
            f"Conflict: entry was modified. Current version: {current_version}, your version: {your_version}"
        )


def create_entry(db: Session, entry: CRMEntryCreate, created_by: str | None = None) -> CRMEntry:
    """Create a new CRM entry."""
    entry_data = entry.model_dump()

    # Remove created_by from entry data if present
    entry_data.pop("created_by", None)

    db_entry = CRMEntry(**entry_data)

    if created_by:
        db_entry.last_edited_by = created_by
        db_entry.last_edited_at = datetime.now(timezone.utc)

    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)
    return db_entry


def get_entry(db: Session, entry_id: str) -> CRMEntry | None:
    """Get entry by ID."""
    return db.query(CRMEntry).filter(CRMEntry.id == entry_id).first()


def get_entry_with_lock(db: Session, entry_id: str) -> CRMEntry | None:
    """Get entry with pessimistic locking (for edit sessions)."""
    return (
        db.query(CRMEntry)
        .filter(CRMEntry.id == entry_id)
        .with_for_update()
        .first()
    )


def update_entry(
    db: Session,
    entry_id: str,
    update: CRMEntryUpdate,
    edited_by: str | None = None,
    track_changes: bool = True,
) -> CRMEntry:
    """Update an existing entry with optimistic locking.

    Raises:
        ConflictError: If the entry was modified by someone else
    """
    db_entry = get_entry(db, entry_id)
    if not db_entry:
        return None

    update_data = update.model_dump(exclude_unset=True)

    # Extract version and edited_by from update data
    new_version = update_data.pop("version", None)
    update_edited_by = update_data.pop("edited_by", None)
    edited_by = edited_by or update_edited_by

    # Optimistic locking check
    if new_version is not None and new_version != db_entry.version:
        raise ConflictError(
            current_version=db_entry.version,
            your_version=new_version,
            current_entry=db_entry,
        )

    # Track changes for history
    if track_changes and edited_by:
        history_user = get_or_create_user(db, edited_by)
        for field, new_value in update_data.items():
            if field in ["attachments"]:
                # Skip complex fields for now
                continue

            old_value = getattr(db_entry, field)
            if old_value != new_value:
                # Create edit history record
                history = EditHistory(
                    entry_id=entry_id,
                    user_id=history_user.id,
                    field_name=field,
                    old_value=str(old_value) if old_value is not None else None,
                    new_value=str(new_value) if new_value is not None else None,
                )
                db.add(history)

    # Apply updates
    for field, value in update_data.items():
        setattr(db_entry, field, value)

    # Increment version and update editor info
    db_entry.version += 1
    if edited_by:
        db_entry.last_edited_by = edited_by
        db_entry.last_edited_at = datetime.now(timezone.utc)

    # Clear edit session
    db_entry.is_being_edited = False
    db_entry.edited_by_session = None
    db_entry.edit_session_expires = None

    db.commit()
    db.refresh(db_entry)
    return db_entry


def delete_entry(db: Session, entry_id: str) -> bool:
    """Delete an entry."""
    db_entry = get_entry(db, entry_id)
    if not db_entry:
        return False

    # Delete associated edit history first
    db.query(EditHistory).filter(EditHistory.entry_id == entry_id).delete()

    db.delete(db_entry)
    db.commit()
    return True


def delete_entries_batch(db: Session, entry_ids: list[str]) -> int:
    """Batch delete entries, return count of successfully deleted."""
    deleted = 0
    for entry_id in entry_ids:
        if delete_entry(db, entry_id):
            deleted += 1
    return deleted


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


def get_stats(db: Session) -> dict:
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

    # Count by feature module
    by_feature_module = {}
    for module, count in (
        db.query(CRMEntry.feature_module, func.count(CRMEntry.id))
        .filter(CRMEntry.feature_module.isnot(None))
        .group_by(CRMEntry.feature_module)
        .all()
    ):
        by_feature_module[module] = count

    # Recent entries
    recent = (
        db.query(CRMEntry).order_by(CRMEntry.created_at.desc()).limit(10).all()
    )

    return {
        "total_entries": total,
        "by_type": by_type,
        "by_status": by_status,
        "by_feature_module": by_feature_module,
        "recent_entries": recent,
    }


# Edit session management

def start_edit_session(
    db: Session, entry_id: str, session_id: str, username: str, expires_minutes: int = 30
) -> CRMEntry | None:
    """Mark an entry as being edited by a session."""
    db_entry = get_entry_with_lock(db, entry_id)
    if not db_entry:
        return None

    # Check if someone else is editing
    if db_entry.is_being_edited and db_entry.edited_by_session != session_id:
        # Check if session expired
        if db_entry.edit_session_expires and db_entry.edit_session_expires > datetime.now(timezone.utc):
            return None  # Someone else is actively editing

    # Claim the edit session
    db_entry.is_being_edited = True
    db_entry.edited_by_session = session_id
    # FIX: use timedelta directly instead of __import__("datetime").timedelta
    db_entry.edit_session_expires = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

    db.commit()
    db.refresh(db_entry)
    return db_entry


def end_edit_session(db: Session, entry_id: str, session_id: str) -> CRMEntry | None:
    """Release edit session."""
    db_entry = get_entry(db, entry_id)
    if not db_entry:
        return None

    if db_entry.edited_by_session == session_id:
        db_entry.is_being_edited = False
        db_entry.edited_by_session = None
        db_entry.edit_session_expires = None
        db.commit()
        db.refresh(db_entry)

    return db_entry


def extend_edit_session(db: Session, entry_id: str, session_id: str, expires_minutes: int = 30) -> bool:
    """Extend edit session expiration."""
    db_entry = get_entry(db, entry_id)
    if not db_entry or db_entry.edited_by_session != session_id:
        return False

    # FIX: use timedelta directly instead of __import__("datetime").timedelta
    db_entry.edit_session_expires = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    db.commit()
    return True


# Edit history

def get_entry_history(db: Session, entry_id: str, limit: int = 50) -> list[EditHistory]:
    """Get edit history for an entry."""
    return (
        db.query(EditHistory)
        .filter(EditHistory.entry_id == entry_id)
        .order_by(EditHistory.created_at.desc())
        .limit(limit)
        .all()
    )


# User management

def get_or_create_user(db: Session, username: str, display_name: str | None = None) -> User:
    """Get existing user or create new one."""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        user = User(
            username=username,
            display_name=display_name or username,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_user_by_username(db: Session, username: str) -> User | None:
    """Get user by username."""
    return db.query(User).filter(User.username == username).first()
