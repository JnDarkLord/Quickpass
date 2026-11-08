from dataclasses import replace
from datetime import date, datetime
from unittest.mock import patch

import openpyxl
import pytest
from conftest import store_school

from access_control import sign_in_visitor
from admin import GuardianData, add_user, promote_grades
from reports import (
    export_e1,
    export_e2,
    export_e3,
    export_e4,
    export_e5,
    export_e6,
    export_e7,
    export_e8,
)
from search import (
    compute_other_role_range_matrix,
    compute_student_range_matrix,
    parse_date_input,
    parse_date_range,
    school_days_on_record,
    search_all_students_by_date,
    search_by_badge,
    search_by_name,
    search_other_role_by_date,
    search_students_by_grade,
    search_students_by_grade_section,
)


def test_search_by_badge_for_each_role(conn, settings, now):
    # Student
    add_user(
        conn,
        settings,
        "AA01",
        "est",
        "Estudiante Uno",
        grade=10,
        section="A",
        guardians=[GuardianData(name="Mama", phone="+1 8091112233")],
        now=now,
    )
    res_s = search_by_badge(conn, "AA01")
    assert res_s is not None
    assert res_s.user["role"] == "student"
    assert res_s.user["grade"] == 10
    assert res_s.user["section"] == "A"
    assert len(res_s.user["guardians"]) == 1

    # Teacher
    add_user(conn, settings, "BB01", "prof", "Profesor Uno", taught_grade=7, now=now)
    res_t = search_by_badge(conn, "BB01")
    assert res_t is not None
    assert res_t.user["role"] == "teacher"
    assert res_t.user["taught_grade"] == 7

    # Admin
    add_user(conn, settings, "CC01", "admin", "Admin Uno", now=now)
    res_a = search_by_badge(conn, "CC01")
    assert res_a is not None
    assert res_a.user["role"] == "admin"

    # Visitor
    add_user(conn, settings, "DD01", "vist", "Visitante Uno", now=now)
    res_v = search_by_badge(conn, "DD01")
    assert res_v is not None
    assert res_v.user["role"] == "visitor"

    # Non-existent badge
    assert search_by_badge(conn, "EE99") is None


def test_history_order_and_check_out_time_values(conn, settings, now):
    s = add_user(conn, settings, "AA01", "est", "Carlos Santana", grade=9, section="B", now=now)
    uid = s.user["id"]

    # Insert records out of chronological order to verify sorting
    with conn:
        # Day 2: check-in and check-out
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-02', '07:15:00', 'late', 'AA01', ?, 'Carlos Santana', 'student', 9, 'B')""",
            (uid,),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', '2026-10-02', '13:00:00', NULL, 'AA01', ?, 'Carlos Santana', 'student', 9, 'B')""",
            (uid,),
        )

        # Day 1: check-in only (no check-out)
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-01', '06:40:00', 'on_time', 'AA01', ?, 'Carlos Santana', 'student', 9, 'B')""",
            (uid,),
        )

    res = search_by_badge(conn, "AA01")
    assert res is not None
    assert len(res.history) == 2

    # Chronological: 2026-10-01 first, then 2026-10-02
    day1 = res.history[0]
    assert day1.date == "2026-10-01"
    assert day1.arrival_time == "06:40:00"
    assert day1.departure_time == ""
    assert day1.status == "on_time"
    assert day1.grade == 9
    assert day1.section == "B"

    day2 = res.history[1]
    assert day2.date == "2026-10-02"
    assert day2.arrival_time == "07:15:00"
    assert day2.departure_time == "13:00:00"
    assert day2.status == "late"


def test_search_by_name_accents_case_and_no_history(conn, settings, now):
    add_user(conn, settings, "AA01", "est", "José Martínez", grade=5, section="A", now=now)
    add_user(conn, settings, "BB02", "vist", "Josefa Morales", now=now)

    # Empty name raises ValueError
    with pytest.raises(ValueError):
        search_by_name(conn, "   ")

    # "jose" (lowercase, no accent) matches both "José Martínez" and "Josefa Morales"
    results = search_by_name(conn, "jose")
    assert len(results) == 2
    names = [r.user["full_name"] for r in results]
    assert "José Martínez" in names
    assert "Josefa Morales" in names

    # Accented query "JOSÉ" matches "José Martínez"
    res_jose = search_by_name(conn, "JOSÉ")
    assert any(r.user["full_name"] == "José Martínez" for r in res_jose)

    # Partial query "martinez" matches only José Martínez
    res_m = search_by_name(conn, "martinez")
    assert len(res_m) == 1
    assert res_m[0].user["full_name"] == "José Martínez"

    # Person with no history has empty history list
    res_josefa = [r for r in results if r.user["full_name"] == "Josefa Morales"][0]
    assert len(res_josefa.history) == 0


def test_export_e1_read_back_with_openpyxl(conn, settings, school, now, tmp_path):
    add_user(conn, settings, "AA01", "est", "Ana García", grade=10, section="A", now=now)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '06:45:00', 'on_time', 'AA01', 1, 'Ana García', 'student', 10, 'A')"""
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', '2026-10-07', '14:00:00', NULL, 'AA01', 1, 'Ana García', 'student', 10, 'A')"""
        )

    person = search_by_badge(conn, "AA01")
    assert person is not None

    export_res = export_e1(tmp_path, school, person)
    assert export_res.success is True
    assert export_res.path is not None
    assert export_res.path.name == "Busqueda de Ana García.xlsx"
    assert export_res.path.exists()

    # Read back with openpyxl
    wb = openpyxl.load_workbook(export_res.path)
    assert wb.active.title == "Sheet1"
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    assert len(rows) == 2

    # Headers
    assert rows[0] == (
        "Día de entrada",
        "Hora de entrada",
        "Hora de salida",
        "Rol",
        "Grado y Sección",
        "Estado",
    )

    # First data row
    assert rows[1] == (
        "07/10/2026",
        "06:45:00",
        "14:00:00",
        "Estudiante",
        "10° A",
        "Puntual",
    )


