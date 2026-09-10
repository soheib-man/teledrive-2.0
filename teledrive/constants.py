"""Constants and enumeration definitions for TeleDrive 2.0."""

import enum

# CLI Exit Codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_CONFIG_AUTH = 3
EXIT_TRANSFER = 4
EXIT_INTEGRITY = 5

# Chunking & Streaming Sizes
STREAM_BUFFER_SIZE = 64 * 1024              # 64 KB streaming buffer for hashing and slicing
DEFAULT_CHUNK_SIZE = 50 * 1024 * 1024       # 50 MB default chunk size
MAX_TELEGRAM_CHUNK_SIZE = 2000 * 1024 * 1024  # 2 GB Telegram max file size

# Retries & Network
MAX_TRANSFER_RETRIES = 5
INITIAL_RETRY_DELAY_SEC = 2.0
MAX_RETRY_DELAY_SEC = 60.0

# Database
SCHEMA_VERSION = 2
DEFAULT_DB_FILENAME = "teledrive.db"
DEFAULT_SESSION_NAME = "teledrive.session"
DEFAULT_TEMP_DIRNAME = ".teledrive_temp"

# File & Transfer Statuses
class Status(str, enum.Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    TRASHED = "trashed"

# Item Types
class ItemType(str, enum.Enum):
    FILE = "file"
    DIRECTORY = "directory"
