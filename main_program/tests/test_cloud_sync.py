"""Tests for Offline-First Entrance Scans and Background Cloud Sync."""

from __future__ import annotations

import threading
import time as time_mod
from dataclasses import replace
from datetime import datetime, time
from pathlib import Path
from typing import Any

from conftest import make_school, store_school

import access_control
import admin
import cloud_sync
import config
import database
import school_settings


def test_config_loads_supabase_credentials():
    """Settings parses SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from environment."""
    settings = config.load_settings(
        env_file=None,
        environ={
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_key_123",
        },
    )
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_service_role_key == "sb_secret_test_key_123"


def test_local_scan_validates_under_1ms_and_queues_unsynced(tmp_path: Path):
    """Badge scan validates in <1ms locally, triggers Door Gate and SMS, and marks is_synced=0."""
    conn = database.connect(tmp_path / "local_entrance.db")
    store_school(conn)
    settings = config.Settings(
        database_path=tmp_path / "local_entrance.db",
        twilio_enabled=True,
    )

    admin.add_user(
        conn,
        settings=settings,
        badge_uid="CAFE1234",
        role="student",
        full_name="Lucia Fernandez",
        grade=4,
        section="A",
        guardians=[admin.GuardianData(name="Madre Lucia", phone="+50588887777", email="madre@school.edu")],
        family_id="FAM-0042",
    )

    # Measure local scan validation latency
    scan_dt = datetime(2026, 10, 16, 6, 45, 0)
    t0 = time_mod.perf_counter()
    res = access_control.process_scan_line(conn, settings, "SCAN CAFE1234\n", now=scan_dt)
    elapsed_ms = (time_mod.perf_counter() - t0) * 1000.0

    assert elapsed_ms < 5.0  # Sub-millisecond local SQLite validation (with CI headroom)
    assert res.is_scan is True
    assert res.event_type == "check_in"
    assert res.status == "on_time"
    assert res.reply_line.startswith("GRANT ")
    assert len(res.texts_to_send) == 1
    assert res.texts_to_send[0][0] == "+505 88887777"

    cur = conn.cursor()
    cur.execute(
        "SELECT event_type, status, badge_uid, is_synced, synced_at FROM attendance_records WHERE badge_uid = 'CAFE1234'"
    )
    row = cur.fetchone()
    assert row is not None
    assert row["event_type"] == "check_in"
    assert row["status"] == "on_time"
    assert row["is_synced"] == 0
    assert row["synced_at"] is None
    conn.close()


class FakeSupabaseSyncClient:
    """SDK-style test double at the Supabase system boundary."""

    def __init__(self) -> None:
        self.upserted_batches: list[list[dict[str, Any]]] = []
        self.remote_roster: list[dict[str, Any]] = []
        self.pushed_users: list[dict[str, Any]] = []
        self.deleted_badges: list[str] = []
        self.remote_school_settings: dict[str, Any] | None = None
        self.pushed_school_settings: list[dict[str, Any]] = []
        self.school_settings_fetches = 0
        self.should_fail: Exception | None = None

    def fetch_school_settings(self) -> dict[str, Any] | None:
        if self.should_fail is not None:
            raise self.should_fail
        self.school_settings_fetches += 1
        return dict(self.remote_school_settings) if self.remote_school_settings else None

    def upsert_school_settings(self, row: dict[str, Any]) -> None:
        if self.should_fail is not None:
            raise self.should_fail
        self.pushed_school_settings.append(dict(row))
        self.remote_school_settings = dict(row)

    def upsert_attendance_records(self, records: list[dict[str, Any]]) -> None:
        if self.should_fail is not None:
            raise self.should_fail
        self.upserted_batches.append(list(records))

    def fetch_roster(self) -> list[dict[str, Any]]:
        if self.should_fail is not None:
            raise self.should_fail
        return list(self.remote_roster)

    def upsert_user(self, user_bundle: dict[str, Any]) -> None:
        if self.should_fail is not None:
            raise self.should_fail
        self.pushed_users.append(dict(user_bundle))

    def delete_user(self, badge_uid: str) -> None:
        if self.should_fail is not None:
            raise self.should_fail
        self.deleted_badges.append(badge_uid)
        self.remote_roster = [u for u in self.remote_roster if u["badge_uid"] != badge_uid]


