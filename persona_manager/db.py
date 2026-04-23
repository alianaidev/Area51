"""
db.py — SQLite schema and connection management for persona manager.

Part of the OSINT persona manager CLI. Owns:
  * Schema definition (CREATE TABLE statements)
  * Connection factory with foreign keys enabled + WAL mode
  * Schema versioning for future migrations
  * init_db() entrypoint for first-run bootstrap
  * log_event() — the only sanctioned writer for the append-only session log

Does NOT own CRUD against personas / platform_accounts / investigations —
those live in persona.py, vpn.py, browser.py, etc. Keep db.py boring.

Design decisions (spelled out so future-you or Daemon can push back):
  * Raw sqlite3, no ORM — dependency-minimal, aligns with self-contained-tool
    convention in the project doc. If schema complexity outgrows this, migrate
    to Peewee, not SQLAlchemy (too heavy for a single-operator CLI).
  * Soft-delete via archived_at instead of hard DELETE on personas /
    platform_accounts — preserves chain of custody for investigation work.
    session_log, investigations, assignments are NOT soft-deletable (by
    omission of the column) — they're the record itself.
  * Credentials are NEVER stored here. credentials_refs holds opaque pointers
    (vault_type + vault_id) into KeePassXC or self-hosted Bitwarden. The real
    secret lives in the vault, not the SQLite file.
  * session_log is append-only by convention — no UPDATE or DELETE helpers
    are exposed in this module. If you need to correct a bad entry, write a
    compensating event, don't mutate history.
  * Timestamps stored as ISO8601 TEXT in UTC. SQLite's native datetime
    handling is fiddly; strings round-trip cleanly and sort lexicographically.
  * Python 3.10+ required for `int | None` union syntax. Parrot ships 3.11+,
    so this is fine.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path("personas.db")
SCHEMA_VERSION = 1


def utcnow_iso() -> str:
    """ISO8601 timestamp in UTC — used across every row's created_at/updated_at."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Schema — one statement per entry, applied idempotently in init_db()
# ---------------------------------------------------------------------------

SCHEMA: list[str] = [
    # Meta: schema version. Future migrations append rows; we never UPDATE.
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,

    # Core persona: identity + infrastructure + operational state.
    """
    CREATE TABLE IF NOT EXISTS personas (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        callsign             TEXT NOT NULL UNIQUE,       -- short handle for CLI use ("alice01")
        display_name         TEXT NOT NULL,              -- full generated name
        dob                  TEXT,                       -- ISO date (YYYY-MM-DD)
        location             TEXT,                       -- "Portland, OR, USA"
        occupation           TEXT,
        backstory            TEXT,
        interests            TEXT,                       -- comma-separated or JSON — keep flexible
        email                TEXT,
        email_source         TEXT,                       -- 'protonmail', 'tutanota', etc.
        phone                TEXT,
        phone_source         TEXT,                       -- 'sms-activate.org', etc.
        vpn_exit_node        TEXT NOT NULL,              -- e.g. 'us-nyc-wg-101' — consistent per persona
        browser_profile_path TEXT NOT NULL,              -- filesystem path to isolated Firefox profile
        photo_path           TEXT,                       -- GAN-generated face, local file
        status               TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'dormant' | 'burned' | 'archived'
        notes                TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        archived_at          TEXT                         -- NULL = live; set on soft-delete
    )
    """,

    # Opaque pointers into the external credential vault (KeePassXC / Bitwarden).
    # Defined BEFORE platform_accounts so the FK resolves on first-run create.
    """
    CREATE TABLE IF NOT EXISTS credentials_refs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_type TEXT NOT NULL,                       -- 'keepassxc' | 'bitwarden'
        vault_id   TEXT NOT NULL,                       -- entry UUID / group path in the vault
        label      TEXT,                                -- human-readable hint
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (vault_type, vault_id)
    )
    """,

    # Platform accounts owned by a persona (many per persona).
    """
    CREATE TABLE IF NOT EXISTS platform_accounts (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        persona_id          INTEGER NOT NULL,
        platform            TEXT NOT NULL,              -- 'reddit', 'twitter', 'discord'
        username            TEXT NOT NULL,
        account_url         TEXT,
        registered_at       TEXT,                       -- when the account was created on the platform
        warmup_status       TEXT NOT NULL DEFAULT 'new', -- 'new' | 'warming' | 'ready' | 'burned'
        warmup_started_at   TEXT,
        last_used_at        TEXT,
        health              TEXT NOT NULL DEFAULT 'ok',  -- 'ok' | 'shadowbanned' | 'locked' | 'banned'
        credentials_ref_id  INTEGER,                    -- FK to credentials_refs (NULL if creds not yet stored)
        notes               TEXT,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL,
        archived_at         TEXT,
        FOREIGN KEY (persona_id)         REFERENCES personas(id)         ON DELETE CASCADE,
        FOREIGN KEY (credentials_ref_id) REFERENCES credentials_refs(id) ON DELETE SET NULL,
        UNIQUE (persona_id, platform, username)
    )
    """,

    # Investigations / operations this toolkit is being used for.
    """
    CREATE TABLE IF NOT EXISTS investigations (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code        TEXT NOT NULL UNIQUE,          -- 'CASE-2026-001'
        title            TEXT NOT NULL,
        objective        TEXT,
        status           TEXT NOT NULL DEFAULT 'active', -- 'active' | 'paused' | 'closed'
        authorized_scope TEXT,                          -- free-text scope doc reference (bug bounty scope, etc.)
        opened_at        TEXT NOT NULL,
        closed_at        TEXT,
        notes            TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    )
    """,

    # N:N — which personas are assigned to which investigations.
    """
    CREATE TABLE IF NOT EXISTS persona_assignments (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        persona_id       INTEGER NOT NULL,
        investigation_id INTEGER NOT NULL,
        role             TEXT,                          -- 'primary' | 'support' | etc.
        assigned_at      TEXT NOT NULL,
        unassigned_at    TEXT,                          -- NULL = still assigned
        FOREIGN KEY (persona_id)       REFERENCES personas(id)       ON DELETE CASCADE,
        FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE,
        UNIQUE (persona_id, investigation_id)
    )
    """,

    # Append-only session log — every action against a persona gets a row.
    # Treat as immutable: no UPDATE/DELETE helpers are exposed in this module.
    # NO ON DELETE CASCADE — history outlives the persona record.
    """
    CREATE TABLE IF NOT EXISTS session_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        persona_id       INTEGER,                       -- nullable: system events have no persona
        investigation_id INTEGER,                       -- nullable
        event_type       TEXT NOT NULL,                 -- 'session_start', 'session_end',
                                                        -- 'browser_launch', 'vpn_connect',
                                                        -- 'platform_action', 'credential_access'
        event_detail     TEXT,                          -- free-form / JSON payload
        actor            TEXT,                          -- 'cli', 'daemon', 'manual'
        occurred_at      TEXT NOT NULL,
        FOREIGN KEY (persona_id)       REFERENCES personas(id),
        FOREIGN KEY (investigation_id) REFERENCES investigations(id)
    )
    """,
]

