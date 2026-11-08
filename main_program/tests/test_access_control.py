from dataclasses import replace
from datetime import datetime, time, timedelta

import pytest
from conftest import gate_screen, store_school

from access_control import ScanDebouncer, process_scan_line, sign_in_visitor
from admin import add_user, assign_visitor_badge


def test_ignore_boot_and_diagnostic_lines(conn, settings, now):
    for line in [
        "QUICKPASS_READY",
        "LCD_OK:0x27",
        "INIT_SPI...",
        "RFID_VERSION: 0x92",
        "RFID_OK",
        "RFID_NOT_DETECTED (check 3.3V, GND, D9, D10, D11, D12, D13)",
        "BOOTING",
        "",
        "RANDOM TEXT",
        "SCAN:99887766",
    ]:
        result = process_scan_line(conn, settings, line, now=now)
        assert result.is_scan is False
        assert result.reply_line == ""


def test_unknown_badge_records_security_incident_and_denies(conn, settings, now):
    result = process_scan_line(conn, settings, "SCAN 99887766", now=now)

    assert result.is_scan is True
    assert result.event_type == "unregistered"
    assert gate_screen(result.reply_line) == ("DENY", "Acceso Denegado", "No Registrado")

    cursor = conn.cursor()
    cursor.execute("SELECT badge_uid, date, time FROM security_incidents WHERE badge_uid = '99887766'")
    rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["date"] == now.strftime("%Y-%m-%d")


def test_unknown_badge_recorded_on_every_scan(conn, settings, now):
    process_scan_line(conn, settings, "SCAN 99887766", now=now)
    process_scan_line(conn, settings, "SCAN 99887766", now=now)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM security_incidents WHERE badge_uid = '99887766'")
    assert cursor.fetchone()[0] == 2


def test_check_in_punctuality_thresholds(conn, settings):
    # Late threshold is 06:50:00
    add_user(conn, settings, "AA11", "est", "Carlos Santana", grade=10, section="A")
    add_user(conn, settings, "BB22", "est", "Ana Gomez", grade=10, section="A")
    add_user(conn, settings, "CC33", "est", "Pedro Perez", grade=10, section="A")

    # 1. Before threshold: 06:49:59 -> On Time
    t_before = datetime(2026, 10, 5, 6, 49, 59)
    res_before = process_scan_line(conn, settings, "SCAN AA11", now=t_before)
    assert res_before.event_type == "check_in"
    assert res_before.status == "on_time"
    assert "Puntual" in res_before.reply_line

    # 2. Exactly at threshold: 06:50:00 -> On Time
    t_exact = datetime(2026, 10, 5, 6, 50, 0)
    res_exact = process_scan_line(conn, settings, "SCAN BB22", now=t_exact)
    assert res_exact.event_type == "check_in"
    assert res_exact.status == "on_time"
    assert "Puntual" in res_exact.reply_line

    # 3. After threshold: 06:50:01 -> Late
    t_after = datetime(2026, 10, 5, 6, 50, 1)
    res_after = process_scan_line(conn, settings, "SCAN CC33", now=t_after)
    assert res_after.event_type == "check_in"
    assert res_after.status == "late"
    assert "Tarde" in res_after.reply_line


def test_late_threshold_is_the_one_in_school_settings(conn, settings, school):
    store_school(conn, replace(school, late_threshold=time(7, 30, 0)))
    add_user(conn, settings, "AA11", "est", "Carlos Santana", grade=10, section="A")
    add_user(conn, settings, "BB22", "est", "Ana Gomez", grade=10, section="A")

    on_time = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 7, 30, 0))
    late = process_scan_line(conn, settings, "SCAN BB22", now=datetime(2026, 10, 5, 7, 30, 1))

    assert on_time.status == "on_time"
    assert late.status == "late"


