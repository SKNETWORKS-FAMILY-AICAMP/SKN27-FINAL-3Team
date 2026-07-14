from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row

from app.config import Settings, get_settings


def connect(settings: Settings | None = None) -> psycopg.Connection:
    selected = settings or get_settings()
    return psycopg.connect(selected.database_url, row_factory=dict_row)


def connection(settings: Settings | None = None) -> Iterator[psycopg.Connection]:
    conn = connect(settings)
    try:
        yield conn
    finally:
        conn.close()
