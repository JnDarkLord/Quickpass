from dataclasses import replace
from datetime import date, datetime

import pytest
from conftest import ADMIN_SECRET_KEY, gate_screen, store_school

import access_control
import database
from admin import (
    GuardianData,
    SystemStatistics,
    add_user,
    assign_visitor_badge,
    delete_user,
    get_statistics,
    modify_user,
    preview_grade_promotion,
    promote_grades,
    wipe_history,
    wipe_users,
)


def test_add_student_with_guardians(conn, settings, now):
    result = add_user(
        conn=conn,
        settings=settings,
        badge_uid="AA11BB22",
        role="est",
        full_name="Carlos Santana",
        grade=10,
        section="A",
        guardians=[
            GuardianData(name="Maria Santana", phone="+18095550101", email="maria@example.com"),
            GuardianData(name="Pedro Santana", phone="+18095550102"),
        ],
        now=now,
    )

    assert result.success is True
    assert result.user["badge_uid"] == "AA11BB22"
    assert result.user["role"] == "student"
    assert result.user["grade"] == 10
    assert result.user["section"] == "A"
    assert len(result.user["guardians"]) == 2
    assert result.user["guardians"][0]["name"] == "Maria Santana"


def test_add_teacher(conn, settings, now):
    result = add_user(
        conn=conn,
        settings=settings,
        badge_uid="BB1001",
        role="prof",
        full_name="Sofia Rodriguez",
        taught_grade=5,
        now=now,
    )

    assert result.success is True
    assert result.user["badge_uid"] == "BB1001"
    assert result.user["role"] == "teacher"
    assert result.user["taught_grade"] == 5


def test_add_visitor(conn, settings, now):
    result = add_user(
        conn=conn,
        settings=settings,
        badge_uid="DE01",
        role="vist",
        full_name="Juan Perez",
        now=now,
    )

    assert result.success is True
    assert result.user["role"] == "visitor"


def test_first_admin_requires_no_approval(conn, settings, now):
    result = add_user(
        conn=conn,
        settings=settings,
        badge_uid="AD01",
        role="admin",
        full_name="Primer Admin",
        now=now,
    )

    assert result.success is True
    assert result.user["role"] == "admin"


def test_second_admin_refused_without_valid_admin_scan(conn, settings, now):
    # Register first admin
    add_user(conn, settings, "AD01", "admin", "Primer Admin", now=now)

    # Attempt second admin with no approving scan
    result_none = add_user(conn, settings, "AD02", "admin", "Segundo Admin", approving_uid=None, now=now)
    assert result_none.success is False
    assert "NO es ADMIN" in result_none.error or "Admin" in result_none.error

    # Attempt second admin with non-admin scan
    add_user(conn, settings, "DE01", "vist", "Visitante", now=now)
    result_non_admin = add_user(conn, settings, "AD02", "admin", "Segundo Admin", approving_uid="DE01", now=now)
    assert result_non_admin.success is False

    # Attempt second admin with valid admin scan
    result_valid = add_user(conn, settings, "AD02", "admin", "Segundo Admin", approving_uid="AD01", now=now)
    assert result_valid.success is True


def test_refuse_duplicate_badge_uid(conn, settings, now):
    add_user(conn, settings, "AA11BB22", "vist", "Persona 1", now=now)

    result = add_user(conn, settings, "AA11BB22", "vist", "Persona 2", now=now)
    assert result.success is False
    assert "ya existe" in result.error.lower()


def test_refuse_invalid_role(conn, settings, now):
    result = add_user(conn, settings, "BB22CC33", "director", "Carlos", now=now)
    assert result.success is False
    assert "inválido" in result.error.lower() or "invalido" in result.error.lower()


def test_refuse_empty_name(conn, settings, now):
    result = add_user(conn, settings, "BB22CC33", "vist", "   ", now=now)
    assert result.success is False
    assert "nombre" in result.error.lower()


@pytest.mark.parametrize("grade", [0, 12, -1, "diez"])
def test_refuse_grade_out_of_range(conn, settings, now, grade):
    result = add_user(conn, settings, "ST001", "est", "Estudiante", grade=grade, section="A", now=now)
    assert result.success is False
    assert "grado" in result.error.lower()


