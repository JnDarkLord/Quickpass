"""Opens the database connection (SQLite or PostgreSQL) and manages schemas.

Supports both plain `sqlite3` and `psycopg2` (PostgreSQL) transparently.
Feature modules keep their SQL queries; this module provides connection
management, row compatibility, and shared queries.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterator, Sequence

# Each statement is idempotent so it can run on every startup.
SCHEMA: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        badge_uid TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        email TEXT UNIQUE,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        is_synced INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        grade INTEGER NOT NULL,
        section TEXT NOT NULL,
        graduation_date TEXT,
        family_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guardians (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS teacher_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        taught_grade INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        status TEXT,
        badge_uid TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        grade INTEGER,
        section TEXT,
        is_synced INTEGER NOT NULL DEFAULT 0,
        synced_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS security_incidents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        badge_uid TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS web_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT,
        oauth_provider TEXT,
        oauth_id TEXT,
        role TEXT NOT NULL,
        linked_entity_id TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS deleted_users (
        badge_uid TEXT PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS school_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        school_language TEXT NOT NULL,
        grades TEXT NOT NULL,
        sections TEXT NOT NULL,
        active_weekdays TEXT NOT NULL,
        holidays TEXT NOT NULL,
        late_threshold TEXT NOT NULL,
        cooldown_seconds INTEGER NOT NULL,
        admin_secret_key_hash TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        is_synced INTEGER NOT NULL DEFAULT 0
    )
    """,
]


def _convert_qmark_to_pyformat(sql: str, has_params: bool = False) -> str:
    """Converts SQLite ? parameter placeholders to PostgreSQL %s outside literals, escaping literal % if params present."""
    out = []
    in_single_quote = False
    in_double_quote = False
    for ch in sql:
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            out.append(ch)
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            out.append(ch)
        elif ch == "%" and has_params:
            out.append("%%")
        elif ch == "?" and not in_single_quote and not in_double_quote:
            out.append("%s")
        else:
            out.append(ch)
    res = "".join(out)
    res = re.sub(r"\bis_active\s*=\s*1\b", "is_active = TRUE", res, flags=re.IGNORECASE)
    res = re.sub(r"\bis_active\s*=\s*0\b", "is_active = FALSE", res, flags=re.IGNORECASE)
    res = re.sub(r",\s*1\s*,\s*%s\s*\)", ", TRUE, %s)", res)
    res = re.sub(r",\s*0\s*,\s*%s\s*\)", ", FALSE, %s)", res)
    return res


class PostgresRow:
    """A row wrapper mimicking sqlite3.Row for PostgreSQL results."""

    def __init__(self, cols: Sequence[str], vals: Sequence[Any]):
        self._cols = list(cols)
        self._vals = list(vals)
        self._map = dict(zip(self._cols, self._vals))
        self._lower_map = {k.lower(): v for k, v in self._map.items()}

    def __getitem__(self, item: int | str) -> Any:
        if isinstance(item, int):
            return self._vals[item]
        if item in self._map:
            return self._map[item]
        return self._lower_map[item.lower()]

    def keys(self) -> list[str]:
        return list(self._cols)

    def values(self) -> list[Any]:
        return list(self._vals)

    def items(self) -> list[tuple[str, Any]]:
        return list(zip(self._cols, self._vals))

    def __iter__(self) -> Iterator[Any]:
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __repr__(self) -> str:
        return f"<PostgresRow {self._map}>"


class PostgresCursorWrapper:
    """Wraps a psycopg2 cursor to match sqlite3 cursor semantics."""

    def __init__(self, inner_cursor: Any, conn: PostgresConnectionWrapper):
        self._cur = inner_cursor
        self._conn = conn
        self._lastrowid: int | None = None

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self) -> Any:
        return self._cur.description

    def _sanitize_params(self, sql: str, params: Sequence[Any] | None) -> list[Any] | None:
        if params is None:
            return None
        cleaned = list(params)
        stripped = sql.strip().upper()
        if ("USERS" in stripped or "WEB_ACCOUNTS" in stripped) and "IS_ACTIVE" in stripped:
            for idx, p in enumerate(cleaned):
                if p == 1 and not isinstance(p, bool):
                    cleaned[idx] = True
                elif p == 0 and not isinstance(p, bool):
                    cleaned[idx] = False
        return cleaned

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> PostgresCursorWrapper:
        stripped = sql.strip()
        if stripped.upper().startswith("PRAGMA"):
            return self

        has_params = params is not None
        clean_params = self._sanitize_params(sql, params)
        pg_sql = _convert_qmark_to_pyformat(sql, has_params)
        is_insert = stripped.upper().startswith("INSERT INTO") and "RETURNING" not in stripped.upper()

        if is_insert:
            insert_sql = pg_sql.rstrip("; ") + " RETURNING id"
            try:
                if has_params:
                    self._cur.execute(insert_sql, clean_params)
                else:
                    self._cur.execute(insert_sql)
                ret = self._cur.fetchone()
                self._lastrowid = ret[0] if ret else None
                return self
            except Exception:
                self._conn._conn.rollback()

        if has_params:
            self._cur.execute(pg_sql, clean_params)
        else:
            self._cur.execute(pg_sql)
        return self

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> PostgresCursorWrapper:
        pg_sql = _convert_qmark_to_pyformat(sql, True)
        self._cur.executemany(pg_sql, params_seq)
        return self

    def fetchone(self) -> PostgresRow | None:
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._cur.description]
        return PostgresRow(cols, row)

    def fetchall(self) -> list[PostgresRow]:
        rows = self._cur.fetchall()
        if not rows:
            return []
        cols = [desc[0] for desc in self._cur.description]
        return [PostgresRow(cols, r) for r in rows]

    def fetchmany(self, size: int) -> list[PostgresRow]:
        rows = self._cur.fetchmany(size)
        if not rows:
            return []
        cols = [desc[0] for desc in self._cur.description]
        return [PostgresRow(cols, r) for r in rows]

    def close(self) -> None:
        self._cur.close()

    def __iter__(self) -> Iterator[PostgresRow]:
        return iter(self.fetchall())


