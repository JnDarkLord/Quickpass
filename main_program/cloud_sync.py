"""Asynchronous background Cloud Sync worker & local SQLite cache manager.

Synchronizes with Supabase as the single Source of Truth and SQLite as a local cache:
- Users & Badges (`users`, `student_details`, `teacher_details`, `guardians`):
  Mirrored persistently in local SQLite (never auto-evicted) so physical entrance badge
  validation and Door Gate opening always run in <1ms even during internet outages.
- Attendance Scans (`attendance_records`):
  Written locally to SQLite first (`is_synced = 0`), batched to Supabase via `supabase-py`
  using the Service Role Key (`is_synced = 1`), and automatically evicted from SQLite once
  the school day ends (`date < today` and `is_synced = 1`) while keeping today's scans
  cached for instant offline Check-in / Check-out / Cooldown deduplication.
- School Settings (`school_settings`):
  Cached locally so the entrance applies the School's policies offline. A change saved
  at this station is pushed (and wins over the cloud copy until then); otherwise the
  cloud copy is pulled when it differs from the cache.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import database
import school_settings
from config import Settings
from school_settings import CachedSchoolSettings, SchoolSettings
from supabase import Client, ClientOptions, create_client

logger = logging.getLogger(__name__)


class SyncTargetClient(Protocol):
    """SDK-style boundary interface for syncing attendance scans, users, and their Badges with Supabase."""

    def upsert_attendance_records(self, records: list[dict[str, Any]]) -> None: ...


@dataclass(frozen=True)
class SyncBatchResult:
    synced_count: int
    evicted_count: int = 0
    failed: bool = False
    error: str = ""
    backoff_seconds: float = 0.0


@dataclass(frozen=True)
class RosterSyncResult:
    pushed_users: int = 0
    pulled_users: int = 0
    failed: bool = False
    error: str = ""


@dataclass(frozen=True)
class SettingsSyncResult:
    pushed: bool = False
    pulled: bool = False
    failed: bool = False
    error: str = ""


class SupabaseSyncClient:
    """Syncs attendance records, users, and their Badges with Supabase via `supabase-py` using the Service Role Key."""

    def __init__(
        self,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._service_role_key = service_role_key
        self._timeout = timeout_seconds
        self._client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = create_client(
                self._base_url,
                self._service_role_key,
                options=ClientOptions(postgrest_client_timeout=self._timeout),
            )
        return self._client

    def upsert_attendance_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        payload = [
            {
                "event_type": r["event_type"],
                "date": r["date"],
                "time": r["time"],
                "status": r["status"],
                "badge_uid": r["badge_uid"],
                "user_id": r["user_id"],
                "name": r["name"],
                "role": r["role"],
                "grade": r["grade"],
                "section": r["section"],
            }
            for r in records
        ]
        client = self._get_client()
        client.table("attendance_records").upsert(
            payload,
            on_conflict="badge_uid,date,time,event_type",
        ).execute()

    def fetch_roster(self) -> list[dict[str, Any]]:
        """Fetch all users and their student/teacher/guardian details from Supabase."""
        client = self._get_client()
        users_res = client.table("users").select("*").execute()
        sd_res = client.table("student_details").select("*").execute()
        td_res = client.table("teacher_details").select("*").execute()
        g_res = client.table("guardians").select("*").order("position").execute()

        sd_by_uid = {row["user_id"]: row for row in (sd_res.data or [])}
        td_by_uid = {row["user_id"]: row for row in (td_res.data or [])}
        g_by_uid: dict[int, list[dict[str, Any]]] = {}
        for g in g_res.data or []:
            g_by_uid.setdefault(g["student_id"], []).append(
                {
                    "position": g["position"],
                    "name": g["name"],
                    "phone": g["phone"],
                    "email": g.get("email"),
                }
            )

        roster: list[dict[str, Any]] = []
        for u in users_res.data or []:
            uid_int = u["id"]
            sd = sd_by_uid.get(uid_int)
            td = td_by_uid.get(uid_int)
            roster.append(
                {
                    "badge_uid": u["badge_uid"],
                    "full_name": u["full_name"],
                    "role": u["role"],
                    "email": u.get("email"),
                    "is_active": bool(u.get("is_active", True)),
                    "created_at": u["created_at"],
                    "grade": sd["grade"] if sd else None,
                    "section": sd["section"] if sd else None,
                    "family_id": sd.get("family_id") if sd else None,
                    "graduation_date": sd.get("graduation_date") if sd else None,
                    "taught_grade": td["taught_grade"] if td else None,
                    "guardians": g_by_uid.get(uid_int, []),
                }
            )
        return roster

    def upsert_user(self, user_bundle: dict[str, Any]) -> None:
        """Upsert a single user and their role-specific details/guardians into Supabase."""
        client = self._get_client()
        user_payload = {
            "badge_uid": user_bundle["badge_uid"],
            "full_name": user_bundle["full_name"],
            "role": user_bundle["role"],
            "email": user_bundle.get("email") or None,
            "is_active": bool(user_bundle.get("is_active", True)),
            "created_at": user_bundle["created_at"],
        }
        res = client.table("users").upsert(user_payload, on_conflict="badge_uid").execute()
        rows = res.data or []
        if not rows:
            lookup = client.table("users").select("id").eq("badge_uid", user_bundle["badge_uid"]).execute()
            rows = lookup.data or []
        if not rows:
            return
        remote_user_id = rows[0]["id"]

        role = user_bundle["role"]
        if role in ("student", "graduate") and user_bundle.get("grade") is not None:
            family_id = user_bundle.get("family_id") or f"FAM-{remote_user_id:04d}"
            client.table("student_details").upsert(
                {
                    "user_id": remote_user_id,
                    "grade": int(user_bundle["grade"]),
                    "section": str(user_bundle.get("section") or "A"),
                    "family_id": family_id,
                    "graduation_date": user_bundle.get("graduation_date"),
                },
                on_conflict="user_id",
            ).execute()

            client.table("guardians").delete().eq("student_id", remote_user_id).execute()
            guardians = user_bundle.get("guardians") or []
            if guardians:
                g_payload = [
                    {
                        "student_id": remote_user_id,
                        "position": int(g.get("position", idx + 1)),
                        "name": g["name"],
                        "phone": g["phone"],
                        "email": g.get("email") or None,
                    }
                    for idx, g in enumerate(guardians)
                ]
                client.table("guardians").insert(g_payload).execute()

        elif role == "teacher" and user_bundle.get("taught_grade") is not None:
            client.table("teacher_details").upsert(
                {
                    "user_id": remote_user_id,
                    "taught_grade": int(user_bundle["taught_grade"]),
                },
                on_conflict="user_id",
            ).execute()

    def delete_user(self, badge_uid: str) -> None:
        """Delete a user by Badge UID from Supabase."""
        client = self._get_client()
        client.table("users").delete().eq("badge_uid", badge_uid).execute()

    def fetch_school_settings(self) -> dict[str, Any] | None:
        """Fetch the School Settings row, or None before any station has pushed one."""
        client = self._get_client()
        res = client.table("school_settings").select("*").eq("id", 1).execute()
        rows = res.data or []
        return rows[0] if rows and isinstance(rows[0], dict) else None

    def upsert_school_settings(self, row: dict[str, Any]) -> None:
        client = self._get_client()
        client.table("school_settings").upsert(row, on_conflict="id").execute()


SupabaseRestSyncClient = SupabaseSyncClient


class CloudSyncWorker:
    """Background worker that syncs local SQLite attendance scans and mirrors users and their Badges with Supabase."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        client: Any | None = None,
        batch_size: int = 50,
        poll_interval_seconds: float = 5.0,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        db_lock: threading.Lock | None = None,
        on_school_settings_changed: Callable[[SchoolSettings], None] | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._batch_size = batch_size
        self._poll_interval = poll_interval_seconds
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._lock = db_lock or threading.Lock()
        self._on_school_settings_changed = on_school_settings_changed

        if client is not None:
            self._client: Any | None = client
        elif settings.supabase_url and settings.supabase_service_role_key:
            self._client = SupabaseSyncClient(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
        else:
            self._client = None

        self._consecutive_failures = 0
        self._current_backoff = 0.0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def current_backoff_seconds(self) -> float:
        return self._current_backoff

    def _evict_previous_days_scans(self, today_str: str) -> int:
        """Delete synced attendance_records from previous days while preserving today's scans."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                    DELETE FROM attendance_records
                    WHERE date < ?
                      AND (is_synced = 1 OR event_type NOT IN ('check_in', 'check_out'))
                    """,
                (today_str,),
            )
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    def sync_once(self, now: datetime | None = None) -> SyncBatchResult:
        """Flushes one batch of unsynced Check-in/Check-out records to Supabase and evicts old synced days."""
        if self._client is None:
            return SyncBatchResult(synced_count=0, evicted_count=0, failed=False)

        now_dt = now or datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT id, event_type, date, time, status, badge_uid, user_id, name, role, grade, section
                FROM attendance_records
                WHERE is_synced = 0 AND event_type IN ('check_in', 'check_out')
                ORDER BY id ASC
                LIMIT ?
                """,
                (self._batch_size,),
            )
            rows = [dict(r) for r in cursor.fetchall()]

        if not rows:
            evicted = self._evict_previous_days_scans(today_str)
            return SyncBatchResult(synced_count=0, evicted_count=evicted, failed=False, backoff_seconds=0.0)

        try:
            self._client.upsert_attendance_records(rows)
        except Exception as exc:
            self._consecutive_failures += 1
            backoff = min(
                self._max_backoff,
                self._base_backoff * (2 ** (self._consecutive_failures - 1)),
            )
            self._current_backoff = float(backoff)
            logger.warning(
                "Cloud Sync failed (attempt %d, backoff %.1fs): %s",
                self._consecutive_failures,
                self._current_backoff,
                exc,
            )
            return SyncBatchResult(
                synced_count=0,
                evicted_count=0,
                failed=True,
                error=str(exc),
                backoff_seconds=self._current_backoff,
            )

        synced_ts = now_dt.strftime("%Y-%m-%dT%H:%M:%S")
        record_ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in record_ids)

        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE attendance_records SET is_synced = 1, synced_at = ? WHERE id IN ({placeholders})",
                [synced_ts, *record_ids],
            )

        evicted = self._evict_previous_days_scans(today_str)
        self._consecutive_failures = 0
        self._current_backoff = 0.0
        return SyncBatchResult(
            synced_count=len(rows),
            evicted_count=evicted,
            failed=False,
            backoff_seconds=0.0,
        )

    def sync_roster(self) -> RosterSyncResult:
        """Synchronize the persistent mirror of users and their Badges between local SQLite and Supabase."""
        if self._client is None or not hasattr(self._client, "fetch_roster"):
            return RosterSyncResult()

        pushed = 0
        pulled = 0

        try:
            with self._lock:
                cur = self._conn.cursor()
                cur.execute("SELECT badge_uid FROM deleted_users")
                deleted_uids = [r["badge_uid"] for r in cur.fetchall()]

            if deleted_uids and hasattr(self._client, "delete_user"):
                for d_uid in deleted_uids:
                    self._client.delete_user(d_uid)
                    with self._lock, self._conn:
                        self._conn.execute("DELETE FROM deleted_users WHERE badge_uid = ?", (d_uid,))

            with self._lock:
                cur = self._conn.cursor()
                cur.execute("SELECT badge_uid FROM users WHERE is_synced = 0")
                unsynced_uids = [r["badge_uid"] for r in cur.fetchall()]

            for uid in unsynced_uids:
                with self._lock:
                    user_bundle = database.get_user_by_badge_uid(self._conn, uid)
                if user_bundle is not None:
                    self._client.upsert_user(user_bundle)
                    with self._lock, self._conn:
                        self._conn.execute(
                            "UPDATE users SET is_synced = 1 WHERE badge_uid = ?",
                            (uid,),
                        )
                    pushed += 1

            remote_roster = self._client.fetch_roster()
            for r_user in remote_roster:
                norm_uid = database.normalize_badge_uid(r_user["badge_uid"])
                if not norm_uid:
                    continue
                with self._lock:
                    existing = database.get_user_by_badge_uid(self._conn, norm_uid)
                    with self._conn:
                        c = self._conn.cursor()
                        is_active_int = 1 if r_user.get("is_active", True) else 0
                        email_val = r_user.get("email") or None
                        if existing is None:
                            c.execute(
                                """
                                INSERT INTO users (badge_uid, full_name, role, email, is_active, created_at, is_synced)
                                VALUES (?, ?, ?, ?, ?, ?, 1)
                                """,
                                (
                                    norm_uid,
                                    r_user["full_name"],
                                    r_user["role"],
                                    email_val,
                                    is_active_int,
                                    r_user.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                ),
                            )
                            local_uid = c.lastrowid
                            pulled += 1
                        else:
                            local_uid = existing["id"]
                            c.execute(
                                """
                                UPDATE users
                                SET full_name = ?, role = ?, email = ?, is_active = ?, is_synced = 1
                                WHERE id = ?
                                """,
                                (
                                    r_user["full_name"],
                                    r_user["role"],
                                    email_val,
                                    is_active_int,
                                    local_uid,
                                ),
                            )

                        role = r_user["role"]
                        if role in ("student", "graduate") and r_user.get("grade") is not None:
                            c.execute("DELETE FROM student_details WHERE user_id = ?", (local_uid,))
                            c.execute(
                                """
                                INSERT INTO student_details (user_id, grade, section, graduation_date, family_id)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    local_uid,
                                    int(r_user["grade"]),
                                    str(r_user.get("section") or "A"),
                                    r_user.get("graduation_date"),
                                    r_user.get("family_id") or f"FAM-{local_uid:04d}",
                                ),
                            )
                            c.execute("DELETE FROM guardians WHERE student_id = ?", (local_uid,))
                            for idx, g in enumerate(r_user.get("guardians") or []):
                                c.execute(
                                    """
                                    INSERT INTO guardians (student_id, position, name, phone, email)
                                    VALUES (?, ?, ?, ?, ?)
                                    """,
                                    (
                                        local_uid,
                                        int(g.get("position", idx + 1)),
                                        g["name"],
                                        g["phone"],
                                        g.get("email") or None,
                                    ),
                                )
                        elif role == "teacher" and r_user.get("taught_grade") is not None:
                            c.execute("DELETE FROM teacher_details WHERE user_id = ?", (local_uid,))
                            c.execute(
                                "INSERT INTO teacher_details (user_id, taught_grade) VALUES (?, ?)",
                                (local_uid, int(r_user["taught_grade"])),
                            )

            return RosterSyncResult(pushed_users=pushed, pulled_users=pulled, failed=False)
        except Exception as exc:
            logger.warning("Roster sync failed: %s", exc)
            return RosterSyncResult(pushed_users=pushed, pulled_users=pulled, failed=True, error=str(exc))

    def sync_school_settings(self, pull: bool = True) -> SettingsSyncResult:
        """Push School Settings saved at this station, or pull the cloud copy when it differs."""
        if self._client is None or not hasattr(self._client, "fetch_school_settings"):
            return SettingsSyncResult()

        try:
            with self._lock:
                cached = school_settings.load_cached(self._conn)
            if cached is not None and not cached.synced:
                self._push_school_settings(cached)
                return SettingsSyncResult(pushed=True)
            if not pull:
                return SettingsSyncResult()

            remote = self._client.fetch_school_settings()
            if remote is None:
                if cached is None:
                    return SettingsSyncResult()
                self._push_school_settings(cached)
                return SettingsSyncResult(pushed=True)

            remote_school = school_settings.from_cloud_row(remote)
            if cached is not None and remote_school == cached.school:
                return SettingsSyncResult()
            with self._lock:
                latest = school_settings.load_cached(self._conn)
                if latest is not None and not latest.synced:
                    return SettingsSyncResult()
                stored = school_settings.store_synced(
                    self._conn, remote_school, updated_at=str(remote.get("updated_at") or "")
                )
        except Exception as exc:
            logger.warning("School Settings sync failed: %s", exc)
            return SettingsSyncResult(failed=True, error=str(exc))

        if self._on_school_settings_changed is not None:
            try:
                self._on_school_settings_changed(stored)
            except Exception:
                logger.exception("Applying the pulled School Settings failed")
        return SettingsSyncResult(pulled=True)

    def _push_school_settings(self, cached: CachedSchoolSettings) -> None:
        assert self._client is not None
        self._client.upsert_school_settings(school_settings.to_cloud_row(cached.school, cached.updated_at))
        with self._lock:
            school_settings.mark_synced(self._conn, cached.updated_at)

    def request_sync(self) -> None:
        """Wake the background loop to sync now instead of at the next poll."""
        self._wake_event.set()

    def start(self) -> None:
        """Starts the background daemon thread if not already running."""
        if self._client is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="CloudSyncWorker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signals the background thread to stop and waits up to `timeout` seconds."""
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run_loop(self) -> None:
        tick = 0
        while not self._stop_event.is_set():
            self._wake_event.clear()
            pull = tick % 6 == 0
            self.sync_school_settings(pull=pull)
            if pull:
                self.sync_roster()
            res = self.sync_once()
            tick += 1
            wait_sec = res.backoff_seconds if res.failed else self._poll_interval
            self._wake_event.wait(timeout=wait_sec)
