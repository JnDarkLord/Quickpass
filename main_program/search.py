"""Search features: search by badge and search by name across all roles.

Legacy menu 3. These functions take the database connection and inputs;
they never read the keyboard, print or touch serial. Results hold neutral
values (ISO dates, status codes such as `on_time`); screens and reports turn
them into text in the School Language.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import database
from school_settings import SchoolSettings

# Filter value meaning "every Grade" or "every Section". Screens show their own
# label for it; only this value travels to the queries.
ALL = "ALL"


@dataclass
class PersonAttendanceDay:
    date: str           # YYYY-MM-DD
    arrival_time: str   # HH:MM:SS
    departure_time: str # HH:MM:SS or ""
    status: str         # "on_time", "late", or ""
    grade: int | None
    section: str | None


@dataclass
class PersonSearchResult:
    user: dict[str, Any]
    history: list[PersonAttendanceDay]


@dataclass
class PresentStudent:
    arrival_time: str
    departure_time: str
    name: str
    grade: int | None
    section: str | None
    status: str
    badge_uid: str = ""
    user_id: int | None = None


@dataclass
class AbsentStudent:
    name: str
    grade: int | None
    section: str | None


@dataclass
class StudentsDaySearchResult:
    iso_date: str
    present: list[PresentStudent]
    absent: list[AbsentStudent]


@dataclass
class StudentRangeMatrixRow:
    student_id: int
    name: str
    grade: int
    section: str
    present_count: int
    late_count: int
    absent_count: int
    day_marks: list[str]  # per day: "present", "late", "absent", or "" before enrollment / after graduation


@dataclass
class OtherRoleAttendanceDay:
    time: str
    departure_time: str
    name: str
    taught_grade: int | None
    status: str
    user_id: int | None
    badge_uid: str


@dataclass
class UserRangeRow:
    name: str
    day_times: list[str]


def parse_date_input(date_str: str) -> tuple[str, str]:
    """Parse user date input in D/M/YYYY or DD/MM/YYYY format.

    Returns (iso_date, display_date) where iso_date is YYYY-MM-DD and display_date is DD/MM/YYYY.
    Raises ValueError("(ES) Formato de fecha inválido. Use DD/MM/YYYY") on invalid format or date.
    """
    parts = date_str.strip().split("/")
    if len(parts) != 3 or len(parts[2].strip()) != 4:
        raise ValueError("(ES) Formato de fecha inválido. Use DD/MM/YYYY")
    try:
        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
        dt = datetime(y, m, d)
    except Exception:
        raise ValueError("(ES) Formato de fecha inválido. Use DD/MM/YYYY") from None
    iso_date = dt.strftime("%Y-%m-%d")
    display_date = dt.strftime("%d/%m/%Y")
    return iso_date, display_date


def _resolve_iso_date(date_str: str) -> str:
    """The ISO date of `date_str`, written either YYYY-MM-DD or DD/MM/YYYY."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        return parse_date_input(date_str)[0]


