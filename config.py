"""Backward compatibility shim for legacy config.py."""

from teledrive.config import Config

_cfg = None

def _get_cfg():
    global _cfg
    if _cfg is None:
        _cfg = Config.load(allow_missing=True)
    return _cfg

def get_verbose():
    return _get_cfg().verbose

def get_telegram_api_id():
    return _get_cfg().telegram_api_id

def get_telegram_api_hash():
    return _get_cfg().telegram_api_hash

def get_phone():
    return _get_cfg().phone_number

def get_db_file():
    return str(_get_cfg().db_file)