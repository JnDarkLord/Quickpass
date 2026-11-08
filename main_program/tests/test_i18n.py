"""School Language catalogs: both languages carry the same texts, and LCD lines fit the display."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, time
from pathlib import Path

import pytest

import arduino
import gui
import i18n
from config import REPO_ROOT

PLACEHOLDER = re.compile(r"\{(\w+)\}")
CATALOG_DIRS = [
    pytest.param(REPO_ROOT / "main_program" / "locales", id="desktop"),
    pytest.param(REPO_ROOT / "web" / "frontend" / "src" / "locales", id="portal"),
]
KEY_NAMESPACES = ("lcd", "sms", "admin", "gui", "report", "status", "role", "settings", "common")
NAMESPACE_PATTERN = "|".join(KEY_NAMESPACES)
KEY_LITERAL = re.compile(r"""["']((?:""" + NAMESPACE_PATTERN + r""")\.[a-z0-9_]+(?:\.[a-z0-9_]+)*)["']""")
# Helpers that put the start of the key in front themselves: admin._error and reports' texts.
PREFIXED_KEY_CALLS = (
    (re.compile(r"""\b_error\(\s*conn,\s*["']([a-z0-9_.]+)["']"""), "admin.error."),
    (re.compile(r"""\btexts\(\s*["']([a-z0-9_.]+)["']"""), "report."),
)
KEY_TEMPLATE = re.compile(r"""\bf"((?:""" + NAMESPACE_PATTERN + r""")\.[^"]*\{[^"]*)\"""")
TEMPLATE_FIELD = re.compile(r"\{[^}]+\}")
WIPE_KINDS = ("users", "history")
# Keys built from a neutral value, such as f"lcd.deny.{reason}", with every value each one is built from.
KEY_TEMPLATE_VALUES: dict[str, tuple[str, ...]] = {
    "admin.error.{key}": (),  # the helpers above, checked call by call
    "report.{key}": (),
    "lcd.check_in.{status}": ("on_time", "late"),
    "lcd.visitor.{event_type}": ("check_in", "check_out"),
    "lcd.deny.{reason}": ("unregistered", "graduate", "inactive"),
    "role.{role}": gui.ROLES,
    "role.{holder['role']}": gui.ROLES,
    "status.{code}": ("on_time", "late", "absent", "visit"),
    "status.{status}": ("on_time", "late", "absent", "visit"),
    "gui.search.event.{event_type}": ("check_in", "check_out"),
    "gui.live.result.{result}": (
        "unregistered",
        "graduate_denied",
        "inactive_denied",
        "access_denied",
        "check_out",
        "on_time",
        "late",
        "visit",
        "check_in",
        "repeat_scan",
        "unknown",
    ),
    "gui.stats.role.{role}": ("student", "teacher", "admin", "visitor"),
    "gui.wipe.{kind}.window_title": WIPE_KINDS,
    "gui.wipe.{kind}.heading": WIPE_KINDS,
    "gui.wipe.{kind}.description": WIPE_KINDS,
    "gui.wipe.{kind}.button": WIPE_KINDS,
    "gui.wipe.{self.kind}.done": WIPE_KINDS,
    "report.mark.{mark}": tuple(gui.MARK_COLORS),
    "report.role_plural.{role}": ("teacher", "admin", "visitor"),
    "gui.weekday.{name}": gui.WEEKDAYS,
}


def _flatten(tree: dict, prefix: str = "") -> dict[str, object]:
    flat: dict[str, object] = {}
    for name, value in tree.items():
        key = f"{prefix}{name}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{key}."))
        else:
            flat[key] = value
    return flat


