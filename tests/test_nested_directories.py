"""Automated tests for deep recursive nested directory structures and empty folder preservation."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from teledrive.config import Config
from teledrive.services import StorageService
from teledrive.ui import render_directory_tree


class TestNestedDirectories(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.db_path = self.dir_path / "nested_test.db"
        self.cfg = Config(
            telegram_api_id=12345,
            telegram_api_hash="hash",
            phone_number="+123456789",
            db_file=self.db_path,
            temp_dir=self.dir_path / "temp",
            chunk_size=500,
        )
        self.service = StorageService(self.cfg)
        self.service.telegram._connected = True

        # Mock Telegram upload_chunk & download_chunk
        self.uploaded_chunks = {}
        self.msg_counter = 1000

        async def _mock_upload(chunk_path, caption="", progress_callback=None):
            self.msg_counter += 1
            data = Path(chunk_path).read_bytes()
            self.uploaded_chunks[self.msg_counter] = data
            return self.msg_counter

        async def _mock_download(telegram_message_id, destination_path, progress_callback=None):
            data = self.uploaded_chunks.get(telegram_message_id, b"")
            Path(destination_path).write_bytes(data)
            return Path(destination_path)

        self.service.telegram.upload_chunk = AsyncMock(side_effect=_mock_upload)
        self.service.telegram.download_chunk = AsyncMock(side_effect=_mock_download)

    def tearDown(self):
        self.service.close()
        self.temp_dir.cleanup()

    def test_nested_directory_upload_download_preserves_structure(self):
        async def _run():
            # 1. Create a deep nested directory structure with an empty folder
            # test_project/
            # ├── README.md
            # └── src/
            #     ├── main.py
            #     └── components/
            #         ├── button.py
            #         └── empty_assets/  <-- EMPTY FOLDER!

            source_root = self.dir_path / "test_project"
            source_root.mkdir()
            (source_root / "README.md").write_text("# Test Project", encoding="utf-8")

            src_dir = source_root / "src"
            src_dir.mkdir()
            (src_dir / "main.py").write_text("print('Hello from main')", encoding="utf-8")

            components_dir = src_dir / "components"
            components_dir.mkdir()
            (components_dir / "button.py").write_text("def render_button(): pass", encoding="utf-8")

            empty_assets_dir = components_dir / "empty_assets"
            empty_assets_dir.mkdir()

            # 2. Upload directory
            dir_rec, uploaded_files = await self.service.upload_directory(source_root)
            self.assertEqual(dir_rec.name, "test_project")
            self.assertEqual(len(uploaded_files), 3)

            # 3. Query directory tree
            tree_data = self.service.get_tree(dir_rec.id)
            self.assertEqual(tree_data["root"]["name"], "test_project")
            self.assertEqual(len(tree_data["files"]), 3)
            # Root + src + components + empty_assets = 4 directories
            self.assertEqual(len(tree_data["subdirectories"]), 4)

            # Check that render_directory_tree executes cleanly
            render_directory_tree(tree_data)

            # 4. Download directory into a new destination
            download_dest = self.dir_path / "restored_output"
            restored_path = await self.service.download_directory(dir_rec.id, destination_dir=download_dest)

            # 5. Verify restored structure matches 100%
            self.assertTrue(restored_path.is_dir())
            self.assertTrue((restored_path / "README.md").is_file())
            self.assertEqual((restored_path / "README.md").read_text(encoding="utf-8"), "# Test Project")

            self.assertTrue((restored_path / "src" / "main.py").is_file())
            self.assertEqual((restored_path / "src" / "main.py").read_text(encoding="utf-8"), "print('Hello from main')")

            self.assertTrue((restored_path / "src" / "components" / "button.py").is_file())
            self.assertEqual(
                (restored_path / "src" / "components" / "button.py").read_text(encoding="utf-8"),
                "def render_button(): pass",
            )

            # CRITICAL CHECK: Empty subdirectory MUST exist!
            self.assertTrue(
                (restored_path / "src" / "components" / "empty_assets").is_dir(),
                "Empty subdirectory was not preserved!",
            )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
