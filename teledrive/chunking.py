"""High-performance streaming chunking, incremental hashing, and memory-safe I/O."""

import hashlib
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Tuple, Optional

from teledrive.constants import DEFAULT_CHUNK_SIZE, STREAM_BUFFER_SIZE


def parse_bytes(num_bytes: float) -> str:
    """Converts bytes to human-readable format supporting B up to PB."""
    if num_bytes < 0:
        return "0.00 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(num_bytes)
    unit_idx = 0

    while value >= 1024.0 and unit_idx < len(units) - 1:
        value /= 1024.0
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(value)} B"
    return f"{value:.2f} {units[unit_idx]}"


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 digest of a file using streaming 64 KB buffers."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(STREAM_BUFFER_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 digest of a byte sequence."""
    return hashlib.sha256(data).hexdigest()


@contextmanager
def temporary_operation_dir(parent_temp: Path, prefix: str = "op_") -> Generator[Path, None, None]:
    """Yields a unique temporary working directory that is guaranteed to be cleaned up."""
    unique_id = uuid.uuid4().hex[:12]
    op_dir = parent_temp / f"{prefix}{unique_id}"
    op_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield op_dir
    finally:
        if op_dir.exists():
            try:
                for item in op_dir.iterdir():
                    if item.is_file() or item.is_symlink():
                        item.unlink(missing_ok=True)
                    elif item.is_dir():
                        import shutil
                        shutil.rmtree(item, ignore_errors=True)
                op_dir.rmdir()
            except Exception:
                pass


def split_file_into_chunks(
    source_path: Path,
    output_dir: Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> List[Tuple[Path, int, str]]:
    """
    Streams a local file into physical chunks within output_dir without loading
    the full file into RAM. Computes per-chunk SHA-256 on the fly.
    Returns: list of (chunk_path, chunk_bytes, chunk_sha256).
    """
    source_path = Path(source_path).resolve()
    file_size = source_path.stat().st_size
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks: List[Tuple[Path, int, str]] = []

    # Handle empty (0-byte) files
    if file_size == 0:
        chunk_file = output_dir / f"{source_path.name}.chunk0"
        chunk_file.touch()
        hasher = hashlib.sha256()
        chunks.append((chunk_file, 0, hasher.hexdigest()))
        return chunks

    chunk_index = 0
    with open(source_path, "rb") as src:
        while True:
            chunk_file_path = output_dir / f"{source_path.name}.part{chunk_index}.chunk"
            bytes_written = 0
            hasher = hashlib.sha256()

            with open(chunk_file_path, "wb") as chunk_out:
                while bytes_written < chunk_size:
                    to_read = min(STREAM_BUFFER_SIZE, chunk_size - bytes_written)
                    buffer = src.read(to_read)
                    if not buffer:
                        break
                    chunk_out.write(buffer)
                    hasher.update(buffer)
                    bytes_written += len(buffer)

            if bytes_written == 0:
                # Reached EOF before writing any bytes for this chunk
                chunk_file_path.unlink(missing_ok=True)
                break

            chunks.append((chunk_file_path, bytes_written, hasher.hexdigest()))
            chunk_index += 1

    return chunks


def slice_single_chunk(
    source_path: Path,
    chunk_index: int,
    chunk_size: int,
    output_path: Path,
) -> Tuple[int, str]:
    """
    Extracts only a single chunk byte range from source file.
    Useful for targeted chunk repairs without re-chunking entire files.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    offset = chunk_index * chunk_size
    bytes_written = 0
    hasher = hashlib.sha256()

    with open(source_path, "rb") as src:
        src.seek(offset)
        with open(output_path, "wb") as dst:
            while bytes_written < chunk_size:
                to_read = min(STREAM_BUFFER_SIZE, chunk_size - bytes_written)
                buf = src.read(to_read)
                if not buf:
                    break
                dst.write(buf)
                hasher.update(buf)
                bytes_written += len(buf)

    return bytes_written, hasher.hexdigest()
