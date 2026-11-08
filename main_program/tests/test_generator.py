from datetime import date, datetime

from conftest import store_school

import database
from tools.generator import generate_test_data


def test_generator_creates_consistent_data(tmp_path, settings):
    db_path = tmp_path / "test_generator.db"
    conn = database.connect(db_path)
    store_school(conn)
    try:
        # Generate with a fixed base date over 5 recent weekdays
        base_date = datetime(2026, 10, 5, 8, 0, 0)
        generate_test_data(
            conn=conn,
            settings=settings,
            num_students=20,
            num_teachers=4,
            num_admins=2,
            num_visitors=3,
            days=5,
            end_date=base_date,
            seed=42,
        )

        cursor = conn.cursor()

        # 1. Grades are from 1 to 11
        cursor.execute("SELECT grade FROM student_details")
        student_grades = [r[0] for r in cursor.fetchall()]
        assert len(student_grades) == 20
        assert all(1 <= g <= 11 for g in student_grades)

        cursor.execute("SELECT taught_grade FROM teacher_details")
        teacher_grades = [r[0] for r in cursor.fetchall()]
        assert len(teacher_grades) == 4
        assert all(1 <= g <= 11 for g in teacher_grades)

        # 2. Each Student has at most two Guardians
        cursor.execute("SELECT student_id, COUNT(*) FROM guardians GROUP BY student_id")
        guardian_counts = [r[1] for r in cursor.fetchall()]
        assert all(1 <= count <= 2 for count in guardian_counts)

        # 3. Each person has at most one Check-in and at most one Check-out per day
        cursor.execute(
            """
            SELECT user_id, date, event_type, COUNT(*)
            FROM attendance_records
            GROUP BY user_id, date, event_type
            """
        )
        for row in cursor.fetchall():
            assert row[3] == 1, f"User {row[0]} on {row[1]} has {row[3]} of {row[2]}"

        # 4. Each Check-out comes after its Check-in
        cursor.execute(
            """
            SELECT a1.user_id, a1.date, a1.time as in_time, a2.time as out_time
            FROM attendance_records a1
            JOIN attendance_records a2
              ON a1.user_id = a2.user_id AND a1.date = a2.date
            WHERE a1.event_type = 'check_in' AND a2.event_type = 'check_out'
            """
        )
        for row in cursor.fetchall():
            assert row["in_time"] < row["out_time"]

        # 5. Some absences and security incidents exist
        cursor.execute("SELECT COUNT(*) FROM security_incidents")
        assert cursor.fetchone()[0] > 0

    finally:
        conn.close()


def test_generator_registers_people_in_the_schools_own_grades_and_sections(tmp_path, settings):
    from conftest import make_school

    conn = database.connect(tmp_path / "named_grades.db")
    store_school(conn, make_school(grades=("Pre-K", "Kinder", "1st"), sections=("Única",)))
    try:
        generate_test_data(
            conn=conn,
            settings=settings,
            num_students=9,
            num_teachers=4,
            num_admins=1,
            num_visitors=0,
            days=1,
            end_date=datetime(2026, 10, 5, 8, 0, 0),
            seed=7,
        )

        students = conn.execute("SELECT grade, section FROM student_details").fetchall()
        assert len(students) == 9
        assert {(r["grade"], r["section"]) for r in students} == {(1, "Única"), (2, "Única"), (3, "Única")}
        taught = {r["taught_grade"] for r in conn.execute("SELECT taught_grade FROM teacher_details")}
        assert taught <= {1, 2, 3}
    finally:
        conn.close()


def test_generator_records_attendance_only_on_school_days(tmp_path, settings):
    from conftest import make_school

    conn = database.connect(tmp_path / "school_days.db")
    store_school(conn, make_school(holidays=(date(2026, 10, 2),)))
    try:
        generate_test_data(
            conn=conn,
            settings=settings,
            num_students=4,
            num_teachers=1,
            num_admins=1,
            num_visitors=0,
            days=3,
            end_date=datetime(2026, 10, 5, 8, 0, 0),
            seed=3,
        )

        dates = {r["date"] for r in conn.execute("SELECT DISTINCT date FROM attendance_records")}
        assert dates == {"2026-09-30", "2026-10-01", "2026-10-05"}
    finally:
        conn.close()