def test_check_out_waits_for_the_cooldown_in_school_settings(conn, settings, school):
    store_school(conn, replace(school, cooldown_seconds=60))
    add_user(conn, settings, "AA11", "est", "Carlos Santana", grade=10, section="A")

    process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 7, 0, 0))
    too_soon = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 7, 0, 59))
    after = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 7, 1, 0))

    assert too_soon.event_type == "repeat_scan"
    assert after.event_type == "check_out"


def test_teacher_check_in(conn, settings, now):
    add_user(conn, settings, "EE55", "prof", "Profesor Rivera", taught_grade=4, now=now)

    res = process_scan_line(conn, settings, "SCAN EE55", now=now)
    assert res.event_type == "check_in"
    assert res.user["role"] == "teacher"
    assert res.status == "late"  # now is 07:00:00


def test_repeat_scan_same_day(conn, settings, now):
    add_user(conn, settings, "AA11", "est", "Carlos Santana", grade=10, section="A", now=now)

    # First scan -> check_in
    res1 = process_scan_line(conn, settings, "SCAN AA11", now=now)
    assert res1.event_type == "check_in"

    # Second scan -> repeat_scan
    res2 = process_scan_line(conn, settings, "SCAN AA11", now=now)
    assert res2.event_type == "repeat_scan"
    assert gate_screen(res2.reply_line) == ("GRANT", "Carlos Santana", "Acceso permitido")

    # Verify no second record was created
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM attendance_records WHERE badge_uid = 'AA11'")
    assert cursor.fetchone()[0] == 1


def test_reply_line_accents_separator_and_length(conn, settings, now):
    # Name with accents, ñ, the line separator, and a long surname
    add_user(
        conn,
        settings,
        "FF66",
        "est",
        "José|Ñandú Rodríguez-Hernández Extra",
        grade=11,
        section="B",
        now=now,
    )

    res = process_scan_line(conn, settings, "SCAN FF66", now=now)
    assert res.event_type == "check_in"
    # Protocol: GRANT <line1>|<line2>
    name, _, lines = res.reply_line.partition(" ")
    assert name == "GRANT"
    line1, line2 = lines.split("|")

    # Max 16 chars per line
    assert len(line1) <= 16
    assert len(line2) <= 16

    # Plain ASCII only
    assert line1.isascii()
    assert line2.isascii()


def test_cooldown_gap_and_check_out(conn, settings):
    # Cooldown is 300 seconds (5 minutes)
    add_user(conn, settings, "AA11", "est", "Ana Gomez", grade=10, section="A")

    t_in = datetime(2026, 10, 5, 7, 0, 0)
    res_in = process_scan_line(conn, settings, "SCAN AA11", now=t_in)
    assert res_in.event_type == "check_in"

    # 1. 299 seconds later -> repeat scan (just before gap)
    from datetime import timedelta

    t_before_gap = t_in + timedelta(seconds=299)
    res_gap = process_scan_line(conn, settings, "SCAN AA11", now=t_before_gap)
    assert res_gap.event_type == "repeat_scan"

    # 2. Exactly 300 seconds later -> check_out
    t_exact_gap = t_in + timedelta(seconds=300)
    res_out = process_scan_line(conn, settings, "SCAN AA11", now=t_exact_gap)
    assert res_out.event_type == "check_out"
    assert res_out.status is None
    assert "Hasta luego" in res_out.reply_line

    # 3. Repeat scan after check_out
    t_after_out = t_in + timedelta(seconds=500)
    res_after = process_scan_line(conn, settings, "SCAN AA11", now=t_after_out)
    assert res_after.event_type == "repeat_scan"

    # 4. New day starts with check_in again
    t_next_day = datetime(2026, 10, 6, 6, 45, 0)
    res_next = process_scan_line(conn, settings, "SCAN AA11", now=t_next_day)
    assert res_next.event_type == "check_in"
    assert res_next.status == "on_time"


