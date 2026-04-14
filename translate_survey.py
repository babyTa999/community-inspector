from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from pathlib import Path
from typing import Any

import anthropic

DEFAULT_MODEL = os.getenv("MODEL_NAME", "claude-sonnet-4-6")
MAX_OUTPUT_TOKENS = 4096
DEFAULT_CONCURRENCY = 5
DEFAULT_MAX_BATCH_CHARS = 12000

EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.|[A-Z0-9.-]+\.[A-Z]{2,}/)", re.IGNORECASE)
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$")
IDISH_RE = re.compile(r"^[A-Z0-9_-]{10,}$", re.IGNORECASE)
HEADER_SKIP_VALUE_RE = re.compile(r"^(#|response type|start date \(utc\)|stage date \(utc\)|submit date \(utc\)|network id|tags)$", re.IGNORECASE)
HEADER_SKIP_TRANSLATE_LINK_RE = re.compile(r"(email|profile|channel links)", re.IGNORECASE)
HEADER_SKIP_TRANSLATE_HEADER_RE = re.compile(r"^#$")

HEADER_TRANSLATION_SYSTEM_PROMPT = """
You translate CSV column headers into natural Simplified Chinese.
Return ONLY a JSON object mapping each id to its translated header text.
Do not omit any ids. No markdown. No explanations.
""".strip()

CELL_TRANSLATION_SYSTEM_PROMPT = """
You translate survey CSV cell values into natural, fluent Simplified Chinese.
Return ONLY a JSON object mapping each id to its translated text.
Do not omit any ids. No markdown. No explanations.
Rules:
- Preserve meaning and tone.
- Preserve emails, URLs, usernames, product names, model names, and numbers when appropriate.
- Keep line breaks if present.
- Use the question only as context; translate only the answer text.
""".strip()


def extract_json_object(payload: str) -> dict[str, Any]:
    text = payload.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {payload[:200]}")

    depth = 0
    in_string = False
    escape_next = False
    end = -1
    for index, char in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break

    if end == -1:
        raise ValueError("Incomplete JSON object in model response")

    return json.loads(text[start : end + 1])


def normalize_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def should_skip_value(header: str, value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return True
    if HEADER_SKIP_VALUE_RE.search(header):
        return True
    if HEADER_SKIP_TRANSLATE_LINK_RE.search(header):
        return True
    if EMAIL_RE.fullmatch(stripped):
        return True
    if DATETIME_RE.fullmatch(stripped):
        return True
    if URL_RE.search(stripped):
        return True
    if IDISH_RE.fullmatch(stripped) and " " not in stripped:
        return True
    return False


async def translate_batch(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    system_prompt: str,
    items: list[dict[str, str]],
) -> dict[str, str]:
    response = await client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": json.dumps(items, ensure_ascii=False),
            }
        ],
    )

    text_parts: list[str] = []
    for block in response.content:
        block_text = getattr(block, "text", None)
        if block_text:
            text_parts.append(str(block_text))
    payload = "\n".join(text_parts).strip()
    parsed = extract_json_object(payload)
    result: dict[str, str] = {}
    for item in items:
        item_id = item["id"]
        if item_id not in parsed:
            raise ValueError(f"Missing translated id in response: {item_id}")
        result[item_id] = str(parsed[item_id])
    return result


async def translate_items(
    client: anthropic.AsyncAnthropic,
    *,
    model: str,
    system_prompt: str,
    items: list[dict[str, str]],
    concurrency: int,
    max_batch_chars: int,
) -> dict[str, str]:
    if not items:
        return {}

    batches: list[list[dict[str, str]]] = []
    current_batch: list[dict[str, str]] = []
    current_chars = 0

    for item in items:
        size = len(json.dumps(item, ensure_ascii=False))
        if current_batch and current_chars + size > max_batch_chars:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0
        current_batch.append(item)
        current_chars += size
    if current_batch:
        batches.append(current_batch)

    print(f"Translating {len(items)} items in {len(batches)} batches...")

    semaphore = asyncio.Semaphore(concurrency)
    results: dict[str, str] = {}
    completed = 0

    async def run_batch(batch: list[dict[str, str]]) -> None:
        nonlocal completed
        async with semaphore:
            translated = await translate_batch(
                client,
                model=model,
                system_prompt=system_prompt,
                items=batch,
            )
            results.update(translated)
            completed += 1
            print(f"Completed batch {completed}/{len(batches)}")

    await asyncio.gather(*(run_batch(batch) for batch in batches))
    return results


async def run_translation(
    input_path: Path,
    output_path: Path,
    *,
    model: str,
    concurrency: int,
    max_batch_chars: int,
) -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")

    csv.field_size_limit(10**7)

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    print(f"Loaded {len(rows)} rows and {len(fieldnames)} columns")

    client = anthropic.AsyncAnthropic(
        api_key=api_key,
        base_url=os.getenv("ANTHROPIC_BASE_URL"),
    )

    header_items = [
        {"id": f"h{index}", "text": field}
        for index, field in enumerate(fieldnames)
        if field and not HEADER_SKIP_TRANSLATE_HEADER_RE.search(field)
    ]
    translated_headers = await translate_items(
        client,
        model=model,
        system_prompt=HEADER_TRANSLATION_SYSTEM_PROMPT,
        items=header_items,
        concurrency=min(concurrency, 3),
        max_batch_chars=4000,
    )
    output_headers = [translated_headers.get(f"h{index}", field) for index, field in enumerate(fieldnames)]

    cell_items: list[dict[str, str]] = []
    seen_cache: dict[str, str] = {}

    for row_index, row in enumerate(rows):
        for field in fieldnames:
            value = row.get(field, "")
            if should_skip_value(field, value):
                continue
            normalized = normalize_text(value)
            if normalized in seen_cache:
                continue
            item_id = f"v{len(seen_cache)}"
            seen_cache[normalized] = item_id
            cell_items.append(
                {
                    "id": item_id,
                    "question": field,
                    "text": normalized,
                }
            )

    print(f"Need to translate {len(cell_items)} unique cell values")
    translated_values = await translate_items(
        client,
        model=model,
        system_prompt=CELL_TRANSLATION_SYSTEM_PROMPT,
        items=cell_items,
        concurrency=concurrency,
        max_batch_chars=max_batch_chars,
    )

    translated_rows: list[dict[str, str]] = []
    translated_cell_count = 0
    for row in rows:
        translated_row: dict[str, str] = {}
        for field in fieldnames:
            value = row.get(field, "")
            normalized = normalize_text(value)
            item_id = seen_cache.get(normalized)
            if item_id and item_id in translated_values:
                translated_row[field] = translated_values[item_id]
                translated_cell_count += 1
            else:
                translated_row[field] = value
        translated_rows.append(translated_row)

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(output_headers)
        for row in translated_rows:
            writer.writerow([row.get(field, "") for field in fieldnames])

    print(f"Wrote translated CSV to: {output_path}")
    print(f"Translated {translated_cell_count} cells across {len(rows)} rows")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate survey CSV into Simplified Chinese")
    parser.add_argument("input_csv", help="Path to source CSV")
    parser.add_argument("--output", help="Path to output CSV")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model name")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent translation batches")
    parser.add_argument("--max-batch-chars", type=int, default=DEFAULT_MAX_BATCH_CHARS, help="Approximate JSON chars per batch")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_csv)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path.with_suffix(".zh.csv")
    asyncio.run(
        run_translation(
            input_path,
            output_path,
            model=args.model,
            concurrency=max(1, args.concurrency),
            max_batch_chars=max(1000, args.max_batch_chars),
        )
    )


if __name__ == "__main__":
    main()
