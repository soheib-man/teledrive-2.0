"""Tests for configuration resolution, validation, and secret sanitization."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from teledrive.config import Config
from teledrive.exceptions import ConfigurationError


class TestConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_config_defaults_without_import_crash(self):
        cfg = Config()
        self.assertIsNone(cfg.telegram_api_id)
        self.assertIsNone(cfg.telegram_api_hash)
        self.assertFalse(cfg.verbose)
        self.assertTrue(cfg.chunk_size > 0)

    def test_config_validation_raises_on_missing_keys(self):
        cfg = Config()
        with self.assertRaises(ConfigurationError) as cm:
            cfg.validate()
        self.assertIn("telegram_api_id", str(cm.exception))

    def test_config_validation_succeeds_when_populated(self):
        cfg = Config(
            telegram_api_id=123456,
            telegram_api_hash="fake_hash_123456",
            phone_number="+1234567890",
        )
        # Should not raise
        cfg.validate()

    def test_config_secret_masking(self):
        cfg = Config(
            telegram_api_id=99999,
            telegram_api_hash="secret_api_hash_abc",
            phone_number="+1234567890",
        )
        safe = cfg.to_safe_dict()
        self.assertEqual(safe["telegram_api_hash"], "***REDACTED***")
        self.assertIn("***", safe["phone_number"])
        self.assertEqual(safe["telegram_api_id"], 99999)

    def test_config_load_from_json(self):
        config_file = self.dir_path / "custom_config.json"
        config_data = {
            "telegram_api_id": 112233,
            "telegram_api_hash": "hash_xyz",
            "phone_number": "+9876543210",
            "db_file": "custom.db",
            "verbose": True,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f)

        cfg = Config.load(explicit_path=str(config_file))
        self.assertEqual(cfg.telegram_api_id, 112233)
        self.assertEqual(cfg.telegram_api_hash, "hash_xyz")
        self.assertEqual(cfg.phone_number, "+9876543210")
        self.assertTrue(cfg.verbose)
        self.assertEqual(cfg.db_file.name, "custom.db")


if __name__ == "__main__":
    unittest.main()
