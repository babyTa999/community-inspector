from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crm import crud
from crm.database import get_engine, get_session_maker, init_db
from crm.schemas import CRMEntryCreate, CRMEntryUpdate


class CRUDTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self._temp_dir.name) / "test_crm.db"
        self.engine = get_engine(f"sqlite:///{db_path}")
        init_db(self.engine)
        self.SessionLocal = get_session_maker(self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self._temp_dir.cleanup()

    def _create_entry(self, title: str = "Initial title", notes: str = "n0", created_by: str = "creator"):
        payload = CRMEntryCreate(title=title, notes=notes, attachments=[])
        return crud.create_entry(self.db, payload, created_by=created_by)

    def test_create_entry_and_get_entry_returns_persisted_record(self):
        created = self._create_entry()

        self.assertIsNotNone(created.id)
        self.assertEqual(created.title, "Initial title")
        self.assertEqual(created.version, 1)
        self.assertEqual(created.last_edited_by, "creator")
        self.assertIsNotNone(created.last_edited_at)

        fetched = crud.get_entry(self.db, created.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.title, "Initial title")

    def test_update_entry_increments_version_and_tracks_history(self):
        entry = self._create_entry()

        entry.is_being_edited = True
        entry.edited_by_session = "session-1"
        entry.edit_session_expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.db.commit()

        updated = crud.update_entry(
            self.db,
            entry.id,
            CRMEntryUpdate(
                title="Updated title",
                notes="n1",
                attachments=["a.png"],
                version=entry.version,
                edited_by="alice",
            ),
        )

        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.title, "Updated title")
        self.assertEqual(updated.notes, "n1")
        self.assertEqual(updated.attachments, ["a.png"])
        self.assertEqual(updated.last_edited_by, "alice")
        self.assertIsNotNone(updated.last_edited_at)
        self.assertFalse(updated.is_being_edited)
        self.assertIsNone(updated.edited_by_session)
        self.assertIsNone(updated.edit_session_expires)

        history = crud.get_entry_history(self.db, entry.id, limit=20)
        history_fields = {item.field_name for item in history}
        self.assertIn("title", history_fields)
        self.assertIn("notes", history_fields)
        self.assertNotIn("attachments", history_fields)

    def test_update_entry_with_stale_version_raises_conflict(self):
        entry = self._create_entry()

        stale_version = entry.version
        crud.update_entry(
            self.db,
            entry.id,
            CRMEntryUpdate(title="Server-side change", version=stale_version, edited_by="alice"),
        )

        with self.assertRaises(crud.ConflictError) as raised:
            crud.update_entry(
                self.db,
                entry.id,
                CRMEntryUpdate(title="Stale client change", version=stale_version, edited_by="bob"),
            )

        error = raised.exception
        self.assertEqual(error.current_version, 2)
        self.assertEqual(error.your_version, 1)
        self.assertEqual(error.current_entry.id, entry.id)

        current = crud.get_entry(self.db, entry.id)
        self.assertEqual(current.title, "Server-side change")

    def test_delete_entry_returns_true_then_false(self):
        entry = self._create_entry()

        self.assertTrue(crud.delete_entry(self.db, entry.id))
        self.assertIsNone(crud.get_entry(self.db, entry.id))
        self.assertFalse(crud.delete_entry(self.db, entry.id))


if __name__ == "__main__":
    unittest.main()