def test_demo_mode_alternating_scans(conn, settings):
    from dataclasses import replace
    from datetime import timedelta

    demo_settings = replace(settings, demo_mode=True)

    add_user(conn, demo_settings, "DD44", "est", "Carlos Santana", grade=10, section="A")

    base_time = datetime(2026, 10, 5, 6, 45, 0)

    # Scan 1: Check-in (no waiting)
    res1 = process_scan_line(conn, demo_settings, "SCAN DD44", now=base_time)
    assert res1.event_type == "check_in"
    assert res1.status == "on_time"

    # Scan 2: Check-out immediately (5 seconds later)
    res2 = process_scan_line(conn, demo_settings, "SCAN DD44", now=base_time + timedelta(seconds=5))
    assert res2.event_type == "check_out"
    assert "Hasta luego" in res2.reply_line

    # Scan 3: Check-in again immediately (10 seconds later, now late)
    late_time = datetime(2026, 10, 5, 7, 0, 0)
    res3 = process_scan_line(conn, demo_settings, "SCAN DD44", now=late_time)
    assert res3.event_type == "check_in"
    assert res3.status == "late"

    # Scan 4: Check-out again immediately
    res4 = process_scan_line(conn, demo_settings, "SCAN DD44", now=late_time + timedelta(seconds=5))
    assert res4.event_type == "check_out"


SCREENS_BY_LANGUAGE = {
    "es": {
        "check_in_on_time": ("GRANT", "Bienvenido Ana", "Entrada Puntual"),
        "check_in_late": ("GRANT", "Bienvenido Eva", "Entrada Tarde"),
        "repeat_scan": ("GRANT", "Ana Santana", "Acceso permitido"),
        "check_out": ("GRANT", "Hasta luego Ana", "Salida Exitosa"),
        "visitor_in": ("GRANT", "Visita: Pedro", "ID: 7E571701"),
        "visitor_out": ("GRANT", "Salida: Pedro", "ID: 7E571701"),
        "unregistered": ("DENY", "Acceso Denegado", "No Registrado"),
        "graduate": ("DENY", "Acceso Denegado", "Graduado"),
        "inactive": ("DENY", "Acceso Denegado", "Inactivo"),
    },
    "en": {
        "check_in_on_time": ("GRANT", "Welcome Ana", "Arrived on time"),
        "check_in_late": ("GRANT", "Welcome Eva", "Arrived late"),
        "repeat_scan": ("GRANT", "Ana Santana", "Access granted"),
        "check_out": ("GRANT", "Goodbye Ana", "Checked out"),
        "visitor_in": ("GRANT", "Visitor: Pedro", "ID: 7E571701"),
        "visitor_out": ("GRANT", "Leaving: Pedro", "ID: 7E571701"),
        "unregistered": ("DENY", "Access Denied", "Not Registered"),
        "graduate": ("DENY", "Access Denied", "Graduated"),
        "inactive": ("DENY", "Access Denied", "Inactive"),
    },
}


@pytest.mark.parametrize("lang", ["es", "en"])
def test_gate_screens_follow_the_school_language(conn, settings, school, lang):
    store_school(conn, replace(school, school_language=lang))
    expected = SCREENS_BY_LANGUAGE[lang]
    add_user(conn, settings, "AA11", "est", "Ana Santana", grade=10, section="A")
    add_user(conn, settings, "BB22", "est", "Eva Rivas", grade=10, section="A")
    add_user(conn, settings, "7E571701", "visitor", "Pedro Mena")
    add_user(conn, settings, "CC33", "admin", "Carlos Duarte")
    conn.execute("UPDATE users SET is_active = 0 WHERE badge_uid = 'CC33'")
    day = datetime(2026, 10, 5)

    def scan(uid: str, at: time) -> tuple[str, str, str]:
        return gate_screen(process_scan_line(conn, settings, f"SCAN {uid}", now=datetime.combine(day, at)).reply_line)

    assert scan("AA11", time(6, 45)) == expected["check_in_on_time"]
    assert scan("BB22", time(7, 5)) == expected["check_in_late"]
    assert scan("AA11", time(6, 46)) == expected["repeat_scan"]
    assert scan("AA11", time(13, 0)) == expected["check_out"]
    assert scan("7E571701", time(9, 0)) == expected["visitor_in"]
    assert scan("7E571701", time(10, 0)) == expected["visitor_out"]
    assert scan("99887766", time(9, 30)) == expected["unregistered"]
    assert scan("CC33", time(9, 30)) == expected["inactive"]

    conn.execute("UPDATE users SET role = 'graduate' WHERE badge_uid = 'BB22'")
    assert scan("BB22", time(9, 30)) == expected["graduate"]


