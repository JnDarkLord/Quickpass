"""Database Engine, Authorized Email Trigger, RLS Policies, and RPC Aggregation tests."""

from __future__ import annotations

import json
import uuid

import psycopg2
import pytest

ERR_UNAUTHORIZED_EMAIL = "ERR_UNAUTHORIZED_EMAIL"


def _seed_school_fixtures(cur):
    """Seeds two families, two grades, a guardian, a teacher, and an admin inside the current transaction."""
    # Student 1: Grade 5, Section A, FAM-5001
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('RLS_S1_5A', 'Valeria Mendoza', 'student', NULL, TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    s1_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO public.student_details (user_id, grade, section, family_id)
        VALUES (%s, 5, 'A', 'FAM-5001')
        """,
        (s1_id,),
    )

    # Student 2 (Sibling of S1): Grade 5, Section B, FAM-5001
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('RLS_S2_5B', 'Mateo Mendoza', 'student', NULL, TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    s2_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO public.student_details (user_id, grade, section, family_id)
        VALUES (%s, 5, 'B', 'FAM-5001')
        """,
        (s2_id,),
    )

    # Student 3 (Different Family & Grade): Grade 8, Section A, FAM-8002
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('RLS_S3_8A', 'Carlos Rivas', 'student', NULL, TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    s3_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO public.student_details (user_id, grade, section, family_id)
        VALUES (%s, 8, 'A', 'FAM-8002')
        """,
        (s3_id,),
    )

    # Guardian for FAM-5001
    cur.execute(
        """
        INSERT INTO public.guardians (student_id, position, name, phone, email)
        VALUES (%s, 1, 'Elena Mendoza', '+50588881111', 'elena.mendoza@school.edu')
        """,
        (s1_id,),
    )

    # Guardian for FAM-8002
    cur.execute(
        """
        INSERT INTO public.guardians (student_id, position, name, phone, email)
        VALUES (%s, 1, 'Roberto Rivas', '+50588882222', 'roberto.rivas@school.edu')
        """,
        (s3_id,),
    )

    # Teacher for Grade 5
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('RLS_T_G5', 'Prof. Laura Solis', 'teacher', 'laura.solis@school.edu', TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    t5_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO public.teacher_details (user_id, taught_grade)
        VALUES (%s, 5)
        """,
        (t5_id,),
    )

    # Admin
    cur.execute(
        """
        INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES ('RLS_ADM1', 'Director General', 'admin', 'director@school.edu', TRUE, '2026-10-16T06:00:00')
        RETURNING id
        """
    )
    adm_id = cur.fetchone()[0]

    return {
        "s1_id": s1_id,
        "s2_id": s2_id,
        "s3_id": s3_id,
        "t5_id": t5_id,
        "adm_id": adm_id,
    }


def _simulate_auth_session(cur, email: str):
    """Switches the current transaction to the `authenticated` role with JWT email claim."""
    claims = json.dumps({"email": email, "role": "authenticated"})
    cur.execute("SET LOCAL ROLE authenticated")
    cur.execute("SELECT set_config('request.jwt.claim.email', %s, true)", (email,))
    cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))


def test_authorized_email_trigger_blocks_unlisted_and_allows_whitelisted(db_conn):
    """BEFORE INSERT trigger on auth.users rejects unauthorized emails and allows whitelisted ones."""
    cur = db_conn.cursor()
    _seed_school_fixtures(cur)

    cur.execute("SAVEPOINT before_unauth")
    with pytest.raises(psycopg2.Error) as exc_info:
        cur.execute(
            """
            INSERT INTO auth.users (id, email)
            VALUES (%s, %s)
            """,
            (str(uuid.uuid4()), "intruder@outsider.org"),
        )
    assert exc_info.value.diag.message_primary == ERR_UNAUTHORIZED_EMAIL
    cur.execute("ROLLBACK TO SAVEPOINT before_unauth")

    # Whitelisted Guardian (case-insensitive check)
    cur.execute(
        "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
        (str(uuid.uuid4()), "ELENA.MENDOZA@SCHOOL.EDU"),
    )
    # Whitelisted Teacher
    cur.execute(
        "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
        (str(uuid.uuid4()), "laura.solis@school.edu"),
    )
    # Whitelisted Admin
    cur.execute(
        "INSERT INTO auth.users (id, email) VALUES (%s, %s)",
        (str(uuid.uuid4()), "director@school.edu"),
    )


