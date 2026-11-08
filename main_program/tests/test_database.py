import pytest
from conftest import postgres_url

import database


def test_fresh_database_file_is_created_with_foreign_keys_on(tmp_path):
    path = tmp_path / "nueva" / "quickpass.db"

    connection = database.connect(path)
    try:
        assert path.exists()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_reopening_an_existing_database_keeps_working(tmp_path):
    path = tmp_path / "quickpass.db"
    database.connect(path).close()

    connection = database.connect(path)
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_get_next_family_id(tmp_path):
    conn = database.connect(tmp_path / "test.db")
    try:
        assert database.get_next_family_id(conn) == "FAM-0001"

        # Insert a user and student detail with FAM-0042
        conn.execute(
            "INSERT INTO users (badge_uid, full_name, role, created_at) VALUES ('A1', 'Student 1', 'student', '2026-10-09T10:00:00')"
        )
        user_id = conn.execute("SELECT id FROM users WHERE badge_uid = 'A1'").fetchone()[0]
        conn.execute(
            "INSERT INTO student_details (user_id, grade, section, family_id) VALUES (?, 10, 'A', 'FAM-0042')",
            (user_id,),
        )
        conn.commit()

        assert database.get_next_family_id(conn) == "FAM-0043"
    finally:
        conn.close()


def test_find_family_by_guardian_phone(tmp_path):
    conn = database.connect(tmp_path / "test.db")
    try:
        conn.execute(
            "INSERT INTO users (badge_uid, full_name, role, created_at) VALUES ('B1', 'Hno Mayor', 'student', '2026-10-09T10:00:00')"
        )
        user_id = conn.execute("SELECT id FROM users WHERE badge_uid = 'B1'").fetchone()[0]
        conn.execute(
            "INSERT INTO student_details (user_id, grade, section, family_id) VALUES (?, 11, 'B', 'FAM-0142')",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO guardians (student_id, position, name, phone, email) VALUES (?, 1, 'Maria Perez', '+505 8888 1234', 'maria@example.com')",
            (user_id,),
        )
        conn.commit()

        match = database.find_family_by_guardian_phone(conn, "+505 8888 1234")
        assert match is not None
        assert match["family_id"] == "FAM-0142"
        assert match["sibling_name"] == "Hno Mayor"

        assert database.find_family_by_guardian_phone(conn, "+505 0000 0000") is None
    finally:
        conn.close()


@pytest.fixture
def pg_connection(supabase_schema):
    """A connection to the DATABASE_URL database; the user the test adds is deleted after."""
    conn = database.connect(postgres_url())
    yield conn
    conn.cursor().execute("DELETE FROM users WHERE badge_uid = 'AA112233'")
    conn.commit()
    conn.close()


def test_postgres_connection_and_crud(pg_connection):
    cursor = pg_connection.cursor()
    cursor.execute(
        """
        INSERT INTO users (badge_uid, full_name, role, email, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("AA112233", "Postgres User", "student", "pgtest@school.edu", 1, "2026-10-16T12:00:00"),
    )
    pg_connection.commit()
    assert cursor.lastrowid is not None

    user = database.get_user_by_badge_uid(pg_connection, "AA112233")
    assert user is not None
    assert user["full_name"] == "Postgres User"
    assert user["email"] == "pgtest@school.edu"
    assert user["role"] == "student"
