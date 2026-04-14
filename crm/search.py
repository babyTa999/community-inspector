"""Search and filter operations for CRM entries."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from crm.models import CRMEntry
from crm.schemas import EntryFilterParams


def apply_filters(query: Query, filters: EntryFilterParams) -> Query:
    """Apply filter parameters to query."""

    # Text search in title and description
    if filters.q:
        search_term = f"%{filters.q}%"
        query = query.filter(
            or_(
                CRMEntry.title.ilike(search_term),
                CRMEntry.description.ilike(search_term),
            )
        )

    # Type tag filter (R/Q/S)
    if filters.type_tag:
        query = query.filter(CRMEntry.type_tag == filters.type_tag)

    # Status tag filter
    if filters.status_tag:
        query = query.filter(CRMEntry.status_tag == filters.status_tag)

    # Product filter
    if filters.product:
        query = query.filter(CRMEntry.product == filters.product)

    # Module filter
    if filters.module:
        query = query.filter(CRMEntry.module == filters.module)

    # Version filter
    if filters.version:
        query = query.filter(CRMEntry.version.ilike(f"%{filters.version}%"))

    # Assignee filter
    if filters.assignee:
        query = query.filter(CRMEntry.assignee.ilike(f"%{filters.assignee}%"))

    # User ID filter
    if filters.user_id:
        query = query.filter(CRMEntry.user_id.ilike(f"%{filters.user_id}%"))

    # Date range filters
    if filters.date_from:
        query = query.filter(CRMEntry.created_at >= filters.date_from)
    if filters.date_to:
        query = query.filter(CRMEntry.created_at <= filters.date_to)

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
    from crm.models import Module, Product, StatusTag, TypeTag

    return {
        "type_tags": [
            {"value": t.value, "label": _get_type_label(t.value)}
            for t in TypeTag
        ],
        "status_tags": [
            {"value": s.value, "label": _get_status_label(s.value)}
            for s in StatusTag
        ],
        "products": [{"value": p.value, "label": p.value} for p in Product],
        "modules": [{"value": m.value, "label": m.value} for m in Module],
        # Dynamic values from database
        "versions": get_distinct_values(db, "version"),
        "assignees": get_distinct_values(db, "assignee"),
        "users": get_distinct_values(db, "user_id"),
    }


def _get_type_label(value: str) -> str:
    """Get human-readable label for type tag."""
    labels = {
        "R": "R - Request (功能请求)",
        "Q": "Q - Question (问题/Bug)",
        "S": "S - Signal (趋势/洞察)",
    }
    return labels.get(value, value)


def _get_status_label(value: str) -> str:
    """Get human-readable label for status tag."""
    labels = {
        "identified": "已定位/知晓",
        "evaluating": "判断中",
        "pending_fix": "待修复",
        "fixing": "修复中",
        "fixed": "已修复",
        "pending_reply": "待回复",
        "replied": "已回复",
        "user_pending": "User待回复",
        "user_responded": "User已反馈",
        "transferred_hardware": "转硬件",
    }
    return labels.get(value, value)
