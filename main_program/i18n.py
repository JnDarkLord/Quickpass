"""School Language text: key-based catalogs and each language's date and time conventions.

Every School-facing text has a dot-separated key with one entry per language in
`locales/es.json` and `locales/en.json`. Code passes keys and neutral values
around and turns them into text only where a person reads it.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from functools import cache
from pathlib import Path
from typing import Any

LANGUAGES = ("es", "en")
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

_DATE_FORMATS = {"es": "%d/%m/%Y", "en": "%m/%d/%Y"}
_SHORT_DATE_FORMATS = {"es": "%d/%m", "en": "%m/%d"}
_TWELVE_HOUR_CLOCK = {"es": False, "en": True}
# Whose month names and AM/PM markers each language uses where a widget writes dates itself.
CALENDAR_LOCALES = {"es": "es_ES", "en": "en_US"}


def _flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for name, value in tree.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{name}."))
        else:
            flat[f"{prefix}{name}"] = str(value)
    return flat


def _checked(lang: str) -> str:
    if lang not in LANGUAGES:
        raise ValueError(f"Unknown School Language {lang!r}; expected one of {', '.join(LANGUAGES)}.")
    return lang


@cache
def catalog(lang: str) -> dict[str, str]:
    """Every text of one language, by dot-separated key."""
    path = LOCALES_DIR / f"{_checked(lang)}.json"
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def t(lang: str, key: str, **params: Any) -> str:
    """The text for `key` in `lang`, with `{name}` placeholders filled in from `params`."""
    text = catalog(lang)[key]
    return text.format(**params) if params else text


def format_date(lang: str, value: date | datetime | str) -> str:
    """Spanish writes DD/MM/YYYY; English writes MM/DD/YYYY. Strings are ISO dates."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime(_DATE_FORMATS[_checked(lang)])


def format_short_date(lang: str, value: date | datetime) -> str:
    """The day and month alone, in the order `format_date` writes them."""
    return value.strftime(_SHORT_DATE_FORMATS[_checked(lang)])


def format_time(lang: str, value: time | datetime | str) -> str:
    """Spanish writes 24-hour HH:MM:SS; English writes 12-hour hh:mm:ss AM/PM. Strings are HH:MM:SS."""
    if isinstance(value, str):
        value = time.fromisoformat(value)
    if not _TWELVE_HOUR_CLOCK[_checked(lang)]:
        return value.strftime("%H:%M:%S")
    # %p follows the operating system's locale, so the AM/PM marker is written out here.
    return f"{value.strftime('%I:%M:%S')} {'AM' if value.hour < 12 else 'PM'}"
