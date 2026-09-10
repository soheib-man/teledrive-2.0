"""Backward compatibility shim for legacy files.py."""

from teledrive.chunking import parse_bytes, split_file_into_chunks

__all__ = ["parse_bytes", "split_file_into_chunks"]
