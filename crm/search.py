"""Search and filter operations for CRM entries."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

try:
    from crm.models import CRMEntry
    from crm.schemas import EntryFilterParams
except ImportError:
    from models import CRMEntry
    from schemas import EntryFilterParams


def apply_filters(query: Query, filters: EntryFilterParams) -> Query:
    """Apply filter parameters to query."""

    # FIX: full-text search now covers title, analysis_todo, notes, and community_todo
    if filters.q:
        search_term = f"%{filters.q}%"
        query = query.filter(
            or_(
                CRMEntry.title.ilike(search_term),
                CRMEntry.analysis_todo.ilike(search_term),
                CRMEntry.notes.ilike(search_term),
                CRMEntry.community_todo.ilike(search_term),
            )
        )

    # Type tag filter (R/Q/S/Tips)
    if filters.type_tag:
        query = query.filter(CRMEntry.type_tag == filters.type_tag)

    # Status tag filter
    if filters.status_tag:
        query = query.filter(CRMEntry.status_tag == filters.status_tag)

    # Feature module filter
    if filters.feature_module:
        query = query.filter(CRMEntry.feature_module == filters.feature_module)

    # Assignee filter
    if filters.assignee:
        query = query.filter(CRMEntry.assignee.ilike(f"%{filters.assignee}%"))

    # User name filter
    if filters.user_name:
        query = query.filter(CRMEntry.user_name.ilike(f"%{filters.user_name}%"))

    # Date range filters
    if filters.date_from:
        try:
            date_from = datetime.strptime(filters.date_from, "%Y-%m-%d")
            query = query.filter(CRMEntry.created_at >= date_from)
        except ValueError:
            pass

    if filters.date_to:
        try:
            date_to = datetime.strptime(filters.date_to, "%Y-%m-%d")
            # Set to end of day
            date_to = date_to.replace(hour=23, minute=59, second=59)
            query = query.filter(CRMEntry.created_at <= date_to)
        except ValueError:
            pass

    return query


def get_filtered_entries(
    db: Session,
    filters: EntryFilterParams,
) -> tuple[list[CRMEntry], int]:
    """Get filtered entries with pagination.

    Returns:
        Tuple of (entries list, total count)
    """
    # Build base query with filters
    query = db.query(CRMEntry)
    query = apply_filters(query, filters)

    # Get total count before pagination
    total = query.count()

    # Apply ordering (default: created_at desc)
    query = query.order_by(CRMEntry.created_at.desc())

    # Apply pagination
    skip = (filters.page - 1) * filters.page_size
    entries = query.offset(skip).limit(filters.page_size).all()

    return entries, total


def get_distinct_values(db: Session, column: str) -> list[str]:
    """Get distinct values for a column (for filter dropdowns)."""
    column_attr = getattr(CRMEntry, column, None)
    if not column_attr:
        return []

    values = (
        db.query(column_attr)
        .filter(column_attr.isnot(None))
        .distinct()
        .order_by(column_attr)
        .all()
    )
    return [v[0] for v in values if v[0]]


def get_filter_options(db: Session) -> dict:
    """Get all filter options for dropdowns."""
    try:
        from crm.models import FeatureModule, StatusTag, TypeTag
    except ImportError:
        from models import FeatureModule, StatusTag, TypeTag

    return {
        "type_tags": [
            {"value": t.value, "label": _get_type_label(t.value)}
            for t in TypeTag
        ],
        "status_tags": [
            {"value": s.value, "label": s.value}
            for s in StatusTag
        ],
        "feature_modules": [
            {"value": m.value, "label": m.value}
            for m in FeatureModule
        ],
        # Dynamic values from database
        "assignees": get_distinct_values(db, "assignee"),
        "users": get_distinct_values(db, "user_name"),
    }


def _get_type_label(value: str) -> str:
    """Get human-readable label for type tag."""
    labels = {
        "R": "R - 需求 (Request)",
        "Q": "Q - 问题 (Question)",
        "S": "S - 信号 (Signal)",
        "Tips": "Tips - 技巧/教程",
    }
    return labels.get(value, value)
