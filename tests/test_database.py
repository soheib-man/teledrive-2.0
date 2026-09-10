"""Tests for normalized SQLite schema, migrations, and repository operations."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from teledrive.constants import Status
from teledrive.database import Database
from teledrive.models import DirectoryRecord, FileRecord, ChunkRecord


class TestDatabase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_schema_created_with_foreign_keys(self):
        cur = self.db.conn.cursor()
        cur.execute("PRAGMA foreign_keys;")
        self.assertEqual(cur.fetchone()[0], 1)

        # Verify tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        self.assertIn("directories", tables)
        self.assertIn("files", tables)
        self.assertIn("chunks", tables)
        self.assertIn("schema_version", tables)

    def test_file_and_chunk_cascade_delete(self):
        f = FileRecord(
            id="f1",
            name="demo.bin",
            original_path="/tmp/demo.bin",
            relative_path="demo.bin",
            size=2048,
            sha256="abc123sha",
        )
        self.db.insert_file(f)

        c1 = ChunkRecord(file_id="f1", chunk_index=0, size=1024, sha256="h1", telegram_message_id=101)
        c2 = ChunkRecord(file_id="f1", chunk_index=1, size=1024, sha256="h2", telegram_message_id=102)
        self.db.insert_chunk(c1)
        self.db.insert_chunk(c2)

        chunks = self.db.get_chunks_for_file("f1")
        self.assertEqual(len(chunks), 2)

        # Delete file permanently
        msg_ids = self.db.delete_file_permanently("f1")
        self.assertEqual(sorted(msg_ids), [101, 102])

        # Verify chunks table was cascade deleted
        cur = self.db.conn.cursor()
        cur.execute("SELECT * FROM chunks WHERE file_id = 'f1';")
        self.assertEqual(len(cur.fetchall()), 0)

    def test_legacy_v1_migration(self):
        legacy_db_path = Path(self.temp_dir.name) / "legacy_v1.db"
        # Create a raw v1 sqlite table without schema_version
        conn = sqlite3.connect(str(legacy_db_path))
        conn.execute(
            "CREATE TABLE file (id text PRIMARY KEY, file_name text, file_path text, file_size integer, chunks text, type text, uploaded text);"
        )
        conn.execute(
            "INSERT INTO file VALUES ('old_id_1', 'legacy.txt', '/tmp/legacy.txt', 500, '[\"chunk1\", \"chunk2\"]', 'file', '2026-09-09');"
        )
        conn.commit()
        conn.close()

        # Opening with modern Database should trigger automatic migration
        modern_db = Database(legacy_db_path)
        rec = modern_db.get_file_by_id("old_id_1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.name, "legacy.txt")
        self.assertEqual(rec.size, 500)

        chunks = modern_db.get_chunks_for_file("old_id_1")
        self.assertEqual(len(chunks), 2)

        # Verify backup was created
        backup_file = legacy_db_path.with_name(f"{legacy_db_path.name}.v1.bak")
        self.assertTrue(backup_file.exists())
        modern_db.close()


if __name__ == "__main__":
    unittest.main()
