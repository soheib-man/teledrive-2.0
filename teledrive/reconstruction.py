"""Atomic file reconstruction, checksum verification, and overwrite protection."""

import hashlib
import os
from pathlib import Path
from typing import List

from teledrive.constants import STREAM_BUFFER_SIZE
from teledrive.exceptions import FileExistsSafetyError, IntegrityError


def reconstruct_file_from_chunks(
    destination_path: Path,
    chunk_paths: List[Path],
    expected_sha256: str,
    force: bool = False,
) -> int:
    """
    Safely concatenates downloaded chunk files into destination_path.
    Writes to a temporary .part file first, verifies final SHA-256,
    and atomically moves into place.
    """
    destination_path = Path(destination_path).resolve()

    if destination_path.exists() and not force:
        raise FileExistsSafetyError(str(destination_path))

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination_path.with_name(f"{destination_path.name}.part")

    total_bytes_written = 0
    hasher = hashlib.sha256()

    try:
        with open(part_path, "wb") as dst:
            for chunk_file in chunk_paths:
                with open(chunk_file, "rb") as src:
                    while True:
                        buf = src.read(STREAM_BUFFER_SIZE)
                        if not buf:
                            break
                        dst.write(buf)
                        hasher.update(buf)
                        total_bytes_written += len(buf)

        calculated_hash = hasher.hexdigest()

        # Verify integrity if expected hash is provided
        if expected_sha256 and calculated_hash.lower() != expected_sha256.lower():
            part_path.unlink(missing_ok=True)
            raise IntegrityError(
                f"Checksum mismatch for '{destination_path.name}'! "
                f"Expected: {expected_sha256}, Calculated: {calculated_hash}"
            )

        # Atomic move/replace into final destination
        os.replace(part_path, destination_path)
        return total_bytes_written

    except Exception:
        part_path.unlink(missing_ok=True)
        raise