def test_get_my_profile_resolves_role_and_scope(db_conn):
    """Authenticated users resolve their Role, display name, and scope via get_my_profile()."""
    cur = db_conn.cursor()
    _seed_school_fixtures(cur)

    # 1. Guardian profile resolution
    _simulate_auth_session(cur, "elena.mendoza@school.edu")
    cur.execute("SELECT public.get_my_profile()")
    g_profile = cur.fetchone()[0]
    assert g_profile["role"] == "guardian"
    assert g_profile["name"] == "Elena Mendoza"
    assert g_profile["linked_entity_id"] == "FAM-5001"
    assert g_profile["details"]["family_id"] == "FAM-5001"
    assert len(g_profile["details"]["children"]) == 2

    # 2. Teacher profile resolution
    cur.execute("RESET ROLE")
    _simulate_auth_session(cur, "laura.solis@school.edu")
    cur.execute("SELECT public.get_my_profile()")
    t_profile = cur.fetchone()[0]
    assert t_profile["role"] == "teacher"
    assert t_profile["name"] == "Prof. Laura Solis"
    assert t_profile["details"]["taught_grade"] == 5

    # 3. Admin profile resolution
    cur.execute("RESET ROLE")
    _simulate_auth_session(cur, "director@school.edu")
    cur.execute("SELECT public.get_my_profile()")
    a_profile = cur.fetchone()[0]
    assert a_profile["role"] == "admin"
    assert a_profile["name"] == "Director General"


def test_web_account_lookup_rejects_unlisted_email_with_the_neutral_code(db_conn):
    cur = db_conn.cursor()
    _seed_school_fixtures(cur)
    _simulate_auth_session(cur, "intruder@outsider.org")

    with pytest.raises(psycopg2.Error) as exc_info:
        cur.execute("SELECT public.get_web_account()")

    assert exc_info.value.diag.message_primary == ERR_UNAUTHORIZED_EMAIL


