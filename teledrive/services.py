"""Core application service orchestrating storage operations, directory recursion, and transfers."""

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional, Tuple

from teledrive.chunking import (
    compute_file_sha256,
    slice_single_chunk,
    split_file_into_chunks,
    temporary_operation_dir,
)
from teledrive.config import Config
from teledrive.constants import Status
from teledrive.database import Database
from teledrive.exceptions import (
    AmbiguousQueryError,
    IntegrityError,
    ItemNotFoundError,
    TeleDriveError,
)
from teledrive.models import (
    ChunkRecord,
    DirectoryRecord,
    FileRecord,
    TransferProgress,
)
from teledrive.reconstruction import reconstruct_file_from_chunks
from teledrive.telegram_client import TelegramService

logger = logging.getLogger("teledrive.services")


def _resolve_safe_subpath(base_dir: Path, relative_str: str, fallback_name: str) -> Path:
    """Guarantees that candidate path is strictly contained within base_dir, preventing path traversal."""
    base_resolved = base_dir.resolve()
    # Normalize slashes and strip leading slashes or Windows drive specifiers
    rel_str = str(relative_str).replace("\\", "/").lstrip("/\\")
    if ":" in rel_str:
        rel_str = rel_str.split(":", 1)[1].lstrip("/\\")

    candidate = (base_resolved / Path(rel_str)).resolve()
    try:
        candidate.relative_to(base_resolved)
        if candidate == base_resolved:
            return base_resolved / Path(fallback_name).name
        return candidate
    except ValueError:
        return base_resolved / Path(fallback_name).name


