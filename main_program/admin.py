"""Admin features: add, delete and modify Badges, statistics, Grade Promotion, wipes and backups.

Legacy menu 1. The core functions take the database connection, the settings,
the inputs and the time; they never read the keyboard, print or touch serial.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import database
import i18n
import school_settings
import sms
from config import Settings

ROLE_MAP = {
    "est": "student",
    "estudiante": "student",
    "student": "student",
    "prof": "teacher",
    "profesor": "teacher",
    "teacher": "teacher",
    "admin": "admin",
    "administrador": "admin",
    "vist": "visitor",
    "visitante": "visitor",
    "visitor": "visitor",
}


@dataclass(frozen=True)
class GuardianData:
    name: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class AddUserResult:
    success: bool
    error: str = ""
    user: dict[str, Any] | None = None


@dataclass
class DeleteUserResult:
    success: bool
    error: str = ""


@dataclass
class ModifyUserResult:
    success: bool
    error: str = ""
    user: dict[str, Any] | None = None


@dataclass
class PromoteGradesResult:
    success: bool
    promoted_count: int = 0
    graduated_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class PromotionPreview:
    promoted_count: int
    graduated_count: int


@dataclass(frozen=True)
class SystemStatistics:
    total_users: int
    total_check_ins: int
    students_by_grade: dict[int, int]
    graduates: int
    teachers_by_grade: dict[int, int]
    recent_check_ins: list[tuple[date, int]]
    users_by_role: dict[str, int]


@dataclass
class WipeResult:
    success: bool
    backup_path: Path | None = None
    error: str = ""


def _error(conn: sqlite3.Connection, key: str, **params: Any) -> str:
    """An Admin error message in the School Language."""
    return i18n.t(school_settings.require(conn).school_language, f"admin.error.{key}", **params)


def _grade_rank(value: int | str | None, school: school_settings.SchoolSettings) -> int | None:
    """The rank of one of the School's Grades, or None for anything else."""
    if value is None:
        return None
    try:
        rank = int(value)
    except ValueError:
        return None
    return rank if 1 <= rank <= school.final_grade else None


def _school_section(value: str | None, school: school_settings.SchoolSettings) -> str | None:
    """The School's spelling of the Section typed, or None when the School has no such Section."""
    typed = (value or "").strip().casefold()
    return next((section for section in school.sections if section.casefold() == typed), None)


def _section_unknown(conn: sqlite3.Connection, school: school_settings.SchoolSettings) -> str:
    return _error(conn, "section_unknown", sections=", ".join(school.sections))


def _has_a_letter(name: str) -> bool:
    return any(c.isalpha() for c in name)


def _checked_guardians(
    conn: sqlite3.Connection, guardians: list[GuardianData], stored: list[dict[str, Any]] | None = None
) -> tuple[list[GuardianData], str]:
    """The Guardians given, each with a name and a phone written as `+<country code> <number>`,
    or the error that refuses them. Names and phones already `stored` are kept as they are."""
    stored_names = {g["name"] for g in stored or []}
    stored_phones = {g["phone"] for g in stored or []}
    checked: list[GuardianData] = []
    for g in guardians:
        name, phone = g.name.strip(), g.phone.strip()
        if bool(name) != bool(phone):
            return [], _error(conn, "guardian_incomplete")
        if not name:
            continue
        if name not in stored_names and not _has_a_letter(name):
            return [], _error(conn, "guardian_name_letters")
        if phone not in stored_phones:
            formatted = sms.format_global_phone(phone)
            if formatted is None:
                return [], _error(conn, "phone_format")
            phone = formatted
        checked.append(GuardianData(name=name, phone=phone, email=g.email.strip()))
    if len(checked) > 2:
        return [], _error(conn, "too_many_guardians")
    return checked, ""


