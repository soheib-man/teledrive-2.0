"""Tests for TelegramService and StorageService transfer workflows using Telethon mocks."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from teledrive.config import Config
from teledrive.models import FileRecord
from teledrive.services import StorageService
from teledrive.telegram_client import TelegramService


class TestTelegramMocks(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upload_chunk_captures_message_id(self):
        async def _run():
            svc = TelegramService(12345, "hash", self.dir_path / "sess", "+123456789")
            try:
                svc._connected = True

                fake_msg = MagicMock()
                fake_msg.id = 555444
                svc._client.send_file = AsyncMock(return_value=fake_msg)

                chunk_file = self.dir_path / "test.chunk"
                chunk_file.write_bytes(b"chunk content")

                msg_id = await svc.upload_chunk(chunk_file, caption="CAPTION")
                self.assertEqual(msg_id, 555444)
                svc._client.send_file.assert_awaited_once()
            finally:
                await svc.disconnect()

        asyncio.run(_run())

    def test_safe_delete_passes_exact_message_ids_only(self):
        async def _run():
            svc = TelegramService(12345, "hash", self.dir_path / "sess", "+123456789")
            try:
                svc._connected = True
                svc._client.delete_messages = AsyncMock()

                target_ids = [1001, 1002, 1003]
                deleted = await svc.delete_messages_safely(target_ids)

                self.assertEqual(deleted, 3)
                svc._client.delete_messages.assert_awaited_once_with("me", [1001, 1002, 1003])
            finally:
                await svc.disconnect()

        asyncio.run(_run())

    def test_storage_service_upload_flow_with_mock(self):
        async def _run():
            cfg = Config(
                telegram_api_id=12345,
                telegram_api_hash="hash",
                phone_number="+123456789",
                db_file=self.dir_path / "storage.db",
                temp_dir=self.dir_path / "temp",
                chunk_size=100,
            )
            service = StorageService(cfg)
            service.telegram._connected = True

            # Mock send_file to return incrementing message IDs
            counter = 100
            async def _fake_send(*args, **kwargs):
                nonlocal counter
                counter += 1
                m = MagicMock()
                m.id = counter
                return m

            service.telegram._client.send_file = AsyncMock(side_effect=_fake_send)

            test_file = self.dir_path / "demo.bin"
            test_file.write_bytes(b"A" * 250)  # Will produce 3 chunks with chunk_size=100

            file_rec = await service.upload_file(test_file)
            self.assertEqual(file_rec.name, "demo.bin")
            self.assertEqual(file_rec.status, "completed")

            chunks = service.db.get_chunks_for_file(file_rec.id)
            self.assertEqual(len(chunks), 3)
            self.assertEqual([c.telegram_message_id for c in chunks], [101, 102, 103])
            service.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