def test_export_e1_write_error_returns_message(conn, settings, school, now, tmp_path):
    add_user(conn, settings, "AA01", "vist", "Carlos Perez", now=now)
    person = search_by_badge(conn, "AA01")
    assert person is not None

    with patch("openpyxl.Workbook.save", side_effect=PermissionError("Permiso denegado")):
        res = export_e1(tmp_path, school, person)
        assert res.success is False
        assert "Error al crear archivo Excel" in res.error


def test_parse_date_input_leading_zeros_and_validation():
    # Leading zeros vs no leading zeros
    assert parse_date_input("7/10/2026") == ("2026-10-07", "07/10/2026")
    assert parse_date_input("07/10/2026") == ("2026-10-07", "07/10/2026")
    assert parse_date_input("1/2/2025") == ("2025-02-01", "01/02/2025")
    assert parse_date_input("01/02/2025") == ("2025-02-01", "01/02/2025")

    # Invalid dates
    for bad in ["", "invalid", "31/04/2025", "29/02/2025", "07-10-2026", "7/10/26", "32/01/2025"]:
        with pytest.raises(ValueError, match=r"\(ES\) Formato de fecha inválido. Use DD/MM/YYYY"):
            parse_date_input(bad)


def test_teacher_check_in_not_counted_as_student(conn, settings, school, now):
    s = add_user(conn, settings, "AA01", "est", "Estudiante Juan", grade=10, section="A", now=now)
    t = add_user(conn, settings, "BB01", "prof", "Profesor Pedro", taught_grade=10, now=now)

    date_str = "2026-10-07"
    with conn:
        # Teacher check-in
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', ?, '06:40:00', 'on_time', 'BB01', ?, 'Profesor Pedro', 'teacher', 10, '')""",
            (date_str, t.user["id"]),
        )
        # Student check-in
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', ?, '06:45:00', 'on_time', 'AA01', ?, 'Estudiante Juan', 'student', 10, 'A')""",
            (date_str, s.user["id"]),
        )

    # Whole school search
    res_all = search_all_students_by_date(conn, "07/10/2026", school)
    assert len(res_all.present) == 1
    assert res_all.present[0].name == "Estudiante Juan"
    assert res_all.present[0].badge_uid == "AA01"
    # Teacher is not in absent list
    assert not any(a.name == "Profesor Pedro" for a in res_all.absent)

    # Search by grade
    res_grade = search_students_by_grade(conn, "7/10/2026", grade=10)
    assert len(res_grade) == 1
    assert res_grade[0].name == "Estudiante Juan"

    # Search by grade and section
    res_sec = search_students_by_grade_section(conn, "7/10/2026", grade=10, section="A")
    assert len(res_sec) == 1
    assert res_sec[0].name == "Estudiante Juan"


def test_absences_exclude_registered_after_date_and_graduates(conn, settings, school):
    # Wednesday 2026-10-07
    d_before = datetime(2026, 10, 5, 8, 0, 0)
    d_target = "2026-10-07"
    d_after = datetime(2026, 10, 8, 8, 0, 0)

    # Student 1: registered before, present on 2026-10-07
    s1 = add_user(conn, settings, "AA01", "est", "Presente Uno", grade=5, section="A", now=d_before)
    # Student 2: registered before, absent on 2026-10-07
    add_user(conn, settings, "AA02", "est", "Ausente Dos", grade=5, section="B", now=d_before)
    # Student 3: registered AFTER target date -> should NOT be absent
    add_user(conn, settings, "AA03", "est", "Tardio Tres", grade=5, section="A", now=d_after)
    # Student 4: registered before, graduated on 2026-10-06 -> should NOT be absent
    s4 = add_user(conn, settings, "AA04", "est", "Graduado Cuatro", grade=11, section="A", now=d_before)
    with conn:
        conn.execute(
            "UPDATE student_details SET graduation_date = '2026-10-06' WHERE user_id = ?",
            (s4.user["id"],),
        )
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (s4.user["id"],))

    # Log check-in for Student 1
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', ?, '06:45:00', 'on_time', 'AA01', ?, 'Presente Uno', 'student', 5, 'A')""",
            (d_target, s1.user["id"]),
        )

    res = search_all_students_by_date(conn, "07/10/2026", school)
    assert len(res.present) == 1
    assert res.present[0].name == "Presente Uno"

    absent_names = [a.name for a in res.absent]
    assert "Ausente Dos" in absent_names
    assert "Tardio Tres" not in absent_names
    assert "Graduado Cuatro" not in absent_names
    assert len(res.absent) == 1


def test_empty_absent_list_on_weekend(conn, settings, school):
    # Enrolled on weekday
    d_reg = datetime(2026, 10, 5, 8, 0, 0)
    add_user(conn, settings, "AA01", "est", "Estudiante Uno", grade=5, section="A", now=d_reg)

    # 2026-10-10 is Saturday, 2026-10-11 is Sunday
    sat_res = search_all_students_by_date(conn, "10/10/2026", school)
    assert sat_res.present == []
    assert sat_res.absent == []

    sun_res = search_all_students_by_date(conn, "11/10/2026", school)
    assert sun_res.present == []
    assert sun_res.absent == []


