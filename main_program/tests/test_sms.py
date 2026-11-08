from dataclasses import replace
from datetime import datetime, timedelta

from conftest import store_school

from access_control import process_scan_line
from admin import GuardianData, add_user
from sms import (
    admin_alert_text,
    arrival_text,
    format_global_phone,
    leaving_text,
    normalize_phone_e164,
    parse_global_phone,
    send_sms_worker,
)


def test_spanish_texts_use_day_month_year_and_24_hour_times():
    at = datetime(2026, 10, 5, 6, 45, 0)

    assert arrival_text("es", "Carlos", at, on_time=True) == (
        "Carlos ingresó al colegio hoy 05/10/2026 a las 06:45:00 (Puntual)."
    )
    assert arrival_text("es", "Carlos", at, on_time=False).endswith("(Tarde).")
    assert leaving_text("es", "Carlos", datetime(2026, 10, 5, 12, 30, 0)) == (
        "Carlos salió del colegio hoy 05/10/2026 a las 12:30:00."
    )
    assert admin_alert_text("es", at) == (
        "Una persona no identificada ha tratado de entrar al colegio, el día de 05/10/2026 a las 06:45:00."
    )


def test_english_texts_use_month_day_year_and_12_hour_times():
    at = datetime(2026, 10, 5, 6, 45, 0)

    assert arrival_text("en", "Carlos", at, on_time=True) == (
        "Carlos entered the school today 10/05/2026 at 06:45:00 AM (On Time)."
    )
    assert arrival_text("en", "Carlos", at, on_time=False).endswith("(Late).")
    assert leaving_text("en", "Carlos", datetime(2026, 10, 5, 12, 30, 0)) == (
        "Carlos left the school today 10/05/2026 at 12:30:00 PM."
    )
    assert admin_alert_text("en", at) == (
        "An unidentified person attempted to enter the school on 10/05/2026 at 06:45:00 AM."
    )


def test_guardian_texts_follow_the_school_language(conn, settings, school):
    store_school(conn, replace(school, school_language="en"))
    add_user(
        conn,
        settings,
        "ST01",
        "est",
        "Laura Diaz",
        grade=9,
        section="B",
        guardians=[GuardianData(name="Mama", phone="+18095559999")],
    )

    res_in = process_scan_line(conn, settings, "SCAN ST01", now=datetime(2026, 10, 5, 7, 5, 0))
    res_out = process_scan_line(conn, settings, "SCAN ST01", now=datetime(2026, 10, 5, 13, 0, 0))

    assert res_in.texts_to_send == [
        ("+1 8095559999", "Laura Diaz entered the school today 10/05/2026 at 07:05:00 AM (Late).")
    ]
    assert res_out.texts_to_send == [
        ("+1 8095559999", "Laura Diaz left the school today 10/05/2026 at 01:00:00 PM.")
    ]


def test_admin_alert_follows_the_school_language(conn, settings, school):
    store_school(conn, replace(school, school_language="en"))

    res = process_scan_line(conn, settings, "SCAN 99887766", now=datetime(2026, 10, 5, 9, 15, 0))

    assert res.texts_to_send == [
        ("+15550000000", "An unidentified person attempted to enter the school on 10/05/2026 at 09:15:00 AM.")
    ]


def test_global_phone_parsing_and_formatting():
    # Split with space
    assert parse_global_phone("+505 88880000") == ("+505", "88880000")
    assert format_global_phone("+505 88880000") == "+505 88880000"

    assert parse_global_phone("+1 8095551234") == ("+1", "8095551234")
    assert format_global_phone("+1 8095551234") == "+1 8095551234"

    assert parse_global_phone("+34 612345678") == ("+34", "612345678")
    assert format_global_phone("+34 612345678") == "+34 612345678"

    assert parse_global_phone("+505 8888-8888") == ("+505", "88888888")
    assert format_global_phone("+505 8888-8888") == "+505 88888888"

    # With dashes separating prefix and subscriber parts
    assert parse_global_phone("+505-8888-0000") == ("+505", "88880000")
    assert format_global_phone("+505-8888-0000") == "+505 88880000"

    assert parse_global_phone("+505 - 8888 - 0000") == ("+505", "88880000")
    assert format_global_phone("+505 - 8888 - 0000") == "+505 88880000"

    assert parse_global_phone("+1-809-555-1234") == ("+1", "8095551234")
    assert format_global_phone("+1-809-555-1234") == "+1 8095551234"

    assert parse_global_phone("+1 (809) 555-1234") == ("+1", "8095551234")
    assert format_global_phone("+1 (809) 555-1234") == "+1 8095551234"

    # Without space
    assert parse_global_phone("+50588880000") == ("+505", "88880000")
    assert format_global_phone("+50588880000") == "+505 88880000"

    # Invalid cases
    assert parse_global_phone("88880000") is None
    assert parse_global_phone("11-B") is None
    assert parse_global_phone("") is None
    assert parse_global_phone("++505") is None