def _get_students_for_date(
    conn: sqlite3.Connection,
    iso_date: str,
    grade: int | None = None,
    section: str | None = None,
) -> list[PresentStudent]:
    """Retrieve present students on iso_date, matching optional grade and section filters."""
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT badge_uid, user_id, time
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_out' AND role = 'student'
        ORDER BY time ASC, id ASC
        """,
        (iso_date,),
    )
    departure_map: dict[Any, str] = {}
    for r in cursor.fetchall():
        uid_key = r["user_id"] if r["user_id"] is not None else r["badge_uid"]
        departure_map[uid_key] = r["time"]

    query = """
        SELECT id, time, badge_uid, user_id, name, grade, section, status
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_in' AND role = 'student'
    """
    params: list[Any] = [iso_date]

    if grade is not None:
        query += " AND grade = ?"
        params.append(grade)
    if section is not None:
        query += " AND UPPER(section) = UPPER(?)"
        params.append(section)

    query += " ORDER BY time ASC, id ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    present: list[PresentStudent] = []
    seen: set[Any] = set()

    for r in rows:
        key = r["user_id"] if r["user_id"] is not None else r["badge_uid"]
        if key in seen:
            continue
        seen.add(key)

        present.append(
            PresentStudent(
                arrival_time=r["time"],
                departure_time=departure_map.get(key, ""),
                name=r["name"],
                grade=r["grade"],
                section=r["section"],
                status=r["status"] or "",
                badge_uid=r["badge_uid"],
                user_id=r["user_id"],
            )
        )

    return present


def search_all_students_by_date(
    conn: sqlite3.Connection,
    date_str: str,
    school: SchoolSettings,
    grade: int | None = None,
    section: str | None = None,
) -> StudentsDaySearchResult:
    """The Students present on a date and, when it is a School Day, the enrolled Students absent from it.

    `grade` and `section` narrow both lists."""
    iso_date = _resolve_iso_date(date_str)
    present = _get_students_for_date(conn, iso_date, grade=grade, section=section)

    absent: list[AbsentStudent] = []
    if school.is_school_day(date.fromisoformat(iso_date)):
        present_uids = {p.user_id for p in present if p.user_id is not None}
        present_badge_uids = {p.badge_uid for p in present if p.badge_uid}

        query = """
            SELECT u.id, u.badge_uid, u.full_name, sd.grade, sd.section
            FROM users u
            JOIN student_details sd ON sd.user_id = u.id
            WHERE (u.role = 'student' OR u.role = 'graduate')
              AND substr(u.created_at, 1, 10) <= ?
              AND (sd.graduation_date IS NULL OR sd.graduation_date > ?)
        """
        params: list[Any] = [iso_date, iso_date]
        if grade is not None:
            query += " AND sd.grade = ?"
            params.append(grade)
        if section is not None:
            query += " AND UPPER(sd.section) = UPPER(?)"
            params.append(section)
        query += " ORDER BY sd.grade ASC, sd.section ASC, u.full_name ASC"

        cursor = conn.cursor()
        cursor.execute(query, params)
        for r in cursor.fetchall():
            if r["id"] not in present_uids and r["badge_uid"] not in present_badge_uids:
                absent.append(AbsentStudent(name=r["full_name"], grade=r["grade"], section=r["section"]))

    return StudentsDaySearchResult(
        iso_date=iso_date,
        present=present,
        absent=absent,
    )


search_students_by_date = search_all_students_by_date


def search_students_by_grade(
    conn: sqlite3.Connection,
    date_str: str,
    grade: int,
) -> list[PresentStudent]:
    """Retrieve present students on date_str filtered by grade."""
    iso_date = _resolve_iso_date(date_str)
    return _get_students_for_date(conn, iso_date, grade=grade)


def search_students_by_grade_section(
    conn: sqlite3.Connection,
    date_str: str,
    grade: int,
    section: str,
) -> list[PresentStudent]:
    """Retrieve present students on date_str filtered by grade and section."""
    iso_date = _resolve_iso_date(date_str)
    return _get_students_for_date(conn, iso_date, grade=grade, section=section)


def parse_date_range(start_str: str, end_str: str) -> tuple[datetime, datetime, str, str, str, str]:
    """Parse start and end date strings.

    Returns (start_dt, end_dt, start_iso, end_iso, start_disp, end_disp).
    Raises ValueError on invalid format or if start_dt > end_dt.
    """
    start_iso, start_disp = parse_date_input(start_str)
    end_iso, end_disp = parse_date_input(end_str)
    start_dt = datetime.strptime(start_iso, "%Y-%m-%d")
    end_dt = datetime.strptime(end_iso, "%Y-%m-%d")
    if start_dt > end_dt:
        raise ValueError("(ES) La fecha de inicio debe ser anterior a la fecha de fin.")
    return start_dt, end_dt, start_iso, end_iso, start_disp, end_disp


def get_student_checkins_for_day(
    conn: sqlite3.Connection,
    iso_date: str,
    grade: int | None = None,
    section: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all student check-in records for a given day and optional grade/section."""
    query = """
        SELECT time, name, grade, section, status
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_in' AND role = 'student'
    """
    params: list[Any] = [iso_date]
    if grade is not None:
        query += " AND grade = ?"
        params.append(grade)
    if section is not None:
        query += " AND UPPER(section) = UPPER(?)"
        params.append(section)
    query += " ORDER BY time ASC, id ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(r) for r in cursor.fetchall()]


