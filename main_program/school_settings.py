"""School Settings: the policies a School sets for itself.

One row in Supabase (`public.school_settings`) is the source of truth, and the
local SQLite database caches it so the entrance keeps working offline. Cloud
Sync keeps both copies in step (`CloudSyncWorker.sync_school_settings`): a
change saved at this station is pushed; otherwise the cloud row is pulled.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SCHOOL_LANGUAGES = ("es", "en")

# Weekdays count from 0 = Monday to 6 = Sunday, as date.weekday() does.
MONDAY_TO_FRIDAY = (0, 1, 2, 3, 4)

DEFAULT_LATE_THRESHOLD = time(6, 50, 0)
DEFAULT_COOLDOWN_SECONDS = 300

SECTION_MAX_LENGTH = 10
ADMIN_SECRET_KEY_MIN_LENGTH = 8

# The filter value that means "every Section" (search.ALL), so no Section may use it as a name.
RESERVED_SECTION_NAME = "ALL"

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 600_000


class SchoolSettingsMissing(Exception):
    """The School has not set up its settings yet."""


class SchoolSettingsError(ValueError):
    """Invalid School Settings. `code` is the catalog key of the message to show; `params` fill it in."""

    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass(frozen=True)
class SchoolSettings:
    school_language: str
    grades: tuple[str, ...]
    sections: tuple[str, ...]
    active_weekdays: tuple[int, ...] = MONDAY_TO_FRIDAY
    holidays: tuple[date, ...] = ()
    late_threshold: time = DEFAULT_LATE_THRESHOLD
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    admin_secret_key_hash: str = ""

    @property
    def final_grade(self) -> int:
        """Rank of the last Grade; Students in it graduate at Grade Promotion."""
        return len(self.grades)

    def grade_label(self, rank: int) -> str:
        """The School's name for the Grade with this 1-based rank."""
        if 1 <= rank <= len(self.grades):
            return self.grades[rank - 1]
        return str(rank)

    def is_school_day(self, day: date) -> bool:
        """A School Day falls on one of the School's active weekdays and is not one of its holidays."""
        # A datetime never equals a date, so compare the calendar day alone.
        day = date(day.year, day.month, day.day)
        return day.weekday() in self.active_weekdays and day not in self.holidays

    def school_days(self, start: date, end: date) -> list[date]:
        """The School Days from `start` to `end`, both included, in order."""
        first = date(start.year, start.month, start.day)
        span = (date(end.year, end.month, end.day) - first).days
        return [day for day in (first + timedelta(days=n) for n in range(span + 1)) if self.is_school_day(day)]


@dataclass(frozen=True)
class CachedSchoolSettings:
    school: SchoolSettings
    updated_at: str
    synced: bool


def validate(school: SchoolSettings) -> None:
    """Raise SchoolSettingsError for the first problem found."""
    if school.school_language not in SCHOOL_LANGUAGES:
        raise SchoolSettingsError("settings.error.language")
    validate_grades(school.grades)
    validate_sections(school.sections)
    validate_weekdays(school.active_weekdays)
    if school.cooldown_seconds < 0:
        raise SchoolSettingsError("settings.error.cooldown")
    if not school.admin_secret_key_hash:
        raise SchoolSettingsError("settings.error.secret_key")


def validate_grades(grades: tuple[str, ...]) -> None:
    if not grades:
        raise SchoolSettingsError("settings.error.grades_empty")
    if any(not grade.strip() for grade in grades):
        raise SchoolSettingsError("settings.error.grade_blank")
    if _has_duplicates(grades):
        raise SchoolSettingsError("settings.error.grade_duplicate")


def validate_sections(sections: tuple[str, ...]) -> None:
    if not sections:
        raise SchoolSettingsError("settings.error.sections_empty")
    if any(not section.strip() for section in sections):
        raise SchoolSettingsError("settings.error.section_blank")
    if _has_duplicates(sections):
        raise SchoolSettingsError("settings.error.section_duplicate")
    if any(section.strip().upper() == RESERVED_SECTION_NAME for section in sections):
        raise SchoolSettingsError("settings.error.section_reserved")
    if any(len(section.strip()) > SECTION_MAX_LENGTH for section in sections):
        raise SchoolSettingsError("settings.error.section_too_long")


def validate_weekdays(active_weekdays: tuple[int, ...]) -> None:
    if not active_weekdays or any(day not in range(7) for day in active_weekdays):
        raise SchoolSettingsError("settings.error.weekdays")


