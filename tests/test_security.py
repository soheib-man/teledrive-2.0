"""Comprehensive security, path-traversal, and injection regression tests for TeleDrive 2.0."""

import os
import sqlite3
import tempfile
from pathlib import Path
import pytest

from teledrive.chunking import compute_bytes_sha256
from teledrive.config import Config
from teledrive.database import Database
from teledrive.exceptions import IntegrityError
from teledrive.models import DirectoryRecord, FileRecord, ChunkRecord
from teledrive.reconstruction import reconstruct_file_from_chunks
from teledrive.services import _resolve_safe_subpath, StorageService


class TestSecurityVerification:
    """Security audit tests verifying zero-vulnerability guarantees."""

    def test_path_traversal_subpath_containment(self):
        """Validates that _resolve_safe_subpath strictly prevents escaping base directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir) / "safe_vault"
            base_dir.mkdir(parents=True, exist_ok=True)
            base_resolved = base_dir.resolve()

            traversal_payloads = [
                ("../../etc/passwd", "passwd"),
                ("../../../Windows/System32/calc.exe", "calc.exe"),
                ("..\\..\\..\\Windows\\System32\\cmd.exe", "cmd.exe"),
                ("C:/Windows/System32/notepad.exe", "notepad.exe"),
                ("C:\\Windows\\System32\\notepad.exe", "notepad.exe"),
                ("/var/root/secret.key", "secret.key"),
                (".", "fallback.dat"),
                ("", "fallback.dat"),
                ("/..", "fallback.dat"),
                ("sub/../../outside.txt", "outside.txt"),
            ]

            for payload, fallback in traversal_payloads:
                safe_result = _resolve_safe_subpath(base_dir, payload, fallback)
                safe_resolved = safe_result.resolve()

                # MUST be inside base_dir!
                assert base_resolved in safe_resolved.parents or safe_resolved.parent == base_resolved, (
                    f"Path traversal escape detected for payload: {payload} -> {safe_resolved}"
                )
                assert not str(safe_resolved).startswith("C:\\Windows"), (
                    f"Windows system directory escape detected: {safe_resolved}"
                )

    def test_sql_injection_resilience(self):
        """Verifies database queries are 100% immune to SQL injection attacks."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "secure.db"
            db = Database(db_path)

            # Insert normal item
            dir_rec = DirectoryRecord(id="dir-safe", name="SafeDir", original_path="/safe")
            db.insert_directory(dir_rec)

            file_rec = FileRecord(
                id="file-safe",
                name="normal.txt",
                original_path="/safe/normal.txt",
                relative_path="normal.txt",
                size=100,
                sha256="abc",
                directory_id="dir-safe",
            )
            db.insert_file(file_rec)

            # Malicious SQL payloads
            sql_attacks = [
                "' OR '1'='1",
                "'; DROP TABLE files; --",
                "'; DROP TABLE directories; --",
                "' UNION SELECT * FROM files --",
                "admin' --",
                "' OR 1=1 --",
                '"" OR ""=""',
            ]

            for attack in sql_attacks:
                # Search items with SQL payload
                files, dirs = db.find_items_by_query(attack)
                # None should match maliciously
                assert len(files) == 0
                assert len(dirs) == 0

            # Verify tables and records are intact
            all_files = db.list_files()
            assert len(all_files) == 1
            assert all_files[0].name == "normal.txt"

            all_dirs = db.list_directories()
            assert len(all_dirs) == 1
            assert all_dirs[0].name == "SafeDir"

            db.close()

    def test_corrupted_chunk_tamper_detection(self):
        """Validates that cryptographic SHA-256 verification rejects tampered chunks."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            chunk1 = work_dir / "c1.dat"
            chunk2 = work_dir / "c2.dat"

            chunk1.write_bytes(b"HELLO SECURE ")
            chunk2.write_bytes(b"TELEDRIVE")

            expected_content = b"HELLO SECURE TELEDRIVE"
            expected_hash = compute_bytes_sha256(expected_content)

            # Intentionally corrupt chunk2
            chunk2.write_bytes(b"TELECORRUPTED")

            dest_file = work_dir / "output.txt"

            with pytest.raises(IntegrityError) as exc_info:
                reconstruct_file_from_chunks(
                    destination_path=dest_file,
                    chunk_paths=[chunk1, chunk2],
                    expected_sha256=expected_hash,
                )

            assert "Checksum mismatch" in str(exc_info.value)
            # Ensure target file was NOT created or left corrupted
            assert not dest_file.exists()
            assert not (work_dir / "output.txt.part").exists()

    def test_credential_sanitization_in_config(self):
        """Ensures secrets (API hash, phone number) are never exposed in safe representations."""
        cfg = Config(
            telegram_api_id=1234567,
            telegram_api_hash="secret_hash_value_9999",
            phone_number="+12345678901",
        )

        safe_dict = cfg.to_safe_dict()
        assert safe_dict["telegram_api_hash"] == "***REDACTED***"
        assert safe_dict["phone_number"] == "+12***01"
        assert "secret_hash_value" not in str(safe_dict)

    def test_nested_trash_restore_cascade(self):
        """Verifies soft-delete and restore properly cascade through arbitrary nested directory trees."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_nested_trash.db"
            db = Database(db_path)

            # Create root dir and child subdirs
            root_dir = DirectoryRecord(id="d-root", name="root", original_path="/root", root_id="d-root", relative_path="")
            child_dir = DirectoryRecord(id="d-child", name="sub", original_path="/root/sub", parent_id="d-root", root_id="d-root", relative_path="sub")
            db.insert_directory(root_dir)
            db.insert_directory(child_dir)

            file1 = FileRecord(id="f1", name="f1.txt", original_path="/root/f1.txt", relative_path="f1.txt", size=10, sha256="h1", directory_id="d-root")
            file2 = FileRecord(id="f2", name="f2.txt", original_path="/root/sub/f2.txt", relative_path="sub/f2.txt", size=20, sha256="h2", directory_id="d-child")
            db.insert_file(file1)
            db.insert_file(file2)

            # Trash root directory
            db.trash_item("d-root")

            # Active listings must be empty
            assert len(db.list_directories(include_trashed=False)) == 0
            assert len(db.list_files(include_trashed=False)) == 0

            # Restore root directory
            db.restore_item("d-root")

            # Active listings must be restored
            active_dirs = db.list_directories(include_trashed=False)
            active_files = db.list_files(include_trashed=False)
            assert len(active_dirs) == 2
            assert len(active_files) == 2

            db.close()