def test_rls_policies_isolate_guardian_teacher_and_allow_admin(db_conn):
    """RLS policies enforce Family Code for Guardians, Grade for Teachers, and school-wide access for Admins."""
    cur = db_conn.cursor()
    ids = _seed_school_fixtures(cur)

    # Seed attendance records for S1 (FAM-5001, Grade 5), S2 (FAM-5001, Grade 5), and S3 (FAM-8002, Grade 8)
    cur.execute(
        """
        INSERT INTO public.attendance_records (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
        VALUES
            ('check_in', '2026-10-16', '06:40:00', 'on_time', 'RLS_S1_5A', %s, 'Valeria Mendoza', 'student', 5, 'A'),
            ('check_in', '2026-10-16', '07:05:00', 'late', 'RLS_S2_5B', %s, 'Mateo Mendoza', 'student', 5, 'B'),
            ('check_in', '2026-10-16', '06:45:00', 'on_time', 'RLS_S3_8A', %s, 'Carlos Rivas', 'student', 8, 'A')
        """,
        (ids["s1_id"], ids["s2_id"], ids["s3_id"]),
    )

    # 1. Guardian Session (FAM-5001)
    _simulate_auth_session(cur, "elena.mendoza@school.edu")
    cur.execute("SELECT public.get_auth_role(), public.get_auth_family_id()")
    role_val, fam_val = cur.fetchone()
    assert role_val == "guardian"
    assert fam_val == "FAM-5001"

    cur.execute("SELECT family_id FROM public.student_details WHERE family_id IN ('FAM-5001', 'FAM-8002')")
    g_families = {r[0] for r in cur.fetchall()}
    assert g_families == {"FAM-5001"}

    cur.execute(
        "SELECT badge_uid FROM public.attendance_records WHERE badge_uid IN ('RLS_S1_5A', 'RLS_S2_5B', 'RLS_S3_8A')"
    )
    g_badges = {r[0] for r in cur.fetchall()}
    assert g_badges == {"RLS_S1_5A", "RLS_S2_5B"}

    # Explicit query for another family returns zero rows
    cur.execute("SELECT COUNT(*) FROM public.student_details WHERE family_id = 'FAM-8002'")
    assert cur.fetchone()[0] == 0

    # 2. Teacher Session (Grade 5)
    cur.execute("RESET ROLE")
    _simulate_auth_session(cur, "laura.solis@school.edu")
    cur.execute("SELECT public.get_auth_role(), public.get_auth_teacher_grade()")
    t_role, t_grade = cur.fetchone()
    assert t_role == "teacher"
    assert t_grade == 5

    cur.execute("SELECT badge_uid FROM public.users WHERE badge_uid IN ('RLS_S1_5A', 'RLS_S2_5B', 'RLS_S3_8A')")
    t_students = {r[0] for r in cur.fetchall()}
    assert t_students == {"RLS_S1_5A", "RLS_S2_5B"}

    cur.execute(
        "SELECT badge_uid FROM public.attendance_records WHERE badge_uid IN ('RLS_S1_5A', 'RLS_S2_5B', 'RLS_S3_8A')"
    )
    t_records = {r[0] for r in cur.fetchall()}
    assert t_records == {"RLS_S1_5A", "RLS_S2_5B"}

    # Explicit query for Grade 8 returns zero rows
    cur.execute("SELECT COUNT(*) FROM public.attendance_records WHERE grade = 8 AND badge_uid = 'RLS_S3_8A'")
    assert cur.fetchone()[0] == 0

    # 3. Admin Session (All Grades & Families)
    cur.execute("RESET ROLE")
    _simulate_auth_session(cur, "director@school.edu")
    cur.execute("SELECT public.get_auth_role()")
    assert cur.fetchone()[0] == "admin"

    cur.execute(
        "SELECT badge_uid FROM public.attendance_records WHERE badge_uid IN ('RLS_S1_5A', 'RLS_S2_5B', 'RLS_S3_8A')"
    )
    a_records = {r[0] for r in cur.fetchall()}
    assert a_records == {"RLS_S1_5A", "RLS_S2_5B", "RLS_S3_8A"}


