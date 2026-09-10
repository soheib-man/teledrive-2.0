"""Tests for streaming chunking, byte parsing, and temporary workspace isolation."""

import tempfile
import unittest
from pathlib import Path

from teledrive.chunking import (
    compute_bytes_sha256,
    compute_file_sha256,
    parse_bytes,
    slice_single_chunk,
    split_file_into_chunks,
    temporary_operation_dir,
)


class TestChunking(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_bytes_complete_ranges(self):
        self.assertEqual(parse_bytes(0), "0 B")
        self.assertEqual(parse_bytes(512), "512 B")
        self.assertEqual(parse_bytes(1024), "1.00 KB")
        self.assertEqual(parse_bytes(1024 * 1024), "1.00 MB")
        self.assertEqual(parse_bytes(1024 * 1024 * 1024), "1.00 GB")
        self.assertEqual(parse_bytes(1024**4), "1.00 TB")
        self.assertEqual(parse_bytes(1024**5), "1.00 PB")
        # Very large number must never return None or crash
        res = parse_bytes(1024**6 * 50)
        self.assertIsInstance(res, str)
        self.assertTrue(len(res) > 0)

    def test_split_empty_file(self):
        empty_file = self.dir_path / "empty.txt"
        empty_file.touch()

        out_dir = self.dir_path / "chunks"
        chunks = split_file_into_chunks(empty_file, out_dir, chunk_size=1024)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][1], 0)
        self.assertEqual(chunks[0][2], compute_bytes_sha256(b""))

    def test_split_file_exact_chunk_boundary(self):
        test_file = self.dir_path / "exact.dat"
        data = b"X" * 1024  # 1024 bytes
        test_file.write_bytes(data)

        out_dir = self.dir_path / "chunks"
        chunks = split_file_into_chunks(test_file, out_dir, chunk_size=512)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0][1], 512)
        self.assertEqual(chunks[1][1], 512)

    def test_split_file_partial_last_chunk(self):
        test_file = self.dir_path / "partial.dat"
        data = b"Y" * 1500
        test_file.write_bytes(data)

        out_dir = self.dir_path / "chunks"
        chunks = split_file_into_chunks(test_file, out_dir, chunk_size=1000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0][1], 1000)
        self.assertEqual(chunks[1][1], 500)

    def test_slice_single_chunk(self):
        test_file = self.dir_path / "multi.dat"
        test_file.write_bytes(b"A" * 100 + b"B" * 100 + b"C" * 100)

        out_chunk = self.dir_path / "sliced.chunk"
        bytes_written, sha = slice_single_chunk(test_file, chunk_index=1, chunk_size=100, output_path=out_chunk)
        self.assertEqual(bytes_written, 100)
        self.assertEqual(out_chunk.read_bytes(), b"B" * 100)
        self.assertEqual(sha, compute_bytes_sha256(b"B" * 100))

    def test_temporary_operation_dir_cleanup_on_error(self):
        parent = self.dir_path / "temp_parent"
        parent.mkdir()

        created_path = None
        try:
            with temporary_operation_dir(parent) as op_dir:
                created_path = op_dir
                (op_dir / "temp_work.bin").write_bytes(b"test")
                raise ValueError("Simulated failure")
        except ValueError:
            pass

        self.assertIsNotNone(created_path)
        self.assertFalse(created_path.exists())


if __name__ == "__main__":
    unittest.main()
