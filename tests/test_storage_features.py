"""Tests for storage-system features: rename, move, soft-delete, restore, import/export."""

import json
import tempfile
import unittest
from pathlib import Path

from teledrive.config import Config
from teledrive.database import Database
from teledrive.exceptions import (
    AlreadyTrashedError,
    AmbiguousQueryError,
    ItemNotFoundError,
    NotTrashedError,
)
from teledrive.models import DirectoryRecord, FileRecord, ChunkRecord
from teledrive.services import StorageService


class TestStorageFeatures(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.db_path = self.dir_path / "test_storage.db"
        self.config = Config(
            db_file=self.db_path,
            temp_dir=self.dir_path / "temp",
        )
        self.service = StorageService(self.config)

        # Seed initial data
        self.d1 = DirectoryRecord(id="dir1", name="Documents", original_path="/docs")
        self.f1 = FileRecord(
            id="file1",
            name="notes.txt",
            original_path="/docs/notes.txt",
            relative_path="notes.txt",
            size=120,
            sha256="fake_sha_notes",
            directory_id="dir1",
        )
        self.f2 = FileRecord(
            id="file2",
            name="photo.png",
            original_path="/photos/photo.png",
            relative_path="photo.png",
            size=5000,
            sha256="fake_sha_photo",
        )
        self.service.db.insert_directory(self.d1)
        self.service.db.insert_file(self.f1)
        self.service.db.insert_file(self.f2)

        c1 = ChunkRecord(file_id="file1", chunk_index=0, size=120, sha256="csha", telegram_message_id=999)
        self.service.db.insert_chunk(c1)

    def tearDown(self):
        self.service.close()
        self.temp_dir.cleanup()

    def test_rename_file_and_directory(self):
        self.service.rename("file1", "updated_notes.txt")
        rec = self.service.db.get_file_by_id("file1")
        self.assertEqual(rec.name, "updated_notes.txt")

        self.service.rename("dir1", "WorkDocuments")
        d_rec = self.service.db.get_directory_by_id("dir1")
        self.assertEqual(d_rec.name, "WorkDocuments")

    def test_move_file_between_directories(self):
        d2 = DirectoryRecord(id="dir2", name="Archive", original_path="/archive")
        self.service.db.insert_directory(d2)

        self.service.move("file1", "dir2")
        rec = self.service.db.get_file_by_id("file1")
        self.assertEqual(rec.directory_id, "dir2")

    def test_trash_and_restore_file(self):
        self.service.trash("file1")
        rec = self.service.db.get_file_by_id("file1")
        self.assertIsNotNone(rec.trashed_at)
        self.assertEqual(rec.status, "trashed")

        # In standard listing, trashed files should be omitted
        active_files = self.service.db.list_files(include_trashed=False)
        self.assertNotIn("file1", [f.id for f in active_files])

        # Double trashing must raise AlreadyTrashedError
        with self.assertRaises(AlreadyTrashedError):
            self.service.trash("file1")

        # Restore
        self.service.restore("file1")
        rec_restored = self.service.db.get_file_by_id("file1")
        self.assertIsNone(rec_restored.trashed_at)
        self.assertEqual(rec_restored.status, "completed")

        # Restoring non-trashed item must raise NotTrashedError
        with self.assertRaises(NotTrashedError):
            self.service.restore("file1")

    def test_ambiguous_query_error(self):
        # Insert two files with similar names
        dup1 = FileRecord("d1", "report_2026.pdf", "/p", "report_2026.pdf", 10, "s1")
        dup2 = FileRecord("d2", "report_2025.pdf", "/p", "report_2025.pdf", 10, "s2")
        self.service.db.insert_file(dup1)
        self.service.db.insert_file(dup2)

        with self.assertRaises(AmbiguousQueryError):
            self.service.resolve_single_item("report")

    def test_export_and_import_metadata(self):
        export_file = self.dir_path / "backup.json"
        self.service.export_metadata(output_path=export_file)
        self.assertTrue(export_file.exists())

        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("files", data)
        self.assertIn("directories", data)

        # Create fresh DB and import
        new_db_path = self.dir_path / "imported.db"
        new_service = StorageService(Config(db_file=new_db_path))
        imported_count = new_service.import_metadata(export_file)
        self.assertTrue(imported_count > 0)

        imported_file = new_service.db.get_file_by_id("file1")
        self.assertIsNotNone(imported_file)
        self.assertEqual(imported_file.name, "notes.txt")
        new_service.close()


if __name__ == "__main__":
    unittest.main()
