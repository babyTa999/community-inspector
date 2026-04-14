"""Tests for translate_survey module."""
import csv
import io
import tempfile
import unittest
from pathlib import Path
from typing import Callable

from translate_survey import (
    detect_text_columns,
    is_text_column,
    process_row,
    translate_text,
)


class FakeTranslator:
    """Fake translator for testing without API calls."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}
        self.call_count = 0
        self.calls: list[str] = []

    def translate(self, text: str) -> str:
        self.call_count += 1
        self.calls.append(text)
        return self.mapping.get(text, f"[ZH:{text}]")


class IsTextColumnTests(unittest.TestCase):
    def test_text_column_with_long_sentences(self) -> None:
        samples = [
            "I work in sales for digital media business.",
            "My interests are in anime and manga.",
            "This is a longer description with multiple words.",
        ]
        self.assertTrue(is_text_column("background", samples))

    def test_numeric_id_column(self) -> None:
        samples = ["29wulq95a5s8mkz0", "2xzmfthdkxkysxjg", "yx50ci440qhhictx"]
        self.assertFalse(is_text_column("id", samples))

    def test_email_column(self) -> None:
        samples = ["test@example.com", "user@domain.org", "name@company.net"]
        self.assertFalse(is_text_column("email", samples))

    def test_date_column(self) -> None:
        samples = ["2026-04-02 04:05:42", "2026-04-01 15:40:49"]
        self.assertFalse(is_text_column("date", samples))

    def test_checkbox_options_column(self) -> None:
        samples = ["Media servers", "Home automation", "", "Docker / self-hosted services"]
        self.assertFalse(is_text_column("options", samples))

    def test_short_single_word_column(self) -> None:
        samples = ["yes", "no", "yes", ""]
        self.assertFalse(is_text_column("response", samples))


class TranslateTextTests(unittest.TestCase):
    def test_empty_string_preserved(self) -> None:
        fake = FakeTranslator()
        result = translate_text("", fake.translate)
        self.assertEqual(result, "")
        self.assertEqual(fake.call_count, 0)

    def test_whitespace_only_preserved(self) -> None:
        fake = FakeTranslator()
        result = translate_text("   \n\t  ", fake.translate)
        self.assertEqual(result, "   \n\t  ")
        self.assertEqual(fake.call_count, 0)

    def test_content_gets_translated(self) -> None:
        fake = FakeTranslator({"Hello": "你好"})
        result = translate_text("Hello", fake.translate)
        self.assertEqual(result, "你好")
        self.assertEqual(fake.call_count, 1)


class ProcessRowTests(unittest.TestCase):
    def test_preserves_non_text_columns(self) -> None:
        fake = FakeTranslator()
        row = {
            "id": "abc123",
            "email": "test@example.com",
            "date": "2026-04-02",
            "name": "John Doe",
        }
        text_cols = {"name"}
        result = process_row(row, text_cols, fake.translate)

        self.assertEqual(result["id"], "abc123")
        self.assertEqual(result["email"], "test@example.com")
        self.assertEqual(result["date"], "2026-04-02")
        self.assertEqual(fake.call_count, 1)

    def test_translates_text_columns(self) -> None:
        fake = FakeTranslator({"Hello world": "你好世界"})
        row = {
            "id": "1",
            "description": "Hello world",
            "title": "Test",
        }
        text_cols = {"description", "title"}
        result = process_row(row, text_cols, fake.translate)

        self.assertEqual(result["description"], "[ZH:Hello world]")
        self.assertEqual(result["title"], "[ZH:Test]")
        self.assertEqual(result["id"], "1")


class DetectTextColumnsTests(unittest.TestCase):
    def test_detects_description_columns(self) -> None:
        rows = [
            {
                "id": "1",
                "description": "I work in tech and love building things.",
                "email": "test@example.com",
            },
            {
                "id": "2",
                "description": "My background is in sales and marketing.",
                "email": "user@example.com",
            },
        ]
        result = detect_text_columns(rows)
        self.assertIn("description", result)
        self.assertNotIn("id", result)
        self.assertNotIn("email", result)

    def test_respects_exclude_pattern(self) -> None:
        rows = [
            {"id": "1", "user_id": "u1", "content": "Some long text here"},
            {"id": "2", "user_id": "u2", "content": "Another long text"},
        ]
        result = detect_text_columns(rows, exclude_pattern=r"(?i)(^id$|_id$)")
        self.assertIn("content", result)
        self.assertNotIn("id", result)
        self.assertNotIn("user_id", result)


class IntegrationTests(unittest.TestCase):
    def test_csv_roundtrip(self) -> None:
        fake = FakeTranslator({
            "Hello": "你好",
            "World": "世界",
        })

        csv_content = """id,description,email
1,Hello,test@example.com
2,World,user@example.com
"""
        input_file = io.StringIO(csv_content)
        output_file = io.StringIO()

        reader = csv.DictReader(input_file)
        rows = list(reader)
        text_cols = detect_text_columns(rows)

        writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in rows:
            translated = process_row(row, text_cols, fake.translate)
            writer.writerow(translated)

        output_file.seek(0)
        result = output_file.read()

        self.assertIn("你好", result)
        self.assertIn("世界", result)
        self.assertIn("test@example.com", result)
        self.assertIn("user@example.com", result)

    def test_handles_unicode_and_special_chars(self) -> None:
        fake = FakeTranslator()
        row = {
            "id": "1",
            "content": "Hello 🎉 World! Special chars: café, naïve",
        }
        text_cols = {"content"}
        result = process_row(row, text_cols, fake.translate)

        self.assertIn("🎉", result["content"])
        self.assertIn("café", result["content"])


if __name__ == "__main__":
    unittest.main()
