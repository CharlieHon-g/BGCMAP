"""
Shared PostgreSQL helpers for scripts/.

Usage:
    from scripts.pg_script_helper import open_db, pg_query, pg_query_one
    conn = open_db()
    rows = pg_query(conn, "SELECT ... WHERE x = %s", (val,))
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.pg_config import get_conn

import psycopg2
import psycopg2.extras


def open_db(autocommit: bool = True):
    conn = get_conn(autocommit=autocommit, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute("SET search_path TO bgcmap, public")
    cur.close()
    return conn


def pg_query(conn, sql: str, params=None):
    cur = conn.cursor()
    try:
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


def pg_query_one(conn, sql: str, params=None):
    cur = conn.cursor()
    try:
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur.fetchone()
    finally:
        cur.close()