def test_switching_the_school_language_changes_the_next_screen(conn, settings, school):
    add_user(conn, settings, "AA11", "est", "Carlos Santana", grade=10, section="A")
    add_user(conn, settings, "BB22", "est", "Ana Rivas", grade=10, section="A")

    spanish = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 6, 45))
    store_school(conn, replace(school, school_language="en"))
    english = process_scan_line(conn, settings, "SCAN BB22", now=datetime(2026, 10, 5, 6, 46))

    assert gate_screen(spanish.reply_line)[1] == "Carlos"
    assert gate_screen(english.reply_line)[1] == "Welcome Ana"


def test_greetings_too_long_for_the_display_drop_the_greeting_or_the_name(conn, settings):
    add_user(conn, settings, "AA11", "est", "Maximiliano Santana", grade=10, section="A")

    check_in = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 6, 45))
    check_out = process_scan_line(conn, settings, "SCAN AA11", now=datetime(2026, 10, 5, 13, 0))

    assert gate_screen(check_in.reply_line) == ("GRANT", "Maximiliano", "Entrada Puntual")
    assert gate_screen(check_out.reply_line) == ("GRANT", "Hasta luego!", "Salida Exitosa")


VISIT_ROW = "SELECT event_type, status, badge_uid, user_id, name, role, grade, section FROM attendance_records"


def test_a_walk_in_visitor_with_a_temporary_badge_checks_in_and_the_gate_shows_their_id(conn, settings, now):
    visitor = assign_visitor_badge(conn, settings, "7E571701", "Carlos Ramírez", now=now).user

    result = sign_in_visitor(conn, "Carlos Ramírez", "A1234567", visitor, now=now)
    leaving = process_scan_line(conn, settings, "SCAN 7E571701", now=now + timedelta(hours=1))

    assert (result.event_type, result.status, result.texts_to_send) == ("check_in", "visit", [])
    assert gate_screen(result.reply_line) == ("GRANT", "Visita: Carlos", "ID: A1234567")
    assert tuple(conn.execute(VISIT_ROW).fetchone()) == (
        "check_in",
        "visit",
        "7E571701",
        visitor["id"],
        "Carlos Ramírez",
        "visitor",
        None,
        "",
    )
    assert (leaving.event_type, gate_screen(leaving.reply_line)) == (
        "check_out",
        ("GRANT", "Salida: Carlos", "ID: 7E571701"),
    )


def test_a_walk_in_visitor_without_a_badge_is_recorded_under_their_name_alone(conn, settings, now):
    result = sign_in_visitor(conn, "Carlos Ramírez", "A1234567", None, now=now)

    assert (result.event_type, result.status) == ("check_in", "visit")
    assert gate_screen(result.reply_line) == ("GRANT", "Visita: Carlos", "ID: A1234567")
    assert tuple(conn.execute(VISIT_ROW).fetchone()) == (
        "check_in",
        "visit",
        "",
        None,
        "Carlos Ramírez",
        "visitor",
        None,
        "",
    )
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_the_same_badge_read_again_within_5_seconds_of_a_scan_is_ignored():
    debouncer = ScanDebouncer()

    assert [
        debouncer.let_through("AA01", at=0.5),
        debouncer.let_through("AA01", at=5.4),
        debouncer.let_through("BB02", at=5.4),
        debouncer.let_through("AA01", at=5.5),
        debouncer.let_through("AA01", at=10.4),
    ] == [True, False, True, True, False]