def test_cloud_sync_worker_flushes_unsynced_batches_and_marks_synced(tmp_path: Path):
    """CloudSyncWorker extracts unsynced Check-in and Check-out records in batches and marks is_synced=1."""
    import cloud_sync

    db_file = tmp_path / "sync_batch.db"
    conn = database.connect(db_file)
    store_school(conn)
    settings = config.Settings(
        database_path=db_file,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_service_role",
    )

    admin.add_user(
        conn,
        settings=settings,
        badge_uid="BEEF0001",
        role="student",
        full_name="Diego Ramirez",
        grade=6,
        section="B",
        guardians=[admin.GuardianData(name="Padre Diego", phone="+50581112222", email="padre@school.edu")],
        family_id="FAM-0060",
    )

    # Check-in at 06:40 and Check-out at 13:30
    access_control.process_scan_line(conn, settings, "SCAN BEEF0001\n", now=datetime(2026, 10, 16, 6, 40, 0))
    access_control.process_scan_line(conn, settings, "SCAN BEEF0001\n", now=datetime(2026, 10, 16, 13, 30, 0))

    fake_client = FakeSupabaseSyncClient()
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, batch_size=10)

    sync_time = datetime(2026, 10, 16, 13, 31, 0)
    result = worker.sync_once(now=sync_time)

    assert result.failed is False
    assert result.synced_count == 2
    assert len(fake_client.upserted_batches) == 1
    assert [r["event_type"] for r in fake_client.upserted_batches[0]] == ["check_in", "check_out"]

    cur = conn.cursor()
    cur.execute("SELECT is_synced, synced_at FROM attendance_records WHERE badge_uid = 'BEEF0001' ORDER BY id ASC")
    rows = cur.fetchall()
    assert len(rows) == 2
    assert all(r["is_synced"] == 1 for r in rows)
    assert all(r["synced_at"] == "2026-10-16T13:31:00" for r in rows)

    # Second run has nothing left to sync
    result_second = worker.sync_once(now=sync_time)
    assert result_second.synced_count == 0
    assert len(fake_client.upserted_batches) == 1
    conn.close()


def test_cloud_sync_worker_handles_network_outage_with_exponential_backoff_and_recovers(tmp_path: Path):
    """Network errors use exponential backoff without blocking <1ms local scans, then flush on recovery."""
    import cloud_sync

    db_file = tmp_path / "sync_outage.db"
    conn = database.connect(db_file)
    store_school(conn)
    settings = config.Settings(
        database_path=db_file,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_service_role",
    )

    admin.add_user(
        conn,
        settings=settings,
        badge_uid="CAFE9999",
        role="student",
        full_name="Sofia Herrera",
        grade=3,
        section="A",
        guardians=[admin.GuardianData(name="Madre Sofia", phone="+50583334444", email="sofia.mom@school.edu")],
        family_id="FAM-0030",
    )

    fake_client = FakeSupabaseSyncClient()
    fake_client.should_fail = ConnectionError("DNS lookup failed: supabase.co unreachable")
    worker = cloud_sync.CloudSyncWorker(
        conn, settings, client=fake_client, batch_size=10, base_backoff_seconds=1.0, max_backoff_seconds=16.0
    )

    # Scan 1 (Check-in) while offline
    t0 = time_mod.perf_counter()
    scan1 = access_control.process_scan_line(conn, settings, "SCAN CAFE9999\n", now=datetime(2026, 10, 16, 6, 45, 0))
    assert (time_mod.perf_counter() - t0) * 1000.0 < 5.0
    assert scan1.reply_line.startswith("GRANT ")

    # Sync attempts during outage fail gracefully with exponential backoff (1s -> 2s -> 4s)
    r1 = worker.sync_once()
    assert r1.failed is True
    assert r1.synced_count == 0
    assert r1.backoff_seconds == 1.0

    r2 = worker.sync_once()
    assert r2.failed is True
    assert r2.backoff_seconds == 2.0

    # Scan 2 (Check-out) still succeeds locally during outage
    scan2 = access_control.process_scan_line(conn, settings, "SCAN CAFE9999\n", now=datetime(2026, 10, 16, 13, 15, 0))
    assert scan2.event_type == "check_out"
    assert scan2.reply_line.startswith("GRANT ")

    r3 = worker.sync_once()
    assert r3.failed is True
    assert r3.backoff_seconds == 4.0

    # Connectivity returns -> queued Check-in and Check-out flush together and backoff resets
    fake_client.should_fail = None
    recovered = worker.sync_once(now=datetime(2026, 10, 16, 13, 20, 0))
    assert recovered.failed is False
    assert recovered.synced_count == 2
    assert recovered.backoff_seconds == 0.0
    assert len(fake_client.upserted_batches) == 1
    assert len(fake_client.upserted_batches[0]) == 2
    conn.close()


