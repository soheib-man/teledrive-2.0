"""Backward compatibility shim for legacy telegram.py."""

import asyncio
from pathlib import Path
from teledrive.config import Config
from teledrive.services import StorageService

class Telegram:
    """Legacy Telegram wrapper delegating to modern StorageService."""

    def __init__(self):
        self._cfg = Config.load(allow_missing=True)
        self._service = StorageService(self._cfg)

    def list_files(self):
        files = self._service.db.list_files()
        dirs = self._service.db.list_directories()
        from teledrive.ui import render_file_table
        render_file_table(files, dirs)

    def download_file(self, file_query: str):
        asyncio.run(self._service.download_file(file_query))

    def remove_file(self, file_query: str):
        asyncio.run(self._service.purge(file_query))

    def upload_file(self, current_dir: str, file_path: str, file_name: str):
        p = Path(current_dir) / file_path
        asyncio.run(self._service.upload_file(p))

    def upload_directory(self, current_dir: str, dir_path: str, dir_name: str):
        p = Path(current_dir) / dir_path
        asyncio.run(self._service.upload_directory(p))

    def download_directory(self, dir_query: str):
        asyncio.run(self._service.download_directory(dir_query))