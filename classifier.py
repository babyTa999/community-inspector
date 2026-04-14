from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

import anthropic

CATEGORY_VALUES = {"Problem", "Signal", "UGC", "Ignore"}
KNOWN_STATUS_VALUES = {"known", "unknown", "n/a"}
KNOWN_SOURCE_VALUES = {
    "https://docs.example.com/product/",
    "https://wiki.example.com/en/home",
    "https://community.example.com",
    "https://github.com/example-org/ProductA/issues",
    "https://github.com/example-org/ProductB/issues",
}
DEFAULT_MODEL_NAME = "claude-opus-4-6"
MAX_OUTPUT_TOKENS = 600
KNOWLEDGE_SOURCES = (
    "https://docs.example.com/product/",
    "https://wiki.example.com/en/home",
    "https://community.example.com",
    "https://github.com/example-org/ProductA/issues",
    "https://github.com/example-org/ProductB/issues",
)
SYSTEM_PROMPT = """
You classify one community source item from Discord or forum for an internal digest.

IMPORTANT: Return ONLY a JSON object. No explanations, no markdown, no code blocks. Just raw JSON.

Tasks:
1. Classify the source item into exactly one of: Problem, Signal, UGC, Ignore.
2. Translate the source item into concise Simplified Chinese.
3. Decide whether the source author later received any reply from other non-bot users in the provided thread/topic context.
4. If category is Problem, decide whether later replies indicate the issue looks solved.
5. If category is Problem, decide whether the issue is already known from your prior knowledge of these sources:
   - https://docs.example.com/product/
   - https://wiki.example.com/en/home
   - https://community.example.com
   - https://github.com/example-org/ProductA/issues
   - https://github.com/example-org/ProductB/issues
   Use prior knowledge only. Do not assume live browsing or live retrieval.

Rules:
- Ignore bot/system noise, pure greetings, emoji-only chatter, and content with no operational value.
- Problem = user is blocked, confused, reporting bug, asking troubleshooting or support help.
- Signal = meaningful product feedback, trend, request, comparison, insight, sentiment worth tracking.
- UGC = user sharing creations, setups, wins, showcases, tutorials, community contribution.
- Ignore = anything else.
- Classify based on the original source content and provided thread/topic context, not on recency implied by forum list ordering.
- translated_zh must be plain Chinese text, no double quotes, no newlines, no markdown.
- has_reply must reflect whether later replies from other non-bot users exist in the provided context.
- solved should be true only when later replies clearly suggest the issue is resolved. If no clear evidence, false.
- If known_status is known, set known_source to the single most relevant URL from the knowledge sources list above. Otherwise set known_source to null.
- rationale must be short.

Return exactly this JSON schema (no other text):
{"category":"Problem | Signal | UGC | Ignore","translated_zh":"string","has_reply":true,"solved":false,"known_status":"known | unknown | n/a","known_source":"url or null","rationale":"short string"}
""".strip()


@dataclass(slots=True)
class FollowupMessage:
    author_name: str
    content: str


@dataclass(slots=True)
class ClassificationResult:
    category: str
    translated_zh: str
    has_reply: bool
    solved: bool
    known_status: str
    known_source: str = ""
    rationale: str = ""