def test_past_date_shows_grade_before_promotion(conn, settings, school):
    d_checkin = datetime(2026, 10, 1, 6, 45, 0)
    s = add_user(conn, settings, "AA01", "est", "Estudiante Juan", grade=5, section="A", now=d_checkin)

    # Check-in on 2026-10-01 (Grade 5, Section A)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-01', '06:45:00', 'on_time', 'AA01', ?, 'Estudiante Juan', 'student', 5, 'A')""",
            (s.user["id"],),
        )

    # Run promotion on 2026-10-05 (Grade 5 -> 6)
    p_res = promote_grades(conn, now=datetime(2026, 10, 5, 9, 0, 0))
    assert p_res.success is True

    # Current grade in student_details is 6
    cursor = conn.cursor()
    cursor.execute("SELECT grade FROM student_details WHERE user_id = ?", (s.user["id"],))
    assert cursor.fetchone()[0] == 6

    # But searching 2026-10-01 reflects copied Grade 5
    res = search_all_students_by_date(conn, "01/10/2026", school)
    assert len(res.present) == 1
    assert res.present[0].grade == 5
    assert res.present[0].section == "A"

    # Search by grade 5 finds the student on 2026-10-01
    res_g5 = search_students_by_grade(conn, "01/10/2026", grade=5)
    assert len(res_g5) == 1
    assert res_g5[0].name == "Estudiante Juan"

    # Search by grade 6 returns empty on 2026-10-01
    res_g6 = search_students_by_grade(conn, "01/10/2026", grade=6)
    assert len(res_g6) == 0


def test_export_e2_and_e3_read_back_with_openpyxl(conn, settings, school, now, tmp_path):
    s = add_user(conn, settings, "AA01", "est", "Lucía Blanco", grade=8, section="B", now=now)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '06:40:00', 'on_time', 'AA01', ?, 'Lucía Blanco', 'student', 8, 'B')""",
            (s.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', '2026-10-07', '13:30:00', NULL, 'AA01', ?, 'Lucía Blanco', 'student', 8, 'B')""",
            (s.user["id"],),
        )

    res_all = search_all_students_by_date(conn, "07/10/2026", school)
    assert len(res_all.present) == 1

    # Empty export returns error
    day = date(2026, 10, 7)
    empty_e2 = export_e2(tmp_path, school, day, [])
    assert empty_e2.success is False
    assert empty_e2.error == "No hay datos para exportar."

    empty_e3 = export_e3(tmp_path, school, day, 8, None, [])
    assert empty_e3.success is False
    assert empty_e3.error == "No hay datos para exportar."

    # Export E2
    e2_res = export_e2(tmp_path, school, day, res_all.present)
    assert e2_res.success is True
    assert e2_res.path is not None
    assert e2_res.path.name == "Búsqueda de fecha total, día 07-10-2026.xlsx"
    assert e2_res.path.exists()

    wb_e2 = openpyxl.load_workbook(e2_res.path)
    assert wb_e2.active.title == "Sheet1"
    rows_e2 = list(wb_e2.active.iter_rows(values_only=True))
    assert rows_e2[0] == ("Hora de entrada", "Hora de salida", "Nombres", "Grado y Sección", "Estado")
    assert rows_e2[1] == ("06:40:00", "13:30:00", "Lucía Blanco", "8° B", "Puntual")

    # Export E3 (by grade)
    e3_res = export_e3(tmp_path, school, day, 8, None, res_all.present)
    assert e3_res.success is True
    assert e3_res.path is not None
    assert e3_res.path.name == "Búsqueda de fecha por grado, día 07-10-2026, 8°.xlsx"
    assert e3_res.path.exists()

    wb_e3 = openpyxl.load_workbook(e3_res.path)
    assert wb_e3.active.title == "Sheet1"
    rows_e3 = list(wb_e3.active.iter_rows(values_only=True))
    assert rows_e3[0] == ("Hora de entrada", "Hora de salida", "Nombres", "Grado y Sección", "Estado")
    assert rows_e3[1] == ("06:40:00", "13:30:00", "Lucía Blanco", "8° B", "Puntual")

    # Export E3 (by grade and section)
    e3_sec_res = export_e3(tmp_path, school, day, 8, "B", res_all.present)
    assert e3_sec_res.success is True
    assert e3_sec_res.path is not None
    assert e3_sec_res.path.name == "Búsqueda de fecha por grado, día 07-10-2026, 8° B.xlsx"
    assert e3_sec_res.path.exists()

    wb_e3_sec = openpyxl.load_workbook(e3_sec_res.path)
    assert wb_e3_sec.active.title == "Sheet1"
    rows_e3_sec = list(wb_e3_sec.active.iter_rows(values_only=True))
    assert rows_e3_sec[1] == ("06:40:00", "13:30:00", "Lucía Blanco", "8° B", "Puntual")


def test_no_absences_on_holidays_or_on_weekdays_the_school_is_closed(conn, settings, school):
    add_user(conn, settings, "AA01", "est", "Estudiante Uno", grade=5, section="A", now=datetime(2026, 10, 5, 8, 0, 0))
    holiday = replace(school, holidays=(date(2026, 10, 7),))
    open_saturdays = replace(school, active_weekdays=(0, 1, 2, 3, 4, 5))

    assert [a.name for a in search_all_students_by_date(conn, "07/10/2026", school).absent] == ["Estudiante Uno"]
    assert search_all_students_by_date(conn, "07/10/2026", holiday).absent == []
    assert [a.name for a in search_all_students_by_date(conn, "10/10/2026", open_saturdays).absent] == [
        "Estudiante Uno"
    ]


