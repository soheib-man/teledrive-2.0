"""Tests for cryptographic integrity, atomic reconstruction, and overwrite protection."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from teledrive.chunking import compute_file_sha256
from teledrive.exceptions import FileExistsSafetyError, IntegrityError
from teledrive.reconstruction import reconstruct_file_from_chunks


class TestIntegrity(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_reconstruct_file_success(self):
        c1 = self.dir_path / "part0.chunk"
        c2 = self.dir_path / "part1.chunk"
        c1.write_bytes(b"Hello, ")
        c2.write_bytes(b"TeleDrive 2.0!")

        expected_content = b"Hello, TeleDrive 2.0!"
        expected_hash = hashlib.sha256(expected_content).hexdigest()

        dest = self.dir_path / "restored.txt"
        written = reconstruct_file_from_chunks(dest, [c1, c2], expected_sha256=expected_hash)

        self.assertEqual(written, len(expected_content))
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), expected_content)
        self.assertEqual(compute_file_sha256(dest), expected_hash)

    def test_reconstruct_file_detects_corrupted_chunk(self):
        c1 = self.dir_path / "part0.chunk"
        c1.write_bytes(b"Corrupted bytes")

        dest = self.dir_path / "should_fail.txt"
        expected_hash = hashlib.sha256(b"Original intact bytes").hexdigest()

        with self.assertRaises(IntegrityError):
            reconstruct_file_from_chunks(dest, [c1], expected_sha256=expected_hash)

        # Dest must not exist and part file must be cleaned up
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".part").exists())

    def test_reconstruct_file_overwrite_protection(self):
        dest = self.dir_path / "existing.txt"
        dest.write_bytes(b"Initial content")

        c1 = self.dir_path / "new.chunk"
        c1.write_bytes(b"New content")
        new_hash = hashlib.sha256(b"New content").hexdigest()

        # Without force, must raise FileExistsSafetyError
        with self.assertRaises(FileExistsSafetyError):
            reconstruct_file_from_chunks(dest, [c1], expected_sha256=new_hash, force=False)

        # Content must remain intact
        self.assertEqual(dest.read_bytes(), b"Initial content")

        # With force=True, must overwrite successfully
        reconstruct_file_from_chunks(dest, [c1], expected_sha256=new_hash, force=True)
        self.assertEqual(dest.read_bytes(), b"New content")


if __name__ == "__main__":
    unittest.main()