class MessageClassifier:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
    ) -> None:
        resolved_api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required")

        self.model_name = model_name or os.getenv("MODEL_NAME") or DEFAULT_MODEL_NAME
        self.client = anthropic.AsyncAnthropic(
            api_key=resolved_api_key,
            base_url=base_url or os.getenv("ANTHROPIC_BASE_URL"),
        )

    async def classify_message(
        self,
        *,
        source_type: str,
        source_location: str,
        thread_title: str,
        channel_name: str,
        author_name: str,
        content: str,
        followups: Sequence[FollowupMessage],
    ) -> ClassificationResult:
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            try:
                # Add JSON enforcement to user content on retry
                user_content = self._build_user_prompt(
                    source_type=source_type,
                    source_location=source_location,
                    thread_title=thread_title,
                    channel_name=channel_name,
                    author_name=author_name,
                    content=content,
                    followups=followups,
                )
                if attempt > 0:
                    user_content += "\n\nCRITICAL: Return ONLY raw JSON. No explanations, no markdown, no thinking. Just JSON starting with { and ending with }."

                response = await self.client.messages.create(
                    model=self.model_name,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_content}],
                )
                payload = self._extract_json_text(response.content)
                return self._parse_result(payload, followups=followups)
            except ValueError as e:
                last_error = e
                if attempt < max_retries - 1:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Classification attempt %s failed, retrying: %s", attempt + 1, e
                    )
                    continue
                raise last_error

    def _build_user_prompt(
        self,
        *,
        source_type: str,
        source_location: str,
        thread_title: str,
        channel_name: str,
        author_name: str,
        content: str,
        followups: Sequence[FollowupMessage],
    ) -> str:
        followup_lines = [
            f"- {item.author_name}: {self._clean_text(item.content)}"
            for item in followups
            if self._clean_text(item.content) != "-"
        ]
        followup_block = "\n".join(followup_lines) if followup_lines else "- none"
        knowledge_block = "\n".join(f"- {source}" for source in KNOWLEDGE_SOURCES)
        title_line = f"Thread title: {self._clean_text(thread_title)}\n" if self._clean_text(thread_title) != "-" else ""
        return (
            f"Source type: {self._clean_text(source_type)}\n"
            f"Source location: {self._clean_text(source_location or channel_name)}\n"
            f"Channel fallback: #{self._clean_text(channel_name)}\n"
            f"Source author: {author_name}\n"
            f"{title_line}"
            f"Source message: {self._clean_text(content)}\n\n"
            f"Later replies from other non-bot users in the same thread/topic context:\n{followup_block}\n\n"
            f"Knowledge sources for prior-knowledge judgment:\n{knowledge_block}\n"
        )

    def _extract_json_text(self, blocks: Sequence[Any]) -> str:
        # Handle empty or None blocks
        if not blocks:
            raise ValueError("Anthropic response blocks are empty")

        text_parts = []
        thinking_parts = []

        for block in blocks:
            block_type = getattr(block, "type", None)
            # Get text content - different block types store content in different attributes
            block_text = None
            if hasattr(block, "text"):
                block_text = block.text
            elif hasattr(block, "thinking"):
                block_text = block.thinking
            elif hasattr(block, "data"):
                block_text = block.data

            if block_text:
                if block_type == "text":
                    text_parts.append(str(block_text))
                elif block_type in ("thinking", "redacted_thinking"):
                    thinking_parts.append(str(block_text))
                else:
                    text_parts.append(str(block_text))

        # Prefer text blocks
        if text_parts:
            combined = "\n".join(text_parts).strip()
            # Try to find JSON in text
            json_match = re.search(r'\{[\s\S]*?"category"[\s\S]*?\}', combined)
            if json_match:
                return json_match.group(0)
            return combined

        # Fallback: try thinking blocks - look for JSON pattern
        if thinking_parts:
            combined = "\n".join(thinking_parts).strip()
            # Look for JSON object with our expected fields
            json_match = re.search(r'\{[\s\S]*?"category"[\s\S]*?"translated_zh"[\s\S]*?\}', combined)
            if json_match:
                return json_match.group(0)
            # Fallback: any JSON-like object
            start = combined.find("{")
            end = combined.rfind("}")
            if start != -1 and end != -1 and end > start:
                return combined[start:end + 1]
            return combined

        block_types = [getattr(b, "type", type(b).__name__) for b in blocks]
        raise ValueError(f"Anthropic response did not contain usable blocks. Got types: {block_types}")

    def _parse_result(self, payload: str, *, followups: Sequence[FollowupMessage]) -> ClassificationResult:
        coerced = self._coerce_json_object(payload)
        try:
            data = json.loads(coerced)
        except json.JSONDecodeError:
            data = self._extract_fields_regex(coerced)

        category = str(data.get("category", "Ignore")).strip()
        if category not in CATEGORY_VALUES:
            category = "Ignore"

        translated_zh = self._clean_text(str(data.get("translated_zh", "")))
        has_reply = self._coerce_bool(data.get("has_reply"), default=bool(followups))
        solved = self._coerce_bool(data.get("solved"), default=False)
        known_status = str(data.get("known_status", "n/a")).strip().lower()
        if known_status not in KNOWN_STATUS_VALUES:
            known_status = "n/a"
        if category != "Problem":
            solved = False
            known_status = "n/a"

        raw_source = str(data.get("known_source") or "").strip()
        known_source = raw_source if raw_source in KNOWN_SOURCE_VALUES else ""

        rationale = self._clean_text(str(data.get("rationale", "")))
        return ClassificationResult(
            category=category,
            translated_zh=translated_zh,
            has_reply=has_reply,
            solved=solved,
            known_status=known_status,
            known_source=known_source,
            rationale=rationale,
        )

    def _extract_fields_regex(self, payload: str) -> dict[str, Any]:
        """Fallback: extract known fields from malformed JSON using regex."""
        result: dict[str, Any] = {}
        for field in ("category", "translated_zh", "known_status", "rationale", "known_source"):
            m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', payload)
            if m:
                result[field] = m.group(1)
        for field in ("has_reply", "solved"):
            m = re.search(rf'"{field}"\s*:\s*(true|false)', payload, re.IGNORECASE)
            if m:
                result[field] = m.group(1).lower() == "true"
        return result

    def _coerce_json_object(self, payload: str) -> str:
        """Extract a complete JSON object from payload by counting braces."""
        stripped = payload.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`")
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()

        # Find the first opening brace
        start = stripped.find("{")
        if start == -1:
            raise ValueError(f"Model response does not contain JSON object: {payload[:200]}")

        # Count braces to find the matching closing brace
        # Handle nested objects and strings with escaped quotes
        depth = 0
        in_string = False
        escape_next = False
        end = -1

        for i, char in enumerate(stripped[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"' and not in_string:
                in_string = True
                continue
            if char == '"' and in_string:
                in_string = False
                continue
            if not in_string:
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

        if end == -1:
            raise ValueError(f"Model response does not contain complete JSON object: {payload[:200]}")
        return stripped[start : end + 1]

    def _clean_text(self, value: str) -> str:
        compact = " ".join((value or "").split())
        return compact or "-"

    def _coerce_bool(self, value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
        return default