def add_user(
    conn: sqlite3.Connection,
    settings: Settings,
    badge_uid: str,
    role: str,
    full_name: str,
    grade: int | str | None = None,
    section: str | None = None,
    guardians: list[GuardianData] | None = None,
    taught_grade: int | str | None = None,
    approving_uid: str | None = None,
    now: datetime | None = None,
    family_id: str | None = None,
) -> AddUserResult:
    """Register a new person and their Badge."""
    norm_uid = database.normalize_badge_uid(badge_uid)
    if not norm_uid:
        return AddUserResult(success=False, error=_error(conn, "invalid_uid"))

    # Check if already registered
    existing = database.get_user_by_badge_uid(conn, norm_uid)
    if existing is not None:
        return AddUserResult(success=False, error=_error(conn, "badge_exists"))

    norm_role = ROLE_MAP.get(role.strip().lower())
    if not norm_role:
        return AddUserResult(success=False, error=_error(conn, "invalid_role"))

    clean_name = full_name.strip()
    if not clean_name:
        return AddUserResult(success=False, error=_error(conn, "name_empty"))
    if not _has_a_letter(clean_name):
        return AddUserResult(success=False, error=_error(conn, "name_letters"))

    school = school_settings.require(conn)
    clean_grade: int | None = None
    clean_section: str = ""
    clean_guardians: list[GuardianData] = []
    clean_taught_grade: int | None = None

    if norm_role == "student":
        clean_grade = _grade_rank(grade, school)
        if clean_grade is None:
            return AddUserResult(success=False, error=_error(conn, "grade_range"))

        if not (section or "").strip():
            return AddUserResult(success=False, error=_error(conn, "section_empty"))
        school_section = _school_section(section, school)
        if school_section is None:
            return AddUserResult(success=False, error=_section_unknown(conn, school))
        clean_section = school_section

        clean_guardians, guardian_error = _checked_guardians(conn, guardians or [])
        if guardian_error:
            return AddUserResult(success=False, error=guardian_error)

    elif norm_role == "teacher":
        clean_taught_grade = _grade_rank(taught_grade, school)
        if clean_taught_grade is None:
            return AddUserResult(success=False, error=_error(conn, "taught_grade_range"))

    elif norm_role == "admin":
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1")
        admin_count = cursor.fetchone()[0]
        if admin_count > 0:
            if not approving_uid:
                return AddUserResult(success=False, error=_error(conn, "not_admin"))
            approver = database.get_user_by_badge_uid(conn, approving_uid)
            if not approver or approver["role"] != "admin" or not approver["is_active"]:
                return AddUserResult(success=False, error=_error(conn, "not_admin"))

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (badge_uid, full_name, role, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            (norm_uid, clean_name, norm_role, timestamp),
        )
        user_id = cursor.lastrowid

        if norm_role == "student":
            cursor.execute(
                "INSERT INTO student_details (user_id, grade, section, family_id) VALUES (?, ?, ?, ?)",
                (user_id, clean_grade, clean_section, family_id),
            )
            for pos, g in enumerate(clean_guardians, start=1):
                cursor.execute(
                    "INSERT INTO guardians (student_id, position, name, phone, email) VALUES (?, ?, ?, ?, ?)",
                    (user_id, pos, g.name, g.phone, g.email or None),
                )
        elif norm_role == "teacher":
            cursor.execute(
                "INSERT INTO teacher_details (user_id, taught_grade) VALUES (?, ?)",
                (user_id, clean_taught_grade),
            )
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("DELETE FROM deleted_users WHERE badge_uid = ?", (norm_uid,))

    user_data = database.get_user_by_badge_uid(conn, norm_uid)
    return AddUserResult(success=True, user=user_data)