def test_get_year_view_stats_aggregates_and_respects_rls(db_conn):
    """get_year_view_stats computes accurate attendance/punctuality metrics and enforces RLS."""
    cur = db_conn.cursor()
    ids = _seed_school_fixtures(cur)

    # Seed 3 days of attendance in window 2026-10-12 .. 2026-10-14
    cur.execute(
        """
        INSERT INTO public.attendance_records (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
        VALUES
            -- 2026-10-12: S1 on_time + check_out, S2 late, S3 on_time
            ('check_in',  '2026-10-12', '06:40:00', 'on_time', 'RLS_S1_5A', %s, 'Valeria Mendoza', 'student', 5, 'A'),
            ('check_out', '2026-10-12', '13:30:00', NULL,      'RLS_S1_5A', %s, 'Valeria Mendoza', 'student', 5, 'A'),
            ('check_in',  '2026-10-12', '07:05:00', 'late',    'RLS_S2_5B', %s, 'Mateo Mendoza',   'student', 5, 'B'),
            ('check_in',  '2026-10-12', '06:42:00', 'on_time', 'RLS_S3_8A', %s, 'Carlos Rivas',    'student', 8, 'A'),
            -- 2026-10-13: S1 late, S2 on_time
            ('check_in',  '2026-10-13', '07:10:00', 'late',    'RLS_S1_5A', %s, 'Valeria Mendoza', 'student', 5, 'A'),
            ('check_in',  '2026-10-13', '06:45:00', 'on_time', 'RLS_S2_5B', %s, 'Mateo Mendoza',   'student', 5, 'B'),
            -- 2026-10-14: S1 on_time, S2 absent
            ('check_in',  '2026-10-14', '06:35:00', 'on_time', 'RLS_S1_5A', %s, 'Valeria Mendoza', 'student', 5, 'A')
        """,
        (
            ids["s1_id"],
            ids["s1_id"],
            ids["s2_id"],
            ids["s3_id"],
            ids["s1_id"],
            ids["s2_id"],
            ids["s1_id"],
        ),
    )

    # 1. Guardian calls get_year_view_stats for 2026-10-12 .. 2026-10-14
    _simulate_auth_session(cur, "elena.mendoza@school.edu")
    cur.execute("SELECT public.get_year_view_stats('2026-10-12', '2026-10-14')")
    g_stats = cur.fetchone()[0]

    assert g_stats["family_id"] == "FAM-5001"
    student_names = [s["name"] for s in g_stats["students"]]
    assert "Valeria Mendoza" in student_names
    assert "Mateo Mendoza" in student_names
    assert "Carlos Rivas" not in student_names

    s1_stats = next(s for s in g_stats["students"] if s["name"] == "Valeria Mendoza")
    assert s1_stats["metrics"]["present_days"] == 3
    assert s1_stats["metrics"]["late_days"] == 1
    assert s1_stats["metrics"]["absent_days"] == 0
    assert s1_stats["metrics"]["punctuality_rate"] == 66.7
    assert s1_stats["days"]["2026-10-12"] == "P"
    assert s1_stats["days"]["2026-10-13"] == "T"
    assert s1_stats["days"]["2026-10-14"] == "P"

    s2_stats = next(s for s in g_stats["students"] if s["name"] == "Mateo Mendoza")
    assert s2_stats["metrics"]["present_days"] == 2
    assert s2_stats["metrics"]["late_days"] == 1
    assert s2_stats["metrics"]["absent_days"] == 1
    assert s2_stats["metrics"]["punctuality_rate"] == 50.0
    assert s2_stats["days"]["2026-10-12"] == "T"
    assert s2_stats["days"]["2026-10-13"] == "P"
    assert s2_stats["days"]["2026-10-14"] == "A"

    # 2. Teacher calls get_year_view_stats with section filter 'B'
    cur.execute("RESET ROLE")
    _simulate_auth_session(cur, "laura.solis@school.edu")
    cur.execute("SELECT public.get_year_view_stats('2026-10-12', '2026-10-14', NULL, NULL, 'B')")
    t_stats = cur.fetchone()[0]
    assert t_stats["grade"] == 5
    t_names = [s["name"] for s in t_stats["students"]]
    assert "Mateo Mendoza" in t_names
    assert "Valeria Mendoza" not in t_names
    assert "Carlos Rivas" not in t_names


SCHOOL_SETTINGS_COLUMNS = (
    "id, school_language, grades, sections, active_weekdays, holidays, "
    "late_threshold, cooldown_seconds, admin_secret_key_hash"
)


def _store_school_settings(cur, **changes) -> None:
    values = {
        "id": "1",
        "school_language": "'en'",
        "grades": """'["Kinder", "Grade 1", "Grade 2"]'::jsonb""",
        "sections": """'["Red", "Blue"]'::jsonb""",
        "active_weekdays": "ARRAY[0, 1, 2, 3, 4]::smallint[]",
        "holidays": """'["2026-12-25"]'::jsonb""",
        "late_threshold": "'07:15:00'",
        "cooldown_seconds": "120",
        "admin_secret_key_hash": "'pbkdf2_sha256$1000$c2FsdA$aGFzaA'",
        **changes,
    }
    cur.execute("DELETE FROM public.school_settings")
    cur.execute(f"INSERT INTO public.school_settings ({SCHOOL_SETTINGS_COLUMNS}) VALUES ({', '.join(values.values())})")


