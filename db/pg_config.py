"""
PostgreSQL connection configuration.

Reads from environment variables with sensible defaults for local development.
For production deployment, set all PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.

Usage:
    from db.pg_config import get_conn, get_pg_config
    conn = get_conn()
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg2
import psycopg2.extras


@dataclass
class PgConfig:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    application_name: str = "spire_portal"


def get_pg_config() -> PgConfig:
    return PgConfig(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "gem_portal"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        application_name=os.environ.get("PGAPPNAME", "spire_portal"),
    )


def get_conn(
    autocommit: bool = True,
    cursor_factory=psycopg2.extras.RealDictCursor,
) -> psycopg2.extensions.connection:
    cfg = get_pg_config()
    conn = psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.dbname,
        user=cfg.user,
        password=cfg.password,
        application_name=cfg.application_name,
    )
    conn.autocommit = autocommit
    conn.cursor_factory = cursor_factory
    return conn


def ensure_database() -> None:
    """Create the database if it does not exist."""
    cfg = get_pg_config()
    conn = psycopg2.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        dbname="postgres",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg.dbname,))
    if cur.fetchone() is None:
        cur.execute(f'CREATE DATABASE "{cfg.dbname}"')
    cur.close()
    conn.close()