def assign_visitor_badge(
    conn: sqlite3.Connection,
    settings: Settings,
    badge_uid: str,
    full_name: str,
    now: datetime | None = None,
) -> AddUserResult:
    """Lend a temporary Badge to a walk-in Visitor. A new Badge is registered to them and a Badge
    an earlier Visitor carried passes to them; a Badge anyone else holds is refused."""
    norm_uid = database.normalize_badge_uid(badge_uid)
    holder = database.get_user_by_badge_uid(conn, norm_uid) if norm_uid else None
    if holder is None:
        return add_user(conn, settings, badge_uid, "visitor", full_name, now=now)

    clean_name = full_name.strip()
    if not clean_name:
        return AddUserResult(success=False, error=_error(conn, "name_empty"))
    if not _has_a_letter(clean_name):
        return AddUserResult(success=False, error=_error(conn, "name_letters"))
    if holder["role"] != "visitor":
        language = school_settings.require(conn).school_language
        role = i18n.t(language, f"role.{holder['role']}")
        return AddUserResult(
            success=False, error=_error(conn, "badge_not_visitor", uid=norm_uid, name=holder["full_name"], role=role)
        )

    with conn:
        conn.execute("UPDATE users SET full_name = ?, is_active = 1 WHERE id = ?", (clean_name, holder["id"]))
        if isinstance(conn, sqlite3.Connection):
            conn.execute("UPDATE users SET is_synced = 0 WHERE id = ?", (holder["id"],))
    return AddUserResult(success=True, user=database.get_user_by_badge_uid(conn, norm_uid))


def _is_active_admin_badge(conn: sqlite3.Connection, badge_uid: str) -> bool:
    approver = database.get_user_by_badge_uid(conn, badge_uid) if badge_uid else None
    return bool(approver and approver["role"] == "admin" and approver["is_active"])


def _matches_admin_secret_key(conn: sqlite3.Connection, typed: str) -> bool:
    school = school_settings.load(conn)
    return school is not None and school_settings.verify_secret_key(typed, school.admin_secret_key_hash)


def delete_user(
    conn: sqlite3.Connection,
    target_badge_uid: str,
    approving_uid: str | None,
    confirmed: bool,
) -> DeleteUserResult:
    """Delete a user along with details and guardians, preserving attendance records."""
    norm_target = database.normalize_badge_uid(target_badge_uid)
    if not norm_target:
        return DeleteUserResult(success=False, error=_error(conn, "invalid_uid"))

    target = database.get_user_by_badge_uid(conn, norm_target)
    if not target:
        return DeleteUserResult(success=False, error=_error(conn, "badge_not_found"))

    if not approving_uid:
        return DeleteUserResult(success=False, error=_error(conn, "not_admin"))

    norm_approver = database.normalize_badge_uid(approving_uid)
    approved_by_badge = _is_active_admin_badge(conn, norm_approver)
    approved_by_key = not approved_by_badge and _matches_admin_secret_key(conn, approving_uid)
    if not approved_by_key and norm_approver == norm_target:
        return DeleteUserResult(
            success=False,
            error=_error(conn, "same_badge"),
        )
    if not (approved_by_badge or approved_by_key):
        return DeleteUserResult(success=False, error=_error(conn, "not_admin"))

    if not confirmed:
        return DeleteUserResult(success=False, error=_error(conn, "cancelled"))

    with conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = ?", (target["id"],))
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("INSERT OR IGNORE INTO deleted_users (badge_uid) VALUES (?)", (norm_target,))

    return DeleteUserResult(success=True)


