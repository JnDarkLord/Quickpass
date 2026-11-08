"""SMS notifications via Twilio REST API.

Texts to Guardians and the Admin are written in the School Language (the
`sms.*` catalog keys). Texts are sent in the background so door operation
never waits.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

import requests

import i18n
from config import Settings


def _when(lang: str, at: datetime) -> dict[str, str]:
    return {"date": i18n.format_date(lang, at), "time": i18n.format_time(lang, at)}


def arrival_text(lang: str, name: str, at: datetime, on_time: bool) -> str:
    status = i18n.t(lang, "status.on_time" if on_time else "status.late")
    return i18n.t(lang, "sms.arrival", name=name, status=status, **_when(lang, at))


def leaving_text(lang: str, name: str, at: datetime) -> str:
    return i18n.t(lang, "sms.leaving", name=name, **_when(lang, at))


def admin_alert_text(lang: str, at: datetime) -> str:
    return i18n.t(lang, "sms.admin_alert", **_when(lang, at))


def normalize_phone_e164(to_phone: str) -> str:
    """Normalize phone number to E.164 for Twilio REST API by stripping internal spaces and punctuation."""
    return "".join(c for c in to_phone.strip() if c.isdigit() or c == "+")


def parse_global_phone(raw_phone: str) -> tuple[str, str] | None:
    """Validate and split a global phone number into (country_code, subscriber_number).

    Accepts spaces, dashes (-), and parentheses in input:
    e.g. "+505 88880000", "+505-8888-0000", "+505 - 8888 - 0000", "+1-809-555-1234"
    Returns (prefix, clean_subscriber_number) with all dashes and spaces stripped from the number.
    Returns None if the phone format is invalid.
    """
    text = raw_phone.strip()
    if not text:
        return None

    # Replace dashes and parentheses with spaces to normalize separators
    normalized = text.replace("-", " ").replace("(", " ").replace(")", " ")
    parts = normalized.split()
    if not parts:
        return None

    prefix = parts[0].strip()
    if not prefix.startswith("+"):
        return None

    # Case 1: Prefix is separate item (e.g. ['+505', '8888', '0000'])
    if len(parts) >= 2:
        if prefix[1:].isdigit() and 1 <= len(prefix[1:]) <= 4:
            sub = "".join(parts[1:])
            sub_clean = "".join(c for c in sub if c.isdigit())
            if len(sub_clean) >= 4:
                return prefix, sub_clean
        return None

    # Case 2: Only 1 item, but starts with '+' (e.g. ['+50588880000'])
    digits_after_plus = prefix[1:]
    if digits_after_plus.isdigit() and len(digits_after_plus) >= 7:
        if digits_after_plus.startswith("1") and len(digits_after_plus) == 11:
            return "+1", digits_after_plus[1:]
        if len(digits_after_plus) >= 8:
            return f"+{digits_after_plus[:3]}", digits_after_plus[3:]
        return f"+{digits_after_plus[:2]}", digits_after_plus[2:]

    return None


def format_global_phone(raw_phone: str) -> str | None:
    """Return phone number formatted with country code and space, or None if invalid."""
    res = parse_global_phone(raw_phone)
    if res:
        return f"{res[0]} {res[1]}"
    return None


def send_sms_worker(
    settings: Settings,
    to_phone: str,
    message: str,
    on_success: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> bool:
    """Post to Twilio REST API synchronously. Runs on background thread."""
    channel_label = "WhatsApp" if settings.twilio_use_whatsapp else "SMS"
    if not settings.twilio_enabled:
        msg = f"{channel_label} skipped: TWILIO_ENABLED is off."
        print(msg)
        if on_error:
            on_error(msg)
        return False

    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        msg = f"{channel_label} to {to_phone} skipped: the Twilio credentials are incomplete."
        print(msg)
        if on_error:
            on_error(msg)
        return False

    clean_target = normalize_phone_e164(to_phone)
    if not clean_target:
        msg = f"{channel_label} skipped: no phone number."
        print(msg)
        if on_error:
            on_error(msg)
        return False

    from_addr = settings.twilio_from_number.strip()
    to_addr = clean_target
    if settings.twilio_use_whatsapp or from_addr.startswith("whatsapp:"):
        channel_label = "WhatsApp"
        if not from_addr.startswith("whatsapp:"):
            from_addr = f"whatsapp:{from_addr}"
        if not to_addr.startswith("whatsapp:"):
            to_addr = f"whatsapp:{to_addr}"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    try:
        response = requests.post(
            url,
            data={
                "From": from_addr,
                "To": to_addr,
                "Body": message,
            },
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            timeout=10,
        )
        if response.status_code == 201:
            success_msg = f"{channel_label} sent to {to_phone}"
            print(success_msg)
            if on_success:
                on_success(success_msg)
            return True
        else:
            detail = ""
            try:
                err_data = response.json()
                code = err_data.get("code")
                msg = err_data.get("message")
                if code or msg:
                    detail = f" [Code {code}: {msg}]"
            except Exception:
                if response.text:
                    detail = f": {response.text.strip()}"
            err_msg = f"Could not send {channel_label} to {to_phone}: HTTP {response.status_code}{detail}"
            print(err_msg)
            if on_error:
                on_error(err_msg)
            return False
    except Exception as error:
        err_msg = f"Connection error sending {channel_label} to {to_phone}: {error}"
        print(err_msg)
        if on_error:
            on_error(err_msg)
        return False


def send_sms_async(
    settings: Settings,
    to_phone: str,
    message: str,
    on_success: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> threading.Thread:
    """Dispatch SMS/WhatsApp sending to a background thread."""
    thread = threading.Thread(
        target=send_sms_worker,
        args=(settings, to_phone, message, on_success, on_error),
        daemon=True,
    )
    thread.start()
    return thread


# Alias for backward compatibility
send_sms = send_sms_async
