"""Backward compatibility shim for legacy db.py."""

from pathlib import Path
from teledrive.database import Database as ModernDatabase
from teledrive.models import FileRecord

class Database:
    """Legacy wrapper delegating to modern normalized Database."""

    def __init__(self, db_name: str):
        self._db = ModernDatabase(Path(db_name))

    def fetch(self):
        files = self._db.list_files()
        # Return tuples compatible with legacy schema: (id, name, path, size, chunks_json, type, uploaded)
        rows = []
        for f in files:
            chunks = self._db.get_chunks_for_file(f.id)
            chunks_json = str([c.chunk_index for c in chunks])
            rows.append((f.id, f.name, f.original_path, f.size, chunks_json, f.file_type, f.created_at))
        return rows

    def insert(self, id, file_name, file_path, file_size, chunks, item_type):
        rec = FileRecord(
            id=str(id),
            name=str(file_name),
            original_path=str(file_path),
            relative_path=str(file_name),
            size=int(file_size),
            sha256="",
            file_type=str(item_type),
        )
        self._db.insert_file(rec)

    def remove(self, id):
        self._db.delete_file_permanently(str(id))

    def get_file(self, id):
        f = self._db.get_file_by_id(str(id))
        if not f:
            return []
        chunks = self._db.get_chunks_for_file(f.id)
        return [(f.id, f.name, f.original_path, f.size, str(chunks), f.file_type, f.created_at)]

    def find_file_by_name_or_path_or_id(self, file_query):
        files, dirs = self._db.find_items_by_query(str(file_query))
        rows = []
        for f in files:
            chunks = self._db.get_chunks_for_file(f.id)
            rows.append((f.id, f.name, f.original_path, f.size, str(chunks), f.file_type, f.created_at))
        for d in dirs:
            rows.append((d.id, d.name, d.original_path, 0, "[]", "dir", d.created_at))
        return rows