def modify_user(
    conn: sqlite3.Connection,
    target_badge_uid: str,
    approving_uid: str | None,
    new_name: str | None = None,
    new_grade: int | str | None = None,
    new_section: str | None = None,
    new_taught_grade: int | str | None = None,
    new_guardians: list[GuardianData] | None = None,
    new_badge_uid: str | None = None,
    new_family_id: str | None = None,
) -> ModifyUserResult:
    """Modify user fields or replace badge UID with admin approval."""
    norm_target = database.normalize_badge_uid(target_badge_uid)
    if not norm_target:
        return ModifyUserResult(success=False, error=_error(conn, "invalid_uid"))

    target = database.get_user_by_badge_uid(conn, norm_target)
    if not target:
        return ModifyUserResult(success=False, error=_error(conn, "badge_not_found"))

    if not approving_uid:
        return ModifyUserResult(success=False, error=_error(conn, "not_admin"))

    approved_by_badge = _is_active_admin_badge(conn, database.normalize_badge_uid(approving_uid))
    if not approved_by_badge and not _matches_admin_secret_key(conn, approving_uid):
        return ModifyUserResult(success=False, error=_error(conn, "not_admin"))

    updated_uid = norm_target
    if new_badge_uid is not None and new_badge_uid.strip() != "":
        candidate_uid = database.normalize_badge_uid(new_badge_uid)
        if not candidate_uid:
            return ModifyUserResult(success=False, error=_error(conn, "invalid_uid"))
        if candidate_uid != norm_target:
            existing = database.get_user_by_badge_uid(conn, candidate_uid)
            if existing is not None:
                return ModifyUserResult(success=False, error=_error(conn, "badge_exists"))
            updated_uid = candidate_uid

    updated_name = target["full_name"]
    if new_name is not None and new_name.strip() not in ("", updated_name):
        if not _has_a_letter(new_name):
            return ModifyUserResult(success=False, error=_error(conn, "name_letters"))
        updated_name = new_name.strip()

    # Only a Grade or Section that changes must be on the School's lists, so a Student
    # whose Grade or Section the School no longer lists can still be edited.
    school = school_settings.require(conn)
    role = target["role"]
    updated_grade = target.get("grade")
    updated_section = target.get("section")
    clean_guardians: list[GuardianData] | None = None
    updated_taught_grade = target.get("taught_grade")

    if role == "student":
        if new_grade is not None and str(new_grade).strip() not in ("", str(updated_grade)):
            rank = _grade_rank(new_grade, school)
            if rank is None:
                return ModifyUserResult(success=False, error=_error(conn, "grade_range"))
            updated_grade = rank

        typed_section = (new_section or "").strip()
        if typed_section and typed_section.casefold() != str(updated_section or "").casefold():
            school_section = _school_section(typed_section, school)
            if school_section is None:
                return ModifyUserResult(success=False, error=_section_unknown(conn, school))
            updated_section = school_section

        if new_guardians is not None:
            if len(new_guardians) > 2:
                return ModifyUserResult(success=False, error=_error(conn, "too_many_guardians"))
            clean_guardians, guardian_error = _checked_guardians(conn, new_guardians, target.get("guardians"))
            if guardian_error:
                return ModifyUserResult(success=False, error=guardian_error)

    elif role == "teacher":
        if new_taught_grade is not None and str(new_taught_grade).strip() not in ("", str(updated_taught_grade)):
            taught_rank = _grade_rank(new_taught_grade, school)
            if taught_rank is None:
                return ModifyUserResult(
                    success=False,
                    error=_error(conn, "taught_grade_range"),
                )
            updated_taught_grade = taught_rank

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET full_name = ?, badge_uid = ? WHERE id = ?",
            (updated_name, updated_uid, target["id"]),
        )
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("UPDATE users SET is_synced = 0 WHERE id = ?", (target["id"],))
        if role == "student":
            cursor.execute(
                "UPDATE student_details SET grade = ?, section = ?, family_id = COALESCE(?, family_id) WHERE user_id = ?",
                (updated_grade, updated_section, new_family_id, target["id"]),
            )
            if clean_guardians is not None:
                cursor.execute("DELETE FROM guardians WHERE student_id = ?", (target["id"],))
                for pos, gd_item in enumerate(clean_guardians, start=1):
                    cursor.execute(
                        "INSERT INTO guardians (student_id, position, name, phone, email) VALUES (?, ?, ?, ?, ?)",
                        (target["id"], pos, gd_item.name, gd_item.phone, gd_item.email or None),
                    )
        elif role == "teacher":
            cursor.execute(
                "UPDATE teacher_details SET taught_grade = ? WHERE user_id = ?",
                (updated_taught_grade, target["id"]),
            )

    updated_user = database.get_user_by_badge_uid(conn, updated_uid)
    return ModifyUserResult(success=True, user=updated_user)