def test_ranges_count_the_school_days_between_the_first_and_last_scans_on_record(conn, school):
    """The web portal's Year View counts the same days (get_school_dates): before the first scan
    Quickpass was not running yet, and after the last one the day's scans are not in yet."""
    october = (date(2026, 10, 1), date(2026, 10, 31))
    assert school_days_on_record(conn, school, *october) == []

    with conn:
        for event_type, day in (("check_in", "2026-10-06"), ("check_out", "2026-10-08"), ("repeat_scan", "2026-10-13")):
            conn.execute(
                """INSERT INTO attendance_records (event_type, date, time, status, badge_uid, name, role)
                   VALUES (?, ?, '06:40:00', NULL, 'AA01', 'Ana Morales', 'student')""",
                (event_type, day),
            )

    assert school_days_on_record(conn, school, *october) == [date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8)]
    assert school_days_on_record(conn, school, date(2026, 10, 7), date(2026, 10, 31)) == [
        date(2026, 10, 7),
        date(2026, 10, 8),
    ]
    assert school_days_on_record(conn, replace(school, holidays=(date(2026, 10, 7),)), *october) == [
        date(2026, 10, 6),
        date(2026, 10, 8),
    ]


def test_daily_absences_follow_the_grade_and_section_chosen(conn, settings, school):
    registered = datetime(2026, 10, 5, 8, 0, 0)
    for uid, name, grade, section in (("AA01", "Ana", 5, "A"), ("AA02", "Beto", 5, "B"), ("AA03", "Carla", 6, "A")):
        add_user(conn, settings, uid, "est", name, grade=grade, section=section, now=registered)

    def absent(**filters) -> list[str]:
        return [a.name for a in search_all_students_by_date(conn, "2026-10-07", school, **filters).absent]

    assert absent() == ["Ana", "Beto", "Carla"]
    assert absent(grade=5) == ["Ana", "Beto"]
    assert absent(grade=5, section="b") == ["Beto"]


def test_a_holiday_registered_later_removes_that_days_absences_from_the_reports(conn, settings, school, tmp_path):
    s = add_user(conn, settings, "AA01", "est", "Ana Morales", grade=7, section="A", now=datetime(2026, 10, 5, 6, 0, 0))
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s.user["id"],),
        )
    start, end = date(2026, 10, 5), date(2026, 10, 7)

    before = compute_student_range_matrix(conn, school.school_days(start, end))
    assert (before[0].day_marks, before[0].absent_count) == (["present", "absent", "absent"], 2)

    school = replace(school, holidays=(date(2026, 10, 6),))
    school_days = school.school_days(start, end)
    after = compute_student_range_matrix(conn, school_days)
    assert (after[0].day_marks, after[0].absent_count) == (["present", "absent"], 1)

    e4 = export_e4(tmp_path, school, start, end, school_days, after)
    rows = list(openpyxl.load_workbook(e4.path).active.iter_rows(values_only=True))
    assert rows[0][5:] == ("05/10/2026", "07/10/2026")
    assert rows[1] == ("Ana Morales", "7° A", 1, 0, 1, "P", "A")


def test_parse_date_range_validation():
    # Valid range
    s_dt, e_dt, s_iso, e_iso, s_disp, e_disp = parse_date_range("1/10/2026", "10/10/2026")
    assert s_iso == "2026-10-01"
    assert e_iso == "2026-10-10"
    assert s_disp == "01/10/2026"
    assert e_disp == "10/10/2026"

    # Equal dates allowed
    s_dt2, e_dt2, _, _, _, _ = parse_date_range("05/10/2026", "05/10/2026")
    assert s_dt2 == e_dt2

    # Start date after end date refused with legacy message
    with pytest.raises(ValueError, match=r"\(ES\) La fecha de inicio debe ser anterior a la fecha de fin\."):
        parse_date_range("15/10/2026", "01/10/2026")

    # Invalid dates refused
    with pytest.raises(ValueError, match=r"\(ES\) Formato de fecha inválido\. Use DD/MM/YYYY"):
        parse_date_range("invalid", "10/10/2026")


def test_student_range_matrix_pt_a_counts_and_teacher_exclusion(conn, settings):
    # Enrolled before range
    d_reg = datetime(2026, 10, 1, 8, 0, 0)
    s = add_user(conn, settings, "AA01", "est", "Estudiante Juan", grade=10, section="A", now=d_reg)
    t = add_user(conn, settings, "BB01", "prof", "Profesor Pedro", taught_grade=10, now=d_reg)

    # Weekdays: Mon 2026-10-05, Tue 2026-10-06, Wed 2026-10-07
    w1 = datetime(2026, 10, 5)
    w2 = datetime(2026, 10, 6)
    w3 = datetime(2026, 10, 7)
    weekdays = [w1, w2, w3]

    with conn:
        # Student on_time on Mon -> P
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', 'AA01', ?, 'Estudiante Juan', 'student', 10, 'A')""",
            (s.user["id"],),
        )
        # Student late on Tue -> T
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-06', '07:15:00', 'late', 'AA01', ?, 'Estudiante Juan', 'student', 10, 'A')""",
            (s.user["id"],),
        )
        # Student no check-in on Wed -> A

        # Teacher check-ins on all three days -> should NOT appear or count
        for d in ["2026-10-05", "2026-10-06", "2026-10-07"]:
            conn.execute(
                """INSERT INTO attendance_records
                   (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
                   VALUES ('check_in', ?, '06:30:00', 'on_time', 'BB01', ?, 'Profesor Pedro', 'teacher', 10, '')""",
                (d, t.user["id"]),
            )

    matrix = compute_student_range_matrix(conn, weekdays)
    assert len(matrix) == 1
    row = matrix[0]
    assert row.name == "Estudiante Juan"
    assert row.grade == 10
    assert row.section == "A"
    assert row.day_marks == ["present", "late", "absent"]
    assert row.present_count == 1
    assert row.late_count == 1
    assert row.absent_count == 1