class StorageService:
    """High-level service coordinating SQLite metadata, chunking, and Telegram cloud transfers."""

    def __init__(self, config: Config):
        self.config = config
        self.db = Database(self.config.db_file)
        self._telegram: Optional[TelegramService] = None

    @property
    def telegram(self) -> TelegramService:
        if self._telegram is None:
            self.config.validate()
            self._telegram = TelegramService(
                api_id=self.config.telegram_api_id,
                api_hash=self.config.telegram_api_hash,
                session_path=self.config.session_path,
                phone_number=self.config.phone_number,
            )
        return self._telegram

    def close(self) -> None:
        self.db.close()

    def resolve_single_item(
        self, query: str, include_trashed: bool = False
    ) -> Tuple[Optional[FileRecord], Optional[DirectoryRecord]]:
        """Resolves a user query to exactly one file or directory, or raises AmbiguousQueryError."""
        files, dirs = self.db.find_items_by_query(query, include_trashed=include_trashed)
        total = len(files) + len(dirs)

        if total == 0:
            raise ItemNotFoundError(query)
        if total > 1:
            matches = [f"{f.name} (file, ID: {f.id})" for f in files] + [
                f"{d.name} (dir, ID: {d.id})" for d in dirs
            ]
            raise AmbiguousQueryError(query, matches)

        return (files[0] if files else None, dirs[0] if dirs else None)

    # --------------------------------------------------------------------------
    # Upload Operations
    # --------------------------------------------------------------------------

    async def upload_file(
        self,
        file_path: Path,
        directory_id: Optional[str] = None,
        relative_path: Optional[str] = None,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> FileRecord:
        """Uploads a local file in streaming chunks to Telegram and commits metadata."""
        file_path = Path(file_path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        file_sha256 = compute_file_sha256(file_path)
        file_id = uuid.uuid4().hex

        file_rec = FileRecord(
            id=file_id,
            name=file_path.name,
            original_path=str(file_path),
            relative_path=relative_path or file_path.name,
            size=file_size,
            sha256=file_sha256,
            file_type="file",
            directory_id=directory_id,
            status=Status.UPLOADING.value,
        )
        self.db.insert_file(file_rec)

        with temporary_operation_dir(self.config.temp_dir, prefix="upl_") as op_dir:
            chunks = split_file_into_chunks(file_path, op_dir, chunk_size=self.config.chunk_size)
            total_chunks = len(chunks)
            total_transferred = 0
            start_time = time.time()

            for chunk_idx, (chunk_path, chunk_bytes, chunk_hash) in enumerate(chunks):
                chunk_rec = ChunkRecord(
                    file_id=file_id,
                    chunk_index=chunk_idx,
                    size=chunk_bytes,
                    sha256=chunk_hash,
                    status=Status.UPLOADING.value,
                )
                self.db.insert_chunk(chunk_rec)

                caption = f"TELEDRIVE_V2|{file_id}|{chunk_idx}|{total_chunks}|{chunk_hash[:12]}"

                # Chunk byte progress handler
                def _telethon_cb(current_bytes, _total):
                    if progress_callback:
                        now = time.time()
                        elapsed = max(now - start_time, 0.001)
                        progress = TransferProgress(
                            file_name=file_path.name,
                            total_bytes=file_size,
                            transferred_bytes=total_transferred + current_bytes,
                            current_chunk=chunk_idx + 1,
                            total_chunks=total_chunks,
                            speed_bps=(total_transferred + current_bytes) / elapsed,
                        )
                        progress_callback(progress)

                msg_id = await self.telegram.upload_chunk(
                    chunk_path,
                    caption=caption,
                    progress_callback=_telethon_cb if progress_callback else None,
                )

                self.db.update_chunk_telegram_id(file_id, chunk_idx, msg_id, status=Status.COMPLETED)
                total_transferred += chunk_bytes

        self.db.update_file_status(file_id, Status.COMPLETED, sha256=file_sha256)
        return self.db.get_file_by_id(file_id)

    async def upload_directory(
        self,
        dir_path: Path,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> Tuple[DirectoryRecord, List[FileRecord]]:
        """Recursively uploads a directory, all subfolders (including empty ones), and files."""
        dir_path = Path(dir_path).resolve()
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        root_id = uuid.uuid4().hex
        root_dir = DirectoryRecord(
            id=root_id,
            name=dir_path.name,
            original_path=str(dir_path),
            root_id=root_id,
            relative_path="",
        )
        self.db.insert_directory(root_dir)

        # Discover all subdirectories (including empty directories)
        dir_map: Dict[str, str] = {"": root_id}
        all_subdirs = [p for p in dir_path.rglob("*") if p.is_dir()]

        # Sort by path depth so parent folders are inserted before child folders
        for sub_dir in sorted(all_subdirs, key=lambda p: len(p.parts)):
            rel = sub_dir.relative_to(dir_path).as_posix()
            parent_rel = (
                sub_dir.parent.relative_to(dir_path).as_posix()
                if sub_dir.parent != dir_path
                else ""
            )
            parent_id = dir_map.get(parent_rel, root_id)
            sub_id = uuid.uuid4().hex
            dir_map[rel] = sub_id

            rec = DirectoryRecord(
                id=sub_id,
                parent_id=parent_id,
                root_id=root_id,
                name=sub_dir.name,
                original_path=str(sub_dir),
                relative_path=rel,
            )
            self.db.insert_directory(rec)

        # Discover all files
        all_files = [p for p in dir_path.rglob("*") if p.is_file()]
        uploaded_files: List[FileRecord] = []

        for file_path in all_files:
            file_rel_parent = (
                file_path.parent.relative_to(dir_path).as_posix()
                if file_path.parent != dir_path
                else ""
            )
            file_dir_id = dir_map.get(file_rel_parent, root_id)
            file_rel_path = file_path.relative_to(dir_path).as_posix()

            f_rec = await self.upload_file(
                file_path=file_path,
                directory_id=file_dir_id,
                relative_path=file_rel_path,
                progress_callback=progress_callback,
            )
            uploaded_files.append(f_rec)

        return (root_dir, uploaded_files)

    # --------------------------------------------------------------------------
    # Download Operations
    # --------------------------------------------------------------------------

    async def download_file(
        self,
        file_query: str,
        destination_dir: Optional[Path] = None,
        force: bool = False,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> Path:
        """Safely downloads and verifies a stored file."""
        file_rec, _ = self.resolve_single_item(file_query)
        if not file_rec:
            raise ItemNotFoundError(file_query)

        chunks = self.db.get_chunks_for_file(file_rec.id)
        if not chunks:
            raise TeleDriveError(f"No chunk records found for file '{file_rec.name}'.")

        dest_base = destination_dir or Path.cwd()
        if dest_base.is_dir():
            dest_file = dest_base / Path(file_rec.name).name
        else:
            dest_file = dest_base

        with temporary_operation_dir(self.config.temp_dir, prefix="dwn_") as op_dir:
            downloaded_chunk_files: List[Path] = []
            total_transferred = 0
            start_time = time.time()

            for chunk in chunks:
                if not chunk.telegram_message_id:
                    raise TeleDriveError(f"Chunk #{chunk.chunk_index} has no Telegram message ID.")

                chunk_file = op_dir / f"chunk_{chunk.chunk_index}.dat"

                def _telethon_cb(current_bytes, _total):
                    if progress_callback:
                        now = time.time()
                        elapsed = max(now - start_time, 0.001)
                        progress = TransferProgress(
                            file_name=file_rec.name,
                            total_bytes=file_rec.size,
                            transferred_bytes=total_transferred + current_bytes,
                            current_chunk=chunk.chunk_index + 1,
                            total_chunks=len(chunks),
                            speed_bps=(total_transferred + current_bytes) / elapsed,
                        )
                        progress_callback(progress)

                await self.telegram.download_chunk(
                    telegram_message_id=chunk.telegram_message_id,
                    destination_path=chunk_file,
                    progress_callback=_telethon_cb if progress_callback else None,
                )
                downloaded_chunk_files.append(chunk_file)
                total_transferred += chunk.size

            reconstruct_file_from_chunks(
                destination_path=dest_file,
                chunk_paths=downloaded_chunk_files,
                expected_sha256=file_rec.sha256,
                force=force,
            )

        return dest_file

    async def download_directory(
        self,
        dir_query: str,
        destination_dir: Optional[Path] = None,
        force: bool = False,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> Path:
        """Safely reconstructs a full directory tree with all nested subdirectories and files."""
        _, dir_rec = self.resolve_single_item(dir_query)
        if not dir_rec:
            raise ItemNotFoundError(dir_query)

        # Retrieve entire tree (root, subdirectories, and files)
        root_dir, all_subdirs, files = self.db.get_directory_tree(dir_rec.id)
        if not root_dir:
            root_dir = dir_rec

        base_dest = (destination_dir or Path.cwd()) / root_dir.name
        base_dest.mkdir(parents=True, exist_ok=True)

        # First recreate all subdirectories (ensuring empty directories exist!)
        for sub_dir in all_subdirs:
            if sub_dir.relative_path:
                safe_subdir_dir = _resolve_safe_subpath(base_dest, sub_dir.relative_path, sub_dir.name)
                safe_subdir_dir.mkdir(parents=True, exist_ok=True)

        # Download each file into its exact reconstructed relative path
        for f_rec in files:
            target_file_path = _resolve_safe_subpath(base_dest, f_rec.relative_path, f_rec.name)
            target_file_path.parent.mkdir(parents=True, exist_ok=True)
            await self.download_file(
                file_query=f_rec.id,
                destination_dir=target_file_path,
                force=force,
                progress_callback=progress_callback,
            )

        return base_dest

    def get_tree(self, query: str) -> Dict[str, Any]:
        """Returns the full hierarchical directory tree structure for visualization."""
        _, dir_rec = self.resolve_single_item(query, include_trashed=True)
        if not dir_rec:
            raise ItemNotFoundError(query)

        root_dir, subdirs, files = self.db.get_directory_tree(dir_rec.id)
        return {
            "root": (root_dir or dir_rec).to_dict(),
            "subdirectories": [d.to_dict() for d in subdirs],
            "files": [f.to_dict() for f in files],
        }

    # --------------------------------------------------------------------------
    # Storage Operations: Info, Verify, Repair, Resume, Trash, Restore, Purge
    # --------------------------------------------------------------------------

    def info(self, query: str) -> Dict[str, Any]:
        """Returns complete structural metadata and chunk details."""
        file_rec, dir_rec = self.resolve_single_item(query, include_trashed=True)

        if file_rec:
            chunks = self.db.get_chunks_for_file(file_rec.id)
            return {
                "type": "file",
                "record": file_rec.to_dict(),
                "chunks": [c.to_dict() for c in chunks],
                "chunk_count": len(chunks),
            }

        if dir_rec:
            files = self.db.list_files(include_trashed=True, directory_id=dir_rec.id)
            total_size = sum(f.size for f in files)
            return {
                "type": "directory",
                "record": dir_rec.to_dict(),
                "file_count": len(files),
                "total_size": total_size,
                "files": [f.to_dict() for f in files],
            }

        raise ItemNotFoundError(query)

    async def verify(self, query: str) -> Dict[str, Any]:
        """Validates that all Telegram chunk messages exist on the server."""
        file_rec, dir_rec = self.resolve_single_item(query, include_trashed=True)

        if file_rec:
            chunks = self.db.get_chunks_for_file(file_rec.id)
            results = []
            all_ok = True

            for c in chunks:
                if not c.telegram_message_id:
                    results.append({"chunk_index": c.chunk_index, "exists": False, "reason": "No message ID recorded"})
                    all_ok = False
                    continue

                exists = await self.telegram.verify_chunk(c.telegram_message_id)
                results.append({"chunk_index": c.chunk_index, "message_id": c.telegram_message_id, "exists": exists})
                if not exists:
                    all_ok = False

            return {
                "type": "file",
                "name": file_rec.name,
                "id": file_rec.id,
                "verified": all_ok,
                "chunks": results,
            }

        if dir_rec:
            files = self.db.list_files(include_trashed=True, directory_id=dir_rec.id)
            file_results = []
            all_ok = True

            for f in files:
                f_ver = await self.verify(f.id)
                file_results.append(f_ver)
                if not f_ver["verified"]:
                    all_ok = False

            return {
                "type": "directory",
                "name": dir_rec.name,
                "id": dir_rec.id,
                "verified": all_ok,
                "files": file_results,
            }

        raise ItemNotFoundError(query)

    async def repair(self, query: str, local_source_path: Path) -> Dict[str, Any]:
        """Re-uploads missing or corrupted chunks from a local file without re-transferring intact chunks."""
        file_rec, _ = self.resolve_single_item(query, include_trashed=True)
        if not file_rec:
            raise ItemNotFoundError(query)

        local_source_path = Path(local_source_path).resolve()
        if not local_source_path.is_file():
            raise FileNotFoundError(f"Local source file '{local_source_path}' not found.")

        # Verify source file SHA-256 matches
        source_hash = compute_file_sha256(local_source_path)
        if source_hash.lower() != file_rec.sha256.lower():
            raise IntegrityError(
                f"Source file checksum ({source_hash}) does not match stored file ({file_rec.sha256})!"
            )

        chunks = self.db.get_chunks_for_file(file_rec.id)
        repaired_chunks = []

        with temporary_operation_dir(self.config.temp_dir, prefix="rpr_") as op_dir:
            for c in chunks:
                needs_repair = False
                if not c.telegram_message_id:
                    needs_repair = True
                else:
                    exists = await self.telegram.verify_chunk(c.telegram_message_id)
                    if not exists:
                        needs_repair = True

                if needs_repair:
                    chunk_file = op_dir / f"repair_{c.chunk_index}.chunk"
                    slice_single_chunk(local_source_path, c.chunk_index, self.config.chunk_size, chunk_file)
                    caption = f"TELEDRIVE_V2|{file_rec.id}|{c.chunk_index}|{len(chunks)}|REPAIR"

                    new_msg_id = await self.telegram.upload_chunk(chunk_file, caption=caption)
                    self.db.update_chunk_telegram_id(file_rec.id, c.chunk_index, new_msg_id, status=Status.COMPLETED)
                    repaired_chunks.append(c.chunk_index)

        return {"file_id": file_rec.id, "repaired_count": len(repaired_chunks), "repaired_indices": repaired_chunks}

    async def resume(
        self,
        query: str,
        local_source_path: Path,
        progress_callback: Optional[Callable[[TransferProgress], None]] = None,
    ) -> FileRecord:
        """Resumes an interrupted upload from the first incomplete chunk."""
        file_rec, _ = self.resolve_single_item(query, include_trashed=True)
        if not file_rec:
            raise ItemNotFoundError(query)

        local_source_path = Path(local_source_path).resolve()
        chunks = self.db.get_chunks_for_file(file_rec.id)
        pending_chunks = [c for c in chunks if not c.telegram_message_id or c.status != Status.COMPLETED.value]

        if not pending_chunks:
            self.db.update_file_status(file_rec.id, Status.COMPLETED)
            return file_rec

        with temporary_operation_dir(self.config.temp_dir, prefix="rsm_") as op_dir:
            for c in pending_chunks:
                chunk_file = op_dir / f"resume_{c.chunk_index}.chunk"
                slice_single_chunk(local_source_path, c.chunk_index, self.config.chunk_size, chunk_file)
                caption = f"TELEDRIVE_V2|{file_rec.id}|{c.chunk_index}|{len(chunks)}|RESUME"

                msg_id = await self.telegram.upload_chunk(chunk_file, caption=caption)
                self.db.update_chunk_telegram_id(file_rec.id, c.chunk_index, msg_id, status=Status.COMPLETED)

        self.db.update_file_status(file_rec.id, Status.COMPLETED)
        return self.db.get_file_by_id(file_rec.id)

    def rename(self, query: str, new_name: str) -> bool:
        """Renames an item instantly in SQLite metadata."""
        file_rec, dir_rec = self.resolve_single_item(query, include_trashed=True)
        target_id = file_rec.id if file_rec else dir_rec.id
        return self.db.rename_item(target_id, new_name)

    def move(self, query: str, target_dir_query: str) -> bool:
        """Moves a file to a different logical directory in SQLite metadata."""
        file_rec, _ = self.resolve_single_item(query, include_trashed=True)
        if not file_rec:
            raise ItemNotFoundError(query)

        _, dir_rec = self.resolve_single_item(target_dir_query, include_trashed=False)
        if not dir_rec:
            raise ItemNotFoundError(f"Target directory '{target_dir_query}' not found.")

        return self.db.move_item(file_rec.id, dir_rec.id)

    def trash(self, query: str) -> bool:
        """Soft-deletes a file or directory into trash."""
        file_rec, dir_rec = self.resolve_single_item(query, include_trashed=False)
        target_id = file_rec.id if file_rec else dir_rec.id
        return self.db.trash_item(target_id)

    def restore(self, query: str) -> bool:
        """Restores a soft-deleted file or directory from trash."""
        file_rec, dir_rec = self.resolve_single_item(query, include_trashed=True)
        target_id = file_rec.id if file_rec else dir_rec.id
        return self.db.restore_item(target_id)

    async def purge(self, query: Optional[str] = None) -> int:
        """
        Permanently deletes items from SQLite and prunes EXACT Telegram message IDs.
        If query is given, permanently deletes that item.
        If query is None, permanently purges everything in the trash.
        """
        if query:
            file_rec, dir_rec = self.resolve_single_item(query, include_trashed=True)
            if file_rec:
                msg_ids = self.db.delete_file_permanently(file_rec.id)
                return await self.telegram.delete_messages_safely(msg_ids)
            if dir_rec:
                msg_ids = self.db.delete_directory_permanently(dir_rec.id)
                return await self.telegram.delete_messages_safely(msg_ids)

        # Purge all trashed items
        trashed_files, trashed_dirs = self.db.list_trashed_items()
        all_msg_ids: List[int] = []

        for f in trashed_files:
            all_msg_ids.extend(self.db.delete_file_permanently(f.id))
        for d in trashed_dirs:
            all_msg_ids.extend(self.db.delete_directory_permanently(d.id))

        if all_msg_ids:
            return await self.telegram.delete_messages_safely(all_msg_ids)
        return 0

    def export_metadata(self, query: Optional[str] = None, output_path: Optional[Path] = None) -> Path:
        """Exports metadata to a portable JSON file."""
        target_id = None
        if query:
            f, d = self.resolve_single_item(query, include_trashed=True)
            target_id = f.id if f else d.id

        data = self.db.export_metadata(target_id)
        out_file = output_path or (Path.cwd() / "teledrive_metadata_backup.json")
        out_file = Path(out_file).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return out_file

    def import_metadata(self, json_path: Path) -> int:
        """Imports metadata from a JSON backup file."""
        json_path = Path(json_path).resolve()
        if not json_path.is_file():
            raise FileNotFoundError(f"Metadata file '{json_path}' not found.")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.db.import_metadata(data)
