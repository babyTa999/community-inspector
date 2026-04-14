from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


DISCORD_MESSAGE_LIMIT = 2000
SAFE_CHUNK_LIMIT = 1900
SECTION_ORDER = ("Problem", "Signal", "UGC")
SECTION_TITLES = {
    "Problem": "🔴 Problem（紧急问题）",
    "Signal": "🔵 Signal（趋势 & 洞察）",
    "UGC": "🟢 UGC（用户创作内容）",
}


@dataclass(slots=True)
class DigestItem:
    message_id: str
    channel_name: str
    author_name: str
    original_text: str
    translated_zh: str
    category: str
    has_reply: bool | None = None
    solved: bool | None = None
    known_status: str = "n/a"
    known_source: str = ""
    message_url: str = ""
    created_at_text: str = ""
    has_attachments: bool = False
    source_label: str = "Discord"
    thread_title: str = ""
    is_dcmirror: bool = False


@dataclass(slots=True)
class DigestChunk:
    text: str
    message_ids: tuple[str, ...]


def render_digest(items: Sequence[DigestItem], run_time: datetime) -> str:
    grouped = _group_items(items)
    lines: list[str] = _render_digest_header(items, run_time)

    for category in SECTION_ORDER:
        category_items = grouped[category]
        if not category_items:
            continue

        lines.append(SECTION_TITLES[category])
        for item in category_items:
            lines.extend(_render_item(item))

    lines.append("==========================================")
    return "\n".join(lines)


def render_digest_chunks(
    items: Sequence[DigestItem],
    run_time: datetime,
    limit: int = SAFE_CHUNK_LIMIT,
) -> list[DigestChunk]:
    if not items:
        return []

    header_lines = _render_digest_header(items, run_time)
    continuation_header = [f"========== [{run_time:%H:%M} 社区巡检播报 - 续] =========="]
    blocks = _render_digest_blocks(items)
    chunks: list[DigestChunk] = []
    current_lines = list(header_lines)
    current_message_ids: list[str] = []

    for block_lines, message_id in blocks:
        candidate_lines = [*current_lines, *block_lines]
        if _joined_length(candidate_lines) <= limit:
            current_lines = candidate_lines
            current_message_ids.append(message_id)
            continue

        if current_message_ids:
            chunks.append(DigestChunk(text="\n".join(current_lines), message_ids=tuple(current_message_ids)))
            current_lines = list(continuation_header)
            current_message_ids = []
            candidate_lines = [*current_lines, *block_lines]
            if _joined_length(candidate_lines) <= limit:
                current_lines = candidate_lines
                current_message_ids.append(message_id)
                continue

        block_chunks = split_for_discord("\n".join(block_lines), limit=max(1, limit - _joined_length(current_lines) - 1))
        for index, block_chunk in enumerate(block_chunks):
            chunk_lines = [*current_lines, block_chunk]
            is_last_chunk = index == len(block_chunks) - 1
            chunk_message_ids = (message_id,) if is_last_chunk else ()
            chunks.append(DigestChunk(text="\n".join(chunk_lines), message_ids=chunk_message_ids))
            current_lines = list(continuation_header)

    if current_message_ids:
        chunks.append(DigestChunk(text="\n".join(current_lines), message_ids=tuple(current_message_ids)))

    return chunks


def split_for_discord(text: str, limit: int = SAFE_CHUNK_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in text.splitlines():
        line_length = len(line) + 1
        if current_lines and current_length + line_length > limit:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_length = 0

        if line_length > limit:
            chunks.extend(_split_long_line(line, limit))
            continue

        current_lines.append(line)
        current_length += line_length

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def _render_item(item: DigestItem) -> list[str]:
    # dcmirror simplified format: only content + knowledge base
    if item.is_dcmirror:
        lines = [
            f"• {_normalize_text(item.translated_zh)}",
        ]
        if item.category == "Problem":
            knowledge_text = _render_known_status(item.known_status, item.known_source)
            lines.append(f"知识库：{knowledge_text}")
        return lines

    # Normal format
    source_prefix = f"[{_normalize_text(item.source_label)}] " if item.source_label else ""
    header = f"• {source_prefix}#{item.channel_name} | {item.author_name}"
    if item.created_at_text:
        header = f"{header} | {item.created_at_text}"

    lines = [
        header,
    ]
    lines.append(f"中文：{_normalize_text(item.translated_zh)}")

    if item.message_url:
        lines.append(f"链接：{item.message_url}")
    if item.has_attachments:
        lines.append("附件：有")

    if item.category == "Problem":
        if item.has_reply is not None:
            reply_text = "✅ 有" if item.has_reply else "❌ 无"
            solved_text = "✅ 是" if item.solved else "❌ 否"
            lines.append(f"是否有人回复他：{reply_text}　　已解决：{solved_text}")
        knowledge_text = _render_known_status(item.known_status, item.known_source)
        lines.append(f"知识库：{knowledge_text}")

    return lines


def _group_items(items: Sequence[DigestItem]) -> dict[str, list[DigestItem]]:
    grouped = {category: [] for category in SECTION_ORDER}
    for item in items:
        if item.category in grouped:
            grouped[item.category].append(item)
    return grouped


def _render_digest_header(items: Sequence[DigestItem], run_time: datetime) -> list[str]:
    counts = Counter(item.category for item in items if item.category in SECTION_ORDER)
    return [
        f"========== [{run_time:%H:%M} 社区巡检播报] ==========",
        f"总计：{len(items)} | Problem：{counts['Problem']} | Signal：{counts['Signal']} | UGC：{counts['UGC']}",
    ]


def _render_digest_blocks(items: Sequence[DigestItem]) -> list[tuple[list[str], str]]:
    grouped = _group_items(items)
    blocks: list[tuple[list[str], str]] = []
    for category in SECTION_ORDER:
        category_items = grouped[category]
        if not category_items:
            continue
        for item in category_items:
            lines = [SECTION_TITLES[category], *_render_item(item)]
            blocks.append((lines, item.message_id))
    return blocks


def _joined_length(lines: Sequence[str]) -> int:
    if not lines:
        return 0
    return sum(len(line) for line in lines) + max(0, len(lines) - 1)


def _render_known_status(status: str, source: str = "") -> str:
    normalized = status.strip().lower()
    if normalized == "known":
        return f"📘 已知晓 {source}".strip()
    if normalized == "unknown":
        return "🆕 未知晓"
    return "-"


def _normalize_text(value: str) -> str:
    compact = " ".join((value or "").split())
    return compact or "-"


def _split_long_line(line: str, limit: int) -> Iterable[str]:
    start = 0
    while start < len(line):
        end = min(start + limit, len(line))
        yield line[start:end]
        start = end