def test_range_matrix_blanks_before_registration_and_after_graduation(conn, settings):
    # Weekdays: Mon 2026-10-05 to Fri 2026-10-09 (5 days)
    weekdays = [
        datetime(2026, 10, 5),
        datetime(2026, 10, 6),
        datetime(2026, 10, 7),
        datetime(2026, 10, 8),
        datetime(2026, 10, 9),
    ]

    # Student 1: registered Wed 2026-10-07
    s1 = add_user(
        conn,
        settings,
        "AA01",
        "est",
        "Estudiante Tardio",
        grade=6,
        section="A",
        now=datetime(2026, 10, 7, 8, 0, 0),
    )
    # Check-in on Wed on-time
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '06:45:00', 'on_time', 'AA01', ?, 'Estudiante Tardio', 'student', 6, 'A')""",
            (s1.user["id"],),
        )

    # Student 2: registered Mon 2026-10-05, graduated on Wed 2026-10-07
    s2 = add_user(
        conn,
        settings,
        "AA02",
        "est",
        "Estudiante Graduado",
        grade=11,
        section="B",
        now=datetime(2026, 10, 5, 8, 0, 0),
    )
    with conn:
        # Check-in on Mon
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:45:00', 'on_time', 'AA02', ?, 'Estudiante Graduado', 'student', 11, 'B')""",
            (s2.user["id"],),
        )
        # Graduated on Wed
        conn.execute(
            "UPDATE student_details SET graduation_date = '2026-10-07' WHERE user_id = ?",
            (s2.user["id"],),
        )

    matrix = compute_student_range_matrix(conn, weekdays)
    assert len(matrix) == 2

    # S1: Mon, Tue blank (""); Wed "P"; Thu, Fri "A"
    r1 = [r for r in matrix if r.name == "Estudiante Tardio"][0]
    assert r1.day_marks == ["", "", "present", "absent", "absent"]
    assert r1.present_count == 1
    assert r1.late_count == 0
    assert r1.absent_count == 2

    # S2: Mon "P"; Tue "A"; Wed, Thu, Fri blank ("" due to graduation on Wed)
    r2 = [r for r in matrix if r.name == "Estudiante Graduado"][0]
    assert r2.day_marks == ["present", "absent", "", "", ""]
    assert r2.present_count == 1
    assert r2.late_count == 0
    assert r2.absent_count == 1


def test_export_e4_e5_e6_read_back_with_openpyxl(conn, settings, school, now, tmp_path):
    s1 = add_user(conn, settings, "AA01", "est", "Ana Morales", grade=7, section="A", now=now)
    s2 = add_user(conn, settings, "BB02", "est", "Beto Cruz", grade=8, section="B", now=now)

    w1 = datetime(2026, 10, 5)
    w2 = datetime(2026, 10, 6)
    weekdays = [w1, w2]

    with conn:
        # Ana: on_time Mon, late Tue
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s1.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-06', '07:10:00', 'late', 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s1.user["id"],),
        )
        # Beto: no check-in Mon (A), on_time Tue (P)
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-06', '06:45:00', 'on_time', 'BB02', ?, 'Beto Cruz', 'student', 8, 'B')""",
            (s2.user["id"],),
        )

    # 1. Export E4 (all grades)
    m_all = compute_student_range_matrix(conn, weekdays)
    assert len(m_all) == 2
    start, end = date(2026, 10, 5), date(2026, 10, 6)
    res_e4 = export_e4(tmp_path, school, start, end, weekdays, m_all)
    assert res_e4.success is True
    assert res_e4.path is not None
    assert res_e4.path.name == "Busqueda de todos los grados desde 05-10-2026 hasta 06-10-2026.xlsx"

    wb_e4 = openpyxl.load_workbook(res_e4.path)
    assert wb_e4.active.title == "Reporte"
    rows_e4 = list(wb_e4.active.iter_rows(values_only=True))
    assert rows_e4[0] == (
        "Nombres completos",
        "Grado y Sección",
        "Cuantas veces presentes",
        "Cuantas veces llego tarde",
        "Cuantas veces no llego",
        "05/10/2026",
        "06/10/2026",
    )
    # Ana row
    assert rows_e4[1] == ("Ana Morales", "7° A", 1, 1, 0, "P", "T")
    # Beto row
    assert rows_e4[2] == ("Beto Cruz", "8° B", 1, 0, 1, "A", "P")

    # 2. Export E5 (single grade 7)
    m_g7 = compute_student_range_matrix(conn, weekdays, grade=7)
    assert len(m_g7) == 1
    res_e5 = export_e5(tmp_path, school, start, end, 7, weekdays, m_g7)
    assert res_e5.success is True
    assert res_e5.path is not None
    assert res_e5.path.name == "Busqueda de 7° desde 05-10-2026 hasta 06-10-2026.xlsx"

    wb_e5 = openpyxl.load_workbook(res_e5.path)
    assert wb_e5.active.title == "Reporte"
    rows_e5 = list(wb_e5.active.iter_rows(values_only=True))
    assert len(rows_e5) == 2  # Header + Ana
    assert rows_e5[1] == ("Ana Morales", "7° A", 1, 1, 0, "P", "T")

    # Non-matching grade returns error
    m_g99 = compute_student_range_matrix(conn, weekdays, grade=99)
    res_e5_bad = export_e5(tmp_path, school, start, end, 99, weekdays, m_g99)
    assert res_e5_bad.success is False
    assert res_e5_bad.error == "No se encontraron estudiantes en 99."

    # 3. Export E6 (grade 7, section A)
    m_g7a = compute_student_range_matrix(conn, weekdays, grade=7, section="A")
    assert len(m_g7a) == 1
    res_e6 = export_e6(tmp_path, school, start, end, 7, "A", weekdays, m_g7a)
    assert res_e6.success is True
    assert res_e6.path is not None
    assert res_e6.path.name == "Busqueda de 7° A desde 05-10-2026 hasta 06-10-2026.xlsx"

    wb_e6 = openpyxl.load_workbook(res_e6.path)
    assert wb_e6.active.title == "Reporte"
    rows_e6 = list(wb_e6.active.iter_rows(values_only=True))
    assert len(rows_e6) == 2
    assert rows_e6[1] == ("Ana Morales", "7° A", 1, 1, 0, "P", "T")

    # Non-matching section returns error
    m_g7z = compute_student_range_matrix(conn, weekdays, grade=7, section="Z")
    res_e6_bad = export_e6(tmp_path, school, start, end, 7, "Z", weekdays, m_g7z)
    assert res_e6_bad.success is False
    assert res_e6_bad.error == "No se encontraron estudiantes en 7° Z."