def _load(locales_dir: Path, lang: str) -> dict[str, object]:
    return _flatten(json.loads((locales_dir / f"{lang}.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize("locales_dir", CATALOG_DIRS)
def test_spanish_and_english_have_the_same_keys(locales_dir):
    spanish, english = _load(locales_dir, "es"), _load(locales_dir, "en")

    assert sorted(set(spanish) - set(english)) == [], "missing from en.json"
    assert sorted(set(english) - set(spanish)) == [], "missing from es.json"


@pytest.mark.parametrize("locales_dir", CATALOG_DIRS)
def test_every_text_is_filled_in_and_uses_the_same_placeholders(locales_dir):
    spanish, english = _load(locales_dir, "es"), _load(locales_dir, "en")

    for key, text in spanish.items():
        assert isinstance(text, str) and text.strip(), f"es: {key} is empty"
        assert isinstance(english[key], str) and str(english[key]).strip(), f"en: {key} is empty"
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(str(english[key]))), key


@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_lcd_lines_fit_the_16_character_display(lang):
    lcd_texts = {key: text for key, text in i18n.catalog(lang).items() if key.startswith("lcd.")}
    assert lcd_texts

    for key, text in lcd_texts.items():
        fixed_part = PLACEHOLDER.sub("", text)
        without_accents = "".join(
            c for c in unicodedata.normalize("NFD", fixed_part) if unicodedata.category(c) != "Mn"
        )
        assert len(fixed_part) <= arduino.LCD_WIDTH, f"{lang}: {key} = {text!r}"
        assert without_accents.isascii(), f"{lang}: {key} = {text!r} cannot be shown"


def test_every_key_the_desktop_program_uses_exists():
    catalog = i18n.catalog("en")
    used: set[str] = set()
    templates: set[str] = set()
    for path in (REPO_ROOT / "main_program").rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        used.update(KEY_LITERAL.findall(source))
        for call, prefix in PREFIXED_KEY_CALLS:
            used.update(prefix + key for key in call.findall(source))
        templates.update(KEY_TEMPLATE.findall(source))

    assert sorted(templates - set(KEY_TEMPLATE_VALUES)) == [], "list the values these keys are built from"
    assert sorted(set(KEY_TEMPLATE_VALUES) - templates) == [], "no longer in the code"
    for template in templates:
        used.update(TEMPLATE_FIELD.sub(value, template) for value in KEY_TEMPLATE_VALUES[template])

    def exists(key: str) -> bool:
        return key in catalog or (f"{key}.line1" in catalog and f"{key}.line2" in catalog)

    assert any(key.startswith("admin.error.") for key in used)
    assert any(key.startswith("report.header.") for key in used)
    assert sorted(key for key in used if not exists(key)) == []


def test_texts_fill_in_their_placeholders():
    assert i18n.t("es", "lcd.check_in.welcome", name="Ana") == "Bienvenido Ana"
    assert i18n.t("en", "lcd.check_in.welcome", name="Ana") == "Welcome Ana"


def test_an_unknown_school_language_is_refused():
    with pytest.raises(ValueError):
        i18n.t("fr", "lcd.idle.line2")


def test_spanish_writes_day_month_year_and_24_hour_times():
    assert i18n.format_date("es", date(2026, 3, 9)) == "09/03/2026"
    assert i18n.format_time("es", time(13, 5, 9)) == "13:05:09"
    assert i18n.format_time("es", datetime(2026, 3, 9, 0, 0, 0)) == "00:00:00"
    assert i18n.format_short_date("es", date(2026, 3, 9)) == "09/03"


def test_english_writes_month_day_year_and_12_hour_am_pm_times():
    assert i18n.format_date("en", date(2026, 3, 9)) == "03/09/2026"
    assert i18n.format_date("en", datetime(2026, 12, 25, 8, 0)) == "12/25/2026"
    assert i18n.format_time("en", time(13, 5, 9)) == "01:05:09 PM"
    assert i18n.format_time("en", time(0, 0, 0)) == "12:00:00 AM"
    assert i18n.format_time("en", time(12, 0, 0)) == "12:00:00 PM"
    assert i18n.format_time("en", "06:50:00") == "06:50:00 AM"
    assert i18n.format_short_date("en", datetime(2026, 3, 9, 7, 0)) == "03/09"
