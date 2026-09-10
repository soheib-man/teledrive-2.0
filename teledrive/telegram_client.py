"""Asynchronous Telethon client service with direct message-ID indexing and safe deletion."""

import asyncio
import logging
from pathlib import Path
from typing import Callable, List, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from teledrive.constants import (
    INITIAL_RETRY_DELAY_SEC,
    MAX_RETRY_DELAY_SEC,
    MAX_TRANSFER_RETRIES,
)
from teledrive.exceptions import TelegramServiceError, TransferError

logger = logging.getLogger("teledrive.telegram")


class TelegramService:
    """Async wrapper managing the Telethon client lifecycle, direct message ID transfers, and safe pruning."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: Path,
        phone_number: str,
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = Path(session_path).resolve()
        self.phone_number = phone_number
        self.session_path.parent.mkdir(parents=True, exist_ok=True)

        self._client = TelegramClient(
            str(self.session_path),
            self.api_id,
            self.api_hash,
        )
        self._connected = False

    @property
    def client(self) -> TelegramClient:
        return self._client

    async def connect(self) -> None:
        """Connects and authenticates with Telegram once for the session lifecycle."""
        if not self._connected:
            try:
                await self._client.start(phone=self.phone_number)
                self._connected = True
                logger.debug("Connected to Telegram client session.")
            except RPCError as exc:
                raise TelegramServiceError(f"Telegram authentication error: {exc}")
            except Exception as exc:
                raise TelegramServiceError(f"Failed to connect to Telegram: {exc}")

    async def disconnect(self) -> None:
        """Disconnects the Telegram client gracefully."""
        if self._connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._connected = False
            logger.debug("Disconnected from Telegram client session.")

    async def __aenter__(self) -> "TelegramService":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    async def upload_chunk(
        self,
        chunk_path: Path,
        caption: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Uploads a chunk file to Saved Messages ("me") with exponential backoff retries.
        Returns the exact Telegram message ID.
        """
        await self.connect()
        chunk_path = Path(chunk_path).resolve()
        delay = INITIAL_RETRY_DELAY_SEC

        for attempt in range(1, MAX_TRANSFER_RETRIES + 1):
            try:
                message = await self._client.send_file(
                    "me",
                    str(chunk_path),
                    caption=caption,
                    progress_callback=progress_callback,
                )
                if not message or not message.id:
                    raise TransferError("Telegram returned an empty message object upon upload.")
                return message.id

            except FloodWaitError as exc:
                wait_sec = min(exc.seconds, MAX_RETRY_DELAY_SEC)
                logger.warning(f"Telegram FloodWait: sleeping for {wait_sec}s (attempt {attempt}/{MAX_TRANSFER_RETRIES})...")
                await asyncio.sleep(wait_sec)

            except (RPCError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(f"Upload error: {exc}. Retrying in {delay}s (attempt {attempt}/{MAX_TRANSFER_RETRIES})...")
                if attempt == MAX_TRANSFER_RETRIES:
                    raise TransferError(f"Failed to upload chunk '{chunk_path.name}' after {MAX_TRANSFER_RETRIES} attempts: {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY_SEC)

        raise TransferError(f"Upload failed for chunk '{chunk_path.name}'.")

    async def download_chunk(
        self,
        telegram_message_id: int,
        destination_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """
        Downloads a chunk directly by Telegram message ID without text/caption searching.
        """
        await self.connect()
        destination_path = Path(destination_path).resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        delay = INITIAL_RETRY_DELAY_SEC

        for attempt in range(1, MAX_TRANSFER_RETRIES + 1):
            try:
                # Direct lookup by ID
                message = await self._client.get_messages("me", ids=telegram_message_id)

                if not message:
                    raise TransferError(f"Telegram message #{telegram_message_id} was not found on the server.")
                if not message.media:
                    raise TransferError(f"Telegram message #{telegram_message_id} does not contain file media.")

                downloaded = await self._client.download_media(
                    message,
                    file=str(destination_path),
                    progress_callback=progress_callback,
                )
                if not downloaded:
                    raise TransferError(f"Failed to download media for message #{telegram_message_id}.")

                return destination_path

            except FloodWaitError as exc:
                wait_sec = min(exc.seconds, MAX_RETRY_DELAY_SEC)
                logger.warning(f"Telegram FloodWait: sleeping for {wait_sec}s (attempt {attempt}/{MAX_TRANSFER_RETRIES})...")
                await asyncio.sleep(wait_sec)

            except (RPCError, OSError, asyncio.TimeoutError) as exc:
                logger.warning(f"Download error: {exc}. Retrying in {delay}s (attempt {attempt}/{MAX_TRANSFER_RETRIES})...")
                if attempt == MAX_TRANSFER_RETRIES:
                    raise TransferError(f"Failed to download chunk #{telegram_message_id} after {MAX_TRANSFER_RETRIES} attempts: {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY_SEC)

        raise TransferError(f"Download failed for message #{telegram_message_id}.")

    async def verify_chunk(self, telegram_message_id: int) -> bool:
        """Checks if a message ID exists in Saved Messages and contains valid media."""
        await self.connect()
        try:
            message = await self._client.get_messages("me", ids=telegram_message_id)
            return bool(message and message.media)
        except Exception:
            return False

    async def delete_messages_safely(self, message_ids: List[int]) -> int:
        """
        Safely deletes ONLY the exact Telegram message IDs provided.
        Batches deletions to avoid rate limiting.
        NEVER performs text searches or touches personal messages!
        """
        if not message_ids:
            return 0

        await self.connect()
        # Filter valid integer IDs
        valid_ids = [int(mid) for mid in message_ids if mid is not None and int(mid) > 0]
        if not valid_ids:
            return 0

        # Batch in chunks of 100
        batch_size = 100
        deleted_count = 0

        for i in range(0, len(valid_ids), batch_size):
            batch = valid_ids[i : i + batch_size]
            try:
                await self._client.delete_messages("me", batch)
                deleted_count += len(batch)
            except Exception as exc:
                logger.warning(f"Warning: Failed to delete Telegram message batch {batch}: {exc}")

        return deleted_count