def test_school_settings_hold_one_row_of_school_policy(db_conn):
    cur = db_conn.cursor()
    _store_school_settings(cur)

    cur.execute(
        "SELECT school_language, grades, sections, active_weekdays, holidays, late_threshold::text, cooldown_seconds "
        "FROM public.school_settings"
    )
    assert cur.fetchall() == [
        ("en", ["Kinder", "Grade 1", "Grade 2"], ["Red", "Blue"], [0, 1, 2, 3, 4], ["2026-12-25"], "07:15:00", 120)
    ]

    cur.execute("SAVEPOINT second_row")
    with pytest.raises(psycopg2.IntegrityError):
        cur.execute(
            f"INSERT INTO public.school_settings ({SCHOOL_SETTINGS_COLUMNS}) "
            "SELECT 2, school_language, grades, sections, active_weekdays, holidays, "
            "late_threshold, cooldown_seconds, admin_secret_key_hash FROM public.school_settings"
        )
    cur.execute("ROLLBACK TO SAVEPOINT second_row")


@pytest.mark.parametrize(
    "column, value",
    [
        ("school_language", "'fr'"),
        ("grades", "'[]'::jsonb"),
        ("grades", """'{"1": "Kinder"}'::jsonb"""),
        ("sections", "'[]'::jsonb"),
        ("active_weekdays", "ARRAY[]::smallint[]"),
        ("active_weekdays", "ARRAY[0, 7]::smallint[]"),
        ("holidays", """'"2026-12-25"'::jsonb"""),
        ("cooldown_seconds", "-1"),
        ("admin_secret_key_hash", "NULL"),
    ],
)
def test_school_settings_refuse_invalid_values(db_conn, column, value):
    cur = db_conn.cursor()

    with pytest.raises((psycopg2.IntegrityError, psycopg2.DataError)):
        _store_school_settings(cur, **{column: value})


def test_portal_reads_school_settings_without_the_secret_key_hash(db_conn):
    cur = db_conn.cursor()
    _store_school_settings(cur)

    for role in ("anon", "authenticated"):
        cur.execute(f"SET LOCAL ROLE {role}")
        cur.execute("SELECT public.get_school_settings()")
        assert cur.fetchone()[0] == {
            "school_language": "en",
            "grades": ["Kinder", "Grade 1", "Grade 2"],
            "sections": ["Red", "Blue"],
            "active_weekdays": [0, 1, 2, 3, 4],
            "holidays": ["2026-12-25"],
            "late_threshold": "07:15:00",
        }

        cur.execute(f"SAVEPOINT direct_read_{role}")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("SELECT admin_secret_key_hash FROM public.school_settings")
        cur.execute(f"ROLLBACK TO SAVEPOINT direct_read_{role}")
        cur.execute("RESET ROLE")


def test_portal_sees_no_school_settings_before_a_school_sets_them_up(db_conn):
    cur = db_conn.cursor()
    cur.execute("DELETE FROM public.school_settings")
    cur.execute("SET LOCAL ROLE anon")

    cur.execute("SELECT public.get_school_settings()")

    assert cur.fetchone()[0] is None


def test_year_view_treats_a_missing_section_as_all_and_todas_as_a_section_name(db_conn):
    cur = db_conn.cursor()
    _seed_school_fixtures(cur)
    _simulate_auth_session(cur, "director@school.edu")

    cur.execute("SELECT public.get_year_view_stats('2026-10-12', '2026-10-14', NULL, 5, NULL)")
    every_section = {s["name"] for s in cur.fetchone()[0]["students"]}
    cur.execute("SELECT public.get_year_view_stats('2026-10-12', '2026-10-14', NULL, 5, 'ALL')")
    all_value = {s["name"] for s in cur.fetchone()[0]["students"]}
    cur.execute("SELECT public.get_year_view_stats('2026-10-12', '2026-10-14', NULL, 5, 'TODAS')")
    todas = cur.fetchone()[0]["students"]

    assert every_section == {"Valeria Mendoza", "Mateo Mendoza"}
    assert all_value == every_section
    assert todas == []


