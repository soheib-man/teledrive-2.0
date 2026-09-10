"""Relational SQLite database manager, migration engine, and repository for TeleDrive 2.0."""

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from teledrive.constants import SCHEMA_VERSION, Status
from teledrive.exceptions import (
    DatabaseError,
    ItemNotFoundError,
    AlreadyTrashedError,
    NotTrashedError,
)
from teledrive.models import DirectoryRecord, FileRecord, ChunkRecord


def _utc_now_str() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    """High-performance SQLite database connection with transactional guarantees and foreign keys."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        """Initializes connection with foreign key enforcement and row factories."""
        self._conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode = WAL;")
        self._conn.row_factory = sqlite3.Row

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._connect()
        return self._conn

    def close(self) -> None:
        """Closes connection gracefully."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @contextmanager
    def transaction(self):
        """Context manager for atomic transactions with automatic rollback on error."""
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _init_schema(self) -> None:
        """Sets up normalized schema, indexes, and handles legacy migration."""
        with self.transaction():
            cur = self.conn.cursor()

            # Check if this is an existing legacy database (v1 single 'file' table)
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='file';")
            legacy_table_exists = cur.fetchone() is not None

            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version';")
            has_version_table = cur.fetchone() is not None

            if legacy_table_exists and not has_version_table:
                self._migrate_legacy_v1()
                return

            # Create standard normalized schema
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS directories (
                    id TEXT PRIMARY KEY,
                    parent_id TEXT REFERENCES directories(id) ON DELETE CASCADE,
                    root_id TEXT,
                    name TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL DEFAULT '',
                    trashed_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    directory_id TEXT REFERENCES directories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trashed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    telegram_message_id INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, chunk_index)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                );
                """
            )

            # Check if columns need migration for existing v2 tables
            cur.execute("PRAGMA table_info(directories);")
            existing_cols = {col[1] for col in cur.fetchall()}
            if "root_id" not in existing_cols:
                cur.execute("ALTER TABLE directories ADD COLUMN root_id TEXT;")
            if "relative_path" not in existing_cols:
                cur.execute("ALTER TABLE directories ADD COLUMN relative_path TEXT NOT NULL DEFAULT '';")

            # Indexes for ultra-fast lookup
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_dir ON files(directory_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_directories_root ON directories(root_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_directories_parent ON directories(parent_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file_idx ON chunks(file_id, chunk_index);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_msg_id ON chunks(telegram_message_id);")

            # Set current schema version
            cur.execute("SELECT version FROM schema_version;")
            row = cur.fetchone()
            if not row:
                cur.execute("INSERT INTO schema_version (version) VALUES (?);", (SCHEMA_VERSION,))

    def _migrate_legacy_v1(self) -> None:
        """Migrates legacy v1 database containing raw JSON chunk paths to normalized schema."""
        backup_path = self.db_path.with_name(f"{self.db_path.name}.v1.bak")
        shutil.copy2(self.db_path, backup_path)

        cur = self.conn.cursor()
        cur.execute("SELECT * FROM file;")
        rows = cur.fetchall()

        # Rename old table
        cur.execute("ALTER TABLE file RENAME TO file_legacy_v1;")

        # Create new tables
        cur.execute(
            """
            CREATE TABLE directories (
                id TEXT PRIMARY KEY,
                parent_id TEXT REFERENCES directories(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                original_path TEXT NOT NULL,
                trashed_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE files (
                id TEXT PRIMARY KEY,
                directory_id TEXT REFERENCES directories(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                original_path TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                file_type TEXT NOT NULL,
                status TEXT NOT NULL,
                trashed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                size INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                telegram_message_id INTEGER,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(file_id, chunk_index)
            );
            """
        )
        cur.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY);")
        cur.execute("INSERT INTO schema_version (version) VALUES (?);", (SCHEMA_VERSION,))

        # Migrate each row
        for row in rows:
            # row: (id, file_name, file_path, file_size, chunks, type, uploaded)
            item_id = str(row[0])
            name = str(row[1])
            path = str(row[2])
            size = int(row[3]) if row[3] else 0
            chunks_json = str(row[4])
            item_type = str(row[5])
            uploaded = str(row[6]) if row[6] else _utc_now_str()

            try:
                chunk_list = json.loads(chunks_json) if chunks_json else []
            except Exception:
                chunk_list = []

            if item_type == "dir":
                cur.execute(
                    "INSERT INTO directories (id, name, original_path, created_at) VALUES (?, ?, ?, ?);",
                    (item_id, name, path, uploaded),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO files (id, name, original_path, relative_path, size, sha256, file_type, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (item_id, name, path, name, size, "", "file", Status.COMPLETED.value, uploaded, uploaded),
                )
                for idx, chunk_path in enumerate(chunk_list):
                    cur.execute(
                        """
                        INSERT INTO chunks (file_id, chunk_index, size, sha256, telegram_message_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?);
                        """,
                        (item_id, idx, 0, "", None, Status.COMPLETED.value, uploaded),
                    )

    # --------------------------------------------------------------------------
    # Directory Operations
    # --------------------------------------------------------------------------

    def insert_directory(self, dir_rec: DirectoryRecord) -> None:
        """Inserts a directory record."""
        created_at = dir_rec.created_at or _utc_now_str()
        with self.transaction():
            self.conn.execute(
                """
                INSERT OR REPLACE INTO directories (id, parent_id, root_id, name, original_path, relative_path, trashed_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    dir_rec.id,
                    dir_rec.parent_id,
                    dir_rec.root_id,
                    dir_rec.name,
                    dir_rec.original_path,
                    dir_rec.relative_path,
                    dir_rec.trashed_at,
                    created_at,
                ),
            )

    def get_directory_by_id(self, dir_id: str) -> Optional[DirectoryRecord]:
        """Fetches directory by ID."""
        cur = self.conn.execute("SELECT * FROM directories WHERE id = ?;", (dir_id,))
        row = cur.fetchone()
        return DirectoryRecord.from_dict(dict(row)) if row else None

    def list_directories(self, include_trashed: bool = False) -> List[DirectoryRecord]:
        """Lists directories."""
        if include_trashed:
            query = "SELECT * FROM directories ORDER BY name ASC;"
            rows = self.conn.execute(query).fetchall()
        else:
            query = "SELECT * FROM directories WHERE trashed_at IS NULL ORDER BY name ASC;"
            rows = self.conn.execute(query).fetchall()
        return [DirectoryRecord.from_dict(dict(r)) for r in rows]

    def get_directory_tree(
        self, root_dir_id: str, include_trashed: bool = False
    ) -> Tuple[Optional[DirectoryRecord], List[DirectoryRecord], List[FileRecord]]:
        """
        Retrieves the root directory, all nested subdirectories, and all files
        belonging to the entire directory hierarchy.
        """
        root_dir = self.get_directory_by_id(root_dir_id)
        if not root_dir:
            return (None, [], [])

        trashed_filter = "" if include_trashed else "AND trashed_at IS NULL"

        # Fetch all directories belonging to this root
        subdirs_rows = self.conn.execute(
            f"SELECT * FROM directories WHERE (root_id = ? OR id = ?) {trashed_filter} ORDER BY relative_path ASC;",
            (root_dir_id, root_dir_id),
        ).fetchall()
        all_dirs = [DirectoryRecord.from_dict(dict(r)) for r in subdirs_rows]
        all_dir_ids = [d.id for d in all_dirs]

        if not all_dir_ids:
            return (root_dir, [root_dir], [])

        # Fetch all files in any of these directory IDs
        placeholders = ",".join("?" * len(all_dir_ids))
        file_rows = self.conn.execute(
            f"SELECT * FROM files WHERE directory_id IN ({placeholders}) {trashed_filter} ORDER BY relative_path ASC;",
            all_dir_ids,
        ).fetchall()
        all_files = [FileRecord.from_dict(dict(r)) for r in file_rows]

        return (root_dir, all_dirs, all_files)

    # --------------------------------------------------------------------------
    # File Operations
    # --------------------------------------------------------------------------

    def insert_file(self, file_rec: FileRecord) -> None:
        """Inserts a file record."""
        created_at = file_rec.created_at or _utc_now_str()
        updated_at = file_rec.updated_at or created_at
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO files (id, directory_id, name, original_path, relative_path, size, sha256, file_type, status, trashed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    file_rec.id,
                    file_rec.directory_id,
                    file_rec.name,
                    file_rec.original_path,
                    file_rec.relative_path,
                    file_rec.size,
                    file_rec.sha256,
                    file_rec.file_type,
                    file_rec.status,
                    file_rec.trashed_at,
                    created_at,
                    updated_at,
                ),
            )

    def get_file_by_id(self, file_id: str) -> Optional[FileRecord]:
        """Fetches file record by exact ID."""
        cur = self.conn.execute("SELECT * FROM files WHERE id = ?;", (file_id,))
        row = cur.fetchone()
        return FileRecord.from_dict(dict(row)) if row else None

    def update_file_status(self, file_id: str, status: Status, sha256: Optional[str] = None) -> None:
        """Updates file status and optionally SHA-256."""
        with self.transaction():
            if sha256:
                self.conn.execute(
                    "UPDATE files SET status = ?, sha256 = ?, updated_at = ? WHERE id = ?;",
                    (status.value, sha256, _utc_now_str(), file_id),
                )
            else:
                self.conn.execute(
                    "UPDATE files SET status = ?, updated_at = ? WHERE id = ?;",
                    (status.value, _utc_now_str(), file_id),
                )

    def list_files(
        self,
        include_trashed: bool = False,
        directory_id: Optional[str] = None,
    ) -> List[FileRecord]:
        """Lists files with optional filtering."""
        params: List[Any] = []
        clauses: List[str] = []

        if not include_trashed:
            clauses.append("trashed_at IS NULL")

        if directory_id is not None:
            clauses.append("directory_id = ?")
            params.append(directory_id)

        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM files {where_clause} ORDER BY name ASC;"
        rows = self.conn.execute(query, params).fetchall()
        return [FileRecord.from_dict(dict(r)) for r in rows]

    def find_items_by_query(
        self, query: str, include_trashed: bool = False
    ) -> Tuple[List[FileRecord], List[DirectoryRecord]]:
        """Searches files and directories by ID, exact name, or partial match without ambiguity."""
        # Check exact ID first
        file_match = self.get_file_by_id(query)
        dir_match = self.get_directory_by_id(query)

        if file_match:
            return ([file_match], [])
        if dir_match:
            return ([], [dir_match])

        # Substring search
        escaped_query = f"%{query}%"
        trashed_filter = "" if include_trashed else "AND trashed_at IS NULL"

        file_rows = self.conn.execute(
            f"SELECT * FROM files WHERE (name LIKE ? OR relative_path LIKE ?) {trashed_filter};",
            (escaped_query, escaped_query),
        ).fetchall()

        dir_rows = self.conn.execute(
            f"SELECT * FROM directories WHERE (name LIKE ? OR original_path LIKE ?) {trashed_filter};",
            (escaped_query, escaped_query),
        ).fetchall()

        return (
            [FileRecord.from_dict(dict(r)) for r in file_rows],
            [DirectoryRecord.from_dict(dict(r)) for r in dir_rows],
        )

    # --------------------------------------------------------------------------
    # Chunk Operations
    # --------------------------------------------------------------------------

    def insert_chunk(self, chunk_rec: ChunkRecord) -> int:
        """Inserts a chunk record and returns auto-increment ID."""
        created_at = chunk_rec.created_at or _utc_now_str()
        with self.transaction():
            cur = self.conn.execute(
                """
                INSERT OR REPLACE INTO chunks (file_id, chunk_index, size, sha256, telegram_message_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    chunk_rec.file_id,
                    chunk_rec.chunk_index,
                    chunk_rec.size,
                    chunk_rec.sha256,
                    chunk_rec.telegram_message_id,
                    chunk_rec.status,
                    created_at,
                ),
            )
            return cur.lastrowid

    def update_chunk_telegram_id(
        self, file_id: str, chunk_index: int, telegram_message_id: int, status: Status = Status.COMPLETED
    ) -> None:
        """Updates Telegram message ID and status for a chunk."""
        with self.transaction():
            self.conn.execute(
                """
                UPDATE chunks
                SET telegram_message_id = ?, status = ?
                WHERE file_id = ? AND chunk_index = ?;
                """,
                (telegram_message_id, status.value, file_id, chunk_index),
            )

    def get_chunks_for_file(self, file_id: str) -> List[ChunkRecord]:
        """Fetches all chunks for a file ordered by index."""
        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index ASC;",
            (file_id,),
        ).fetchall()
        return [ChunkRecord.from_dict(dict(r)) for r in rows]

    # --------------------------------------------------------------------------
    # Advanced Storage Features: Rename, Move, Trash, Restore, Purge
    # --------------------------------------------------------------------------

    def rename_item(self, item_id: str, new_name: str) -> bool:
        """Renames a file or directory instantly in metadata."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("New name cannot be empty.")

        with self.transaction():
            # Try file
            cur = self.conn.execute("SELECT id FROM files WHERE id = ?;", (item_id,))
            if cur.fetchone():
                self.conn.execute(
                    "UPDATE files SET name = ?, updated_at = ? WHERE id = ?;",
                    (new_name, _utc_now_str(), item_id),
                )
                return True

            # Try directory
            cur = self.conn.execute("SELECT id FROM directories WHERE id = ?;", (item_id,))
            if cur.fetchone():
                self.conn.execute(
                    "UPDATE directories SET name = ? WHERE id = ?;",
                    (new_name, item_id),
                )
                return True

        raise ItemNotFoundError(item_id)

    def move_item(self, file_id: str, target_directory_id: Optional[str]) -> bool:
        """Moves a file to a different logical directory."""
        if target_directory_id is not None:
            dir_rec = self.get_directory_by_id(target_directory_id)
            if not dir_rec:
                raise ItemNotFoundError(f"Target directory '{target_directory_id}' not found.")

        with self.transaction():
            cur = self.conn.execute("SELECT id FROM files WHERE id = ?;", (file_id,))
            if not cur.fetchone():
                raise ItemNotFoundError(file_id)

            self.conn.execute(
                "UPDATE files SET directory_id = ?, updated_at = ? WHERE id = ?;",
                (target_directory_id, _utc_now_str(), file_id),
            )
            return True

    def trash_item(self, item_id: str) -> bool:
        """Soft-deletes a file or directory by marking trashed_at."""
        now_ts = _utc_now_str()
        with self.transaction():
            # Check file
            cur = self.conn.execute("SELECT id, trashed_at FROM files WHERE id = ?;", (item_id,))
            file_row = cur.fetchone()
            if file_row:
                if file_row["trashed_at"]:
                    raise AlreadyTrashedError(item_id)
                self.conn.execute(
                    "UPDATE files SET trashed_at = ?, status = ?, updated_at = ? WHERE id = ?;",
                    (now_ts, Status.TRASHED.value, now_ts, item_id),
                )
                return True

            # Check directory
            cur = self.conn.execute("SELECT id, trashed_at FROM directories WHERE id = ?;", (item_id,))
            dir_row = cur.fetchone()
            if dir_row:
                if dir_row["trashed_at"]:
                    raise AlreadyTrashedError(item_id)
                self.conn.execute("UPDATE directories SET trashed_at = ? WHERE id = ? OR root_id = ?;", (now_ts, item_id, item_id))
                # Trash nested files in root directory and all its subdirectories
                self.conn.execute(
                    """
                    UPDATE files SET trashed_at = ?, status = ?, updated_at = ?
                    WHERE directory_id IN (SELECT id FROM directories WHERE id = ? OR root_id = ?);
                    """,
                    (now_ts, Status.TRASHED.value, now_ts, item_id, item_id),
                )
                return True

        raise ItemNotFoundError(item_id)

    def restore_item(self, item_id: str) -> bool:
        """Restores a soft-deleted item from trash."""
        now_ts = _utc_now_str()
        with self.transaction():
            # Check file
            cur = self.conn.execute("SELECT id, trashed_at FROM files WHERE id = ?;", (item_id,))
            file_row = cur.fetchone()
            if file_row:
                if not file_row["trashed_at"]:
                    raise NotTrashedError(item_id)
                self.conn.execute(
                    "UPDATE files SET trashed_at = NULL, status = ?, updated_at = ? WHERE id = ?;",
                    (Status.COMPLETED.value, now_ts, item_id),
                )
                return True

            # Check directory
            cur = self.conn.execute("SELECT id, trashed_at FROM directories WHERE id = ?;", (item_id,))
            dir_row = cur.fetchone()
            if dir_row:
                if not dir_row["trashed_at"]:
                    raise NotTrashedError(item_id)
                self.conn.execute("UPDATE directories SET trashed_at = NULL WHERE id = ? OR root_id = ?;", (item_id, item_id))
                self.conn.execute(
                    """
                    UPDATE files SET trashed_at = NULL, status = ?, updated_at = ?
                    WHERE directory_id IN (SELECT id FROM directories WHERE id = ? OR root_id = ?);
                    """,
                    (Status.COMPLETED.value, now_ts, item_id, item_id),
                )
                return True

        raise ItemNotFoundError(item_id)

    def list_trashed_items(self) -> Tuple[List[FileRecord], List[DirectoryRecord]]:
        """Returns all items currently in the trash."""
        file_rows = self.conn.execute(
            "SELECT * FROM files WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC;"
        ).fetchall()
        dir_rows = self.conn.execute(
            "SELECT * FROM directories WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC;"
        ).fetchall()
        return (
            [FileRecord.from_dict(dict(r)) for r in file_rows],
            [DirectoryRecord.from_dict(dict(r)) for r in dir_rows],
        )

    def delete_file_permanently(self, file_id: str) -> List[int]:
        """Deletes file from SQLite and returns list of Telegram message IDs to prune."""
        with self.transaction():
            chunks = self.get_chunks_for_file(file_id)
            message_ids = [c.telegram_message_id for c in chunks if c.telegram_message_id is not None]
            self.conn.execute("DELETE FROM files WHERE id = ?;", (file_id,))
            return message_ids

    def delete_directory_permanently(self, dir_id: str) -> List[int]:
        """Deletes directory and all contained files/subdirectories; returns all Telegram message IDs."""
        with self.transaction():
            _, all_dirs, all_files = self.get_directory_tree(dir_id, include_trashed=True)
            all_message_ids: List[int] = []
            for f in all_files:
                chunks = self.get_chunks_for_file(f.id)
                all_message_ids.extend([c.telegram_message_id for c in chunks if c.telegram_message_id is not None])

            # Delete any subdirectories explicitly tied to this root
            self.conn.execute("DELETE FROM directories WHERE root_id = ?;", (dir_id,))
            self.conn.execute("DELETE FROM directories WHERE id = ?;", (dir_id,))
            return all_message_ids

    def export_metadata(self, item_id: Optional[str] = None) -> Dict[str, Any]:
        """Exports metadata package for backup or sharing."""
        export_data: Dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "exported_at": _utc_now_str(),
            "directories": [],
            "files": [],
            "chunks": [],
        }

        if item_id:
            file_rec = self.get_file_by_id(item_id)
            if file_rec:
                export_data["files"].append(file_rec.to_dict())
                for chunk in self.get_chunks_for_file(file_rec.id):
                    export_data["chunks"].append(chunk.to_dict())
                return export_data

            dir_rec = self.get_directory_by_id(item_id)
            if dir_rec:
                _, all_dirs, all_files = self.get_directory_tree(dir_rec.id, include_trashed=True)
                for d in all_dirs:
                    export_data["directories"].append(d.to_dict())
                for f in all_files:
                    export_data["files"].append(f.to_dict())
                    for chunk in self.get_chunks_for_file(f.id):
                        export_data["chunks"].append(chunk.to_dict())
                return export_data

            raise ItemNotFoundError(item_id)

        # Full export
        for d in self.list_directories(include_trashed=True):
            export_data["directories"].append(d.to_dict())
        for f in self.list_files(include_trashed=True):
            export_data["files"].append(f.to_dict())
            for chunk in self.get_chunks_for_file(f.id):
                export_data["chunks"].append(chunk.to_dict())

        return export_data

    def import_metadata(self, data: Dict[str, Any]) -> int:
        """Imports metadata package into SQLite without touching Telegram."""
        imported_count = 0
        with self.transaction():
            for d in data.get("directories", []):
                rec = DirectoryRecord.from_dict(d)
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO directories (id, parent_id, root_id, name, original_path, relative_path, trashed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (rec.id, rec.parent_id, rec.root_id, rec.name, rec.original_path, rec.relative_path, rec.trashed_at, rec.created_at),
                )
                imported_count += 1

            for f in data.get("files", []):
                f_rec = FileRecord.from_dict(f)
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO files (id, directory_id, name, original_path, relative_path, size, sha256, file_type, status, trashed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        f_rec.id,
                        f_rec.directory_id,
                        f_rec.name,
                        f_rec.original_path,
                        f_rec.relative_path,
                        f_rec.size,
                        f_rec.sha256,
                        f_rec.file_type,
                        f_rec.status,
                        f_rec.trashed_at,
                        f_rec.created_at,
                        f_rec.updated_at,
                    ),
                )
                imported_count += 1

            for c in data.get("chunks", []):
                c_rec = ChunkRecord.from_dict(c)
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO chunks (file_id, chunk_index, size, sha256, telegram_message_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        c_rec.file_id,
                        c_rec.chunk_index,
                        c_rec.size,
                        c_rec.sha256,
                        c_rec.telegram_message_id,
                        c_rec.status,
                        c_rec.created_at,
                    ),
                )
        return imported_count
