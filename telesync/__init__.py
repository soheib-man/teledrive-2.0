"""Telesync backward-compatibility alias pointing to TeleDrive 2.0."""

import sys
from teledrive import __version__, __app_name__
import teledrive.constants as constants
import teledrive.exceptions as exceptions
import teledrive.models as models
import teledrive.config as config
import teledrive.database as database
import teledrive.chunking as chunking
import teledrive.telegram_client as telegram_client
import teledrive.services as services
import teledrive.cli as cli

# Expose modules under telesync.*
sys.modules["telesync.constants"] = constants
sys.modules["telesync.exceptions"] = exceptions
sys.modules["telesync.models"] = models
sys.modules["telesync.config"] = config
sys.modules["telesync.database"] = database
sys.modules["telesync.chunking"] = chunking
sys.modules["telesync.telegram_client"] = telegram_client
sys.modules["telesync.services"] = services
sys.modules["telesync.cli"] = cli

main = cli.main