def check_new_secret_key(secret: str, confirmation: str) -> None:
    """Raise SchoolSettingsError unless `secret` can become the Admin Secret Key: it is long
    enough, and `confirmation` repeats it. Surrounding spaces never count, as in verify_secret_key."""
    if len(secret.strip()) < ADMIN_SECRET_KEY_MIN_LENGTH:
        raise SchoolSettingsError("settings.error.secret_key_short", min=ADMIN_SECRET_KEY_MIN_LENGTH)
    if secret.strip() != confirmation.strip():
        raise SchoolSettingsError("settings.error.secret_key_mismatch")


def _has_duplicates(names: tuple[str, ...]) -> bool:
    folded = [name.strip().casefold() for name in names]
    return len(set(folded)) != len(folded)


def _normalized(school: SchoolSettings) -> SchoolSettings:
    return replace(
        school,
        grades=tuple(grade.strip() for grade in school.grades),
        sections=tuple(section.strip() for section in school.sections),
        active_weekdays=tuple(sorted(set(school.active_weekdays))),
        holidays=tuple(sorted(set(school.holidays))),
    )


# --- Local cache -------------------------------------------------------------


def load_cached(conn: Any) -> CachedSchoolSettings | None:
    row = conn.execute("SELECT * FROM school_settings WHERE id = 1").fetchone()
    if row is None:
        return None
    school = SchoolSettings(
        school_language=row["school_language"],
        grades=tuple(json.loads(row["grades"])),
        sections=tuple(json.loads(row["sections"])),
        active_weekdays=tuple(json.loads(row["active_weekdays"])),
        holidays=tuple(date.fromisoformat(day) for day in json.loads(row["holidays"])),
        late_threshold=time.fromisoformat(row["late_threshold"]),
        cooldown_seconds=int(row["cooldown_seconds"]),
        admin_secret_key_hash=row["admin_secret_key_hash"],
    )
    return CachedSchoolSettings(school=school, updated_at=row["updated_at"], synced=bool(row["is_synced"]))


def load(conn: Any) -> SchoolSettings | None:
    """The School Settings cached at this station, or None before the first-run setup."""
    cached = load_cached(conn)
    return cached.school if cached else None


def require(conn: Any) -> SchoolSettings:
    school = load(conn)
    if school is None:
        raise SchoolSettingsMissing("School Settings are not set up yet; finish the first-run setup.")
    return school


def check(conn: Any, school: SchoolSettings, renamed_sections: Mapping[str, str] | None = None) -> SchoolSettings:
    """The settings as `save` would store them; raises SchoolSettingsError when `save` would refuse them."""
    school = _normalized(school)
    validate(school)
    _refuse_dropping_what_people_hold(conn, school, renamed_sections or {})
    return school


def save(
    conn: Any,
    school: SchoolSettings,
    now: datetime | None = None,
    renamed_sections: Mapping[str, str] | None = None,
) -> SchoolSettings:
    """Store a change made at this station. `renamed_sections` maps each renamed Section's old name
    to its new one; its Students move to the new name. Cloud Sync pushes the settings and those Students."""
    renamed = renamed_sections or {}
    school = check(conn, school, renamed)
    updated_at = (now or datetime.now(timezone.utc)).isoformat()
    with conn:
        _write(conn, school, updated_at=updated_at, synced=False)
        _move_students_to_renamed_sections(conn, renamed)
    return school


def _move_students_to_renamed_sections(conn: Any, renamed: Mapping[str, str]) -> None:
    new_names = {old.strip().casefold(): new.strip() for old, new in renamed.items()}
    if not new_names:
        return
    moves = [
        (new_names[folded], row["user_id"])
        for row in conn.execute("SELECT user_id, section FROM student_details")
        if (folded := str(row["section"] or "").strip().casefold()) in new_names
    ]
    conn.executemany("UPDATE student_details SET section = ? WHERE user_id = ?", moves)
    conn.executemany("UPDATE users SET is_synced = 0 WHERE id = ?", [(user_id,) for _, user_id in moves])


