"""Access control: decides what a scan means and records it.

The core functions take the database connection, the settings, the line received
from Arduino and the time; they return a ScanResult whose reply line shows the
outcome on the LCD in the School Language.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

import arduino
import database
import i18n
import school_settings
import sms
from config import Settings
from school_settings import SchoolSettings


IGNORE_SAME_BADGE_SECONDS = 5.0


@dataclass
class ScanResult:
    is_scan: bool
    event_type: str = ""  # check_in, check_out, repeat_scan, unregistered, graduate_denied, inactive_denied
    user: dict[str, Any] | None = None
    status: str | None = None  # on_time, late, visit
    reply_line: str = ""
    texts_to_send: list[tuple[str, str]] = field(default_factory=list)


class ScanDebouncer:
    """Drops a Badge read again less than IGNORE_SAME_BADGE_SECONDS after it was let through,
    so a Badge held against the reader counts as one scan."""

    def __init__(self) -> None:
        self._let_through_at: dict[str, float] = {}

    def let_through(self, badge_uid: str, at: float) -> bool:
        """`at` is a time in seconds from a clock that never goes back, such as time.monotonic()."""
        last = self._let_through_at.get(badge_uid)
        if last is not None and at - last < IGNORE_SAME_BADGE_SECONDS:
            return False
        self._let_through_at[badge_uid] = at
        return True


def parse_name_parts(full_name: str) -> tuple[str, str, str]:
    parts = full_name.strip().split()
    if not parts:
        return ("", "", "")
    first_name = parts[0]
    if len(parts) == 1:
        last_name = ""
    elif len(parts) == 2:
        last_name = parts[1]
    else:
        # Hispanic naming: [first name, middle name, first surname, second surname]
        last_name = parts[2]
    short_name = f"{first_name} {last_name}".strip()
    return (first_name, last_name, short_name)


def _greeting(lang: str, key: str, first_name: str, too_long: str) -> str:
    """The greeting with the first name, or `too_long` when both do not fit on one LCD line."""
    first = arduino.lcd_text(first_name)
    greeting = i18n.t(lang, key, name=first)
    if first and len(greeting) <= arduino.LCD_WIDTH:
        return greeting
    return too_long or greeting.strip()


def check_in_screen(lang: str, full_name: str, status: str) -> str:
    first_name, _, _ = parse_name_parts(full_name)
    line1 = _greeting(lang, "lcd.check_in.welcome", first_name, too_long=arduino.lcd_text(first_name))
    return arduino.command(arduino.GRANT, line1, i18n.t(lang, f"lcd.check_in.{status}"))


def check_out_screen(lang: str, full_name: str) -> str:
    first_name, _, _ = parse_name_parts(full_name)
    line1 = _greeting(lang, "lcd.check_out.goodbye", first_name, too_long=i18n.t(lang, "lcd.check_out.goodbye_anonymous"))
    return arduino.command(arduino.GRANT, line1, i18n.t(lang, "lcd.check_out.done"))


def repeat_scan_screen(lang: str, full_name: str) -> str:
    _, _, short_name = parse_name_parts(full_name)
    return arduino.command(arduino.GRANT, short_name, i18n.t(lang, "lcd.repeat_scan.granted"))


def visitor_screen(lang: str, full_name: str, shown_id: str, event_type: str) -> str:
    """`shown_id` is the Badge UID at the Door Gate, or the ID document when signing a visitor in."""
    first_name, _, _ = parse_name_parts(full_name)
    return arduino.command(
        arduino.GRANT,
        i18n.t(lang, f"lcd.visitor.{event_type}", name=arduino.lcd_text(first_name)),
        i18n.t(lang, "lcd.visitor.badge", id=shown_id),
    )


def deny_screen(lang: str, reason: str) -> str:
    """`reason` is unregistered, graduate or inactive."""
    return arduino.command(arduino.DENY, i18n.t(lang, "lcd.deny.header"), i18n.t(lang, f"lcd.deny.{reason}"))


def process_scan_line(
    conn: sqlite3.Connection,
    settings: Settings,
    line: str,
    now: datetime | None = None,
) -> ScanResult:
    """Process one line from the Arduino (or typed UID in Demo Mode)."""
    badge_uid = arduino.parse_scan(line)
    if badge_uid is None:
        return ScanResult(is_scan=False)

    school = school_settings.require(conn)
    lang = school.school_language
    now = now or datetime.now()
    # Demo Mode sends texts only when Twilio is switched on.
    texts_allowed = not settings.demo_mode or settings.twilio_enabled

    user = database.get_user_by_badge_uid(conn, badge_uid)
    if user is None:
        return _unregistered(conn, settings, lang, badge_uid, now, texts_allowed)

    if user.get("graduation_date") or user.get("role") == "graduate" or (user.get("role") == "student" and not user.get("is_active")):
        return ScanResult(is_scan=True, event_type="graduate_denied", user=user, reply_line=deny_screen(lang, "graduate"))

    if not user.get("is_active"):
        return ScanResult(is_scan=True, event_type="inactive_denied", user=user, reply_line=deny_screen(lang, "inactive"))

    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type, time FROM attendance_records WHERE user_id = ? AND date = ? ORDER BY id ASC",
        (user["id"], now.strftime("%Y-%m-%d")),
    )
    today_records = cursor.fetchall()

    if settings.demo_mode:
        # In Demo Mode, scans alternate between Check-in and Check-out
        # based on the latest record that day, with no waiting gap and no daily limit.
        latest_event = today_records[-1]["event_type"] if today_records else None
        if latest_event != "check_in":
            return _check_in(conn, school, user, badge_uid, now, texts_allowed)
        return _check_out(conn, lang, user, badge_uid, now, texts_allowed)

    check_in = next((r for r in today_records if r["event_type"] == "check_in"), None)
    has_check_out = any(r["event_type"] == "check_out" for r in today_records)

    if check_in is None:
        return _check_in(conn, school, user, badge_uid, now, texts_allowed)

    if not has_check_out:
        # Check-out needs the School's cooldown to have passed since Check-in
        check_in_dt = datetime.combine(now.date(), time.fromisoformat(check_in["time"]))
        if (now - check_in_dt).total_seconds() >= school.cooldown_seconds:
            return _check_out(conn, lang, user, badge_uid, now, texts_allowed)

    # Inside cooldown gap or after check-out -> Repeat Scan
    return ScanResult(
        is_scan=True,
        event_type="repeat_scan",
        user=user,
        reply_line=repeat_scan_screen(lang, user["full_name"]),
    )


def sign_in_visitor(
    conn: sqlite3.Connection,
    full_name: str,
    id_document: str,
    visitor: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ScanResult:
    """Check in a walk-in Visitor signed in at the station; the LCD shows their ID document.
    `visitor` holds the temporary Badge lent to them (see admin.assign_visitor_badge),
    or is None when they go in without one."""
    lang = school_settings.require(conn).school_language
    now = now or datetime.now()
    record = {**(visitor or {"id": None, "role": "visitor"}), "full_name": full_name.strip()}
    _record(conn, "check_in", "visit", record, (visitor or {}).get("badge_uid", ""), now)
    return ScanResult(
        is_scan=True,
        event_type="check_in",
        user=visitor,
        status="visit",
        reply_line=visitor_screen(lang, record["full_name"], id_document.strip(), "check_in"),
    )


def _unregistered(
    conn: sqlite3.Connection,
    settings: Settings,
    lang: str,
    badge_uid: str,
    now: datetime,
    texts_allowed: bool,
) -> ScanResult:
    date_str = now.strftime("%Y-%m-%d")
    with conn:
        conn.execute(
            "INSERT INTO security_incidents (badge_uid, date, time) VALUES (?, ?, ?)",
            (badge_uid, date_str, now.strftime("%H:%M:%S")),
        )
    texts_to_send: list[tuple[str, str]] = []
    if texts_allowed and settings.admin_alert_phone:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM security_incidents WHERE badge_uid = ? AND date = ?",
            (badge_uid, date_str),
        )
        if cursor.fetchone()[0] == 1:
            texts_to_send.append((settings.admin_alert_phone, sms.admin_alert_text(lang, now)))

    return ScanResult(
        is_scan=True,
        event_type="unregistered",
        reply_line=deny_screen(lang, "unregistered"),
        texts_to_send=texts_to_send,
    )


def _record(
    conn: sqlite3.Connection,
    event_type: str,
    status: str | None,
    user: dict[str, Any],
    badge_uid: str,
    now: datetime,
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO attendance_records (event_type, date, time, status, badge_uid, user_id, name, role, grade, section)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                status,
                badge_uid,
                user["id"],
                user["full_name"],
                user["role"],
                user.get("grade") or user.get("taught_grade"),
                user.get("section") or "",
            ),
        )


def _guardian_phones(user: dict[str, Any]) -> list[str]:
    if user.get("role") != "student":
        return []
    return [phone for g in user.get("guardians", []) if (phone := g.get("phone", "").strip())]


def _check_in(
    conn: sqlite3.Connection,
    school: SchoolSettings,
    user: dict[str, Any],
    badge_uid: str,
    now: datetime,
    texts_allowed: bool,
) -> ScanResult:
    lang = school.school_language
    if user.get("role") == "visitor":
        status = "visit"
        reply_line = visitor_screen(lang, user["full_name"], badge_uid, "check_in")
    else:
        status = "on_time" if now.time() <= school.late_threshold else "late"
        reply_line = check_in_screen(lang, user["full_name"], status)

    _record(conn, "check_in", status, user, badge_uid, now)

    texts_to_send = []
    if texts_allowed:
        text = sms.arrival_text(lang, user["full_name"], now, on_time=status == "on_time")
        texts_to_send = [(phone, text) for phone in _guardian_phones(user)]

    return ScanResult(
        is_scan=True,
        event_type="check_in",
        user=user,
        status=status,
        reply_line=reply_line,
        texts_to_send=texts_to_send,
    )


def _check_out(
    conn: sqlite3.Connection,
    lang: str,
    user: dict[str, Any],
    badge_uid: str,
    now: datetime,
    texts_allowed: bool,
) -> ScanResult:
    _record(conn, "check_out", None, user, badge_uid, now)

    texts_to_send = []
    if texts_allowed:
        text = sms.leaving_text(lang, user["full_name"], now)
        texts_to_send = [(phone, text) for phone in _guardian_phones(user)]

    if user.get("role") == "visitor":
        reply_line = visitor_screen(lang, user["full_name"], badge_uid, "check_out")
    else:
        reply_line = check_out_screen(lang, user["full_name"])
    return ScanResult(
        is_scan=True,
        event_type="check_out",
        user=user,
        reply_line=reply_line,
        texts_to_send=texts_to_send,
    )
