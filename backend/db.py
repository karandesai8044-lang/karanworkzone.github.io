"""
SQLite database layer for the print kiosk.

Uses the stdlib sqlite3 module directly (no ORM) to keep the free-tier
footprint tiny. One file-based DB: orders.db, created automatically on
first run.
"""

import sqlite3
import uuid
import secrets
import string
import json
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "orders.db"

# Order lifecycle: uploaded -> converting -> queued -> printing -> printed -> expired
VALID_STATUSES = {"uploaded", "converting", "queued", "printing", "printed", "expired", "error"}


def _token(length: int = 6) -> str:
    """Short human-typeable token, e.g. 'A1B2C3'. Not sequential/guessable enough
    for random strangers to enumerate (uses secrets, not random)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,           -- internal UUID
                token TEXT UNIQUE NOT NULL,    -- short customer-facing code
                module TEXT NOT NULL,          -- document | id_card | photo
                status TEXT NOT NULL,
                file_path TEXT,                -- final print-ready PDF, local temp path
                drive_file_id TEXT,             -- Google Drive file id once uploaded
                copies INTEGER DEFAULT 1,
                settings_json TEXT DEFAULT '{}',
                error_message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_token ON orders(token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")


def create_order(module: str, copies: int = 1, settings: dict | None = None) -> dict:
    order_id = str(uuid.uuid4())
    token = _token()
    now = time.time()
    with get_conn() as conn:
        # retry on the astronomically unlikely token collision
        for _ in range(5):
            try:
                conn.execute(
                    """INSERT INTO orders
                       (id, token, module, status, copies, settings_json, created_at, updated_at)
                       VALUES (?, ?, ?, 'uploaded', ?, ?, ?, ?)""",
                    (order_id, token, module, copies, json.dumps(settings or {}), now, now),
                )
                break
            except sqlite3.IntegrityError:
                token = _token()
        else:
            raise RuntimeError("Could not allocate a unique token")
    return get_order_by_id(order_id)


def get_order_by_token(token: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE token = ?", (token.upper(),)).fetchone()
        return dict(row) if row else None


def get_order_by_id(order_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


def update_order(order_id: str, **fields):
    if not fields:
        return
    if "status" in fields and fields["status"] not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE orders SET {cols} WHERE id = ?", (*fields.values(), order_id))


def get_expired_candidates(older_than_seconds: int) -> list[dict]:
    cutoff = time.time() - older_than_seconds
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE created_at < ? AND status != 'expired'",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