def test_other_roles_kept_apart_single_date(conn, settings, now):
    s = add_user(conn, settings, "AA01", "est", "Estudiante Juan", grade=10, section="A", now=now)
    t = add_user(conn, settings, "BB01", "prof", "Profesor Pedro", taught_grade=3, now=now)
    a = add_user(conn, settings, "CC01", "admin", "Admin Clara", now=now)
    v = add_user(conn, settings, "DD01", "vist", "Visitante Victor", now=now)

    date_str = "2026-10-07"
    with conn:
        for u_id, b_uid, name, role in [
            (s.user["id"], "AA01", "Estudiante Juan", "student"),
            (t.user["id"], "BB01", "Profesor Pedro", "teacher"),
            (a.user["id"], "CC01", "Admin Clara", "admin"),
            (v.user["id"], "DD01", "Visitante Victor", "visitor"),
        ]:
            conn.execute(
                """INSERT INTO attendance_records
                   (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
                   VALUES ('check_in', ?, '06:40:00', 'on_time', ?, ?, ?, ?, 3, '')""",
                (date_str, b_uid, u_id, name, role),
            )
        # Teacher and Admin check out
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', ?, '14:00:00', NULL, 'BB01', ?, 'Profesor Pedro', 'teacher', 3, '')""",
            (date_str, t.user["id"]),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', ?, '15:00:00', NULL, 'CC01', ?, 'Admin Clara', 'admin', NULL, '')""",
            (date_str, a.user["id"]),
        )

    # 1. Teachers query
    t_res = search_other_role_by_date(conn, "07/10/2026", "teacher")
    assert len(t_res) == 1
    assert t_res[0].name == "Profesor Pedro"
    assert t_res[0].taught_grade == 3
    assert t_res[0].departure_time == "14:00:00"

    # 2. Admins query
    a_res = search_other_role_by_date(conn, "07/10/2026", "admin")
    assert len(a_res) == 1
    assert a_res[0].name == "Admin Clara"
    assert a_res[0].departure_time == "15:00:00"

    # 3. Visitors query
    v_res = search_other_role_by_date(conn, "07/10/2026", "visitor")
    assert len(v_res) == 1
    assert v_res[0].name == "Visitante Victor"
    assert v_res[0].departure_time == ""


def test_walk_in_visitors_without_a_badge_each_get_their_own_line(conn, settings, now):
    sign_in_visitor(conn, "Carlos Ramírez", "A1234567", None, now=now)
    sign_in_visitor(conn, "Lucía Gómez", "B7654321", None, now=now.replace(minute=30))

    visits = search_other_role_by_date(conn, now.strftime("%Y-%m-%d"), "visitor")

    assert [(v.name, v.time, v.departure_time) for v in visits] == [
        ("Carlos Ramírez", "07:00:00", ""),
        ("Lucía Gómez", "07:30:00", ""),
    ]


def test_teacher_taught_grade_filter_single_date_and_range(conn, settings, now):
    t1 = add_user(conn, settings, "BB01", "prof", "Profesor Cuatro", taught_grade=4, now=now)
    t2 = add_user(conn, settings, "BB02", "prof", "Profesor Cinco", taught_grade=5, now=now)

    date_str = "2026-10-07"
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', ?, '06:40:00', 'on_time', 'BB01', ?, 'Profesor Cuatro', 'teacher', 4, '')""",
            (date_str, t1.user["id"]),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', ?, '06:50:00', 'late', 'BB02', ?, 'Profesor Cinco', 'teacher', 5, '')""",
            (date_str, t2.user["id"]),
        )

    # Single date - all grades
    all_t = search_other_role_by_date(conn, "07/10/2026", "teacher")
    assert len(all_t) == 2

    # Single date - grade 4
    g4_t = search_other_role_by_date(conn, "07/10/2026", "teacher", taught_grade=4)
    assert len(g4_t) == 1
    assert g4_t[0].name == "Profesor Cuatro"

    # Single date - grade 99
    g99_t = search_other_role_by_date(conn, "07/10/2026", "teacher", taught_grade=99)
    assert len(g99_t) == 0

    # Range matrix
    weekdays = [datetime(2026, 10, 7)]
    m_all = compute_other_role_range_matrix(conn, weekdays, "teacher")
    assert len(m_all) == 2

    m_g4 = compute_other_role_range_matrix(conn, weekdays, "teacher", taught_grade=4)
    assert len(m_g4) == 1
    assert m_g4[0].name == "Profesor Cuatro"
    assert m_g4[0].day_times == ["06:40:00"]

    m_g5 = compute_other_role_range_matrix(conn, weekdays, "teacher", taught_grade=5)
    assert len(m_g5) == 1
    assert m_g5[0].name == "Profesor Cinco"
    assert m_g5[0].day_times == ["06:50:00"]


