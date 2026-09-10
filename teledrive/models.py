"""Data models and records for TeleDrive 2.0."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class DirectoryRecord:
    """Represents a logical or physical directory structure in TeleDrive."""

    id: str
    name: str
    original_path: str
    parent_id: Optional[str] = None
    root_id: Optional[str] = None
    relative_path: str = ""
    trashed_at: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "original_path": self.original_path,
            "parent_id": self.parent_id,
            "root_id": self.root_id,
            "relative_path": self.relative_path,
            "trashed_at": self.trashed_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DirectoryRecord":
        return cls(
            id=data["id"],
            name=data["name"],
            original_path=data["original_path"],
            parent_id=data.get("parent_id"),
            root_id=data.get("root_id"),
            relative_path=data.get("relative_path", ""),
            trashed_at=data.get("trashed_at"),
            created_at=data.get("created_at", ""),
        )


@dataclass
class FileRecord:
    """Represents a stored file and its cryptographic/storage metadata."""

    id: str
    name: str
    original_path: str
    relative_path: str
    size: int
    sha256: str
    file_type: str = "file"
    directory_id: Optional[str] = None
    status: str = "completed"
    trashed_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "original_path": self.original_path,
            "relative_path": self.relative_path,
            "size": self.size,
            "sha256": self.sha256,
            "file_type": self.file_type,
            "directory_id": self.directory_id,
            "status": self.status,
            "trashed_at": self.trashed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileRecord":
        return cls(
            id=data["id"],
            name=data["name"],
            original_path=data["original_path"],
            relative_path=data.get("relative_path", data["name"]),
            size=data["size"],
            sha256=data["sha256"],
            file_type=data.get("file_type", "file"),
            directory_id=data.get("directory_id"),
            status=data.get("status", "completed"),
            trashed_at=data.get("trashed_at"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass
class ChunkRecord:
    """Represents an individually uploaded slice of a file in Telegram."""

    file_id: str
    chunk_index: int
    size: int
    sha256: str
    id: Optional[int] = None
    telegram_message_id: Optional[int] = None
    status: str = "completed"
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "file_id": self.file_id,
            "chunk_index": self.chunk_index,
            "size": self.size,
            "sha256": self.sha256,
            "telegram_message_id": self.telegram_message_id,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkRecord":
        return cls(
            id=data.get("id"),
            file_id=data["file_id"],
            chunk_index=data["chunk_index"],
            size=data["size"],
            sha256=data["sha256"],
            telegram_message_id=data.get("telegram_message_id"),
            status=data.get("status", "completed"),
            created_at=data.get("created_at", ""),
        )


@dataclass
class TransferProgress:
    """Tracks real-time progress of a file transfer."""

    file_name: str
    total_bytes: int
    transferred_bytes: int = 0
    current_chunk: int = 0
    total_chunks: int = 1
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