def school_days_on_record(conn: Any, school: SchoolSettings, start: date, end: date) -> list[date]:
    """The School Days from `start` to `end` between the first and the last date with a Check-in or
    Check-out on record, the days the web portal's Year View counts too (`get_school_dates`): before
    the first, Quickpass was not running yet; after the last, the day's scans are not in yet."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT MIN(date) AS first_day, MAX(date) AS last_day
        FROM attendance_records
        WHERE event_type IN ('check_in', 'check_out')
        """
    )
    row = cursor.fetchone()
    if row is None or row["first_day"] is None:
        return []
    first_day = date.fromisoformat(str(row["first_day"])[:10])
    last_day = date.fromisoformat(str(row["last_day"])[:10])
    return school.school_days(max(start, first_day), min(end, last_day))


def compute_student_range_matrix(
    conn: sqlite3.Connection,
    school_days: Sequence[date],
    grade: int | None = None,
    section: str | None = None,
) -> list[StudentRangeMatrixRow]:
    """Build the present/late/absent matrix rows for eligible students across the School Days given
    (`school_days_on_record`), so holidays and closed weekdays never count as Absences."""
    cursor = conn.cursor()

    q = """
        SELECT u.id, u.full_name, sd.grade, sd.section, u.created_at, sd.graduation_date
        FROM users u
        JOIN student_details sd ON sd.user_id = u.id
        WHERE (u.role = 'student' OR u.role = 'graduate')
    """
    params: list[Any] = []
    if grade is not None:
        q += " AND sd.grade = ?"
        params.append(grade)
    if section is not None:
        q += " AND UPPER(sd.section) = UPPER(?)"
        params.append(section)

    q += " ORDER BY sd.grade ASC, sd.section ASC, u.full_name ASC"
    cursor.execute(q, params)
    students = cursor.fetchall()
    if not students:
        return []

    iso_dates = [d.strftime("%Y-%m-%d") for d in school_days]
    if not iso_dates:
        return [
            StudentRangeMatrixRow(
                student_id=s["id"],
                name=s["full_name"],
                grade=s["grade"],
                section=s["section"],
                present_count=0,
                late_count=0,
                absent_count=0,
                day_marks=[],
            )
            for s in students
        ]

    placeholders = ",".join("?" for _ in iso_dates)
    cursor.execute(
        f"""
        SELECT user_id, date, time, status
        FROM attendance_records
        WHERE event_type = 'check_in'
          AND role = 'student'
          AND date IN ({placeholders})
        ORDER BY date ASC, time ASC, id ASC
        """,
        iso_dates,
    )
    records = cursor.fetchall()

    checkin_map: dict[tuple[int, str], str] = {}
    for r in records:
        uid = r["user_id"]
        if uid is not None:
            key = (uid, r["date"])
            if key not in checkin_map:
                checkin_map[key] = r["status"] or ""

    matrix_rows: list[StudentRangeMatrixRow] = []
    for s in students:
        uid = s["id"]
        reg_date = s["created_at"][:10]
        grad_date = s["graduation_date"]

        present_count = 0
        late_count = 0
        absent_count = 0
        marks: list[str] = []

        for d_iso in iso_dates:
            if (uid, d_iso) in checkin_map:
                if checkin_map[(uid, d_iso)] == "late":
                    marks.append("late")
                    late_count += 1
                else:
                    marks.append("present")
                    present_count += 1
            else:
                if d_iso < reg_date or (grad_date is not None and d_iso >= grad_date):
                    marks.append("")
                else:
                    marks.append("absent")
                    absent_count += 1

        matrix_rows.append(
            StudentRangeMatrixRow(
                student_id=uid,
                name=s["full_name"],
                grade=s["grade"],
                section=s["section"],
                present_count=present_count,
                late_count=late_count,
                absent_count=absent_count,
                day_marks=marks,
            )
        )

    return matrix_rows