class PostgresConnectionWrapper:
    """Wraps psycopg2 connection to mimic sqlite3.Connection."""

    def __init__(self, pg_url: str):
        import psycopg2

        if pg_url.startswith("postgresql+psycopg2://"):
            pg_url = pg_url.replace("postgresql+psycopg2://", "postgresql://", 1)
        elif pg_url.startswith("postgres://"):
            pg_url = pg_url.replace("postgres://", "postgresql://", 1)

        self._url = pg_url
        self._conn = psycopg2.connect(pg_url)
        self.row_factory: Any = None

    def cursor(self) -> PostgresCursorWrapper:
        return PostgresCursorWrapper(self._conn.cursor(), self)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> PostgresCursorWrapper:
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, params_seq: Sequence[Sequence[Any]]) -> PostgresCursorWrapper:
        cur = self.cursor()
        cur.executemany(sql, params_seq)
        return cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresConnectionWrapper:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def connect(target: Path | str) -> Any:
    """Open (creating if needed) the database at `target` with foreign keys on.

    Supports both SQLite file paths and PostgreSQL URLs.
    """
    target_str = str(target)
    if any(target_str.startswith(prefix) for prefix in ("postgresql://", "postgres://", "postgresql+psycopg2://")):
        return PostgresConnectionWrapper(target_str)

    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: access control reads the Arduino on a background
    # thread; callers serialize access with a lock.
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        for statement in SCHEMA:
            connection.execute(statement)
        try:
            connection.execute("ALTER TABLE student_details ADD COLUMN family_id TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE users ADD COLUMN email TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE attendance_records ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE attendance_records ADD COLUMN synced_at TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            connection.execute("ALTER TABLE users ADD COLUMN is_synced INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    return connection


def connect_historical(settings: Any) -> Any:
    """Connect to Supabase PostgreSQL (`settings.database_url`) for historical attendance
    queries and reports if configured and reachable; otherwise fall back to local SQLite.
    """
    pg_url = getattr(settings, "database_url", None) or ""
    if pg_url.strip():
        try:
            return connect(pg_url.strip())
        except Exception:
            pass
    return connect(settings.database_path)


def normalize_badge_uid(raw_uid: str) -> str:
    """Uppercase hexadecimal without separators."""
    return "".join(c for c in raw_uid if c in "0123456789ABCDEFabcdef").upper()


def get_user_by_badge_uid(conn: Any, badge_uid: str) -> dict[str, Any] | None:
    """Find a user and their role-specific details by badge UID."""
    norm_uid = normalize_badge_uid(badge_uid)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, badge_uid, full_name, role, email, is_active, created_at FROM users WHERE badge_uid = ?",
        (norm_uid,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    user = dict(row)
    role = user["role"]

    if role in ("student", "graduate"):
        cursor.execute(
            "SELECT grade, section, graduation_date, family_id FROM student_details WHERE user_id = ?",
            (user["id"],),
        )
        s_row = cursor.fetchone()
        if s_row:
            user.update(dict(s_row))
        else:
            user["grade"] = None
            user["section"] = None
            user["graduation_date"] = None
            user["family_id"] = None

        cursor.execute(
            "SELECT position, name, phone, email FROM guardians WHERE student_id = ? ORDER BY position",
            (user["id"],),
        )
        user["guardians"] = [dict(g) for g in cursor.fetchall()]

    elif role == "teacher":
        cursor.execute(
            "SELECT taught_grade FROM teacher_details WHERE user_id = ?",
            (user["id"],),
        )
        t_row = cursor.fetchone()
        user["taught_grade"] = t_row["taught_grade"] if t_row else None

    return user


def get_next_family_id(conn: Any) -> str:
    """Compute the next available family ID in the format FAM-XXXX (e.g. FAM-0001, FAM-0142)."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT family_id FROM student_details WHERE family_id IS NOT NULL AND family_id != ''")
        rows = cursor.fetchall()
        max_num = 0
        for r in rows:
            val = str(r[0]).strip().upper()
            m = re.match(r"^FAM-(\d+)$", val)
            if m:
                num = int(m.group(1))
                if num > max_num:
                    max_num = num
        next_num = max_num + 1
        return f"FAM-{next_num:04d}"
    except Exception:
        return "FAM-0001"


def find_family_by_guardian_phone(conn: Any, phone: str) -> dict[str, str] | None:
    """Find existing family ID and sibling student name by matching guardian phone."""
    clean_phone = phone.strip()
    if not clean_phone or len(clean_phone) < 6:
        return None
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT sd.family_id, u.full_name
            FROM guardians g
            JOIN student_details sd ON sd.user_id = g.student_id
            JOIN users u ON u.id = g.student_id
            WHERE g.phone = ? AND sd.family_id IS NOT NULL AND sd.family_id != ''
            LIMIT 1
            """,
            (clean_phone,),
        )
        row = cursor.fetchone()
        if row:
            return {"family_id": str(row[0]), "sibling_name": str(row[1])}
    except Exception:
        pass
    return None