def test_normalize_phone_e164():
    assert normalize_phone_e164("+505 88880000") == "+50588880000"
    assert normalize_phone_e164("+1 8095551234") == "+18095551234"
    assert normalize_phone_e164("+505 8888-8888") == "+50588888888"
    assert normalize_phone_e164("8091112233") == "8091112233"


def test_send_sms_worker_cleans_e164_to_phone(settings, monkeypatch):
    from unittest.mock import MagicMock

    import requests

    mock_post = MagicMock()
    mock_post.return_value.status_code = 201
    monkeypatch.setattr(requests, "post", mock_post)

    sms_settings = replace(
        settings,
        twilio_enabled=True,
        twilio_account_sid="AC123",
        twilio_auth_token="auth123",
        twilio_from_number="+15550000000",
    )

    # Calling with phone with spaces
    send_sms_worker(sms_settings, "+505 88880000", "Hola")

    assert mock_post.called
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["data"]["To"] == "+50588880000"
    assert call_kwargs["data"]["From"] == "+15550000000"
    assert call_kwargs["data"]["Body"] == "Hola"


def test_send_whatsapp_worker_formats_addresses(settings, monkeypatch):
    from unittest.mock import MagicMock

    import requests

    mock_post = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_post.return_value = mock_resp
    monkeypatch.setattr(requests, "post", mock_post)

    wa_settings = replace(
        settings,
        twilio_enabled=True,
        twilio_use_whatsapp=True,
        twilio_account_sid="AC123",
        twilio_auth_token="auth123",
        twilio_from_number="+14155238886",
    )

    send_sms_worker(wa_settings, "+505 88880000", "Hola WhatsApp")

    assert mock_post.called
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["data"]["To"] == "whatsapp:+50588880000"
    assert call_kwargs["data"]["From"] == "whatsapp:+14155238886"
    assert call_kwargs["data"]["Body"] == "Hola WhatsApp"




def test_check_in_texts_to_two_guardians(conn, settings, now):
    # Student with 2 guardians
    add_user(
        conn,
        settings,
        "AA11",
        "est",
        "Carlos Santana",
        grade=10,
        section="A",
        guardians=[
            GuardianData(name="Mama", phone="+18095550101"),
            GuardianData(name="Papa", phone="+18095550102"),
        ],
        now=now,
    )

    # now is 07:00:00 -> late
    res = process_scan_line(conn, settings, "SCAN AA11", now=now)
    assert res.event_type == "check_in"
    assert len(res.texts_to_send) == 2
    phones = [phone for phone, _ in res.texts_to_send]
    assert "+1 8095550101" in phones
    assert "+1 8095550102" in phones
    for _, msg in res.texts_to_send:
        assert "Carlos Santana" in msg
        assert "(Tarde)" in msg


def test_check_in_texts_to_one_and_zero_guardians(conn, settings):
    # Student with 1 guardian
    add_user(
        conn,
        settings,
        "BB22",
        "est",
        "Ana Gomez",
        grade=10,
        section="A",
        guardians=[GuardianData(name="Mama", phone="+18095550202")],
    )
    # Student with 0 guardians
    add_user(
        conn,
        settings,
        "CC33",
        "est",
        "Pedro Perez",
        grade=10,
        section="A",
        guardians=[],
    )

    t_ontime = datetime(2026, 10, 5, 6, 45, 0)

    # 1 guardian -> 1 text, on-time wording
    res_one = process_scan_line(conn, settings, "SCAN BB22", now=t_ontime)
    assert len(res_one.texts_to_send) == 1
    assert res_one.texts_to_send[0][0] == "+1 8095550202"
    assert "(Puntual)" in res_one.texts_to_send[0][1]

    # 0 guardians -> 0 texts
    res_zero = process_scan_line(conn, settings, "SCAN CC33", now=t_ontime)
    assert len(res_zero.texts_to_send) == 0


def test_no_texts_for_teacher_check_in_or_out(conn, settings, school, now):
    add_user(conn, settings, "TC01", "prof", "Profesor Lopez", taught_grade=7, now=now)

    res_in = process_scan_line(conn, settings, "SCAN TC01", now=now)
    assert res_in.event_type == "check_in"
    assert len(res_in.texts_to_send) == 0

    t_out = now + timedelta(seconds=school.cooldown_seconds + 10)
    res_out = process_scan_line(conn, settings, "SCAN TC01", now=t_out)
    assert res_out.event_type == "check_out"
    assert len(res_out.texts_to_send) == 0


def test_leaving_text_on_check_out(conn, settings, school, now):
    add_user(
        conn,
        settings,
        "ST99",
        "est",
        "Laura Diaz",
        grade=9,
        section="B",
        guardians=[GuardianData(name="Mama", phone="+18095559999")],
        now=now,
    )

    # Check-in
    process_scan_line(conn, settings, "SCAN ST99", now=now)

    # Check-out after cooldown
    t_out = now + timedelta(seconds=school.cooldown_seconds + 10)
    res_out = process_scan_line(conn, settings, "SCAN ST99", now=t_out)
    assert res_out.event_type == "check_out"
    assert len(res_out.texts_to_send) == 1
    phone, msg = res_out.texts_to_send[0]
    assert phone == "+1 8095559999"
    assert "Laura Diaz salió del colegio hoy 05/10/2026" in msg