def _refuse_dropping_what_people_hold(conn: Any, school: SchoolSettings, renamed: Mapping[str, str]) -> None:
    """Raise SchoolSettingsError when the change drops a Grade or Section that active Students or
    Teachers still hold. Ranks beyond the old list, Sections it already lacked, and renamed Sections,
    whose Students move to the new name, are not dropped here."""
    current = load(conn)
    if current is None:
        return

    if school.final_grade < current.final_grade:
        held = conn.execute(
            """
            SELECT grade, COUNT(*) AS people FROM (
                SELECT sd.grade AS grade
                FROM student_details sd JOIN users u ON u.id = sd.user_id
                WHERE u.role = 'student' AND u.is_active = 1
                UNION ALL
                SELECT td.taught_grade AS grade
                FROM teacher_details td JOIN users u ON u.id = td.user_id
                WHERE u.role = 'teacher' AND u.is_active = 1
            )
            WHERE grade > ? AND grade <= ?
            GROUP BY grade
            ORDER BY grade
            """,
            (school.final_grade, current.final_grade),
        ).fetchone()
        if held is not None:
            raise SchoolSettingsError(
                "settings.error.grade_in_use", grade=current.grade_label(held["grade"]), count=held["people"]
            )

    kept = {section.casefold() for section in school.sections}
    kept |= {old.strip().casefold() for old, new in renamed.items() if new.strip().casefold() in kept}
    dropped = [section for section in current.sections if section.casefold() not in kept]
    if dropped:
        people_by_section: dict[str, int] = {}
        for row in conn.execute(
            """
            SELECT sd.section AS section
            FROM student_details sd JOIN users u ON u.id = sd.user_id
            WHERE u.role = 'student' AND u.is_active = 1
            """
        ):
            folded = str(row["section"] or "").casefold()
            people_by_section[folded] = people_by_section.get(folded, 0) + 1
        for section in dropped:
            count = people_by_section.get(section.casefold(), 0)
            if count:
                raise SchoolSettingsError("settings.error.section_in_use", section=section, count=count)


def store_synced(conn: Any, school: SchoolSettings, updated_at: str) -> SchoolSettings:
    """Store settings that already match the cloud copy."""
    school = _normalized(school)
    validate(school)
    with conn:
        _write(conn, school, updated_at=updated_at, synced=True)
    return school


def mark_synced(conn: Any, updated_at: str) -> None:
    """Mark the cached row as pushed, unless it changed again since `updated_at`."""
    with conn:
        conn.execute(
            "UPDATE school_settings SET is_synced = 1 WHERE id = 1 AND updated_at = ?",
            (updated_at,),
        )


def _write(conn: Any, school: SchoolSettings, updated_at: str, synced: bool) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO school_settings (
            id, school_language, grades, sections, active_weekdays, holidays,
            late_threshold, cooldown_seconds, admin_secret_key_hash, updated_at, is_synced
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            school.school_language,
            json.dumps(list(school.grades), ensure_ascii=False),
            json.dumps(list(school.sections), ensure_ascii=False),
            json.dumps(list(school.active_weekdays)),
            json.dumps([day.isoformat() for day in school.holidays]),
            school.late_threshold.isoformat(),
            school.cooldown_seconds,
            school.admin_secret_key_hash,
            updated_at,
            1 if synced else 0,
        ),
    )


# --- Cloud row ---------------------------------------------------------------


def to_cloud_row(school: SchoolSettings, updated_at: str) -> dict[str, Any]:
    return {
        "id": 1,
        "school_language": school.school_language,
        "grades": list(school.grades),
        "sections": list(school.sections),
        "active_weekdays": list(school.active_weekdays),
        "holidays": [day.isoformat() for day in school.holidays],
        "late_threshold": school.late_threshold.isoformat(),
        "cooldown_seconds": school.cooldown_seconds,
        "admin_secret_key_hash": school.admin_secret_key_hash,
        "updated_at": updated_at,
    }


def from_cloud_row(row: dict[str, Any]) -> SchoolSettings:
    return _normalized(
        SchoolSettings(
            school_language=str(row["school_language"]),
            grades=tuple(str(grade) for grade in row["grades"]),
            sections=tuple(str(section) for section in row["sections"]),
            active_weekdays=tuple(int(day) for day in row["active_weekdays"]),
            holidays=tuple(date.fromisoformat(str(day)) for day in row["holidays"]),
            late_threshold=time.fromisoformat(str(row["late_threshold"])),
            cooldown_seconds=int(row["cooldown_seconds"]),
            admin_secret_key_hash=str(row["admin_secret_key_hash"]),
        )
    )


# --- Admin Secret Key --------------------------------------------------------


def hash_secret_key(secret: str, *, iterations: int = _HASH_ITERATIONS) -> str:
    """A salted PBKDF2 hash of the Admin Secret Key; the key itself is never stored."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.strip().encode("utf-8"), salt, iterations)
    return f"{_HASH_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_secret_key(secret: str, stored_hash: str) -> bool:
    candidate = secret.strip()
    if not candidate:
        return False
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        salt_bytes = _b64decode(salt)
        expected_bytes = _b64decode(expected)
        rounds = int(iterations)
    except (ValueError, binascii.Error):
        return False
    if algorithm != _HASH_ALGORITHM or rounds < 1:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), salt_bytes, rounds)
    return hmac.compare_digest(digest, expected_bytes)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
