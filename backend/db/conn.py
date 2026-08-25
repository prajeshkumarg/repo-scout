"""Database connections built from settings."""

from typing import Any

import psycopg

from config import get_settings


def connect() -> psycopg.Connection[Any]:
    """Open a connection using the app's configured database URL."""
    return psycopg.connect(get_settings().database_url)