def test_admin_alert_once_per_badge_per_day_and_next_day(conn, settings, now):
    # Scan 1 on day 1 -> sends alert to admin
    res1 = process_scan_line(conn, settings, "SCAN BADGE999", now=now)
    assert res1.event_type == "unregistered"
    assert len(res1.texts_to_send) == 1
    phone, msg = res1.texts_to_send[0]
    assert phone == settings.admin_alert_phone
    assert "Una persona no identificada" in msg

    # Scan 2 on day 1 -> no alert
    res2 = process_scan_line(conn, settings, "SCAN BADGE999", now=now + timedelta(minutes=5))
    assert res2.event_type == "unregistered"
    assert len(res2.texts_to_send) == 0

    # Scan 3 on day 2 -> sends alert again
    next_day = now + timedelta(days=1)
    res3 = process_scan_line(conn, settings, "SCAN BADGE999", now=next_day)
    assert res3.event_type == "unregistered"
    assert len(res3.texts_to_send) == 1
    assert res3.texts_to_send[0][0] == settings.admin_alert_phone


def test_no_texts_in_demo_mode(conn, settings, now):
    demo_settings = replace(settings, demo_mode=True)
    add_user(
        conn,
        demo_settings,
        "DM01",
        "est",
        "Demo Student",
        grade=10,
        section="A",
        guardians=[GuardianData(name="Mama", phone="+18095551111")],
        now=now,
    )

    # Check-in -> no texts
    res_in = process_scan_line(conn, demo_settings, "SCAN DM01", now=now)
    assert res_in.event_type == "check_in"
    assert len(res_in.texts_to_send) == 0

    # Check-out -> no texts
    res_out = process_scan_line(conn, demo_settings, "SCAN DM01", now=now + timedelta(seconds=1))
    assert res_out.event_type == "check_out"
    assert len(res_out.texts_to_send) == 0

    # Unknown badge -> no texts
    res_unk = process_scan_line(conn, demo_settings, "SCAN EE99AA88", now=now)
    assert res_unk.event_type == "unregistered"
    assert len(res_unk.texts_to_send) == 0


def test_texts_sent_in_demo_mode_when_twilio_enabled(conn, settings, now):
    demo_twilio_settings = replace(settings, demo_mode=True, twilio_enabled=True)
    add_user(
        conn,
        demo_twilio_settings,
        "DM02",
        "est",
        "Demo Twilio Student",
        grade=10,
        section="A",
        guardians=[GuardianData(name="Papa", phone="+18095552222")],
        now=now,
    )

    # Check-in in Demo Mode with twilio_enabled -> sends arrival text
    res_in = process_scan_line(conn, demo_twilio_settings, "SCAN DM02", now=now)
    assert res_in.event_type == "check_in"
    assert len(res_in.texts_to_send) == 1
    assert res_in.texts_to_send[0][0] == "+1 8095552222"
    assert "Demo Twilio Student" in res_in.texts_to_send[0][1]

    # Check-out in Demo Mode with twilio_enabled -> sends leaving text
    res_out = process_scan_line(conn, demo_twilio_settings, "SCAN DM02", now=now + timedelta(seconds=1))
    assert res_out.event_type == "check_out"
    assert len(res_out.texts_to_send) == 1
    assert res_out.texts_to_send[0][0] == "+1 8095552222"
    assert "Demo Twilio Student" in res_out.texts_to_send[0][1]



def test_send_sms_worker_error_reporting(settings, monkeypatch, capsys):
    from unittest.mock import MagicMock

    import requests

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "code": 21608,
        "message": "The number is unverified",
    }
    mock_post = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(requests, "post", mock_post)

    sms_settings = replace(
        settings,
        twilio_enabled=True,
        twilio_account_sid="AC123",
        twilio_auth_token="auth123",
        twilio_from_number="+15550000000",
    )

    send_sms_worker(sms_settings, "+505 88880000", "Hola")
    captured = capsys.readouterr()
    assert "HTTP 400" in captured.out
    assert "Code 21608" in captured.out
    assert "The number is unverified" in captured.out


def test_send_sms_alias_and_callbacks(settings, monkeypatch):
    from unittest.mock import MagicMock

    import requests

    import sms

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    monkeypatch.setattr(requests, "post", MagicMock(return_value=mock_resp))

    wa_settings = replace(
        settings,
        twilio_enabled=True,
        twilio_use_whatsapp=True,
        twilio_account_sid="AC123",
        twilio_auth_token="auth123",
        twilio_from_number="+14155238886",
    )

    success_events = []
    error_events = []

    thread = sms.send_sms(
        wa_settings,
        "+505 88880000",
        "Prueba de alias",
        on_success=lambda msg: success_events.append(msg),
        on_error=lambda err: error_events.append(err),
    )
    thread.join(timeout=2.0)

    assert len(success_events) == 1
    assert "WhatsApp sent to +505 88880000" in success_events[0]
    assert len(error_events) == 0


