"""Shared MariaDB connection settings loaded from environment / .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(_REPO_ROOT / ".env")


def _require_password():
    password = os.environ.get("VCKO_DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "VCKO_DB_PASSWORD is not set. Copy .env.example to .env and set your password."
        )
    return password


def get_db_config():
    return {
        "host": os.environ.get("VCKO_DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("VCKO_DB_PORT", "3306")),
        "database": os.environ.get("VCKO_DB_NAME", "vckonline"),
        "user": os.environ.get("VCKO_DB_USER", "vckonline"),
        "password": _require_password(),
    }


def connect(**kwargs):
    import mariadb

    config = get_db_config()
    config.update(kwargs)
    return mariadb.connect(**config)


def __getattr__(name):
    if name == "DB_CONFIG":
        return get_db_config()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