def test_grades_are_ranks_into_the_schools_own_list_with_no_fixed_last_grade(db_conn):
    cur = db_conn.cursor()

    def register(badge_uid, role, details_sql, value):
        cur.execute(
            """
            INSERT INTO public.users (badge_uid, full_name, role, email, is_active, created_at)
            VALUES (%s, 'Persona de Prueba', %s, NULL, TRUE, '2026-10-16T06:00:00')
            RETURNING id
            """,
            (badge_uid, role),
        )
        cur.execute(details_sql, (cur.fetchone()[0], value))

    student_sql = (
        "INSERT INTO public.student_details (user_id, grade, section, family_id) VALUES (%s, %s, 'A', 'FAM-1301')"
    )
    teacher_sql = "INSERT INTO public.teacher_details (user_id, taught_grade) VALUES (%s, %s)"

    register("GRADE_13_STUDENT", "student", student_sql, 13)
    register("GRADE_13_TEACHER", "teacher", teacher_sql, 13)
    cur.execute("SELECT COUNT(*) FROM public.student_details WHERE grade = 13")
    assert cur.fetchone()[0] == 1

    for badge_uid, role, sql in (
        ("GRADE_0_STUDENT", "student", student_sql),
        ("GRADE_0_TEACHER", "teacher", teacher_sql),
    ):
        cur.execute("SAVEPOINT rank_zero")
        with pytest.raises(psycopg2.IntegrityError):
            register(badge_uid, role, sql, 0)
        cur.execute("ROLLBACK TO SAVEPOINT rank_zero")


def test_year_view_counts_school_days_from_the_calendar(db_conn):
    """School Days are the active weekdays that are not holidays, within the dates that have scans on record."""
    cur = db_conn.cursor()
    ids = _seed_school_fixtures(cur)
    _store_school_settings(cur, holidays="""'["2026-10-14"]'::jsonb""")
    cur.execute(
        """
        INSERT INTO public.attendance_records (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
        VALUES
            -- Valeria checks in on Monday and Friday; nobody scans on Tuesday or Thursday
            ('check_in', '2026-10-12', '06:40:00', 'on_time', 'RLS_S1_5A', %(s1)s, 'Valeria Mendoza', 'student', 5, 'A'),
            ('check_in', '2026-10-16', '06:40:00', 'on_time', 'RLS_S1_5A', %(s1)s, 'Valeria Mendoza', 'student', 5, 'A'),
            -- Wednesday is a holiday, though she came in late for an event
            ('check_in', '2026-10-14', '09:00:00', 'late', 'RLS_S1_5A', %(s1)s, 'Valeria Mendoza', 'student', 5, 'A'),
            -- A Visitor on Saturday, when the School is closed
            ('check_in', '2026-10-17', '10:00:00', NULL, 'RLS_VISITOR', NULL, 'Visitante', 'visitor', NULL, NULL)
        """,
        {"s1": ids["s1_id"]},
    )

    def valerias_year_view(start: str | None = "2026-10-01", end: str | None = "2026-10-31") -> tuple[dict, dict]:
        _simulate_auth_session(cur, "elena.mendoza@school.edu")
        cur.execute("SELECT public.get_year_view_stats(%s, %s)", (start, end))
        stats = cur.fetchone()[0]
        cur.execute("RESET ROLE")
        return stats, next(s for s in stats["students"] if s["name"] == "Valeria Mendoza")

    stats, valeria = valerias_year_view()
    assert stats["school_dates"] == ["2026-10-16", "2026-10-15", "2026-10-13", "2026-10-12"]
    assert valerias_year_view(None, None)[0]["school_dates"] == stats["school_dates"]
    assert stats["total_school_days"] == 4
    assert valeria["days"] == {"2026-10-12": "P", "2026-10-13": "A", "2026-10-15": "A", "2026-10-16": "P"}
    assert (valeria["present_days"], valeria["late_days"], valeria["absent_days"]) == (2, 0, 2)

    _store_school_settings(cur, holidays="'[]'::jsonb")
    stats, valeria = valerias_year_view()
    assert stats["total_school_days"] == 5
    assert valeria["days"]["2026-10-14"] == "T"
    assert (valeria["present_days"], valeria["late_days"], valeria["absent_days"]) == (3, 1, 2)

    _store_school_settings(cur, active_weekdays="ARRAY[0, 1, 2, 3, 4, 5]::smallint[]")
    stats, valeria = valerias_year_view()
    assert stats["school_dates"][0] == "2026-10-17"
    assert valeria["days"]["2026-10-17"] == "A"
