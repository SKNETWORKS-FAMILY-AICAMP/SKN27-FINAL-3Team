from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection

from .db_config import SETTINGS


def connect(db_name: str) -> connection:
    return psycopg2.connect(
        host=SETTINGS.host,
        port=SETTINGS.port,
        user=SETTINGS.user,
        password=SETTINGS.password,
        dbname=db_name,
    )


@contextmanager
def get_connection(db_name: str, autocommit: bool = False) -> Iterator[connection]:
    conn = connect(db_name)
    conn.autocommit = autocommit
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        if not autocommit:
            conn.rollback()
        raise
    finally:
        conn.close()


def database_exists(db_name: str) -> bool:
    with get_connection(SETTINGS.maintenance_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            return cur.fetchone() is not None


def create_database_if_missing(db_name: str) -> bool:
    if database_exists(db_name):
        return False
    with get_connection(SETTINGS.maintenance_db, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{db_name}"')
    return True


def apply_sql_file(db_name: str, sql_text: str) -> None:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)


def count_rows(db_name: str, table_name: str) -> int:
    with get_connection(db_name) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            return int(cur.fetchone()[0])