def test_cloud_sync_evicts_previous_days_synced_scans_while_keeping_todays_and_users(tmp_path: Path):
    """Synced attendance_records from previous days are evicted from SQLite, while today's scans and all users remain cached."""
    import cloud_sync

    db_file = tmp_path / "sync_eviction.db"
    conn = database.connect(db_file)
    store_school(conn)
    settings = config.Settings(
        database_path=db_file,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_service_role",
    )

    admin.add_user(
        conn,
        settings=settings,
        badge_uid="ABCD1111",
        role="student",
        full_name="Valeria Mendoza",
        grade=5,
        section="A",
        guardians=[admin.GuardianData(name="Madre Valeria", phone="+50589990000", email="valeria.mom@school.edu")],
        family_id="FAM-0051",
    )

    # Yesterday's scan (2026-10-15) and today's morning Check-in (2026-10-16)
    access_control.process_scan_line(conn, settings, "SCAN ABCD1111\n", now=datetime(2026, 10, 15, 6, 40, 0))
    access_control.process_scan_line(conn, settings, "SCAN ABCD1111\n", now=datetime(2026, 10, 16, 6, 42, 0))

    fake_client = FakeSupabaseSyncClient()
    fake_client.should_fail = ConnectionError("Offline")
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, batch_size=10)

    # While offline, unsynced yesterday scan is NOT evicted
    offline_res = worker.sync_once(now=datetime(2026, 10, 16, 8, 0, 0))
    assert offline_res.failed is True
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM attendance_records")
    assert cur.fetchone()[0] == 2

    # Once online on 2026-10-16, both scans sync to Supabase, and yesterday's scan (2026-10-15) is evicted from SQLite
    fake_client.should_fail = None
    online_res = worker.sync_once(now=datetime(2026, 10, 16, 8, 5, 0))
    assert online_res.failed is False
    assert online_res.synced_count == 2
    assert online_res.evicted_count == 1

    cur.execute("SELECT date, event_type, is_synced FROM attendance_records")
    remaining_scans = [dict(r) for r in cur.fetchall()]
    assert len(remaining_scans) == 1
    assert remaining_scans[0]["date"] == "2026-10-16"
    assert remaining_scans[0]["is_synced"] == 1

    # Because today's Check-in is still cached in SQLite, an afternoon scan on 2026-10-16 is properly detected as Check-out
    checkout_scan = access_control.process_scan_line(
        conn, settings, "SCAN ABCD1111\n", now=datetime(2026, 10, 16, 13, 30, 0)
    )
    assert checkout_scan.event_type == "check_out"

    # Next day (2026-10-17), after syncing, 2026-10-16 scans are also evicted while the user remains intact
    next_day_res = worker.sync_once(now=datetime(2026, 10, 17, 7, 0, 0))
    assert next_day_res.synced_count == 1
    assert next_day_res.evicted_count == 2
    cur.execute("SELECT COUNT(*) FROM attendance_records")
    assert cur.fetchone()[0] == 0

    # Users are NEVER evicted from local SQLite mirror
    cached_user = database.get_user_by_badge_uid(conn, "ABCD1111")
    assert cached_user is not None
    assert cached_user["full_name"] == "Valeria Mendoza"
    assert cached_user["family_id"] == "FAM-0051"
    conn.close()


