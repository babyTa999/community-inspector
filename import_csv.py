"""CSV import script for Feishu CRM data."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from crm.database import get_db, get_engine, init_db
from crm.models import CRMEntry, FeatureModule, StatusTag, TypeTag
from crm.schemas import CRMEntryCreate
from crm import crud


def parse_tags(tag_value: str) -> tuple[str, str]:
    """Parse type and status tags from CSV value.

    Returns:
        Tuple of (type_tag, status_tag)
    """
    if not tag_value:
        return "S", "已定位/知晓"

    tag_value = tag_value.strip()

    # Check if this is ONLY a type indicator (e.g., "S 信号", "R 需求")
    # These should use default status
    only_type_patterns = [
        ("S", ["S 信号", "S-信号", "信号"]),
        ("R", ["R 需求", "R-需求", "需求"]),
        ("Q", ["Q 问题", "Q-问题", "问题"]),
        ("Tips", ["Tips", "技巧", "教程"]),
    ]

    for type_tag, patterns in only_type_patterns:
        for pattern in patterns:
            if tag_value == pattern or tag_value.startswith(pattern):
                return type_tag, "已定位/知晓"

    # If not a pure type indicator, check for combined or status-only
    # First check for type prefix
    type_tag = "S"
    remaining = tag_value

    if tag_value.startswith("R") or "需求" in tag_value:
        type_tag = "R"
        remaining = tag_value.replace("R", "").replace("需求", "").strip("-: ")
    elif tag_value.startswith("Q") or "问题" in tag_value:
        type_tag = "Q"
        remaining = tag_value.replace("Q", "").replace("问题", "").strip("-: ")
    elif tag_value.startswith("S") or "信号" in tag_value:
        type_tag = "S"
        remaining = tag_value.replace("S", "").replace("信号", "").strip("-: ")
    elif "Tips" in tag_value or "技巧" in tag_value:
        type_tag = "Tips"
        remaining = tag_value.replace("Tips", "").replace("技巧", "").strip("-: ")

    # If nothing remains, use default status
    if not remaining:
        return type_tag, "已定位/知晓"

    # Map remaining to valid status
    status_map = {
        "已定位/知晓": ["已定位", "知晓"],
        "待/判断/中": ["待判断", "判断中", "待/判断"],
        "待修复": ["待修复"],
        "修复中": ["修复中"],
        "已解决": ["已解决", "已修复"],
        "已回复": ["已回复"],
        "待回复": ["待回复"],
        "重要": ["重要"],
    }

    for valid_status, aliases in status_map.items():
        if any(alias in remaining for alias in aliases):
            return type_tag, valid_status

    # If no match, return as-is
    return type_tag, remaining if remaining else "已定位/知晓"


def parse_feature_module(module_value: str) -> str | None:
    """Parse feature module from CSV value."""
    if not module_value:
        return None

    module_value = module_value.strip()

    # Get valid module values from enum
    valid_modules = {m.value for m in FeatureModule}

    # Check if the value is already a valid module
    if module_value in valid_modules:
        return module_value

    # Try to match partial names
    for valid in valid_modules:
        if valid.lower() in module_value.lower() or module_value.lower() in valid.lower():
            return valid

    # Return as-is if no match (will be stored as string)
    return module_value if module_value else None


def parse_volume(volume_value: str) -> int:
    """Parse volume from CSV value."""
    if not volume_value:
        return 1

    try:
        return int(volume_value.strip())
    except (ValueError, TypeError):
        return 1


def parse_date(date_value: str) -> datetime | None:
    """Parse date from CSV value."""
    if not date_value:
        return None

    date_value = date_value.strip()

    # Try different date formats
    formats = [
        "%Y/%m/%d",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_value, fmt)
        except ValueError:
            continue

    return None


def clean_text(text: str) -> str | None:
    """Clean text value from CSV."""
    if not text:
        return None

    text = text.strip()
    if text == "-" or text == ",":
        return None

    return text if text else None


def parse_attachments(attachment_value: str) -> list[str]:
    """Parse attachments from CSV value (comma-separated filenames)."""
    if not attachment_value:
        return []

    # Split by comma and clean
    files = [f.strip() for f in attachment_value.split(",") if f.strip()]

    # Note: These are just filenames from Feishu
    # In a real import, you'd need to download/copy the actual files
    return files


def import_csv(csv_path: str, db: Session) -> tuple[int, list[str]]:
    """Import CSV file into CRM database.

    Returns:
        Tuple of (success_count, error_messages)
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        return 0, [f"CSV file not found: {csv_path}"]

    success_count = 0
    errors = []

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is 1)
            try:
                # Extract fields
                title = clean_text(row.get("问题/需求描述", ""))
                if not title:
                    errors.append(f"Row {row_num}: Empty title, skipping")
                    continue

                # Parse fields
                attachments = parse_attachments(row.get("附件", ""))
                source_url = clean_text(row.get("链接", ""))
                assignee = clean_text(row.get("相关人员", ""))

                # Parse type and status from tag column
                type_tag, status_tag = parse_tags(row.get("tag", ""))

                feature_module = parse_feature_module(row.get("描述性tag", ""))
                analysis_todo = clean_text(row.get("分析和todo", ""))
                community_todo = clean_text(row.get("社区todo", ""))
                user_name = clean_text(row.get("名字", ""))
                volume = parse_volume(row.get("声量", ""))
                notes = clean_text(row.get("备注", ""))
                parent_record = clean_text(row.get("父记录", ""))

                # Create entry
                entry_create = CRMEntryCreate(
                    title=title,
                    analysis_todo=analysis_todo,
                    community_todo=community_todo,
                    source_url=source_url,
                    assignee=assignee,
                    status_tag=status_tag,
                    feature_module=feature_module,
                    user_name=user_name,
                    volume=volume,
                    notes=notes,
                    parent_record=parent_record,
                    type_tag=type_tag,
                    attachments=attachments,
                    knowledge_base_url=None,
                    github_issue_url=None,
                    source_type=None,
                )

                # Save to database
                crud.create_entry(db, entry_create)
                success_count += 1

            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

    return success_count, errors


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Import Feishu CSV into CRM")
    parser.add_argument("csv_file", help="Path to CSV file")
    parser.add_argument("--init-db", action="store_true", help="Initialize database first")

    args = parser.parse_args()

    # Initialize database if requested
    if args.init_db:
        engine = get_engine()
        init_db(engine)
        print("Database initialized")

    # Get database session
    db = next(get_db())

    print(f"Importing from {args.csv_file}...")
    success_count, errors = import_csv(args.csv_file, db)

    print(f"\nImport complete!")
    print(f"Successfully imported: {success_count} entries")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for error in errors[:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")


if __name__ == "__main__":
    main()
