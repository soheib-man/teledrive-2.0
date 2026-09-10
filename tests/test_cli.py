"""Tests for TeleDrive CLI argument parsing and error handling."""

import sys
import unittest
from unittest.mock import patch
from teledrive.cli import build_parser, main
from teledrive.constants import EXIT_SUCCESS, EXIT_USAGE


class TestCLI(unittest.TestCase):

    def test_cli_help(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_version(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_no_arguments_exit_code(self):
        with patch.object(sys, "argv", ["teledrive"]):
            code = main()
            self.assertEqual(code, EXIT_SUCCESS)

    def test_cli_invalid_command(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["nonexistent_action"])
        self.assertEqual(cm.exception.code, 2)

    def test_cli_missing_upload_path(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["upload"])
        self.assertEqual(cm.exception.code, 2)

    def test_cli_missing_download_query(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["download"])
        self.assertEqual(cm.exception.code, 2)

    def test_cli_missing_rename_arguments(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as cm:
            parser.parse_args(["rename", "item_id"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