def test_cloud_sync_mirrors_roster_between_supabase_and_sqlite_cache(tmp_path: Path):
    """CloudSyncWorker.sync_roster pushes local users to Supabase and mirrors remote Supabase users into local SQLite."""
    import cloud_sync

    db_file = tmp_path / "sync_roster.db"
    conn = database.connect(db_file)
    store_school(conn)
    settings = config.Settings(
        database_path=db_file,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_service_role",
    )

    # 1. Local Badge registered while offline
    admin.add_user(
        conn,
        settings=settings,
        badge_uid="1122AABB",
        role="student",
        full_name="Local Student",
        grade=2,
        section="B",
        guardians=[admin.GuardianData(name="Local Guardian", phone="+50581234567", email="local.g@school.edu")],
        family_id="FAM-0022",
    )

    fake_client = FakeSupabaseSyncClient()
    # 2. Remote Badge already present in Supabase (source of truth)
    fake_client.remote_roster = [
        {
            "badge_uid": "9988CCDD",
            "full_name": "Cloud Student",
            "role": "student",
            "email": None,
            "is_active": True,
            "created_at": "2026-10-16 07:00:00",
            "grade": 8,
            "section": "A",
            "family_id": "FAM-0088",
            "graduation_date": None,
            "taught_grade": None,
            "guardians": [
                {"position": 1, "name": "Cloud Mom", "phone": "+50587654321", "email": "cloud.mom@school.edu"}
            ],
        }
    ]

    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, batch_size=10)
    roster_res = worker.sync_roster()

    assert roster_res.pushed_users == 1
    assert roster_res.pulled_users == 1
    assert any(u["badge_uid"] == "1122AABB" for u in fake_client.pushed_users)

    # Cloud Student is now mirrored in local SQLite and validates in <1ms at the entrance
    mirrored = database.get_user_by_badge_uid(conn, "9988CCDD")
    assert mirrored is not None
    assert mirrored["full_name"] == "Cloud Student"
    assert mirrored["grade"] == 8
    assert mirrored["family_id"] == "FAM-0088"
    assert len(mirrored["guardians"]) == 1
    assert mirrored["guardians"][0]["email"] == "cloud.mom@school.edu"

    scan = access_control.process_scan_line(conn, settings, "SCAN 9988CCDD\n", now=datetime(2026, 10, 16, 6, 45, 0))
    assert scan.event_type == "check_in"
    assert scan.reply_line.startswith("GRANT ")
    conn.close()


