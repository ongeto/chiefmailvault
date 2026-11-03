"""SQLite database connection and schema initialization."""

import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import DB_PATH, ensure_data_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    imap_host TEXT NOT NULL,
    imap_port INTEGER NOT NULL DEFAULT 993,
    ollama_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mailboxes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    encrypted_password BLOB NOT NULL,
    credentials_validated INTEGER NOT NULL DEFAULT 0,
    validated_at TEXT,
    last_sync_at TEXT,
    last_integrity_at TEXT,
    last_integrity_ok INTEGER,
    last_integrity_total INTEGER,
    FOREIGN KEY (domain_id) REFERENCES domains(id) ON DELETE CASCADE,
    UNIQUE(domain_id, email)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id INTEGER NOT NULL,
    uid INTEGER NOT NULL,
    folder TEXT NOT NULL,
    message_id TEXT,
    md5_hash TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    date TEXT,
    eml_path TEXT,
    sender TEXT,
    subject TEXT,
    content_type TEXT,
    snippet TEXT,
    cloud_synced INTEGER NOT NULL DEFAULT 0,
    nas_synced INTEGER NOT NULL DEFAULT 0,
    is_large INTEGER NOT NULL DEFAULT 0,
    integrity_ok INTEGER,
    verified_at TEXT,
    FOREIGN KEY (mailbox_id) REFERENCES mailboxes(id) ON DELETE CASCADE,
    UNIQUE(mailbox_id, folder, uid)
);

CREATE TABLE IF NOT EXISTS duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    inbox_uid INTEGER NOT NULL,
    sent_uid INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'flagged',
    FOREIGN KEY (mailbox_id) REFERENCES mailboxes(id) ON DELETE CASCADE,
    UNIQUE(mailbox_id, message_id)
);

CREATE TABLE IF NOT EXISTS cleanup_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    message_ids TEXT NOT NULL,
    reason TEXT,
    approved INTEGER NOT NULL DEFAULT 0,
    executed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (mailbox_id) REFERENCES mailboxes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backup_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mailbox_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    messages_added INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY (mailbox_id) REFERENCES mailboxes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_mailbox ON messages(mailbox_id);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_duplicates_mailbox ON duplicates(mailbox_id);
"""


def get_connection() -> sqlite3.Connection:
    ensure_data_dirs()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply schema updates for existing databases."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(mailboxes)").fetchall()}
    if "credentials_validated" not in cols:
        conn.execute(
            "ALTER TABLE mailboxes ADD COLUMN credentials_validated INTEGER NOT NULL DEFAULT 0"
        )
    if "validated_at" not in cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN validated_at TEXT")

    msg_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "purge_status" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN purge_status TEXT")
    if "integrity_ok" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN integrity_ok INTEGER")
    if "verified_at" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN verified_at TEXT")

    mb_cols = {row[1] for row in conn.execute("PRAGMA table_info(mailboxes)").fetchall()}
    if "last_integrity_at" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN last_integrity_at TEXT")
    if "last_integrity_ok" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN last_integrity_ok INTEGER")
    if "last_integrity_total" not in mb_cols:
        conn.execute("ALTER TABLE mailboxes ADD COLUMN last_integrity_total INTEGER")

    sug_cols = {row[1] for row in conn.execute("PRAGMA table_info(cleanup_suggestions)").fetchall()}
    for col, typedef in (
        ("subject", "TEXT"),
        ("sender", "TEXT"),
        ("date", "TEXT"),
        ("folder", "TEXT"),
        ("size", "INTEGER"),
    ):
        if col not in sug_cols:
            conn.execute(f"ALTER TABLE cleanup_suggestions ADD COLUMN {col} {typedef}")
