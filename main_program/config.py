"""Settings: reads `.env` into one Settings object.

Relative paths resolve from the repository root, so the program finds its
files no matter which folder it is started from. Keys the program no longer
uses are ignored: DOOR_DWELL_SECONDS, and the School policies that moved to
School Settings (ATTENDANCE_LATE_THRESHOLD, COOLDOWN_SECONDS, ADMIN_SECRET_KEY).
DATABASE_URL is supported for PostgreSQL.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


class ConfigError(Exception):
    """A value in `.env` is invalid. The message is shown to the operator."""


@dataclass(frozen=True)
class Settings:
    serial_port: str | None = None
    serial_baudrate: int = 9600
    database_path: Path = field(default_factory=lambda: REPO_ROOT / "quickpass.db")
    database_url: str | None = None
    demo_mode: bool = False
    twilio_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    admin_alert_phone: str = ""
    wipe_password: str | None = None
    reports_dir: Path = field(default_factory=lambda: REPO_ROOT / "Reports")
    twilio_use_whatsapp: bool = False
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None


T = TypeVar("T")


def _parse_bool(text: str) -> bool:
    lowered = text.lower()
    if lowered in ("true", "1", "yes", "si", "sí"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ValueError("must be true or false")


def _parse_int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError("must be a whole number") from None


def _parse_positive_int(text: str) -> int:
    value = _parse_int(text)
    if value <= 0:
        raise ValueError("must be greater than zero")
    return value


def _parse_path(text: str) -> Path:
    path = Path(text).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def load_settings(
    env_file: Path | None = DEFAULT_ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Read settings from `env_file`; the process environment takes precedence.

    Raises ConfigError with an English message naming the key when a value is invalid.
    """
    values: dict[str, str] = {}
    if env_file is not None and Path(env_file).is_file():
        values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    values.update(os.environ if environ is None else environ)

    def get(key: str, parse: Callable[[str], T], default: T) -> T:
        raw = values.get(key, "").strip()
        if raw == "":
            return default
        try:
            return parse(raw)
        except ValueError as error:
            raise ConfigError(f"Invalid value for {key} in .env: {raw!r} ({error}).") from None

    defaults = Settings()
    return Settings(
        serial_port=get("SERIAL_PORT", str, None),
        serial_baudrate=get("SERIAL_BAUDRATE", _parse_positive_int, defaults.serial_baudrate),
        database_path=get("DATABASE_PATH", _parse_path, defaults.database_path),
        database_url=get("DATABASE_URL", str, defaults.database_url),
        demo_mode=get("DEMO_MODE", _parse_bool, defaults.demo_mode),
        twilio_enabled=get("TWILIO_ENABLED", _parse_bool, defaults.twilio_enabled),
        twilio_account_sid=get("TWILIO_ACCOUNT_SID", str, ""),
        twilio_auth_token=get("TWILIO_AUTH_TOKEN", str, ""),
        twilio_from_number=get("TWILIO_FROM_NUMBER", str, ""),
        admin_alert_phone=get("ADMIN_ALERT_PHONE", str, ""),
        wipe_password=get("WIPE_PASSWORD", str, None),
        reports_dir=get("REPORTS_DIR", _parse_path, defaults.reports_dir),
        twilio_use_whatsapp=get("TWILIO_USE_WHATSAPP", _parse_bool, defaults.twilio_use_whatsapp),
        supabase_url=get("SUPABASE_URL", str, defaults.supabase_url),
        supabase_service_role_key=get("SUPABASE_SERVICE_ROLE_KEY", str, defaults.supabase_service_role_key),
    )