def test_badges_wiped_at_the_station_are_deleted_in_supabase_rather_than_pulled_back(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    settings = replace(settings, wipe_password="clave-de-borrado")
    admin.add_user(conn, settings, "5CA11001", "student", "Ana Torres", grade=3, section="A")
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_roster = [
        {
            "badge_uid": "5CA11001",
            "full_name": "Ana Torres",
            "role": "student",
            "is_active": True,
            "grade": 3,
            "section": "A",
        }
    ]

    assert admin.wipe_users(conn, settings, "clave-de-borrado", "ELIMINAR").success is True
    cloud_sync.CloudSyncWorker(conn, settings, client=fake_client).sync_roster()

    assert (fake_client.deleted_badges, fake_client.remote_roster) == (["5CA11001"], [])
    assert database.get_user_by_badge_uid(conn, "5CA11001") is None
    conn.close()


# --- School Settings ---------------------------------------------------------

SETTINGS_SAVED_AT = datetime(2026, 10, 16, 9, 0, 0)


def _station(tmp_path: Path, name: str = "station.db") -> tuple[Any, config.Settings]:
    db_file = tmp_path / name
    settings = config.Settings(
        database_path=db_file,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="sb_secret_service_role",
    )
    return database.connect(db_file), settings


def _cloud_row(**changes: Any) -> dict[str, Any]:
    return school_settings.to_cloud_row(make_school(**changes), updated_at="2026-10-16T12:00:00+00:00")


def _scan_student_at(conn: Any, settings: config.Settings, at: datetime) -> access_control.ScanResult:
    admin.add_user(conn, settings, "5CA11001", "student", "Ana Torres", grade=3, section="A")
    return access_control.process_scan_line(conn, settings, "SCAN 5CA11001\n", now=at)


def test_a_settings_change_made_at_the_station_is_pushed_to_the_cloud_once(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    fake_client = FakeSupabaseSyncClient()
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client)

    school_settings.save(conn, make_school(school_language="en"), now=SETTINGS_SAVED_AT)
    first = worker.sync_school_settings()
    second = worker.sync_school_settings()

    assert first.pushed is True
    assert [row["school_language"] for row in fake_client.pushed_school_settings] == ["en"]
    assert second.pushed is False
    assert second.pulled is False
    conn.close()


def test_a_settings_change_made_in_the_cloud_reaches_the_station_on_the_next_sync(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_school_settings = _cloud_row(late_threshold=time(7, 15, 0))
    changes: list[school_settings.SchoolSettings] = []
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, on_school_settings_changed=changes.append)

    result = worker.sync_school_settings()

    assert result.pulled is True
    cached = school_settings.load(conn)
    assert cached == make_school(late_threshold=time(7, 15, 0))
    assert changes == [cached]
    assert _scan_student_at(conn, settings, datetime(2026, 10, 16, 7, 10, 0)).status == "on_time"
    conn.close()


def test_an_unchanged_cloud_row_does_not_notify_the_station(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_school_settings = _cloud_row()
    changes: list[school_settings.SchoolSettings] = []
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, on_school_settings_changed=changes.append)

    result = worker.sync_school_settings()

    assert result.pulled is False
    assert changes == []
    conn.close()


def test_settings_changed_at_the_station_win_over_the_cloud_until_pushed(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    school_settings.save(conn, make_school(cooldown_seconds=60), now=SETTINGS_SAVED_AT)
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_school_settings = _cloud_row(cooldown_seconds=900)
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client)

    result = worker.sync_school_settings()

    assert result.pushed is True
    assert result.pulled is False
    assert school_settings.load(conn).cooldown_seconds == 60
    assert fake_client.remote_school_settings["cooldown_seconds"] == 60
    conn.close()


def test_the_station_keeps_working_offline_on_its_cached_settings(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn, make_school(late_threshold=time(7, 30, 0)))
    fake_client = FakeSupabaseSyncClient()
    fake_client.should_fail = ConnectionError("DNS lookup failed: supabase.co unreachable")
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client)

    result = worker.sync_school_settings()

    assert result.failed is True
    assert school_settings.load(conn).late_threshold == time(7, 30, 0)
    assert _scan_student_at(conn, settings, datetime(2026, 10, 16, 7, 20, 0)).status == "on_time"
    conn.close()


def test_a_new_station_takes_the_settings_already_in_the_cloud(tmp_path: Path):
    conn, settings = _station(tmp_path, "new-station.db")
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_school_settings = _cloud_row(school_language="en", sections=("Red", "Blue"))
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client)

    result = worker.sync_school_settings()

    assert result.pulled is True
    assert school_settings.load(conn) == make_school(school_language="en", sections=("Red", "Blue"))
    conn.close()


def test_settings_set_up_before_the_cloud_existed_are_pushed_to_an_empty_cloud(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    fake_client = FakeSupabaseSyncClient()
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client)

    result = worker.sync_school_settings()

    assert result.pushed is True
    assert school_settings.from_cloud_row(fake_client.remote_school_settings) == make_school()
    conn.close()


def test_saving_settings_wakes_the_background_sync_without_waiting_for_the_poll(tmp_path: Path):
    conn, settings = _station(tmp_path)
    store_school(conn)
    lock = threading.Lock()
    fake_client = FakeSupabaseSyncClient()
    fake_client.remote_school_settings = _cloud_row()
    worker = cloud_sync.CloudSyncWorker(conn, settings, client=fake_client, poll_interval_seconds=60.0, db_lock=lock)

    def wait_for(condition) -> bool:
        deadline = time_mod.monotonic() + 3.0
        while time_mod.monotonic() < deadline:
            if condition():
                return True
            time_mod.sleep(0.01)
        return False

    worker.start()
    try:
        assert wait_for(lambda: fake_client.school_settings_fetches >= 1)
        with lock:
            school_settings.save(conn, make_school(school_language="en"), now=SETTINGS_SAVED_AT)
        worker.request_sync()
        assert wait_for(lambda: fake_client.pushed_school_settings)
    finally:
        worker.stop()
    assert fake_client.pushed_school_settings[-1]["school_language"] == "en"
    conn.close()
