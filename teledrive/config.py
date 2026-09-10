"""Configuration management for TeleDrive 2.0 with zero import-time side effects."""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from teledrive.constants import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_DB_FILENAME,
    DEFAULT_SESSION_NAME,
    DEFAULT_TEMP_DIRNAME,
)
from teledrive.exceptions import ConfigurationError


class Config:
    """Manages application settings, path resolution, and secret sanitization."""

    def __init__(
        self,
        telegram_api_id: Optional[int] = None,
        telegram_api_hash: Optional[str] = None,
        phone_number: Optional[str] = None,
        db_file: Optional[Path] = None,
        session_path: Optional[Path] = None,
        temp_dir: Optional[Path] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        verbose: bool = False,
        config_source: Optional[Path] = None,
    ):
        self.telegram_api_id = telegram_api_id
        self.telegram_api_hash = telegram_api_hash
        self.phone_number = phone_number
        self.db_file = db_file or (Path.cwd() / DEFAULT_DB_FILENAME)
        self.session_path = session_path or (Path.cwd() / DEFAULT_SESSION_NAME)
        self.temp_dir = temp_dir or (Path.cwd() / DEFAULT_TEMP_DIRNAME)
        self.chunk_size = chunk_size
        self.verbose = verbose
        self.config_source = config_source

    def validate(self) -> None:
        """Validates that necessary credentials exist for Telegram operations."""
        missing = []
        if not self.telegram_api_id:
            missing.append("telegram_api_id")
        if not self.telegram_api_hash:
            missing.append("telegram_api_hash")
        if not self.phone_number:
            missing.append("phone_number")

        if missing:
            source_info = f" in '{self.config_source}'" if self.config_source else ""
            raise ConfigurationError(
                f"Missing required configuration setting(s){source_info}: {', '.join(missing)}. "
                f"Please update your config.json with your Telegram API credentials."
            )

    def to_safe_dict(self) -> Dict[str, Any]:
        """Returns configuration dictionary with secrets masked for safe logging/display."""
        masked_phone = self.phone_number
        if masked_phone and len(masked_phone) > 5:
            masked_phone = f"{masked_phone[:3]}***{masked_phone[-2:]}"

        return {
            "telegram_api_id": self.telegram_api_id,
            "telegram_api_hash": "***REDACTED***" if self.telegram_api_hash else None,
            "phone_number": masked_phone,
            "db_file": str(self.db_file),
            "session_path": str(self.session_path),
            "temp_dir": str(self.temp_dir),
            "chunk_size": self.chunk_size,
            "verbose": self.verbose,
            "config_source": str(self.config_source) if self.config_source else None,
        }

    @classmethod
    def find_config_file(cls, explicit_path: Optional[str] = None) -> Optional[Path]:
        """Searches standard paths for a valid config file."""
        candidates: List[Path] = []

        if explicit_path:
            p = Path(explicit_path).expanduser().resolve()
            if p.is_file():
                return p
            raise ConfigurationError(f"Specified configuration file not found: {explicit_path}")

        # Check environment variables
        for env_var in ["TELEDRIVE_CONFIG", "TELESYNC_CONFIG"]:
            env_val = os.environ.get(env_var)
            if env_val:
                p = Path(env_val).expanduser().resolve()
                if p.is_file():
                    return p

        # Check current working directory
        for name in ["config.json", "teledrive.json", "telesync.json"]:
            cwd_path = Path.cwd() / name
            if cwd_path.is_file():
                candidates.append(cwd_path)

        # Check script / package root directory
        package_root = Path(__file__).resolve().parent.parent
        for name in ["config.json", "example.config.json"]:
            root_path = package_root / name
            if root_path.is_file():
                candidates.append(root_path)

        # Check user config directory (~/.config/teledrive/config.json)
        user_config = Path.home() / ".config" / "teledrive" / "config.json"
        if user_config.is_file():
            candidates.append(user_config)

        for candidate in candidates:
            # Return first non-example candidate if possible
            if "example" not in candidate.name and candidate.is_file():
                return candidate.resolve()

        if candidates:
            return candidates[0].resolve()

        return None

    @classmethod
    def load(cls, explicit_path: Optional[str] = None, allow_missing: bool = False) -> "Config":
        """Loads configuration from file, falling back to defaults if allowed."""
        config_path = cls.find_config_file(explicit_path)

        if not config_path:
            if allow_missing:
                return cls()
            raise ConfigurationError(
                "Could not find 'config.json'. Please create one from 'example.config.json' "
                "or specify its location with --config <path> or TELEDRIVE_CONFIG environment variable."
            )

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"Failed to parse config file '{config_path}': {exc}")
        except OSError as exc:
            raise ConfigurationError(f"Could not read config file '{config_path}': {exc}")

        # Resolve paths relative to config file directory if not absolute
        base_dir = config_path.parent

        db_path = data.get("db_file") or DEFAULT_DB_FILENAME
        db_file = Path(db_path)
        if not db_file.is_absolute():
            db_file = (base_dir / db_file).resolve()

        session_name = data.get("session_name") or DEFAULT_SESSION_NAME
        session_path = Path(session_name)
        if not session_path.is_absolute():
            session_path = (base_dir / session_path).resolve()

        temp_name = data.get("temp_dir") or DEFAULT_TEMP_DIRNAME
        temp_dir = Path(temp_name)
        if not temp_dir.is_absolute():
            temp_dir = (base_dir / temp_dir).resolve()

        api_id_val = data.get("telegram_api_id")
        try:
            api_id = int(api_id_val) if api_id_val else None
        except (ValueError, TypeError):
            raise ConfigurationError(f"Invalid 'telegram_api_id' in '{config_path}'. Must be an integer.")

        return cls(
            telegram_api_id=api_id,
            telegram_api_hash=data.get("telegram_api_hash") or None,
            phone_number=str(data.get("phone_number")).strip() if data.get("phone_number") else None,
            db_file=db_file,
            session_path=session_path,
            temp_dir=temp_dir,
            chunk_size=int(data.get("chunk_size", DEFAULT_CHUNK_SIZE)),
            verbose=bool(data.get("verbose", False)),
            config_source=config_path,
        )