def test_refuse_half_filled_guardian(conn, settings, now):
    # Name without phone
    result1 = add_user(
        conn,
        settings,
        "ST001",
        "est",
        "Estudiante",
        grade=5,
        section="A",
        guardians=[GuardianData(name="Mama", phone="")],
        now=now,
    )
    assert result1.success is False

    # Phone without name
    result2 = add_user(
        conn,
        settings,
        "ST002",
        "est",
        "Estudiante",
        grade=5,
        section="A",
        guardians=[GuardianData(name="", phone="8095551234")],
        now=now,
    )
    assert result2.success is False


NAME_NEEDS_A_LETTER = "El nombre debe tener al menos una letra."
GUARDIAN_NAME_NEEDS_A_LETTER = "El nombre de cada acudiente debe tener al menos una letra."
PHONE_NEEDS_ITS_COUNTRY_CODE = (
    "Escriba el teléfono de cada acudiente con + y el código del país, un espacio y el número (ej: +505 88888888)."
)


@pytest.mark.parametrize("name", ["12345", "123 456", "-"])
def test_a_name_needs_at_least_one_letter(conn, settings, now, name):
    result = add_user(conn, settings, "AA01", "est", name, grade=5, section="A", now=now)

    assert (result.success, result.error) == (False, NAME_NEEDS_A_LETTER)
    assert database.get_user_by_badge_uid(conn, "AA01") is None


@pytest.mark.parametrize(
    ("guardian", "error"),
    [
        (GuardianData(name="1234", phone="+505 88888888"), GUARDIAN_NAME_NEEDS_A_LETTER),
        (GuardianData(name="Ana Torres", phone="88888888"), PHONE_NEEDS_ITS_COUNTRY_CODE),
        (GuardianData(name="Ana Torres", phone="+505"), PHONE_NEEDS_ITS_COUNTRY_CODE),
    ],
)
def test_a_guardian_needs_a_name_with_letters_and_a_phone_with_its_country_code(conn, settings, now, guardian, error):
    result = add_user(conn, settings, "AA01", "est", "Luis Torres", grade=5, section="A", guardians=[guardian], now=now)

    assert (result.success, result.error) == (False, error)
    assert database.get_user_by_badge_uid(conn, "AA01") is None


def test_guardian_phones_are_stored_as_the_country_code_a_space_and_the_number(conn, settings, now):
    guardians = [
        GuardianData(name="Ana Torres", phone="+505 8888-8888"),
        GuardianData(name="Raúl Torres", phone="+18095550102"),
    ]

    result = add_user(conn, settings, "AA01", "est", "Luis Torres", grade=5, section="A", guardians=guardians, now=now)

    assert [g["phone"] for g in result.user["guardians"]] == ["+505 88888888", "+1 8095550102"]


def test_delete_refused_without_admin_scan(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)
    add_user(conn, settings, "BB22", "vist", "Visitante", now=now)

    # No approver
    res_none = delete_user(conn, "AA11", approving_uid=None, confirmed=True)
    assert res_none.success is False
    assert "NO es ADMIN" in res_none.error

    # Non-admin approver
    res_non_admin = delete_user(conn, "AA11", approving_uid="BB22", confirmed=True)
    assert res_non_admin.success is False
    assert "NO es ADMIN" in res_non_admin.error


def test_delete_refused_with_target_own_badge(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)

    res = delete_user(conn, "AD01", approving_uid="AD01", confirmed=True)
    assert res.success is False
    assert "misma tarjeta" in res.error.lower()