def test_export_e7_read_back_with_openpyxl(conn, settings, school, now, tmp_path):
    t = add_user(conn, settings, "BB01", "prof", "Profesor Pedro", taught_grade=4, now=now)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-07', '06:40:00', 'on_time', 'BB01', ?, 'Profesor Pedro', 'teacher', 4, '')""",
            (t.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', '2026-10-07', '14:00:00', NULL, 'BB01', ?, 'Profesor Pedro', 'teacher', 4, '')""",
            (t.user["id"],),
        )

    entries = search_other_role_by_date(conn, "07/10/2026", "teacher")
    assert len(entries) == 1

    res_e7 = export_e7(tmp_path, school, "teacher", date(2026, 10, 7), entries)
    assert res_e7.success is True
    assert res_e7.path is not None
    assert res_e7.path.name == "Busqueda de profesores - 07-10-2026.xlsx"

    wb = openpyxl.load_workbook(res_e7.path)
    assert wb.active.title == "Sheet1"
    rows = list(wb.active.iter_rows(values_only=True))
    assert rows[0] == ("Nombres", "Fecha", "Hora", "Hora de salida", "Estado")
    assert rows[1] == ("Profesor Pedro", "07/10/2026", "06:40:00", "14:00:00", "Puntual")


def test_export_e8_read_back_with_openpyxl(conn, settings, school, now, tmp_path):
    a = add_user(conn, settings, "CC01", "admin", "Admin Clara", now=now)
    w1 = datetime(2026, 10, 5)
    w2 = datetime(2026, 10, 6)
    weekdays = [w1, w2]

    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:30:00', 'on_time', 'CC01', ?, 'Admin Clara', 'admin', NULL, '')""",
            (a.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-06', '06:35:00', 'on_time', 'CC01', ?, 'Admin Clara', 'admin', NULL, '')""",
            (a.user["id"],),
        )

    matrix = compute_other_role_range_matrix(conn, weekdays, "admin")
    assert len(matrix) == 1

    start, end = date(2026, 10, 5), date(2026, 10, 6)
    res_e8 = export_e8(tmp_path, school, "admin", start, end, weekdays, matrix)
    assert res_e8.success is True
    assert res_e8.path is not None
    assert res_e8.path.name == "Busqueda de admins desde 05-10-2026 hasta 06-10-2026.xlsx"

    wb = openpyxl.load_workbook(res_e8.path)
    assert wb.active.title == "Reporte"
    rows = list(wb.active.iter_rows(values_only=True))
    assert rows[1] == ("Admin Clara", "06:30:00", "06:35:00")

    # Also verify teachers E8 with taught-grade filter
    t1 = add_user(conn, settings, "BB01", "prof", "Profesor Cuatro", taught_grade=4, now=now)
    t2 = add_user(conn, settings, "BB02", "prof", "Profesor Cinco", taught_grade=5, now=now)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', 'BB01', ?, 'Profesor Cuatro', 'teacher', 4, '')""",
            (t1.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:50:00', 'late', 'BB02', ?, 'Profesor Cinco', 'teacher', 5, '')""",
            (t2.user["id"],),
        )

    t_matrix = compute_other_role_range_matrix(conn, weekdays, "teacher", taught_grade=4)
    assert len(t_matrix) == 1
    assert t_matrix[0].name == "Profesor Cuatro"
    assert t_matrix[0].day_times == ["06:40:00", ""]

    res_t_e8 = export_e8(tmp_path, school, "teacher", start, end, weekdays, t_matrix)
    assert res_t_e8.success is True
    assert res_t_e8.path is not None
    assert res_t_e8.path.name == "Busqueda de profesores desde 05-10-2026 hasta 06-10-2026.xlsx"

    wb_t = openpyxl.load_workbook(res_t_e8.path)
    rows_t = list(wb_t["Reporte"].iter_rows(values_only=True))
    assert rows_t[0] == ("Nombre", "05/10/2026", "06/10/2026")
    assert rows_t[1] == ("Profesor Cuatro", "06:40:00", None)

    # Empty rows returns error
    res_empty = export_e8(tmp_path, school, "admin", start, end, weekdays, [])
    assert res_empty.success is False
    assert "No hay datos para exportar" in res_empty.error


def test_other_roles_range_matrix_role_separation_and_deleted_users(conn, settings, now):
    # Insert attendance records for student, teacher, admin, visitor, and a deleted user (user_id = None)
    weekdays = [datetime(2026, 10, 5), datetime(2026, 10, 6)]
    with conn:
        for r_role, r_name, r_uid, r_grade in [
            ("student", "Estudiante Juan", "S1", 10),
            ("teacher", "Profesor Pedro", "T1", 4),
            ("admin", "Admin Clara", "A1", None),
            ("visitor", "Visitante Victor", "V1", None),
            ("teacher", "Profesor Borrado", "T2", 4),  # Historical teacher with no current user row
        ]:
            conn.execute(
                """INSERT INTO attendance_records
                   (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
                   VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', ?, NULL, ?, ?, ?, '')""",
                (r_uid, r_name, r_role, r_grade),
            )

    # Teachers query should only return teachers (both Pedro and Borrado)
    t_rows = compute_other_role_range_matrix(conn, weekdays, "teacher")
    assert len(t_rows) == 2
    assert [r.name for r in t_rows] == ["Profesor Borrado", "Profesor Pedro"]

    # Admins query should only return Admin Clara
    a_rows = compute_other_role_range_matrix(conn, weekdays, "admin")
    assert len(a_rows) == 1
    assert a_rows[0].name == "Admin Clara"

    # Visitors query should only return Visitante Victor
    v_rows = compute_other_role_range_matrix(conn, weekdays, "visitor")
    assert len(v_rows) == 1
    assert v_rows[0].name == "Visitante Victor"