def search_other_role_by_date(
    conn: sqlite3.Connection,
    date_str: str,
    role: str,
    taught_grade: int | None = None,
) -> list[OtherRoleAttendanceDay]:
    """Retrieve check-ins for a non-student role on date_str, with optional taught_grade filter."""
    iso_date = _resolve_iso_date(date_str)
    cursor = conn.cursor()

    def person(r: sqlite3.Row) -> Any:
        # A walk-in Visitor without a Badge has no user and no Badge UID, only a name.
        return r["user_id"] if r["user_id"] is not None else (r["badge_uid"], r["name"])

    cursor.execute(
        """
        SELECT badge_uid, user_id, name, time
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_out' AND role = ?
        ORDER BY time ASC, id ASC
        """,
        (iso_date, role),
    )
    departure_map: dict[Any, str] = {}
    for r in cursor.fetchall():
        departure_map[person(r)] = r["time"]

    query = """
        SELECT id, time, badge_uid, user_id, name, grade, status
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_in' AND role = ?
    """
    params: list[Any] = [iso_date, role]
    if taught_grade is not None:
        query += " AND grade = ?"
        params.append(taught_grade)
    query += " ORDER BY time ASC, id ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    result: list[OtherRoleAttendanceDay] = []
    seen: set[Any] = set()
    for r in rows:
        key = person(r)
        if key in seen:
            continue
        seen.add(key)

        result.append(
            OtherRoleAttendanceDay(
                time=r["time"],
                departure_time=departure_map.get(key, ""),
                name=r["name"],
                taught_grade=r["grade"],
                status=r["status"] or "",
                user_id=r["user_id"],
                badge_uid=r["badge_uid"],
            )
        )

    return result


def get_other_role_checkins_for_day(
    conn: sqlite3.Connection,
    iso_date: str,
    role: str,
    taught_grade: int | None = None,
) -> list[dict[str, Any]]:
    """Retrieve check-ins for a role on a single day for range display."""
    query = """
        SELECT time, name, grade, status
        FROM attendance_records
        WHERE date = ? AND event_type = 'check_in' AND role = ?
    """
    params: list[Any] = [iso_date, role]
    if taught_grade is not None:
        query += " AND grade = ?"
        params.append(taught_grade)
    query += " ORDER BY time ASC, id ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(r) for r in cursor.fetchall()]


def compute_other_role_range_matrix(
    conn: sqlite3.Connection,
    school_days: Sequence[date],
    role: str,
    taught_grade: int | None = None,
) -> list[UserRangeRow]:
    """Compute E8 matrix rows for role across the School Days given."""
    iso_dates = [d.strftime("%Y-%m-%d") for d in school_days]
    if not iso_dates:
        return []

    placeholders = ",".join("?" for _ in iso_dates)
    query = f"""
        SELECT name, date, time
        FROM attendance_records
        WHERE event_type = 'check_in'
          AND role = ?
          AND date IN ({placeholders})
    """
    params: list[Any] = [role] + iso_dates
    if taught_grade is not None:
        query += " AND grade = ?"
        params.append(taught_grade)
    query += " ORDER BY name ASC, date ASC, time ASC, id ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    records = cursor.fetchall()

    user_dates: dict[str, dict[str, str]] = {}
    for r in records:
        name = r["name"]
        if name not in user_dates:
            user_dates[name] = {}
        if r["date"] not in user_dates[name]:
            user_dates[name][r["date"]] = r["time"]

    rows: list[UserRangeRow] = []
    for name in sorted(user_dates.keys()):
        times = [user_dates[name].get(d_iso, "") for d_iso in iso_dates]
        rows.append(UserRangeRow(name=name, day_times=times))

    return rows



