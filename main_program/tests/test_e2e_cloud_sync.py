"""End-to-End integration test: Local SQLite Entrance Scan -> Cloud Sync (Service Role Key) -> Supabase RLS & RPC."""

from __future__ import annotations

import json
import os
import time as time_mod
from datetime import datetime, time
from pathlib import Path

import psycopg2
import pytest
from conftest import make_school, postgres_url, store_school
from dotenv import dotenv_values

import access_control
import admin
import cloud_sync
import config
import database

_DOTENV = dotenv_values(config.REPO_ROOT / ".env")
SUPABASE_URL = os.environ.get("SUPABASE_URL", _DOTENV.get("SUPABASE_URL") or "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get(
    "SUPABASE_SERVICE_ROLE_KEY", _DOTENV.get("SUPABASE_SERVICE_ROLE_KEY") or ""
)

pytestmark = pytest.mark.skipif(
    not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY),
    reason="needs a Supabase project: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
)


@pytest.fixture
def supabase_e2e_seed(supabase_schema):
    """Seeds isolated E2E test records in Supabase PostgreSQL and cleans them up after the test."""
    conn = psycopg2.connect(postgres_url())
    conn.autocommit = True
    cur = conn.cursor()

    # Cleanup any prior E2E records
    cur.execute("DELETE FROM public.attendance_records WHERE badge_uid IN ('E2E10001', 'E2E20002', 'E2EC1', 'TEST_KEY')")
    cur.execute("DELETE FROM public.guardians WHERE email IN ('e2e.sync.guardian@school.edu', 'e2e.other.guardian@school.edu')")
    cur.execute("DELETE FROM public.student_details WHERE family_id IN ('FAM-7100', 'FAM-8200')")
    cur.execute("DELETE FROM public.users WHERE badge_uid IN ('E2E10001', 'E2E20002', 'E2E70007', 'E2EA0001')")

    # 1. Student 1: Grade 7, Section A, FAM-7100
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('E2E10001', 'Camila Ortega', 'student', NULL, TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    s1_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO public.student_details (user_id, grade, section, family_id) VALUES (%s, 7, 'A', 'FAM-7100')",
        (s1_id,),
    )
    cur.execute(
        "INSERT INTO public.guardians (student_id, position, name, phone, email) VALUES (%s, 1, 'Madre Camila', '+50587771111', 'e2e.sync.guardian@school.edu')",
        (s1_id,),
    )

    # 2. Student 2: Grade 9, Section B, FAM-8200 (Other Family & Grade)
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('E2E20002', 'Andres Castillo', 'student', NULL, TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    s2_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO public.student_details (user_id, grade, section, family_id) VALUES (%s, 9, 'B', 'FAM-8200')",
        (s2_id,),
    )
    cur.execute(
        "INSERT INTO public.guardians (student_id, position, name, phone, email) VALUES (%s, 1, 'Padre Andres', '+50587772222', 'e2e.other.guardian@school.edu')",
        (s2_id,),
    )

    # 3. Teacher for Grade 7
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('E2E70007', 'Prof. Septimo', 'teacher', 'e2e.sync.teacher@school.edu', TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    t7_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO public.teacher_details (user_id, taught_grade) VALUES (%s, 7)",
        (t7_id,),
    )

    # 4. Admin
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('E2EA0001', 'Admin E2E Sync', 'admin', 'e2e.sync.admin@school.edu', TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    adm_id = cur.fetchone()[0]

    cur.close()
    conn.close()

    yield {"s1_id": s1_id, "s2_id": s2_id, "t7_id": t7_id, "adm_id": adm_id}

    # Cleanup
    conn = psycopg2.connect(postgres_url())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM public.attendance_records WHERE badge_uid IN ('E2E10001', 'E2E20002', 'E2EC1', 'TEST_KEY')")
    cur.execute("DELETE FROM public.guardians WHERE email IN ('e2e.sync.guardian@school.edu', 'e2e.other.guardian@school.edu')")
    cur.execute("DELETE FROM public.student_details WHERE family_id IN ('FAM-7100', 'FAM-8200')")
    cur.execute("DELETE FROM public.users WHERE badge_uid IN ('E2E10001', 'E2E20002', 'E2E70007', 'E2EA0001')")
    cur.close()
    conn.close()


def test_e2e_offline_scan_cloud_sync_and_rls_portal_visibility(tmp_path: Path, supabase_e2e_seed):
    """Local SQLite scan (<1ms) queues while offline, flushes to Supabase via Service Role Key, and respects RLS."""
    sqlite_file = tmp_path / "entrance_local.db"
    local_conn = database.connect(sqlite_file)
    store_school(local_conn, make_school(late_threshold=time(6, 50, 0), cooldown_seconds=300))
    settings = config.Settings(
        database_path=sqlite_file,
        supabase_url=SUPABASE_URL,
        supabase_service_role_key=SUPABASE_SERVICE_ROLE_KEY,
    )

    # Register Student 1 in local SQLite cache
    admin.add_user(
        local_conn,
        settings=settings,
        badge_uid="E2E10001",
        role="student",
        full_name="Camila Ortega",
        grade=7,
        section="A",
        guardians=[admin.GuardianData(name="Madre Camila", phone="+50587771111", email="e2e.sync.guardian@school.edu")],
        family_id="FAM-7100",
    )

    # Step 1: Simulate offline outage during morning arrival scan
    unreachable_client = cloud_sync.SupabaseRestSyncClient(
        "http://127.0.0.1:59999", "sb_secret_invalid", timeout_seconds=0.2
    )
    offline_worker = cloud_sync.CloudSyncWorker(
        local_conn, settings, client=unreachable_client, base_backoff_seconds=0.5
    )

    t0 = time_mod.perf_counter()
    checkin_res = access_control.process_scan_line(
        local_conn, settings, "SCAN E2E10001\n", now=datetime(2026, 10, 16, 6, 42, 0)
    )
    elapsed_ms = (time_mod.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 5.0
    assert checkin_res.event_type == "check_in"
    assert checkin_res.status == "on_time"
    assert checkin_res.reply_line.startswith("GRANT ")

    # Attempt sync while unreachable -> fails gracefully, local record stays is_synced=0
    outage_sync = offline_worker.sync_once()
    assert outage_sync.failed is True
    assert outage_sync.synced_count == 0

    # Step 2: Afternoon Check-out scan
    checkout_res = access_control.process_scan_line(
        local_conn, settings, "SCAN E2E10001\n", now=datetime(2026, 10, 16, 13, 35, 0)
    )
    assert checkout_res.event_type == "check_out"
    assert checkout_res.reply_line.startswith("GRANT ")

    # Step 3: Connectivity returns -> CloudSyncWorker flushes queued Check-in & Check-out to live Supabase using Service Role Key
    live_worker = cloud_sync.CloudSyncWorker(local_conn, settings)
    flush_res = live_worker.sync_once(now=datetime(2026, 10, 16, 13, 36, 0))
    assert flush_res.failed is False
    assert flush_res.synced_count == 2

    # Verify local SQLite records are marked is_synced = 1
    l_cur = local_conn.cursor()
    l_cur.execute("SELECT is_synced FROM attendance_records WHERE badge_uid = 'E2E10001'")
    assert all(r["is_synced"] == 1 for r in l_cur.fetchall())
    local_conn.close()

    # Step 4: Verify visibility & RLS isolation across Guardian, Teacher, and Admin sessions in Supabase
    pg_conn = psycopg2.connect(postgres_url())
    pg_conn.autocommit = False
    cur = pg_conn.cursor()

    def set_jwt_role(email: str):
        cur.execute("RESET ROLE")
        claims = json.dumps({"email": email, "role": "authenticated"})
        cur.execute("SET LOCAL ROLE authenticated")
        cur.execute("SELECT set_config('request.jwt.claim.email', %s, true)", (email,))
        cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))

    # 4a. Guardian of FAM-7100 sees Camila's Check-in and Check-out and Year View stats
    set_jwt_role("e2e.sync.guardian@school.edu")
    cur.execute(
        "SELECT event_type, status, time FROM public.attendance_records WHERE date = '2026-10-16' ORDER BY time ASC"
    )
    g_rows = cur.fetchall()
    assert g_rows == [("check_in", "on_time", "06:42:00"), ("check_out", None, "13:35:00")]

    cur.execute("SELECT public.get_year_view_stats('2026-10-16', '2026-10-16')")
    g_year = cur.fetchone()[0]
    assert g_year["family_id"] == "FAM-7100"
    assert len(g_year["students"]) == 1
    assert g_year["students"][0]["name"] == "Camila Ortega"
    assert g_year["students"][0]["metrics"]["present_days"] == 1
    assert g_year["students"][0]["metrics"]["punctuality_rate"] == 100.0
    assert g_year["students"][0]["history"][0]["status"] == "departed"

    # 4b. Guardian of FAM-8200 CANNOT see FAM-7100 records, and sees their own absent child's Absence on 2026-10-16
    set_jwt_role("e2e.other.guardian@school.edu")
    cur.execute("SELECT COUNT(*) FROM public.attendance_records WHERE badge_uid = 'E2E10001'")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT public.get_year_view_stats('2026-10-16', '2026-10-16')")
    other_year = cur.fetchone()[0]
    assert other_year["family_id"] == "FAM-8200"
    assert len(other_year["students"]) == 1
    assert other_year["students"][0]["name"] == "Andres Castillo"
    assert other_year["students"][0]["absent_days"] == 1
    assert other_year["students"][0]["days"]["2026-10-16"] == "A"

    # 4c. Teacher of Grade 7 sees Camila Ortega (Grade 7) but NOT Andres Castillo (Grade 9)
    set_jwt_role("e2e.sync.teacher@school.edu")
    cur.execute("SELECT public.get_year_view_stats('2026-10-16', '2026-10-16')")
    t_year = cur.fetchone()[0]
    assert t_year["grade"] == 7
    t_names = [s["name"] for s in t_year["students"]]
    assert "Camila Ortega" in t_names
    assert "Andres Castillo" not in t_names

    # 4d. Admin sees both Grade 7 and Grade 9 students
    set_jwt_role("e2e.sync.admin@school.edu")
    cur.execute("SELECT public.get_year_view_stats('2026-10-16', '2026-10-16')")
    a_year = cur.fetchone()[0]
    a_names = [s["name"] for s in a_year["students"]]
    assert "Camila Ortega" in a_names
    assert "Andres Castillo" in a_names

    pg_conn.rollback()
    pg_conn.close()