# Indexes — keep common lookups fast as data grows.
INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_personas_status            ON personas(status)",
    "CREATE INDEX IF NOT EXISTS idx_personas_archived_at       ON personas(archived_at)",
    "CREATE INDEX IF NOT EXISTS idx_platform_accounts_persona  ON platform_accounts(persona_id)",
    "CREATE INDEX IF NOT EXISTS idx_platform_accounts_platform ON platform_accounts(platform)",
    "CREATE INDEX IF NOT EXISTS idx_assignments_persona        ON persona_assignments(persona_id)",
    "CREATE INDEX IF NOT EXISTS idx_assignments_investigation  ON persona_assignments(investigation_id)",
    "CREATE INDEX IF NOT EXISTS idx_session_log_persona        ON session_log(persona_id)",
    "CREATE INDEX IF NOT EXISTS idx_session_log_occurred_at    ON session_log(occurred_at)",
]


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Return a configured sqlite3 connection.

    - Foreign keys ON (off by default in SQLite; easy to forget).
    - row_factory = sqlite3.Row for dict-like access.
    - WAL mode so a long-running browser session logger doesn't block CLI reads.
    - isolation_level=None disables Python's implicit BEGIN; we control txns
      explicitly via the transaction() context manager.
    """
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Atomic transaction context manager.

    Usage:
        with transaction(conn):
            conn.execute(...)
            conn.execute(...)

    Rolls back on any exception, commits on clean exit.
    """
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Initialization / migration
# ---------------------------------------------------------------------------

def _current_schema_version(conn: sqlite3.Connection) -> int:
    """Highest applied schema version, or 0 if the table doesn't exist yet."""
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM schema_version"
        ).fetchone()
        return int(row["v"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create tables + indexes if missing, stamp schema version. Idempotent.

    Safe to call on every CLI startup. Returns an open connection.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect(db_path)
    with transaction(conn):
        for stmt in SCHEMA:
            conn.execute(stmt)
        for stmt in INDEXES:
            conn.execute(stmt)

        applied = _current_schema_version(conn)
        if applied < SCHEMA_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utcnow_iso()),
            )
            logger.info("schema stamped: %d -> %d", applied, SCHEMA_VERSION)

    return conn


# ---------------------------------------------------------------------------
# Session log — the ONLY sanctioned writer against session_log
# ---------------------------------------------------------------------------

def log_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    persona_id: int | None = None,
    investigation_id: int | None = None,
    detail: str | None = None,
    actor: str = "cli",
) -> int:
    """Append a row to session_log. Returns the new row id.

    Intentionally the only write helper against session_log in this module —
    keeps the append-only contract enforced by convention visible in the code.
    If you find yourself needing to mutate a past entry, write a compensating
    event instead.
    """
    cur = conn.execute(
        """
        INSERT INTO session_log
            (persona_id, investigation_id, event_type, event_detail, actor, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (persona_id, investigation_id, event_type, detail, actor, utcnow_iso()),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Bootstrap entrypoint:  python -m persona_manager.db
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = init_db()
    print(f"initialized {DEFAULT_DB_PATH.resolve()} at schema v{SCHEMA_VERSION}")
    conn.close()
