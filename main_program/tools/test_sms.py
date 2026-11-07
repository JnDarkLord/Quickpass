"""Twilio SMS Diagnostic and Testing Tool.

Usage:
    python main_program/tools/test_sms.py [--phone PHONE] [--message MESSAGE]

Examples:
    python main_program/tools/test_sms.py --phone "+1 555 123 4567"
    python main_program/tools/test_sms.py --phone "+505 88880000" --message "Quickpass test message"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_main_dir = Path(__file__).resolve().parent.parent
if str(_main_dir) not in sys.path:
    sys.path.insert(0, str(_main_dir))

from config import load_settings
import sms


def main() -> int:
    parser = argparse.ArgumentParser(description="Test and diagnose Twilio SMS sending.")
    parser.add_argument(
        "--phone",
        type=str,
        default=None,
        help="Target phone number (e.g. '+1 555 123 4567'). Defaults to ADMIN_ALERT_PHONE from .env.",
    )
    parser.add_argument(
        "--message",
        type=str,
        default="Quickpass: This is a test message to verify the SMS configuration.",
        help="Message body to send.",
    )
    args = parser.parse_args()

    settings = load_settings()

    print("=== SMS Sending Diagnostic (Twilio) ===")
    print(f"TWILIO_ENABLED     : {settings.twilio_enabled}")
    print(f"DEMO_MODE          : {settings.demo_mode}")
    if settings.demo_mode:
        print("  ℹ️ NOTE: With DEMO_MODE=TRUE, the program sends no SMS during scans.")
        print("     This tool sends the message directly to check your Twilio account.")

    print(f"TWILIO_ACCOUNT_SID : {settings.twilio_account_sid[:6]}...{settings.twilio_account_sid[-4:] if len(settings.twilio_account_sid) > 10 else settings.twilio_account_sid}")
    print(f"TWILIO_FROM_NUMBER : {settings.twilio_from_number}")
    print(f"ADMIN_ALERT_PHONE  : {settings.admin_alert_phone}")

    target_phone = args.phone or settings.admin_alert_phone
    if not target_phone:
        print("\n❌ Error: no phone number was given and ADMIN_ALERT_PHONE is empty in .env.")
        print("   Use --phone '+1 555 123 4567' to give the target number.")
        return 1

    formatted_target = sms.format_global_phone(target_phone)
    e164_target = sms.normalize_phone_e164(target_phone)

    print(f"\nTarget phone (as typed)      : {target_phone}")
    print(f"Target phone (formatted)     : {formatted_target or '(non-standard)'}")
    print(f"Target phone (E.164 for API) : {e164_target}")
    print(f"Message to send              : {args.message}")

    if not settings.twilio_enabled:
        print("\n⚠️ Warning: TWILIO_ENABLED=FALSE in your .env file.")
        print("   To send real messages, set TWILIO_ENABLED=TRUE in .env.")

    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        print("\n❌ Error: Twilio credentials are missing from .env (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN or TWILIO_FROM_NUMBER).")
        return 1

    print("\nSending the message to Twilio...")
    sms.send_sms_worker(settings, target_phone, args.message)
    print("\nTest finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