def test_delete_refused_without_confirmation(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res = delete_user(conn, "AA11", approving_uid="AD01", confirmed=False)
    assert res.success is False
    assert "cancelada" in res.error.lower()


def test_delete_allowed_with_admin_secret_key(conn, settings, now):
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    # The Admin Secret Key in School Settings approves even when no Admin Badge exists
    res = delete_user(conn, "AA11", approving_uid=ADMIN_SECRET_KEY, confirmed=True)
    assert res.success is True
    assert database.get_user_by_badge_uid(conn, "AA11") is None


def test_delete_own_badge_allowed_with_admin_secret_key(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)

    # An Admin with a single Badge can delete it by typing the Admin Secret Key instead
    res = delete_user(conn, "AD01", approving_uid=ADMIN_SECRET_KEY, confirmed=True)
    assert res.success is True
    assert database.get_user_by_badge_uid(conn, "AD01") is None


def test_delete_with_wrong_secret_key_fails(conn, settings, now):
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res = delete_user(conn, "AA11", approving_uid="wrong_secret", confirmed=True)
    assert res.success is False
    assert "NO es ADMIN" in res.error


def test_delete_with_admin_secret_key_requires_confirmation(conn, settings, now):
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res = delete_user(conn, "AA11", approving_uid=ADMIN_SECRET_KEY, confirmed=False)
    assert res.success is False
    assert "cancelada" in res.error.lower()


def test_admin_secret_key_from_the_environment_is_not_accepted(conn, settings, now, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "env_secret_key")
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res = delete_user(conn, "AA11", approving_uid="env_secret_key", confirmed=True)
    assert res.success is False
    assert database.get_user_by_badge_uid(conn, "AA11") is not None


def test_modify_allowed_with_the_admin_secret_key_in_school_settings(conn, settings, now):
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res = modify_user(conn, "AA11", approving_uid=ADMIN_SECRET_KEY, new_name="Estudiante Renombrado")
    assert res.success is True
    assert res.user["full_name"] == "Estudiante Renombrado"


def test_delete_keeps_history(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_student = add_user(
        conn,
        settings,
        "AA11",
        "est",
        "Carlos Santana",
        grade=10,
        section="A",
        guardians=[GuardianData(name="Mama", phone="+1 8091112233")],
        now=now,
    )
    assert add_student.user is not None
    user_id = add_student.user["id"]

    # Insert attendance record
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '07:30:00', 'on_time', 'AA11', ?, 'Carlos Santana', 'student', 10, 'A')""",
            (user_id,),
        )

    # Delete student
    res = delete_user(conn, "AA11", approving_uid="AD01", confirmed=True)
    assert res.success is True

    # User, student_details, guardians deleted
    assert database.get_user_by_badge_uid(conn, "AA11") is None
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM student_details WHERE user_id = ?", (user_id,))
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM guardians WHERE student_id = ?", (user_id,))
    assert cursor.fetchone()[0] == 0

    # Attendance record preserved, with user_id NULL
    cursor.execute("SELECT user_id, name, role, grade, section FROM attendance_records WHERE badge_uid = 'AA11'")
    row = cursor.fetchone()
    assert row is not None
    assert row["user_id"] is None
    assert row["name"] == "Carlos Santana"
    assert row["role"] == "student"
    assert row["grade"] == 10
    assert row["section"] == "A"


def test_modify_approved_by_target_admin_itself(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)

    res = modify_user(
        conn,
        target_badge_uid="AD01",
        approving_uid="AD01",
        new_name="Admin Renombrado",
    )
    assert res.success is True
    assert res.user is not None
    assert res.user["full_name"] == "Admin Renombrado"


def test_rename_and_badge_replacement_keeps_history_link(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_student = add_user(
        conn,
        settings,
        "AA11",
        "est",
        "Original Name",
        grade=8,
        section="B",
        now=now,
    )
    assert add_student.user is not None
    user_id = add_student.user["id"]

    # Insert attendance record
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '07:30:00', 'on_time', 'AA11', ?, 'Original Name', 'student', 8, 'B')""",
            (user_id,),
        )

    # Modify name and replace badge
    res = modify_user(
        conn,
        target_badge_uid="AA11",
        approving_uid="AD01",
        new_name="Updated Name",
        new_badge_uid="CC33",
    )
    assert res.success is True
    assert res.user is not None
    assert res.user["id"] == user_id
    assert res.user["full_name"] == "Updated Name"
    assert res.user["badge_uid"] == "CC33"

    # Old badge no longer found, new badge finds user
    assert database.get_user_by_badge_uid(conn, "AA11") is None
    new_user = database.get_user_by_badge_uid(conn, "CC33")
    assert new_user is not None
    assert new_user["id"] == user_id

    # Historical attendance record still linked via user_id
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM attendance_records WHERE user_id = ?", (user_id,))
    rows = cursor.fetchall()
    assert len(rows) == 1


