"""Domain exception hierarchy for TeleDrive 2.0."""


class TeleDriveError(Exception):
    """Base exception for all TeleDrive errors."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class ConfigurationError(TeleDriveError):
    """Raised when configuration is missing, unreadable, or invalid."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


class DatabaseError(TeleDriveError):
    """Raised on SQLite database failures, constraints, or query errors."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=1)


class TelegramServiceError(TeleDriveError):
    """Raised on Telegram / Telethon client connection, auth, or API errors."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


class TransferError(TeleDriveError):
    """Raised on network timeout, chunk transmission, or stream interruption."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=4)


class IntegrityError(TeleDriveError):
    """Raised when SHA-256 checksum or file size does not match expected value."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=5)


class ItemNotFoundError(TeleDriveError):
    """Raised when a requested file or directory is not found in the storage database."""

    def __init__(self, query: str):
        super().__init__(f"Item '{query}' not found in TeleDrive storage.", exit_code=1)
        self.query = query


class AmbiguousQueryError(TeleDriveError):
    """Raised when a search query matches multiple items and cannot be uniquely resolved."""

    def __init__(self, query: str, matches: list):
        formatted = "\n  • " + "\n  • ".join(matches) if matches else ""
        super().__init__(
            f"Query '{query}' matched multiple items:{formatted}\nPlease provide more characters or specify the full ID/name.",
            exit_code=1,
        )
        self.query = query
        self.matches = matches


class FileExistsSafetyError(TeleDriveError):
    """Raised when destination path already exists and --force was not specified."""

    def __init__(self, path: str):
        super().__init__(
            f"Destination file '{path}' already exists. Use --force to overwrite.",
            exit_code=1,
        )
        self.path = path


class AlreadyTrashedError(TeleDriveError):
    """Raised when trying to trash an item that is already in trash."""

    def __init__(self, item_id: str):
        super().__init__(f"Item '{item_id}' is already in the trash.", exit_code=1)


class NotTrashedError(TeleDriveError):
    """Raised when trying to restore an item that is not in trash."""

    def __init__(self, item_id: str):
        super().__init__(f"Item '{item_id}' is not in the trash.", exit_code=1)