def get_student_counts_by_grade(conn: sqlite3.Connection) -> dict[int, int]:
    """Return a mapping of grade to count of active students."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sd.grade, COUNT(*)
        FROM student_details sd
        JOIN users u ON u.id = sd.user_id
        WHERE u.role = 'student' AND u.is_active = 1
        GROUP BY sd.grade
        ORDER BY sd.grade ASC
        """
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def preview_grade_promotion(conn: sqlite3.Connection) -> PromotionPreview:
    """How many active Students Grade Promotion would move up, and how many it would graduate."""
    final_grade = school_settings.require(conn).final_grade
    counts = get_student_counts_by_grade(conn)
    graduated = sum(count for rank, count in counts.items() if rank >= final_grade)
    return PromotionPreview(promoted_count=sum(counts.values()) - graduated, graduated_count=graduated)


def promote_grades(
    conn: sqlite3.Connection,
    now: datetime | None = None,
) -> PromoteGradesResult:
    """Move every active Student up one of the School's Grades; Students in the final Grade graduate."""
    now_dt = now or datetime.now()
    grad_date_str = now_dt.strftime("%Y-%m-%d")
    final_grade = school_settings.require(conn).final_grade

    with conn:
        cursor = conn.cursor()

        # 1. Graduate the final Grade first (and anyone left beyond it when the School shortened its list)
        cursor.execute(
            """
            SELECT u.id
            FROM users u
            JOIN student_details sd ON sd.user_id = u.id
            WHERE u.role = 'student' AND u.is_active = 1 AND sd.grade >= ?
            """,
            (final_grade,),
        )
        grad_user_ids = [row[0] for row in cursor.fetchall()]
        graduated_count = len(grad_user_ids)

        if grad_user_ids:
            placeholders = ",".join("?" for _ in grad_user_ids)
            cursor.execute(
                f"""
                UPDATE student_details
                SET graduation_date = ?
                WHERE user_id IN ({placeholders})
                """,
                [grad_date_str] + grad_user_ids,
            )
            cursor.execute(
                f"""
                UPDATE users
                SET is_active = 0, role = 'graduate'
                WHERE id IN ({placeholders})
                """,
                grad_user_ids,
            )

        # 2. Move everyone else up one Grade
        cursor.execute(
            """
            UPDATE student_details
            SET grade = grade + 1
            WHERE grade < ?
              AND user_id IN (
                  SELECT id FROM users WHERE role = 'student' AND is_active = 1
              )
            """,
            (final_grade,),
        )
        promoted_count = cursor.rowcount
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("UPDATE users SET is_synced = 0 WHERE role IN ('student', 'graduate')")

    return PromoteGradesResult(
        success=True,
        promoted_count=promoted_count,
        graduated_count=graduated_count,
    )


def get_statistics(conn: sqlite3.Connection) -> SystemStatistics:
    """Counts of people and Check-ins: active Students and Teachers per Grade rank, Graduates,
    people per Role and the Check-ins of the last 10 dates that have any, oldest first."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance_records WHERE event_type = 'check_in'")
    total_check_ins = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT sd.grade, COUNT(*)
        FROM student_details sd
        JOIN users u ON u.id = sd.user_id
        WHERE u.role = 'student' AND u.is_active = 1
        GROUP BY sd.grade
        ORDER BY sd.grade ASC
        """
    )
    students_by_grade = {int(rank): count for rank, count in cursor.fetchall()}

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM student_details sd
        JOIN users u ON u.id = sd.user_id
        WHERE sd.graduation_date IS NOT NULL OR (u.role = 'student' AND u.is_active = 0)
        """
    )
    graduates = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT td.taught_grade, COUNT(*)
        FROM teacher_details td
        JOIN users u ON u.id = td.user_id
        WHERE u.role = 'teacher' AND u.is_active = 1
        GROUP BY td.taught_grade
        ORDER BY td.taught_grade ASC
        """
    )
    teachers_by_grade = {int(rank): count for rank, count in cursor.fetchall()}

    cursor.execute(
        """
        SELECT date, COUNT(*)
        FROM attendance_records
        WHERE event_type = 'check_in'
        GROUP BY date
        ORDER BY date DESC
        LIMIT 10
        """
    )
    recent_check_ins = [(date.fromisoformat(str(day)), count) for day, count in reversed(cursor.fetchall())]

    cursor.execute("SELECT role, COUNT(*) FROM users GROUP BY role")
    role_counts = {row[0]: row[1] for row in cursor.fetchall()}
    users_by_role = {role: role_counts.get(role, 0) for role in ("student", "teacher", "admin", "visitor")}

    return SystemStatistics(
        total_users=total_users,
        total_check_ins=total_check_ins,
        students_by_grade=students_by_grade,
        graduates=graduates,
        teachers_by_grade=teachers_by_grade,
        recent_check_ins=recent_check_ins,
        users_by_role=users_by_role,
    )


