"""统一数据库层：生产用 PostgreSQL（Supabase），本地/测试用 SQLite。"""
import re
import sqlite3
from pathlib import Path
from . import config

SCHEMA = Path(__file__).resolve().parent.parent / "database" / "schema.sql"


def is_sqlite():
    return config.DATABASE_URL.startswith("sqlite")


def connect():
    if is_sqlite():
        conn = sqlite3.connect(config.DATABASE_URL.replace("sqlite:///", ""))
        conn.row_factory = sqlite3.Row
        return conn
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(config.DATABASE_URL,
                            cursor_factory=psycopg2.extras.RealDictCursor)


def _sql(sql):
    """业务代码统一写 %s 占位符；SQLite 自动转换。"""
    return sql.replace("%s", "?") if is_sqlite() else sql


def execute(sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(sql), params)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def query(sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(_sql(sql), params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def init_schema():
    text = SCHEMA.read_text(encoding="utf-8")
    if is_sqlite():
        text = (text.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                    .replace("TIMESTAMPTZ", "TIMESTAMP")
                    .replace("NOW()", "CURRENT_TIMESTAMP")
                    .replace("BIGINT", "INTEGER"))
    conn = connect()
    try:
        cur = conn.cursor()
        for stmt in filter(None, (s.strip() for s in text.split(";"))):
            cur.execute(re.sub(r"--.*", "", stmt))
        conn.commit()
    finally:
        conn.close()


def log_scrape(module, target, status, error=None):
    execute("INSERT INTO scraper_logs (module, target, status, error) VALUES (%s,%s,%s,%s)",
            (module, target, status, error))