def test_english_reports_use_english_headers_dates_times_and_marks(conn, settings, school, now, tmp_path):
    school = replace(school, school_language="en")
    s = add_user(conn, settings, "AA01", "est", "Ana Morales", grade=7, section="A", now=now)
    with conn:
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_out', '2026-10-05', '13:30:00', NULL, 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s.user["id"],),
        )
        conn.execute(
            """INSERT INTO attendance_records
               (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
               VALUES ('check_in', '2026-10-06', '07:10:00', 'late', 'AA01', ?, 'Ana Morales', 'student', 7, 'A')""",
            (s.user["id"],),
        )

    person = search_by_badge(conn, "AA01")
    e1 = export_e1(tmp_path, school, person)
    assert e1.path.name == "Search for Ana Morales.xlsx"
    rows_e1 = list(openpyxl.load_workbook(e1.path).active.iter_rows(values_only=True))
    assert rows_e1[0] == ("Check-in date", "Check-in time", "Check-out time", "Role", "Grade & Section", "Status")
    assert rows_e1[1] == ("10/05/2026", "06:40:00 AM", "01:30:00 PM", "Student", "7° A", "On Time")

    e2 = export_e2(tmp_path, school, date(2026, 10, 5), search_all_students_by_date(conn, "2026-10-05", school).present)
    assert e2.path.name == "Whole school, 10-05-2026.xlsx"
    rows_e2 = list(openpyxl.load_workbook(e2.path).active.iter_rows(values_only=True))
    assert rows_e2[0] == ("Check-in time", "Check-out time", "Name", "Grade & Section", "Status")

    weekdays = [datetime(2026, 10, 5), datetime(2026, 10, 6), datetime(2026, 10, 7)]
    matrix = compute_student_range_matrix(conn, weekdays)
    e4 = export_e4(tmp_path, school, date(2026, 10, 5), date(2026, 10, 7), weekdays, matrix)
    assert e4.path.name == "All grades from 10-05-2026 to 10-07-2026.xlsx"
    workbook = openpyxl.load_workbook(e4.path)
    assert workbook.active.title == "Report"
    rows_e4 = list(workbook.active.iter_rows(values_only=True))
    assert rows_e4[0] == (
        "Full name",
        "Grade & Section",
        "Times present",
        "Times late",
        "Times absent",
        "10/05/2026",
        "10/06/2026",
        "10/07/2026",
    )
    assert rows_e4[1] == ("Ana Morales", "7° A", 1, 1, 1, "P", "L", "A")

    assert export_e2(tmp_path, school, date(2026, 10, 5), []).error == "There is no data to export."


def test_reports_name_grades_the_way_the_school_does(conn, settings, school, tmp_path):
    school = store_school(
        conn, replace(school, school_language="en", grades=("Kinder", "Year 1", "Year 2"), sections=("Red", "Blue"))
    )
    registered = datetime(2026, 10, 1, 7, 0, 0)
    s = add_user(conn, settings, "AA01", "est", "Lucy White", grade=2, section="Blue", now=registered)
    t = add_user(conn, settings, "BB01", "prof", "Tom Green", taught_grade=3, now=registered)
    with conn:
        for user, role, grade, section in ((s.user, "student", 2, "Blue"), (t.user, "teacher", 3, "")):
            conn.execute(
                """INSERT INTO attendance_records
                   (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
                   VALUES ('check_in', '2026-10-05', '06:40:00', 'on_time', ?, ?, ?, ?, ?, ?)""",
                (user["badge_uid"], user["id"], user["full_name"], role, grade, section),
            )

    e3 = export_e3(
        tmp_path, school, date(2026, 10, 5), 2, "Blue", search_all_students_by_date(conn, "2026-10-05", school).present
    )
    assert e3.path.name == "By grade, 10-05-2026, Year 1 Blue.xlsx"
    rows_e3 = list(openpyxl.load_workbook(e3.path).active.iter_rows(values_only=True))
    assert rows_e3[1] == ("06:40:00 AM", None, "Lucy White", "Year 1 Blue", "On Time")

    e1 = export_e1(tmp_path, school, search_by_badge(conn, "BB01"))
    rows_e1 = list(openpyxl.load_workbook(e1.path).active.iter_rows(values_only=True))
    assert rows_e1[0][4] == "Grade taught"
    assert rows_e1[1][4] == "Year 2"

    weekdays = [datetime(2026, 10, 5)]
    e5 = export_e5(
        tmp_path,
        school,
        date(2026, 10, 5),
        date(2026, 10, 5),
        2,
        weekdays,
        compute_student_range_matrix(conn, weekdays, grade=2),
    )
    assert e5.path.name == "Year 1 from 10-05-2026 to 10-05-2026.xlsx"
    assert (
        export_e5(tmp_path, school, date(2026, 10, 5), date(2026, 10, 5), 1, weekdays, []).error
        == "No students found in Kinder."
    )