def backup_database(
    conn: sqlite3.Connection,
    backup_dir: Path,
    now: datetime | None = None,
) -> Path:
    """Create a timestamped backup copy of the database using SQLite's backup API."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    now_dt = now or datetime.now()
    timestamp_str = now_dt.strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"quickpass_backup_{timestamp_str}.db"

    dest_conn = sqlite3.connect(backup_file)
    try:
        conn.backup(dest_conn)
    finally:
        dest_conn.close()

    return backup_file


def _wipe_confirmation_word(conn: sqlite3.Connection) -> str:
    """The word an Admin types to confirm a wipe, in the School Language."""
    return i18n.t(school_settings.require(conn).school_language, "admin.wipe.confirm_word")


def wipe_users(
    conn: sqlite3.Connection,
    settings: Settings,
    password_input: str,
    confirmation_input: str,
    now: datetime | None = None,
) -> WipeResult:
    """Wipe every user along with details and guardians, preserving attendance records."""
    if not settings.wipe_password:
        return WipeResult(
            success=False,
            error=_error(conn, "wipe_password_missing"),
        )

    if password_input != settings.wipe_password:
        return WipeResult(
            success=False,
            error=_error(conn, "wrong_password"),
        )

    if confirmation_input.strip().upper() != _wipe_confirmation_word(conn):
        return WipeResult(
            success=False,
            error=_error(conn, "bad_confirmation"),
        )

    backup_dir = settings.database_path.parent / "backups"
    try:
        b_path = backup_database(conn, backup_dir, now=now)
    except Exception as e:
        return WipeResult(
            success=False,
            error=_error(conn, "backup_failed", error=e),
        )

    with conn:
        cursor = conn.cursor()
        if isinstance(conn, sqlite3.Connection):
            cursor.execute("INSERT OR IGNORE INTO deleted_users (badge_uid) SELECT badge_uid FROM users")
        cursor.execute("DELETE FROM users")

    return WipeResult(success=True, backup_path=b_path)


def wipe_history(
    conn: sqlite3.Connection,
    settings: Settings,
    password_input: str,
    confirmation_input: str,
    now: datetime | None = None,
) -> WipeResult:
    """Wipe all attendance records and security incidents, preserving users."""
    if not settings.wipe_password:
        return WipeResult(
            success=False,
            error=_error(conn, "wipe_password_missing"),
        )

    if password_input != settings.wipe_password:
        return WipeResult(
            success=False,
            error=_error(conn, "wrong_password"),
        )

    if confirmation_input.strip().upper() != _wipe_confirmation_word(conn):
        return WipeResult(
            success=False,
            error=_error(conn, "bad_confirmation"),
        )

    backup_dir = settings.database_path.parent / "backups"
    try:
        b_path = backup_database(conn, backup_dir, now=now)
    except Exception as e:
        return WipeResult(
            success=False,
            error=_error(conn, "backup_failed", error=e),
        )

    with conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM attendance_records")
        cursor.execute("DELETE FROM security_incidents")

    return WipeResult(success=True, backup_path=b_path)