def test_modify_refuse_invalid_grade(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    res_invalid_str = modify_user(conn, "AA11", "AD01", new_grade="invalido")
    assert res_invalid_str.success is False
    assert "grado" in res_invalid_str.error.lower()

    res_out_of_range = modify_user(conn, "AA11", "AD01", new_grade=15)
    assert res_out_of_range.success is False
    assert "grado" in res_out_of_range.error.lower()


def test_modify_refuse_third_guardian(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin 1", now=now)
    add_user(conn, settings, "AA11", "est", "Estudiante", grade=5, section="A", now=now)

    three_guardians = [
        GuardianData(name="G1", phone="+1 8091110001"),
        GuardianData(name="G2", phone="+1 8091110002"),
        GuardianData(name="G3", phone="+1 8091110003"),
    ]
    res = modify_user(conn, "AA11", "AD01", new_guardians=three_guardians)
    assert res.success is False
    assert "dos acudientes" in res.error.lower()


def test_editing_checks_a_new_name_or_phone_but_keeps_a_phone_stored_before_the_checks(conn, settings, now):
    student = add_user(conn, settings, "AA11", "est", "Luis Torres", grade=5, section="A", now=now).user
    with conn:
        conn.execute(
            "INSERT INTO guardians (student_id, position, name, phone) VALUES (?, 1, 'Ana Torres', '88888888')",
            (student["id"],),
        )
    stored_guardian = GuardianData(name="Ana Torres", phone="88888888")

    renamed = modify_user(conn, "AA11", ADMIN_SECRET_KEY, new_name="Luis A. Torres", new_guardians=[stored_guardian])
    bad_name = modify_user(conn, "AA11", ADMIN_SECRET_KEY, new_name="2026")
    bad_guardian_name = modify_user(
        conn, "AA11", ADMIN_SECRET_KEY, new_guardians=[GuardianData(name="1", phone="88888888")]
    )
    bad_phone = modify_user(
        conn, "AA11", ADMIN_SECRET_KEY, new_guardians=[GuardianData(name="Ana Torres", phone="87777777")]
    )
    new_phone = modify_user(
        conn, "AA11", ADMIN_SECRET_KEY, new_guardians=[GuardianData(name="Ana Torres", phone="+505 8777 7777")]
    )

    assert renamed.success is True
    assert (bad_name.error, bad_guardian_name.error, bad_phone.error) == (
        NAME_NEEDS_A_LETTER,
        GUARDIAN_NAME_NEEDS_A_LETTER,
        PHONE_NEEDS_ITS_COUNTRY_CODE,
    )
    assert new_phone.user["full_name"] == "Luis A. Torres"
    assert [g["phone"] for g in new_phone.user["guardians"]] == ["+505 87777777"]


def test_a_walk_in_visitor_gets_a_new_temporary_badge(conn, settings, now):
    result = assign_visitor_badge(conn, settings, "7E571701", "Carlos Ramírez", now=now)

    assert result.success is True
    assert (result.user["badge_uid"], result.user["full_name"], result.user["role"]) == (
        "7E571701",
        "Carlos Ramírez",
        "visitor",
    )


def test_a_temporary_badge_passes_to_the_next_walk_in_visitor(conn, settings, now):
    add_user(conn, settings, "7E571701", "vist", "Primera Visita", now=now)
    with conn:
        conn.execute("UPDATE users SET is_active = 0, is_synced = 1 WHERE badge_uid = '7E571701'")

    result = assign_visitor_badge(conn, settings, "7E571701", "Segunda Visita", now=now)

    assert result.success is True
    assert (result.user["full_name"], result.user["is_active"]) == ("Segunda Visita", 1)
    synced = conn.execute("SELECT is_synced FROM users WHERE badge_uid = '7E571701'").fetchone()[0]
    assert synced == 0


def test_a_badge_that_belongs_to_anyone_but_a_visitor_is_not_lent_to_one(conn, settings, now):
    add_user(conn, settings, "AA01", "est", "Ana Rivas", grade=5, section="A", now=now)

    result = assign_visitor_badge(conn, settings, "AA01", "Carlos Ramírez", now=now)
    nameless = assign_visitor_badge(conn, settings, "7E571701", "1234", now=now)

    assert (result.success, result.error) == (
        False,
        "La tarjeta AA01 es de Ana Rivas (Estudiante), no de un visitante.",
    )
    assert (nameless.success, nameless.error) == (False, NAME_NEEDS_A_LETTER)
    holder = database.get_user_by_badge_uid(conn, "AA01")
    assert (holder["full_name"], holder["role"]) == ("Ana Rivas", "student")


def test_promotion_results_stay_saved(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings, "ST01", "est", "Estudiante 1", grade=1, section="A", now=now)
    add_user(conn, settings, "ST10", "est", "Estudiante 10", grade=10, section="B", now=now)
    add_user(conn, settings, "ST11", "est", "Estudiante 11", grade=11, section="C", now=now)

    res = promote_grades(conn, now=now)
    assert res.success is True
    assert res.promoted_count == 2
    assert res.graduated_count == 1

    # Check student 1 (grade 1 -> 2)
    s1 = database.get_user_by_badge_uid(conn, "ST01")
    assert s1 is not None
    assert s1["grade"] == 2
    assert s1["is_active"] == 1
    assert s1["graduation_date"] is None

    # Check student 10 (grade 10 -> 11)
    s10 = database.get_user_by_badge_uid(conn, "ST10")
    assert s10 is not None
    assert s10["grade"] == 11
    assert s10["is_active"] == 1
    assert s10["graduation_date"] is None

    # Check student 11 (grade 11 -> Graduate)
    s11 = database.get_user_by_badge_uid(conn, "ST11")
    assert s11 is not None
    assert s11["grade"] == 11
    assert s11["is_active"] == 0
    assert s11["graduation_date"] is not None


def test_promotion_teachers_and_sections_unchanged(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings, "PR01", "prof", "Profesor", taught_grade=7, now=now)
    add_user(conn, settings, "ST05", "est", "Estudiante 5", grade=5, section="D", now=now)

    promote_grades(conn, now=now)

    teacher = database.get_user_by_badge_uid(conn, "PR01")
    assert teacher is not None
    assert teacher["taught_grade"] == 7

    student = database.get_user_by_badge_uid(conn, "ST05")
    assert student is not None
    assert student["grade"] == 6
    assert student["section"] == "D"


KINDER_SCHOOL = {"grades": ("Pre-K", "Kinder", "1st"), "sections": ("Única", "Azul")}


def test_registration_takes_grades_and_sections_from_the_school(conn, settings, school, now):
    store_school(conn, replace(school, **KINDER_SCHOOL))

    student = add_user(conn, settings, "AA01", "est", "Ana", grade=3, section="única", now=now)
    teacher = add_user(conn, settings, "BB01", "prof", "Beto", taught_grade=2, now=now)
    beyond = add_user(conn, settings, "AA02", "est", "Carla", grade=4, section="Azul", now=now)
    unknown = add_user(conn, settings, "AA03", "est", "Dario", grade=1, section="A", now=now)
    teacher_beyond = add_user(conn, settings, "BB02", "prof", "Elena", taught_grade=4, now=now)

    assert (student.user["grade"], student.user["section"]) == (3, "Única")
    assert teacher.user["taught_grade"] == 2
    assert beyond.error == "Elija un grado de la lista del colegio."
    assert unknown.error == "Elija una sección de la lista del colegio: Única, Azul."
    assert teacher_beyond.error == "Elija el grado que enseña de la lista del colegio."


def test_editing_checks_only_the_grade_and_section_that_change(conn, settings, school, now):
    add_user(conn, settings, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings, "AA01", "est", "Ana", grade=11, section="D", now=now)
    # Cloud Sync brought settings from another station with fewer Grades and Sections
    store_school(conn, replace(school, grades=school.grades[:6], sections=("A", "B")))

    renamed = modify_user(conn, "AA01", "AD01", new_name="Ana María", new_grade=11, new_section="D")
    beyond = modify_user(conn, "AA01", "AD01", new_grade=9)
    unknown = modify_user(conn, "AA01", "AD01", new_section="C")
    moved = modify_user(conn, "AA01", "AD01", new_grade=6, new_section="b")

    assert renamed.user["full_name"] == "Ana María"
    assert beyond.error == "Elija un grado de la lista del colegio."
    assert unknown.error == "Elija una sección de la lista del colegio: A, B."
    assert (moved.user["grade"], moved.user["section"]) == (6, "B")


def test_grade_promotion_follows_the_schools_own_grades(conn, settings, school, now):
    # Registered while the School still had Grades up to 11°
    add_user(conn, settings, "AA05", "est", "Dario", grade=5, section="A", now=now)
    store_school(conn, replace(school, **KINDER_SCHOOL))
    add_user(conn, settings, "AA01", "est", "Ana", grade=1, section="Única", now=now)
    add_user(conn, settings, "AA02", "est", "Beto", grade=2, section="Única", now=now)
    add_user(conn, settings, "AA03", "est", "Carla", grade=3, section="Azul", now=now)

    preview = preview_grade_promotion(conn)
    result = promote_grades(conn, now=now)

    assert (preview.promoted_count, preview.graduated_count) == (2, 2)
    assert (result.promoted_count, result.graduated_count) == (2, 2)
    people = {uid: database.get_user_by_badge_uid(conn, uid) for uid in ("AA01", "AA02", "AA03", "AA05")}
    assert {uid: (p["grade"], p["role"], p["is_active"]) for uid, p in people.items()} == {
        "AA01": (2, "student", 1),
        "AA02": (3, "student", 1),
        "AA03": (3, "graduate", 0),
        "AA05": (5, "graduate", 0),
    }
    assert people["AA03"]["graduation_date"] == now.strftime("%Y-%m-%d")


def test_promoted_student_next_check_in_copies_new_grade(conn, settings):
    day1 = datetime(2026, 10, 7, 7, 0, 0)
    add_user(conn, settings, "AA04", "est", "Estudiante 4", grade=4, section="A", now=day1)

    # First check-in
    res1 = access_control.process_scan_line(conn, settings, "SCAN AA04\n", now=day1)
    assert res1.event_type == "check_in"
    cursor = conn.cursor()
    cursor.execute("SELECT grade FROM attendance_records WHERE badge_uid = 'AA04'")
    assert cursor.fetchone()[0] == 4

    # Promote grade
    promote_grades(conn, now=day1)

    # Next day check-in
    day2 = datetime(2026, 10, 8, 7, 0, 0)
    res2 = access_control.process_scan_line(conn, settings, "SCAN AA04\n", now=day2)
    assert res2.event_type == "check_in"

    cursor.execute("SELECT date, grade, section FROM attendance_records WHERE badge_uid = 'AA04' ORDER BY id")
    assert [tuple(row) for row in cursor.fetchall()] == [("2026-10-07", 4, "A"), ("2026-10-08", 5, "A")]


def test_graduate_scan_denied_with_nothing_recorded(conn, settings):
    day1 = datetime(2026, 10, 7, 7, 0, 0)
    add_user(conn, settings, "CC11", "est", "Estudiante 11", grade=11, section="A", now=day1)

    # Record attendance prior to graduation
    res_in = access_control.process_scan_line(conn, settings, "SCAN CC11\n", now=day1)
    assert res_in.event_type == "check_in"

    # Graduate the student
    promote_grades(conn, now=day1)

    # Subsequent scan as Graduate
    day2 = datetime(2026, 10, 8, 7, 0, 0)
    res_grad = access_control.process_scan_line(conn, settings, "SCAN CC11\n", now=day2)
    assert res_grad.event_type == "graduate_denied"
    assert gate_screen(res_grad.reply_line) == ("DENY", "Acceso Denegado", "Graduado")
    assert res_grad.texts_to_send == []

    # Nothing recorded on day 2
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM attendance_records WHERE date = '2026-10-08'")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM security_incidents")
    assert cursor.fetchone()[0] == 0

    # Earlier check-in on day 1 remains recorded
    cursor.execute("SELECT COUNT(*) FROM attendance_records WHERE date = '2026-10-07'")
    assert cursor.fetchone()[0] == 1


def test_statistics_count_by_grade_rank_and_role_with_the_dates_of_the_last_check_ins(conn, settings, now):
    add_user(conn, settings, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings, "BB01", "prof", "Profesor", taught_grade=5, now=now)
    add_user(conn, settings, "CC01", "est", "Estudiante 1", grade=1, section="A", now=now)
    add_user(conn, settings, "DD11", "est", "Estudiante 11", grade=11, section="B", now=now)

    # Graduate DD11 (CC01 becomes grade 2)
    promote_grades(conn, now=now)

    # Add 12 check-in records across 12 distinct dates
    with conn:
        for i in range(1, 13):
            date_str = f"2026-09-{i:02d}"
            conn.execute(
                """INSERT INTO attendance_records
                   (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
                   VALUES ('check_in', ?, '07:00:00', 'on_time', 'CC01', 3, 'Estudiante 1', 'student', 2, 'A')""",
                (date_str,),
            )

    assert get_statistics(conn) == SystemStatistics(
        total_users=4,
        total_check_ins=12,
        students_by_grade={2: 1},
        graduates=1,
        teachers_by_grade={5: 1},
        recent_check_ins=[(date(2026, 9, day), 1) for day in range(3, 13)],
        users_by_role={"student": 1, "teacher": 1, "admin": 1, "visitor": 0},
    )


def test_wipe_refused_conditions(conn, settings, now):
    from dataclasses import replace

    add_user(conn, settings, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings, "AA01", "est", "Estudiante", grade=5, section="A", now=now)

    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '07:00:00', 'on_time', 'ST01', 2, 'Estudiante', 'student', 5, 'A')"""
        )

    # 1. Unset password
    settings_no_pwd = replace(settings, wipe_password=None)
    res_u1 = wipe_users(conn, settings_no_pwd, "algo", "ELIMINAR", now=now)
    assert res_u1.success is False
    assert "no está configurada" in res_u1.error

    res_h1 = wipe_history(conn, settings_no_pwd, "algo", "ELIMINAR", now=now)
    assert res_h1.success is False
    assert "no está configurada" in res_h1.error

    # 2. Wrong password
    settings_with_pwd = replace(settings, wipe_password="clave_correcta")
    res_u2 = wipe_users(conn, settings_with_pwd, "clave_incorrecta", "ELIMINAR", now=now)
    assert res_u2.success is False
    assert "Contraseña incorrecta" in res_u2.error

    res_h2 = wipe_history(conn, settings_with_pwd, "clave_incorrecta", "ELIMINAR", now=now)
    assert res_h2.success is False
    assert "Contraseña incorrecta" in res_h2.error

    # 3. Wrong confirmation text
    res_u3 = wipe_users(conn, settings_with_pwd, "clave_correcta", "NO_ELIMINAR", now=now)
    assert res_u3.success is False
    assert "Confirmación no válida" in res_u3.error

    res_h3 = wipe_history(conn, settings_with_pwd, "clave_correcta", "CANCELAR", now=now)
    assert res_h3.success is False
    assert "Confirmación no válida" in res_h3.error

    # Verify nothing was deleted
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 2
    cursor.execute("SELECT COUNT(*) FROM attendance_records")
    assert cursor.fetchone()[0] == 1


def test_wipe_users_with_backup_and_keeps_attendance_history(conn, settings, now):
    import sqlite3
    from dataclasses import replace

    settings_with_pwd = replace(settings, wipe_password="clave_secreta")
    add_user(conn, settings_with_pwd, "AD01", "admin", "Admin", now=now)
    add_user(
        conn,
        settings_with_pwd,
        "AA01",
        "est",
        "Estudiante",
        grade=5,
        section="A",
        guardians=[GuardianData(name="Mama", phone="+1 8091112233")],
        now=now,
    )

    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '07:00:00', 'on_time', 'ST01', 2, 'Estudiante', 'student', 5, 'A')"""
        )

    res = wipe_users(conn, settings_with_pwd, "clave_secreta", "ELIMINAR", now=now)
    assert res.success is True
    assert res.backup_path is not None
    assert res.backup_path.exists()

    # Verify backup contains the old data
    b_conn = sqlite3.connect(res.backup_path)
    b_cur = b_conn.cursor()
    b_cur.execute("SELECT COUNT(*) FROM users")
    assert b_cur.fetchone()[0] == 2
    b_cur.execute("SELECT COUNT(*) FROM student_details")
    assert b_cur.fetchone()[0] == 1
    b_cur.execute("SELECT COUNT(*) FROM guardians")
    assert b_cur.fetchone()[0] == 1
    b_cur.execute("SELECT COUNT(*) FROM attendance_records")
    assert b_cur.fetchone()[0] == 1
    b_conn.close()

    # Verify main database: users, details, guardians wiped
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM student_details")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM guardians")
    assert cursor.fetchone()[0] == 0

    # Attendance record preserved with user_id NULL
    cursor.execute("SELECT user_id, name, role, grade, section FROM attendance_records")
    att = cursor.fetchone()
    assert att is not None
    assert att["user_id"] is None
    assert att["name"] == "Estudiante"
    assert att["role"] == "student"

    # Cloud Sync deletes the wiped Badges in Supabase too, rather than pulling them back
    cursor.execute("SELECT badge_uid FROM deleted_users ORDER BY badge_uid")
    assert [row[0] for row in cursor.fetchall()] == ["AA01", "AD01"]

    # First admin after wipe requires NO approval
    add_res = add_user(conn, settings_with_pwd, "AD99", "admin", "Nuevo Admin", approving_uid=None, now=now)
    assert add_res.success is True
    assert add_res.user["full_name"] == "Nuevo Admin"


