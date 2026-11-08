"""Shared fixtures: a fresh database file and Reports folder per test,
settings built in code, School Settings stored in that database, a fixed date
and time, a PostgreSQL database with every Supabase migration applied, and the
QApplication the window tests share."""

import os
from dataclasses import replace
from datetime import datetime, time
from types import SimpleNamespace

import psycopg2
import pytest
from dotenv import dotenv_values

import database
import school_settings
from config import REPO_ROOT, Settings
from school_settings import SchoolSettings

# Monday 5 October 2026, 07:00:00 (after the default Late Threshold).
FIXED_NOW = datetime(2026, 10, 5, 7, 0, 0)

MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

ADMIN_SECRET_KEY = "clave-admin-prueba"
_ADMIN_SECRET_KEY_HASH = school_settings.hash_secret_key(ADMIN_SECRET_KEY, iterations=1000)


def make_school(**changes) -> SchoolSettings:
    """A Spanish School with Grades 1° to 11°, Sections A to D, Monday to Friday."""
    base = SchoolSettings(
        school_language="es",
        grades=tuple(f"{rank}°" for rank in range(1, 12)),
        sections=("A", "B", "C", "D"),
        active_weekdays=(0, 1, 2, 3, 4),
        holidays=(),
        late_threshold=time(6, 50, 0),
        cooldown_seconds=300,
        admin_secret_key_hash=_ADMIN_SECRET_KEY_HASH,
    )
    return replace(base, **changes)


def store_school(conn, school: SchoolSettings | None = None) -> SchoolSettings:
    """Stores School Settings in the local cache as if Cloud Sync had pulled them."""
    school = school or make_school()
    school_settings.store_synced(conn, school, updated_at=FIXED_NOW.isoformat())
    return school


def gate_screen(command: str) -> tuple[str, str, str]:
    """Split a gate command such as `GRANT <line1>|<line2>` into its name and its two
    LCD lines, without the spaces that center them."""
    name, _, lines = command.strip().partition(" ")
    line1, _, line2 = lines.partition("|")
    return name, line1.strip(), line2.strip()


def postgres_url() -> str:
    """DATABASE_URL from the environment, else from `.env`, else a local default."""
    url = os.environ.get("DATABASE_URL") or dotenv_values(REPO_ROOT / ".env").get("DATABASE_URL")
    url = url or "postgresql://localhost:5432/quickpass"
    for prefix in ("postgresql+psycopg2://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def apply_supabase_migrations() -> None:
    conn = psycopg2.connect(postgres_url())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                cur.execute(path.read_text(encoding="utf-8"))
    finally:
        conn.close()


@pytest.fixture(scope="session")
def supabase_schema() -> None:
    """Applies every Supabase migration, in order, to the DATABASE_URL database."""
    apply_supabase_migrations()


@pytest.fixture
def db_conn(supabase_schema):
    """A PostgreSQL connection whose changes roll back after the test."""
    conn = psycopg2.connect(postgres_url())
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_path=tmp_path / "quickpass.db",
        reports_dir=tmp_path / "Reports",
        wipe_password="clave-de-prueba",
        admin_alert_phone="+15550000000",
    )


@pytest.fixture
def school() -> SchoolSettings:
    """The School Settings each test's database starts with; override per module."""
    return make_school()


@pytest.fixture(autouse=True)
def _school_settings_stored(settings, school):
    connection = database.connect(settings.database_path)
    try:
        store_school(connection, school)
    finally:
        connection.close()


@pytest.fixture
def conn(settings):
    connection = database.connect(settings.database_path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture(scope="session")
def qapp():
    """The one QApplication the window tests share, drawing offscreen."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.processEvents()


@pytest.fixture
def messages(monkeypatch):
    """The message boxes the windows show, as (kind, text) pairs, instead of showing them.
    A box a window builds itself, such as the one after an export, counts as kind "box"."""
    import gui

    shown = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(
            gui.QMessageBox, kind, lambda *args, _kind=kind, **kwargs: shown.append((_kind, args[2]))
        )
    monkeypatch.setattr(gui.QMessageBox, "exec", lambda box: shown.append(("box", box.text())) or 0)
    return shown


@pytest.fixture
def approval(monkeypatch):
    """Admin Approval dialogs are answered by typing `approval.key`, the School's key unless a test
    changes it, or by scanning `approval.badge` once a test sets one. `approval.key_offered` tells
    whether the last dialog offered the key at all."""
    from PySide6.QtWidgets import QDialog

    import gui

    state = SimpleNamespace(key=ADMIN_SECRET_KEY, badge=None, asked=0, key_offered=None)

    def exec_answering(dialog):
        state.asked += 1
        state.key_offered = not dialog.key_box.isHidden()
        if state.badge is not None:
            dialog.worker.badge_captured.emit(state.badge)
        else:
            dialog.inp_key.setText(state.key)
            dialog.verify_key()
        if dialog.result() != QDialog.Accepted:
            dialog.reject()
        return dialog.result()

    monkeypatch.setattr(gui.AdminAuthDialog, "exec", exec_answering)
    return state