def normalize_search_text(text: str) -> str:
    """Lowercase and remove accents/diacritics."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def get_person_history(conn: sqlite3.Connection, user_id: int) -> list[PersonAttendanceDay]:
    """Retrieve chronological attendance history for a user, grouping check-ins and check-outs by day."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT date, time, event_type, status, grade, section
        FROM attendance_records
        WHERE user_id = ?
        ORDER BY date ASC, time ASC, id ASC
        """,
        (user_id,),
    )
    rows = cursor.fetchall()

    days_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = r["date"]
        ev = r["event_type"]
        if d not in days_map:
            days_map[d] = {
                "date": d,
                "arrival_time": "",
                "departure_time": "",
                "status": "",
                "grade": r["grade"],
                "section": r["section"],
            }
        day_info = days_map[d]
        if ev == "check_in":
            day_info["arrival_time"] = r["time"]
            day_info["status"] = r["status"] or ""
            day_info["grade"] = r["grade"]
            day_info["section"] = r["section"]
        elif ev == "check_out":
            day_info["departure_time"] = r["time"]

    history: list[PersonAttendanceDay] = []
    for d, info in sorted(days_map.items(), key=lambda x: x[0]):
        history.append(
            PersonAttendanceDay(
                date=d,
                arrival_time=info["arrival_time"],
                departure_time=info["departure_time"],
                status=info["status"],
                grade=info["grade"],
                section=info["section"],
            )
        )

    return history


def search_by_badge(conn: sqlite3.Connection, badge_uid: str) -> PersonSearchResult | None:
    """Find a person and their attendance history by badge UID."""
    norm_uid = database.normalize_badge_uid(badge_uid)
    if not norm_uid:
        return None

    user = database.get_user_by_badge_uid(conn, norm_uid)
    if user is None:
        return None

    history = get_person_history(conn, user["id"])
    return PersonSearchResult(user=user, history=history)


def search_by_name(conn: sqlite3.Connection, query: str) -> list[PersonSearchResult]:
    """Find all matching users by partial name (case & accent insensitive), with their history."""
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("(ES) Nombre no válido.")

    norm_query = normalize_search_text(clean_query)

    cursor = conn.cursor()
    cursor.execute("SELECT badge_uid FROM users ORDER BY id ASC")
    all_uids = [row[0] for row in cursor.fetchall()]

    results: list[PersonSearchResult] = []
    for uid in all_uids:
        user = database.get_user_by_badge_uid(conn, uid)
        if user and norm_query in normalize_search_text(user["full_name"]):
            history = get_person_history(conn, user["id"])
            results.append(PersonSearchResult(user=user, history=history))

    return results


def search_by_family_id(conn: sqlite3.Connection, family_id: str) -> list[PersonSearchResult]:
    """Find all students sharing a family code (e.g. FAM-5001), with their attendance history."""
    clean = family_id.strip()
    if not clean:
        return []

    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.id, u.badge_uid
        FROM users u
        JOIN student_details sd ON sd.user_id = u.id
        WHERE UPPER(sd.family_id) = UPPER(?) AND u.is_active = 1
        ORDER BY sd.grade ASC, sd.section ASC, u.full_name ASC
        """,
        (clean,),
    )
    rows = cursor.fetchall()
    results: list[PersonSearchResult] = []
    for r in rows:
        user = database.get_user_by_badge_uid(conn, r["badge_uid"])
        if user:
            history = get_person_history(conn, user["id"])
            results.append(PersonSearchResult(user=user, history=history))
    return results