def test_wipe_history_with_backup_and_keeps_users(conn, settings, now):
    import sqlite3
    from dataclasses import replace

    settings_with_pwd = replace(settings, wipe_password="clave_secreta")
    add_user(conn, settings_with_pwd, "AD01", "admin", "Admin", now=now)
    add_user(conn, settings_with_pwd, "AA01", "est", "Estudiante", grade=5, section="A", now=now)

    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '07:00:00', 'on_time', 'ST01', 2, 'Estudiante', 'student', 5, 'A')"""
        )
        conn.execute(
            """INSERT INTO security_incidents (badge_uid, date, time)
               VALUES ('DEADBEEF', '2026-10-07', '07:05:00')"""
        )

    res = wipe_history(conn, settings_with_pwd, "clave_secreta", "ELIMINAR", now=now)
    assert res.success is True
    assert res.backup_path is not None
    assert res.backup_path.exists()

    # Backup contains history
    b_conn = sqlite3.connect(res.backup_path)
    b_cur = b_conn.cursor()
    b_cur.execute("SELECT COUNT(*) FROM attendance_records")
    assert b_cur.fetchone()[0] == 1
    b_cur.execute("SELECT COUNT(*) FROM security_incidents")
    assert b_cur.fetchone()[0] == 1
    b_conn.close()

    # Main database has history wiped but users kept
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM attendance_records")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM security_incidents")
    assert cursor.fetchone()[0] == 0
    cursor.execute("SELECT COUNT(*) FROM users")
    assert cursor.fetchone()[0] == 2
    cursor.execute("SELECT COUNT(*) FROM student_details")
    assert cursor.fetchone()[0] == 1


def test_admin_messages_follow_the_school_language(conn, settings, school, now):
    store_school(conn, replace(school, school_language="en"))
    add_user(conn, settings, "AA01", "est", "Ana Rivas", grade=5, section="A", now=now)
    settings_with_pwd = replace(settings, wipe_password="clave_secreta")

    duplicate = add_user(conn, settings, "AA01", "est", "Ana Rivas", grade=5, section="A", now=now)
    not_admin = delete_user(conn, "AA01", "ZZ99", confirmed=True)
    wrong_word = wipe_users(conn, settings_with_pwd, "clave_secreta", "ELIMINAR", now=now)
    wiped = wipe_history(conn, settings_with_pwd, "clave_secreta", "delete", now=now)

    assert duplicate.error == "This badge already exists."
    assert not_admin.error == "That badge is NOT an Admin badge. Cancelled."
    assert wrong_word.error == "Confirmation not valid. Operation cancelled."
    assert wiped.success is True
