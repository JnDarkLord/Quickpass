#!/usr/bin/env python3
"""Quickpass Desktop Application (PySide6).

Modern accessible GUI for school physical access control, attendance tracking,
RFID badge management, unified search/reports with Excel export, statistics, wipes behind
a backup, and the School Settings, which a first-run setup asks for on a station that has none.
Features official Quickpass branding, dedicated Live Access Window (for simultaneous operation),
mutually exclusive RFID capture mode for badge registration, WCAG-compliant color palette,
smooth circular corners for logos, dual guardian (mother & father) enrollment, and native macOS application icon.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Ensure main_program is in import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDate, QLocale, QRectF, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

import access_control
import admin
import arduino
import cloud_sync
import database
import i18n
import reports
import school_settings
import search
import sms
from arduino import ArduinoError, ArduinoLink
from config import ConfigError, Settings, load_settings

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.jpg"
LOGO_PNG = ASSETS_DIR / "logo.png"
LOGO_ROUNDED_PNG = ASSETS_DIR / "logo_rounded.png"
LOGO_ICNS = ASSETS_DIR / "logo.icns"

ROLES = ("student", "teacher", "admin", "visitor", "graduate")

_school: school_settings.SchoolSettings | None = None
_language = i18n.LANGUAGES[0]


def set_school(school: school_settings.SchoolSettings) -> None:
    """From now on, show School-facing text in the School Language, and Grades and Sections by the School's names."""
    global _school
    set_language(school.school_language)
    _school = school


def set_language(lang: str) -> None:
    """From now on, show School-facing text in `lang`; the first-run setup does so before the School has settings."""
    global _language
    i18n.catalog(lang)
    _language = lang
    # Date and time pickers built from now on take their month names and AM/PM from this, not from the computer.
    QLocale.setDefault(QLocale(i18n.CALENDAR_LOCALES[lang]))


def tr(key: str, **params: Any) -> str:
    """The text for `key` in the School Language."""
    return i18n.t(_language, key, **params)


def in_every_language(key: str, separator: str = " / ") -> str:
    """The text for `key` in each School Language, for the screen where a School picks one."""
    return separator.join(i18n.t(lang, key) for lang in i18n.LANGUAGES)


def show_date(iso_date: str) -> str:
    return i18n.format_date(_language, iso_date) if iso_date else ""


def show_time(iso_time: str) -> str:
    return i18n.format_time(_language, iso_time) if iso_time else ""


def show_short_date(day: date) -> str:
    return i18n.format_short_date(_language, day)


def role_text(role: str | None) -> str:
    return tr(f"role.{role}") if role in ROLES else tr("gui.common.unknown")


def status_text(status: str | None) -> str:
    return tr(f"status.{status}") if status else ""


def event_text(event_type: str) -> str:
    return tr(f"gui.search.event.{event_type}") if event_type in ("check_in", "check_out") else event_type


def school_grades() -> tuple[str, ...]:
    return _school.grades if _school else ()


def school_sections() -> tuple[str, ...]:
    return _school.sections if _school else ()


def grade_text(rank: Any) -> str:
    """The School's name for a Grade rank."""
    if not rank:
        return ""
    return _school.grade_label(int(rank)) if _school else str(rank)


def final_grade_text() -> str:
    return grade_text(len(school_grades()))


def grade_section_text(rank: Any, section: str | None) -> str:
    return " ".join(part for part in (grade_text(rank), section or "") if part)


def fill_grade_combo(combo: QComboBox, current: int | None = None) -> None:
    """The School's Grades in order, each holding its rank. A current rank the School
    no longer lists stays selectable, so saving other changes keeps it."""
    combo.clear()
    for rank, label in enumerate(school_grades(), start=1):
        combo.addItem(label, rank)
    if current:
        if combo.findData(current) < 0:
            combo.addItem(grade_text(current), current)
        combo.setCurrentIndex(combo.findData(current))


def fill_section_combo(combo: QComboBox, current: str | None = None) -> None:
    """The School's Sections. A current Section the School no longer lists stays selectable."""
    combo.clear()
    for section in school_sections():
        combo.addItem(section, section)
    if current:
        index = next((i for i in range(combo.count()) if combo.itemData(i).casefold() == current.casefold()), -1)
        if index < 0:
            combo.addItem(current, current)
            index = combo.count() - 1
        combo.setCurrentIndex(index)


def load_school(settings: Settings) -> school_settings.SchoolSettings:
    """The School Settings kept in the local cache."""
    conn = database.connect(settings.database_path)
    try:
        return school_settings.require(conn)
    finally:
        conn.close()


def app_icon_path(platform: str = sys.platform) -> Path | None:
    """The Quickpass icon file for `platform`; only macOS reads the `.icns` format."""
    candidates = [LOGO_ROUNDED_PNG, LOGO_PNG, LOGO_PATH]
    if platform == "darwin":
        candidates.insert(0, LOGO_ICNS)
    return next((path for path in candidates if path.exists()), None)


def get_app_icon() -> QIcon:
    """Return the official Quickpass application icon with smooth circular rounded corners."""
    path = app_icon_path()
    return QIcon(str(path)) if path else QIcon()


def get_rounded_pixmap(
    pixmap: QPixmap,
    radius: int = 28,
    border_color: str | None = None,
    border_width: int = 0,
) -> QPixmap:
    """Clip a pixmap with smooth antialiased circular rounded corners and optional border outline."""
    if pixmap.isNull():
        return pixmap
    rounded = QPixmap(pixmap.size())
    rounded.fill(Qt.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)

    if border_color and border_width > 0:
        painter.setClipping(False)
        pen = QPen(QColor(border_color), border_width)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = border_width / 2.0
        border_rect = QRectF(inset, inset, pixmap.width() - border_width, pixmap.height() - border_width)
        border_path = QPainterPath()
        border_path.addRoundedRect(border_rect, radius - inset, radius - inset)
        painter.drawPath(border_path)

    painter.end()
    return rounded


# ---------------------------------------------------------------------------
# UI/UX Brand Design Tokens (Derived from Quickpass Logo & WCAG Guidelines)
# ---------------------------------------------------------------------------
# 1. Brand & UI Core Colors
COLOR_PRIMARY = "#122A42"  # Technical Deep Navy: main headings, text, brand headers
COLOR_SECONDARY = "#4A607A"  # Modern Slate Blue: subheadings, borders, captions, labels
COLOR_ACCENT = "#0066FF"  # Electric Blue: CTA buttons, active links, primary highlights
COLOR_ACCENT_HOVER = "#0052CC"  # Hover state for primary buttons
COLOR_DARK_BLUE = "#27475c"  # Dark slate blue: sidebar hover accents, logo border, live card
COLOR_SIDEBAR_HOVER = "#27475c"  # Darker blue hover for sidebar lateral buttons

# 2. Surfaces & Backgrounds
COLOR_BG_LIGHT = "#F4F8FB"  # Soft off-white with cool blue tint (anti-fatigue canvas)
COLOR_SIDEBAR_BG = "#A4D0E9"  # Logo background light blue (#A4D0E9)
COLOR_SIDEBAR_BORDER = "#8CB8D4"  # Matching border for logo light blue
COLOR_SURFACE = "#FFFFFF"  # Cards, dialogs, tables
COLOR_SURFACE_ALT = "#EDF4FA"  # Subtle tint for active items, table headers
COLOR_BORDER = "#D1DCE5"  # Neutral border for cards and dividers
COLOR_INPUT_BORDER = "#B8C8D6"  # Crisp border for inputs and selects

# 3. Functional Status Colors (Quickpass Access Control)
COLOR_SUCCESS = "#10B981"  # Emerald Green: Access granted, puntual, Excel export
COLOR_SUCCESS_BG = "#ECFDF5"
COLOR_SUCCESS_TEXT = "#047857"

COLOR_WARNING = "#F59E0B"  # Amber: Notice, late check-in
COLOR_WARNING_BG = "#FFFBEB"
COLOR_WARNING_TEXT = "#B45309"

COLOR_ERROR = "#EF4444"  # Crimson Red: Denied, blocked, delete
COLOR_ERROR_BG = "#FEF2F2"
COLOR_ERROR_TEXT = "#DC2626"


# ---------------------------------------------------------------------------
# RFID Operational Modes
# ---------------------------------------------------------------------------
class RFIDMode:
    STANDBY = "STANDBY"
    ACCESS_CONTROL = "ACCESS_CONTROL"
    CAPTURE = "CAPTURE"


# ---------------------------------------------------------------------------
# Background Hardware Worker (Arduino + Terminal Sync with Mutually Exclusive Modes)
# ---------------------------------------------------------------------------
class HardwareWorker(QThread):
    scan_event = Signal(dict)
    badge_captured = Signal(str)
    status_changed = Signal(str, bool)  # message, is_connected
    gate_state = Signal(bool, int)  # is_open, dwell_seconds
    mode_changed = Signal(str)  # current RFID mode

    def __init__(self, settings: Settings, parent=None, clock: Callable[[], float] = time.monotonic):
        super().__init__(parent)
        self.settings = settings
        self.link = ArduinoLink(settings)
        self.running = True
        self.rfid_mode = RFIDMode.STANDBY
        self._pending_commands: list[str] = []
        self._capture_callback: Callable[[str], None] | None = None
        self._clock = clock
        self._debouncer = access_control.ScanDebouncer()

    def set_rfid_mode(self, mode: str, callback: Callable[[str], None] | None = None):
        self.rfid_mode = mode
        self._capture_callback = callback
        # A window that starts asking for a scan takes the first read, even of a Badge just let through.
        self._debouncer = access_control.ScanDebouncer()
        self.mode_changed.emit(mode)
        self._log_terminal("RFID_MODE", f"RFID mode changed to: {mode}")

    def run(self):
        last_reconnect_time = 0.0

        # Initial connection attempt
        connect_msg = self.link.connect()
        if self.link.connected:
            self._on_connected()
        else:
            msg = "Simulation Mode (no hardware connected)"
            self.status_changed.emit(msg, False)
            self._log_terminal("SYSTEM", f"{msg} - {connect_msg}")

        while self.running:
            # Auto-reconnection loop: retry every 2.5s if disconnected
            if not self.link.connected:
                now_mono = time.monotonic()
                if now_mono - last_reconnect_time > 2.5:
                    last_reconnect_time = now_mono
                    self.link.connect()
                    if self.link.connected:
                        self._on_connected()

            # Dispatch queued commands to Arduino
            while self._pending_commands:
                cmd = self._pending_commands.pop(0)
                self._log_terminal("TX", cmd.strip())
                if self.link.connected:
                    try:
                        self.link.send(cmd)
                    except ArduinoError as err:
                        self._log_terminal("ERR", f"TX Error: {err}")
                        self.status_changed.emit("Disconnected from Arduino", False)

            # Read incoming lines from Arduino
            if self.link.connected:
                try:
                    line = self.link.read_line(timeout=0.05)
                    if line:
                        self._log_terminal("RX", line)
                        self._handle_serial_line(line)
                except ArduinoError as err:
                    if self.running:
                        self._log_terminal("ERR", f"RX Error: {err}")
                        self.status_changed.emit("Disconnected - retrying...", False)
            else:
                time.sleep(0.05)

    def _on_connected(self):
        port = self.settings.serial_port or "Arduino"
        msg = f"Connected to Arduino ({port})"
        self.status_changed.emit(msg, True)
        self._log_terminal("SYSTEM", msg)
        self.send_idle_screen()

    def _log_terminal(self, prefix: str, text: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        sys.stdout.write(f"[{now_str}] [Quickpass | {prefix}] {text}\n")
        sys.stdout.flush()

    def _handle_serial_line(self, line: str):
        if line == arduino.READY_LINE:
            self.send_idle_screen()
            return
        uid = arduino.parse_scan(line)
        if uid is None or not self._debouncer.let_through(uid, self._clock()):
            return

        # Mutually exclusive processing based on RFID mode:
        if self.rfid_mode == RFIDMode.CAPTURE:
            self._log_terminal("CAPTURE", f"Badge read for registration: {uid}")
            self.send_screen("lcd.capture.badge_read", uid=uid)
            self.badge_captured.emit(uid)
            if self._capture_callback:
                try:
                    self._capture_callback(uid)
                except Exception as e:
                    self._log_terminal("CAPTURE ERR", str(e))
        elif self.rfid_mode == RFIDMode.ACCESS_CONTROL:
            self.process_uid(uid)
        else:
            self._log_terminal("SCAN_STANDBY", f"Badge read in standby mode: {uid}")
            self.send_screen("lcd.standby_scan")

    def send_command(self, cmd: str):
        self._pending_commands.append(cmd)

    def school_language(self) -> str:
        return load_school(self.settings).school_language

    def send_screen(self, key: str, **params: Any):
        """Show the catalog screen `key` on the LCD for a moment."""
        self.send_command(arduino.screen(arduino.MSG, self.school_language(), key, **params))

    def send_idle_screen(self):
        self.send_command(arduino.idle_screen(self.school_language()))

    def trigger_unlock(self):
        self.send_command(arduino.unlock_screen(self.school_language()))
        self.gate_state.emit(True, 3)
        self._log_terminal("GATE", "Manual unlock requested.")

    def process_uid(self, uid: str, force_status: str | None = None, now: datetime | None = None):
        uid = uid.strip().upper()
        now = now or datetime.now()
        conn = database.connect(self.settings.database_path)

        res = access_control.process_scan_line(conn, self.settings, f"SCAN {uid}", now)

        # Dispatch reply to Arduino
        if res.reply_line:
            self.send_command(res.reply_line)

        # If granted access or check-in/out, animate gate
        if res.reply_line.startswith(arduino.GRANT):
            self.gate_state.emit(True, 3)

        # Dispatch async SMS/WhatsApp notifications if any
        if res.texts_to_send and self.settings.twilio_enabled:
            channel = "WhatsApp" if self.settings.twilio_use_whatsapp else "SMS"
            for phone, body in res.texts_to_send:
                try:
                    sms.send_sms_async(
                        self.settings,
                        phone,
                        body,
                        on_success=lambda msg, p=phone: self._log_terminal(channel.upper(), f"{channel} sent to {p}"),
                        on_error=lambda err: self._log_terminal(f"{channel.upper()} ERR", err),
                    )
                    self._log_terminal(channel.upper(), f"Sending to {phone}: {body}")
                except Exception as err:
                    self._log_terminal(f"{channel.upper()} ERR", f"Could not send to {phone}: {err}")

        # Assemble UI payload
        name = res.user.get("full_name") if res.user else tr("gui.scan_tile.unregistered_name")
        role = res.user.get("role", "") if res.user else ""
        grade = (res.user.get("grade") or res.user.get("taught_grade")) if res.user else None
        section = res.user.get("section", "") if res.user else ""
        grade_sec = grade_section_text(grade, section) if grade else ""
        initials = "".join([part[0] for part in name.split()[:2]]).upper() if name else "??"

        phone = "N/A"
        if res.user and res.user.get("guardians"):
            phone = res.user["guardians"][0].get("phone", "N/A")

        payload = {
            "uid": uid,
            "full_name": name,
            "role": role,
            "grade_sec": grade_sec,
            "time_str": now.strftime("%H:%M:%S"),
            "date_str": now.strftime("%Y-%m-%d"),
            "event_type": res.event_type,
            "status": res.status or ("late" if force_status == "late" else None),
            "phone": phone,
            "avatar_initials": initials,
            "is_registered": res.event_type != "unregistered",
        }

        self._log_terminal("ACCESS", f"{name} ({uid}) -> Event: {res.event_type} | Status: {res.status}")

        conn.close()
        self.scan_event.emit(payload)

    def stop(self):
        self.running = False
        self.wait(200)
        self.link.close()
        self.wait(1000)


# ---------------------------------------------------------------------------
# Student Square Card - Clean Light Theme
# ---------------------------------------------------------------------------
class StudentSquareWidget(QFrame):
    """Dedicated Student Card Square that displays student identity,
    high-contrast status badges, gate state, and resets automatically.
    """

    def __init__(self, parent=None, is_kiosk=False):
        super().__init__(parent)
        self.is_kiosk = is_kiosk
        self.setObjectName("studentSquare")
        self._init_ui()

        # Idle reset timer: after 6 seconds of a scan, returns to ready state
        self.reset_timer = QTimer(self)
        self.reset_timer.setInterval(6000)
        self.reset_timer.setSingleShot(True)
        self.reset_timer.timeout.connect(self.set_idle_state)

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame#studentSquare {{
                background-color: {COLOR_SURFACE};
                border: 2px solid {COLOR_ACCENT};
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        pad = 24 if self.is_kiosk else 16
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(10)

        # Header Bar
        top_bar = QHBoxLayout()
        self.lbl_title = QLabel(tr("gui.scan_tile.title"))
        self.lbl_title.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_title.setStyleSheet(f"color: {COLOR_PRIMARY}; letter-spacing: 0.5px;")
        top_bar.addWidget(self.lbl_title)
        top_bar.addStretch()

        self.gate_badge = QLabel(tr("gui.scan_tile.gate_closed"))
        self.gate_badge.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;"
        )
        top_bar.addWidget(self.gate_badge)
        layout.addLayout(top_bar)

        # Status Banner (Solid Flat color)
        self.status_banner = QLabel(tr("gui.scan_tile.ready"))
        font_size = 16 if self.is_kiosk else 13
        self.status_banner.setFont(QFont("Arial", font_size, QFont.Bold))
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.status_banner.setStyleSheet(f"""
            background-color: {COLOR_ACCENT};
            color: #FFFFFF;
            padding: 10px;
            border-radius: 8px;
            letter-spacing: 0.5px;
        """)
        layout.addWidget(self.status_banner)

        # Student Profile Box
        profile_box = QHBoxLayout()
        profile_box.setSpacing(16)

        # Avatar
        avatar_size = 80 if self.is_kiosk else 64
        self.avatar = QLabel("QP")
        self.avatar.setFixedSize(avatar_size, avatar_size)
        self.avatar.setFont(QFont("Arial", 22 if self.is_kiosk else 18, QFont.Bold))
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(f"""
            background-color: {COLOR_SURFACE_ALT};
            color: {COLOR_ACCENT};
            border: 2px solid {COLOR_INPUT_BORDER};
            border-radius: {avatar_size // 2}px;
        """)
        profile_box.addWidget(self.avatar)

        # Details
        info_lay = QVBoxLayout()
        info_lay.setSpacing(4)

        self.lbl_name = QLabel(tr("gui.scan_tile.prompt"))
        self.lbl_name.setFont(QFont("Arial", 17 if self.is_kiosk else 14, QFont.Bold))
        self.lbl_name.setStyleSheet(f"color: {COLOR_PRIMARY};")
        info_lay.addWidget(self.lbl_name)

        # Chips row
        chips_row = QHBoxLayout()
        chips_row.setSpacing(8)

        self.lbl_grade = QLabel(tr("gui.scan_tile.school"))
        self.lbl_grade.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_BORDER}; padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        chips_row.addWidget(self.lbl_grade)

        self.lbl_uid = QLabel(tr("gui.scan_tile.reader_ready"))
        self.lbl_uid.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; padding: 3px 8px; border-radius: 4px; font-family: monospace; font-size: 11px;"
        )
        chips_row.addWidget(self.lbl_uid)

        self.lbl_phone = QLabel(tr("gui.scan_tile.whatsapp_active"))
        self.lbl_phone.setStyleSheet(
            f"background-color: {COLOR_SUCCESS_BG}; color: {COLOR_SUCCESS_TEXT}; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold;"
        )
        chips_row.addWidget(self.lbl_phone)

        chips_row.addStretch()
        info_lay.addLayout(chips_row)
        profile_box.addLayout(info_lay)
        layout.addLayout(profile_box)

        # Footer Timestamp
        self.lbl_time = QLabel(tr("gui.scan_tile.waiting"))
        self.lbl_time.setAlignment(Qt.AlignCenter)
        self.lbl_time.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px; margin-top: 4px;")
        layout.addWidget(self.lbl_time)

    def update_scan(self, payload: dict):
        self.reset_timer.stop()

        name = payload.get("full_name", tr("gui.common.unknown"))
        initials = payload.get("avatar_initials", "??")
        grade_sec = payload.get("grade_sec", "")
        role = payload.get("role", "student")
        uid = payload.get("uid", "N/A")
        phone = payload.get("phone", "N/A")
        status = payload.get("status")
        event_type = payload.get("event_type")
        is_registered = payload.get("is_registered", True)

        self.lbl_name.setText(name)
        self.avatar.setText(initials)
        self.lbl_grade.setText(" • ".join(part for part in (role_text(role).upper(), grade_sec) if part))
        self.lbl_uid.setText(f"UID: {uid}")
        self.lbl_phone.setText(f"WA: {phone}" if phone != "N/A" else tr("gui.scan_tile.no_whatsapp"))
        self.lbl_time.setText(
            tr(
                "gui.scan_tile.recorded",
                time=show_time(payload.get("time_str", "")),
                date=show_date(payload.get("date_str", "")),
            )
        )

        # Color Banner Logic adhering to functional status palette
        if not is_registered:
            self.status_banner.setText(tr("gui.scan_tile.banner.unregistered"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_ERROR}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_ERROR_BG}; color: {COLOR_ERROR_TEXT}; border: 2px solid #F87171; border-radius: 32px;"
            )
        elif event_type == "graduate_denied":
            self.status_banner.setText(tr("gui.scan_tile.banner.graduate_denied"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_ERROR}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_ERROR_BG}; color: {COLOR_ERROR_TEXT}; border: 2px solid #F87171; border-radius: 32px;"
            )
        elif event_type == "inactive_denied":
            self.status_banner.setText(tr("gui.scan_tile.banner.inactive_denied"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_ERROR}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_ERROR_BG}; color: {COLOR_ERROR_TEXT}; border: 2px solid #F87171; border-radius: 32px;"
            )
        elif event_type == "access_denied":
            self.status_banner.setText(tr("gui.scan_tile.banner.access_denied"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_ERROR}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_ERROR_BG}; color: {COLOR_ERROR_TEXT}; border: 2px solid #F87171; border-radius: 32px;"
            )
        elif event_type == "check_out":
            self.status_banner.setText(tr("gui.scan_tile.banner.check_out"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_ACCENT}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_ACCENT}; border: 2px solid {COLOR_INPUT_BORDER}; border-radius: 32px;"
            )
        elif status == "on_time":
            self.status_banner.setText(tr("gui.scan_tile.banner.on_time"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_SUCCESS}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_SUCCESS_BG}; color: {COLOR_SUCCESS_TEXT}; border: 2px solid #6EE7B7; border-radius: 32px;"
            )
        elif status == "late":
            self.status_banner.setText(tr("gui.scan_tile.banner.late"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_WARNING}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_WARNING_BG}; color: {COLOR_WARNING_TEXT}; border: 2px solid #FCD34D; border-radius: 32px;"
            )
        else:
            self.status_banner.setText(tr("gui.scan_tile.banner.granted"))
            self.status_banner.setStyleSheet(
                f"background-color: {COLOR_SUCCESS}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
            )
            self.avatar.setStyleSheet(
                f"background-color: {COLOR_SUCCESS_BG}; color: {COLOR_SUCCESS_TEXT}; border: 2px solid #6EE7B7; border-radius: 32px;"
            )

        # Start 6-second reset timer
        self.reset_timer.start()

    def set_gate_state(self, is_open: bool, dwell: int = 3):
        if is_open:
            self.gate_badge.setText(tr("gui.scan_tile.gate_open", seconds=dwell))
            self.gate_badge.setStyleSheet(
                f"background-color: {COLOR_SUCCESS_BG}; color: {COLOR_SUCCESS_TEXT}; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;"
            )
        else:
            self.gate_badge.setText(tr("gui.scan_tile.gate_closed"))
            self.gate_badge.setStyleSheet(
                f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 11px;"
            )

    def set_idle_state(self):
        self.status_banner.setText(tr("gui.scan_tile.ready"))
        self.status_banner.setStyleSheet(
            f"background-color: {COLOR_ACCENT}; color: #FFFFFF; padding: 10px; border-radius: 8px; font-weight: bold;"
        )
        self.lbl_name.setText(tr("gui.scan_tile.prompt"))
        self.avatar.setText("QP")
        self.avatar.setStyleSheet(
            f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_ACCENT}; border: 2px solid {COLOR_INPUT_BORDER}; border-radius: 32px;"
        )
        self.lbl_grade.setText(tr("gui.scan_tile.school"))
        self.lbl_uid.setText(tr("gui.scan_tile.reader_ready"))
        self.lbl_phone.setText(tr("gui.scan_tile.whatsapp_active"))
        self.lbl_time.setText(tr("gui.scan_tile.waiting"))


FEED_RESULT_COLORS = {
    "on_time": COLOR_SUCCESS_TEXT,
    "late": COLOR_WARNING_TEXT,
    "check_out": COLOR_ACCENT,
    "unregistered": COLOR_ERROR_TEXT,
    "graduate_denied": COLOR_ERROR_TEXT,
    "inactive_denied": COLOR_ERROR_TEXT,
    "access_denied": COLOR_ERROR_TEXT,
}


def feed_result(payload: dict) -> str:
    """The outcome of a scan, as a `gui.live.result` key."""
    event_type = payload.get("event_type")
    status = payload.get("status")
    if not payload.get("is_registered"):
        return "unregistered"
    if event_type in ("graduate_denied", "inactive_denied", "access_denied", "check_out"):
        return event_type
    if status in ("on_time", "late", "visit"):
        return status
    if event_type in ("check_in", "repeat_scan"):
        return event_type
    return "unknown"


class TypedBadgeInput(QWidget):
    """A Badge UID typed in Demo Mode, standing in for scanning that Badge."""

    badge_typed = Signal(str)

    def __init__(self, button_text: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.inp_uid = QLineEdit()
        self.inp_uid.setPlaceholderText(tr("gui.demo.uid_placeholder"))
        self.inp_uid.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 6px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; font-family: monospace;"
        )
        self.inp_uid.returnPressed.connect(self._use_uid)
        layout.addWidget(self.inp_uid, stretch=1)

        self.btn_use = QPushButton(button_text or tr("gui.demo.use_uid"))
        self.btn_use.setStyleSheet(
            f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_ACCENT}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 6px 10px; font-weight: 500;"
        )
        self.btn_use.clicked.connect(self._use_uid)
        layout.addWidget(self.btn_use)

    def _use_uid(self):
        uid = database.normalize_badge_uid(self.inp_uid.text())
        if uid:
            self.badge_typed.emit(uid)


def badge_uid_input(settings: Settings, placeholder_key: str) -> QLineEdit:
    """The field a scanned Badge UID fills in; only Demo Mode lets the UID be typed into it."""
    field = QLineEdit()
    field.setPlaceholderText(tr(placeholder_key))
    field.setReadOnly(not settings.demo_mode)
    return field


# ---------------------------------------------------------------------------
# Independent Dedicated Window: Live Access Control
# (Lets the operator keep using the main window at the same time)
# ---------------------------------------------------------------------------
class LiveAccessWindow(QMainWindow):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle(tr("gui.live.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(940, 620)
        self.resize(1020, 680)
        self._init_ui()

        # Connect signals
        self.worker.scan_event.connect(self.on_scan_event)
        self.worker.gate_state.connect(self.on_gate_state)
        self.worker.mode_changed.connect(self.on_mode_changed)

    def _init_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {COLOR_BG_LIGHT};")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # Header Bar
        header = QHBoxLayout()
        header.setSpacing(12)

        # Logo with smooth circular rounded corners
        logo_file = LOGO_PNG if LOGO_PNG.exists() else LOGO_PATH
        if logo_file.exists():
            lbl_logo = QLabel()
            raw_pix = QPixmap(str(logo_file)).scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = get_rounded_pixmap(raw_pix, radius=12)
            lbl_logo.setPixmap(pix)
            header.addWidget(lbl_logo)

        brand_box = QVBoxLayout()
        lbl_b = QLabel(tr("gui.live.heading"))
        lbl_b.setFont(QFont("Arial", 16, QFont.Bold))
        lbl_b.setStyleSheet(f"color: {COLOR_PRIMARY}; letter-spacing: 0.5px;")
        self.lbl_mode_status = QLabel(tr("gui.live.mode_access"))
        self.lbl_mode_status.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT}; font-size: 11px; font-weight: bold;")
        brand_box.addWidget(lbl_b)
        brand_box.addWidget(self.lbl_mode_status)
        header.addLayout(brand_box)

        header.addStretch()

        self.btn_unlock = QPushButton(tr("gui.live.unlock"))
        self.btn_unlock.setFixedHeight(38)
        self.btn_unlock.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        self.btn_unlock.clicked.connect(self.worker.trigger_unlock)
        header.addWidget(self.btn_unlock)

        self.btn_visit = QPushButton(tr("gui.live.register_visit"))
        self.btn_visit.setFixedHeight(38)
        self.btn_visit.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: #FFFFFF;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #059669; }}
        """)
        self.btn_visit.clicked.connect(self.open_register_visit_dialog)
        header.addWidget(self.btn_visit)

        self.btn_fs = QPushButton(tr("gui.live.fullscreen"))
        self.btn_fs.setFixedHeight(38)
        self.btn_fs.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 0 12px; font-weight: 500;"
        )
        self.btn_fs.clicked.connect(self.toggle_fullscreen)
        header.addWidget(self.btn_fs)

        layout.addLayout(header)

        # Main Workspace: Left Column (Student Square) & Right Column (Live Scan Stream)
        content_split = QHBoxLayout()
        content_split.setSpacing(16)

        # LEFT: Student Square & Action Card
        left_box = QVBoxLayout()
        left_box.setSpacing(12)

        self.student_square = StudentSquareWidget(is_kiosk=False)
        left_box.addWidget(self.student_square)

        # Demo Mode only: a typed Badge UID, or a Badge no one holds, stands in for a scan
        self.sim_frame = QFrame()
        self.sim_frame.setObjectName("sim_frame")
        self.sim_frame.setStyleSheet(
            f"QFrame#sim_frame {{ background-color: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; border-radius: 10px; padding: 12px; }}"
        )
        sim_lay = QVBoxLayout(self.sim_frame)
        sim_lay.setSpacing(8)

        lbl_sim = QLabel(tr("gui.live.simulators"))
        lbl_sim.setStyleSheet(f"color: {COLOR_SECONDARY}; font-weight: bold; font-size: 11px;")
        sim_lay.addWidget(lbl_sim)

        self.typed_badge = TypedBadgeInput(tr("gui.live.simulate_scan"))
        self.typed_badge.badge_typed.connect(self.worker.process_uid)
        sim_lay.addWidget(self.typed_badge)

        self.btn_sim_unregistered = QPushButton(tr("gui.live.simulate_unregistered"))
        self.btn_sim_unregistered.setStyleSheet(
            f"background-color: {COLOR_ERROR_BG}; color: {COLOR_ERROR_TEXT}; border: 1px solid #FECACA; border-radius: 6px; padding: 6px 10px; font-weight: 500;"
        )
        self.btn_sim_unregistered.clicked.connect(lambda: self.worker.process_uid("99887766"))
        sim_lay.addWidget(self.btn_sim_unregistered)

        self.sim_frame.setVisible(self.worker.settings.demo_mode)
        left_box.addWidget(self.sim_frame)
        left_box.addStretch()
        content_split.addLayout(left_box, stretch=4)

        # RIGHT: Live Scan Stream
        right_box = QVBoxLayout()
        right_box.setSpacing(8)

        feed_head = QLabel(tr("gui.live.feed_title"))
        feed_head.setFont(QFont("Arial", 13, QFont.Bold))
        feed_head.setStyleSheet(f"color: {COLOR_PRIMARY};")
        right_box.addWidget(feed_head)

        self.feed_table = QTableWidget()
        self.feed_table.setColumnCount(5)
        self.feed_table.setHorizontalHeaderLabels(
            [
                tr("gui.live.column.time"),
                tr("gui.live.column.person"),
                tr("gui.live.column.role"),
                tr("gui.live.column.grade"),
                tr("gui.live.column.result"),
            ]
        )
        self.feed_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.feed_table.horizontalHeader().setStretchLastSection(True)
        self.feed_table.setColumnWidth(0, 95)
        self.feed_table.setColumnWidth(1, 200)
        self.feed_table.setColumnWidth(2, 90)
        self.feed_table.setColumnWidth(3, 80)
        self.feed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.feed_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.feed_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_PRIMARY};
                gridline-color: #EBF2F7;
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QHeaderView::section {{
                background-color: {COLOR_SURFACE_ALT};
                color: {COLOR_PRIMARY};
                font-weight: bold;
                border: none;
                padding: 6px;
            }}
        """)
        right_box.addWidget(self.feed_table)
        content_split.addLayout(right_box, stretch=5)

        layout.addLayout(content_split)

    def rebuild(self):
        """Build the window again, in the School Language now set."""
        self.setWindowTitle(tr("gui.live.window_title"))
        self._init_ui()
        self.on_mode_changed(self.worker.rfid_mode)
        if self.isFullScreen():
            self.btn_fs.setText(tr("gui.live.exit_fullscreen"))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_fs.setText(tr("gui.live.fullscreen"))
        else:
            self.showFullScreen()
            self.btn_fs.setText(tr("gui.live.exit_fullscreen"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            self.btn_fs.setText(tr("gui.live.fullscreen"))
        else:
            super().keyPressEvent(event)

    def open_register_visit_dialog(self):
        dlg = RegisterVisitDialog(self.worker, self)
        dlg.exec()

    def showEvent(self, event):
        super().showEvent(event)
        if self.worker.rfid_mode != RFIDMode.CAPTURE:
            self.worker.set_rfid_mode(RFIDMode.ACCESS_CONTROL)

    def closeEvent(self, event):
        event.accept()

    def on_mode_changed(self, mode: str):
        if mode == RFIDMode.CAPTURE:
            self.lbl_mode_status.setText(tr("gui.live.mode_capture"))
            self.lbl_mode_status.setStyleSheet(f"color: {COLOR_WARNING_TEXT}; font-size: 11px; font-weight: bold;")
        elif mode == RFIDMode.ACCESS_CONTROL:
            self.lbl_mode_status.setText(tr("gui.live.mode_access"))
            self.lbl_mode_status.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT}; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_mode_status.setText(tr("gui.live.mode_standby"))
            self.lbl_mode_status.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px; font-weight: bold;")

    def on_scan_event(self, payload: dict):
        self.student_square.update_scan(payload)

        # Prepend to live table
        self.feed_table.insertRow(0)
        self.feed_table.setItem(0, 0, QTableWidgetItem(show_time(payload.get("time_str", ""))))
        self.feed_table.setItem(0, 1, QTableWidgetItem(payload.get("full_name", "")))
        self.feed_table.setItem(0, 2, QTableWidgetItem(role_text(payload.get("role"))))
        self.feed_table.setItem(0, 3, QTableWidgetItem(payload.get("grade_sec", "")))

        result = feed_result(payload)
        item_status = QTableWidgetItem(tr(f"gui.live.result.{result}"))
        if result in FEED_RESULT_COLORS:
            item_status.setForeground(QColor(FEED_RESULT_COLORS[result]))
        self.feed_table.setItem(0, 4, item_status)

        if self.feed_table.rowCount() > 50:
            self.feed_table.removeRow(50)

    def on_gate_state(self, is_open: bool, dwell: int):
        self.student_square.set_gate_state(is_open, dwell)


def resolve_post_dialog_rfid_mode(preferred_mode: str | None = None) -> str:
    """Determine the proper RFID mode when a Badge dialog closes.
    If LiveAccessWindow is currently open, we must return to ACCESS_CONTROL so
    scans continue processing. Otherwise, fallback to STANDBY.
    """
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, LiveAccessWindow) and widget.isVisible():
            return RFIDMode.ACCESS_CONTROL
    if preferred_mode and preferred_mode != RFIDMode.CAPTURE:
        return preferred_mode
    return RFIDMode.STANDBY


# ---------------------------------------------------------------------------
# Dialog: Admin Approval
# (By scanning an Admin's Badge or typing the Admin Secret Key; adding another
# Admin takes the scan alone)
# ---------------------------------------------------------------------------
class AdminAuthDialog(QDialog):
    def __init__(
        self,
        worker: HardwareWorker,
        parent=None,
        operation_title: str | None = None,
        allow_secret_key: bool = True,
    ):
        super().__init__(parent)
        self.worker = worker
        self.allow_secret_key = allow_secret_key
        self.auth_token: str | None = None
        self.setWindowTitle(tr("gui.admin_auth.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(460)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        # Save previous mode and set CAPTURE mode
        self.previous_mode = self.worker.rfid_mode
        self._rfid_connected = True
        self.worker.badge_captured.connect(self.on_rfid_captured)
        self.worker.set_rfid_mode(RFIDMode.CAPTURE)
        self.worker.send_screen("lcd.admin_auth")

        self._init_ui(operation_title or tr("gui.admin_auth.default_operation"))

    def _init_ui(self, operation_title: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel(tr("gui.admin_auth.heading"))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        layout.addWidget(title)

        description_key = (
            "gui.admin_auth.description" if self.allow_secret_key else "gui.admin_auth.description_scan_only"
        )
        desc = QLabel(tr(description_key, operation=operation_title))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc)

        # RFID Scan Banner
        self.scan_box = QFrame()
        self.scan_box.setObjectName("auth_scan_box")
        self.scan_box.setStyleSheet(f"""
            QFrame#auth_scan_box {{
                background-color: {COLOR_SURFACE_ALT};
                border: 2px dashed {COLOR_ACCENT};
                border-radius: 8px;
                padding: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        s_lay = QVBoxLayout(self.scan_box)
        s_lay.setAlignment(Qt.AlignCenter)

        self.lbl_scan = QLabel(tr("gui.admin_auth.reader_ready"))
        self.lbl_scan.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_scan.setStyleSheet(f"color: {COLOR_ACCENT};")
        self.lbl_scan.setAlignment(Qt.AlignCenter)
        s_lay.addWidget(self.lbl_scan)

        self.lbl_scan_sub = QLabel(tr("gui.admin_auth.tap_admin_badge"))
        self.lbl_scan_sub.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        self.lbl_scan_sub.setAlignment(Qt.AlignCenter)
        s_lay.addWidget(self.lbl_scan_sub)
        layout.addWidget(self.scan_box)

        self.typed_badge = TypedBadgeInput()
        self.typed_badge.badge_typed.connect(self.on_rfid_captured)
        self.typed_badge.setVisible(self.worker.settings.demo_mode)
        layout.addWidget(self.typed_badge)

        # The Admin Secret Key, behind a divider
        self.key_box = QWidget()
        key_lay = QVBoxLayout(self.key_box)
        key_lay.setContentsMargins(0, 0, 0, 0)
        key_lay.setSpacing(6)
        div_lay = QHBoxLayout()
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setStyleSheet(f"color: {COLOR_BORDER};")
        div_lbl = QLabel(tr("gui.admin_auth.or_key"))
        div_lbl.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet(f"color: {COLOR_BORDER};")
        div_lay.addWidget(line1)
        div_lay.addWidget(div_lbl)
        div_lay.addWidget(line2)
        key_lay.addLayout(div_lay)

        lbl_key = QLabel(tr("gui.admin_auth.key_label"))
        lbl_key.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold; font-size: 12px;")
        key_lay.addWidget(lbl_key)

        self.inp_key = QLineEdit()
        self.inp_key.setEchoMode(QLineEdit.Password)
        self.inp_key.setPlaceholderText(tr("gui.admin_auth.key_placeholder"))
        self.inp_key.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 8px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        self.inp_key.returnPressed.connect(self.verify_key)
        key_lay.addWidget(self.inp_key)
        self.key_box.setVisible(self.allow_secret_key)
        layout.addWidget(self.key_box)

        self.lbl_error = QLabel("")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setStyleSheet(f"color: {COLOR_ERROR_TEXT}; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.lbl_error)

        # Buttons
        btn_box = QHBoxLayout()
        self.btn_auth = QPushButton(tr("gui.admin_auth.approve"))
        self.btn_auth.setFixedHeight(38)
        self.btn_auth.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        self.btn_auth.clicked.connect(self.verify_key)
        self.btn_auth.setVisible(self.allow_secret_key)
        btn_box.addWidget(self.btn_auth, stretch=2)

        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(38)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel, stretch=1)
        layout.addLayout(btn_box)

    @Slot(str)
    def on_rfid_captured(self, uid: str):
        conn = database.connect(self.worker.settings.database_path)
        user = database.get_user_by_badge_uid(conn, uid)
        conn.close()

        if user and user.get("role") == "admin" and user.get("is_active"):
            self.auth_token = uid
            self.accept()
        else:
            self.lbl_error.setText(tr("gui.admin_auth.not_admin", uid=uid))
            self.scan_box.setStyleSheet(f"""
                QFrame#auth_scan_box {{
                    background-color: {COLOR_ERROR_BG};
                    border: 2px solid {COLOR_ERROR};
                    border-radius: 8px;
                    padding: 12px;
                }}
                QLabel {{
                    border: none;
                    background: transparent;
                }}
            """)
            self.lbl_scan.setText(tr("gui.admin_auth.badge_refused"))
            self.lbl_scan.setStyleSheet(f"color: {COLOR_ERROR_TEXT};")
            self.lbl_scan_sub.setText(tr("gui.admin_auth.no_admin_role"))

    def verify_key(self):
        if not self.allow_secret_key:
            return
        typed = self.inp_key.text().strip()
        if not typed:
            self.lbl_error.setText(tr("gui.admin_auth.key_empty"))
            return

        conn = database.connect(self.worker.settings.database_path)
        school = school_settings.load(conn)
        conn.close()
        if school is not None and school_settings.verify_secret_key(typed, school.admin_secret_key_hash):
            self.auth_token = typed
            self.accept()
        else:
            self.lbl_error.setText(tr("gui.admin_auth.key_wrong"))

    def _cleanup_rfid(self):
        if getattr(self, "_rfid_connected", False):
            try:
                self.worker.badge_captured.disconnect(self.on_rfid_captured)
            except Exception:
                pass
            self._rfid_connected = False
            next_mode = resolve_post_dialog_rfid_mode(getattr(self, "previous_mode", None))
            self.worker.set_rfid_mode(next_mode)
            self.worker.send_idle_screen()

    def accept(self):
        self._cleanup_rfid()
        super().accept()

    def reject(self):
        self._cleanup_rfid()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_rfid()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Dialog: Scan a Badge to find whose it is
# ---------------------------------------------------------------------------
class BadgeScanDialog(QDialog):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.badge_uid: str | None = None
        self.setWindowTitle(tr("gui.badge_scan.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(420)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel(tr("gui.badge_scan.heading"))
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)
        hint = QLabel(tr("gui.badge_scan.tap_badge"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        layout.addWidget(hint)

        self.typed_badge = TypedBadgeInput()
        self.typed_badge.badge_typed.connect(self.on_rfid_captured)
        self.typed_badge.setVisible(self.worker.settings.demo_mode)
        layout.addWidget(self.typed_badge)

        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(36)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        self.previous_mode = self.worker.rfid_mode
        self._rfid_connected = True
        self.worker.badge_captured.connect(self.on_rfid_captured)
        self.worker.set_rfid_mode(RFIDMode.CAPTURE)
        self.worker.send_screen("lcd.badge_search")

    @Slot(str)
    def on_rfid_captured(self, uid: str):
        self.badge_uid = uid
        self.accept()

    def _cleanup_rfid(self):
        if getattr(self, "_rfid_connected", False):
            try:
                self.worker.badge_captured.disconnect(self.on_rfid_captured)
            except Exception:
                pass
            self._rfid_connected = False
            self.worker.set_rfid_mode(resolve_post_dialog_rfid_mode(self.previous_mode))
            self.worker.send_idle_screen()

    def accept(self):
        self._cleanup_rfid()
        super().accept()

    def reject(self):
        self._cleanup_rfid()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_rfid()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Modal Dialog: Register a Visitor (name, ID document, and an optional Badge)
# ---------------------------------------------------------------------------
class RegisterVisitDialog(QDialog):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle(tr("gui.visit.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(500)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        self.previous_mode = self.worker.rfid_mode
        self._rfid_connected = True
        self.worker.badge_captured.connect(self.on_rfid_captured)
        self.worker.set_rfid_mode(RFIDMode.CAPTURE)
        self.worker.send_screen("lcd.visit_registration")

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        title = QLabel(tr("gui.visit.heading"))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        layout.addWidget(title)

        desc = QLabel(tr("gui.visit.description"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px; line-height: 1.4;")
        layout.addWidget(desc)

        # RFID Scan Banner
        self.scan_box = QFrame()
        self.scan_box.setStyleSheet(f"""
            background-color: {COLOR_SURFACE_ALT};
            border: 1px dashed {COLOR_ACCENT};
            border-radius: 8px;
            padding: 10px;
        """)
        s_lay = QVBoxLayout(self.scan_box)
        s_lay.setAlignment(Qt.AlignCenter)
        self.lbl_scan = QLabel(tr("gui.visit.reader_ready"))
        self.lbl_scan.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_scan.setStyleSheet(f"color: {COLOR_ACCENT};")
        self.lbl_scan.setAlignment(Qt.AlignCenter)
        s_lay.addWidget(self.lbl_scan)
        self.lbl_scan_sub = QLabel(tr("gui.visit.tap_badge"))
        self.lbl_scan_sub.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        self.lbl_scan_sub.setAlignment(Qt.AlignCenter)
        s_lay.addWidget(self.lbl_scan_sub)
        layout.addWidget(self.scan_box)

        # Form
        form_frame = QFrame()
        f_lay = QFormLayout(form_frame)
        f_lay.setSpacing(10)

        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText(tr("gui.visit.name_placeholder"))
        self.inp_name.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 7px 10px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        f_lay.addRow(tr("gui.visit.name_label"), self.inp_name)

        self.inp_id = QLineEdit()
        self.inp_id.setPlaceholderText(tr("gui.visit.id_placeholder"))
        self.inp_id.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 7px 10px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        f_lay.addRow(tr("gui.visit.id_label"), self.inp_id)

        self.inp_uid = badge_uid_input(self.worker.settings, "gui.visit.uid_placeholder")
        self.inp_uid.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 7px 10px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; font-family: monospace;"
        )
        f_lay.addRow(tr("gui.visit.uid_label"), self.inp_uid)

        layout.addWidget(form_frame)

        # Buttons
        btn_box = QHBoxLayout()
        self.btn_submit = QPushButton(tr("gui.visit.submit"))
        self.btn_submit.setFixedHeight(40)
        self.btn_submit.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: #FFFFFF;
                font-weight: bold;
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background-color: #059669; }}
        """)
        self.btn_submit.clicked.connect(self.submit_visit)
        btn_box.addWidget(self.btn_submit, stretch=2)

        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(40)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel, stretch=1)
        layout.addLayout(btn_box)

    @Slot(str)
    def on_rfid_captured(self, uid: str):
        self.inp_uid.setText(uid)
        self.lbl_scan.setText(tr("gui.visit.badge_detected"))
        self.lbl_scan.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT};")
        self.lbl_scan_sub.setText(tr("gui.visit.badge_assigned", uid=uid))
        self.scan_box.setStyleSheet(f"""
            background-color: {COLOR_SUCCESS_BG};
            border: 1px solid {COLOR_SUCCESS};
            border-radius: 8px;
            padding: 10px;
        """)
        if not self.inp_name.text().strip():
            self.inp_name.setFocus()

    def submit_visit(self):
        name = self.inp_name.text().strip()
        doc_id = self.inp_id.text().strip()
        if not name or not doc_id:
            QMessageBox.warning(self, tr("gui.common.missing_fields"), tr("gui.visit.missing"))
            return

        badge_uid = database.normalize_badge_uid(self.inp_uid.text())
        now = datetime.now()
        conn = database.connect(self.worker.settings.database_path)
        try:
            visitor = None
            if badge_uid:
                lent = admin.assign_visitor_badge(conn, self.worker.settings, badge_uid, name, now=now)
                if not lent.success:
                    QMessageBox.critical(self, tr("gui.visit.error_title"), lent.error)
                    return
                visitor = lent.user
            res = access_control.sign_in_visitor(conn, name, doc_id, visitor, now=now)
        finally:
            conn.close()

        self.worker.send_command(res.reply_line)
        self.worker.gate_state.emit(True, 3)

        payload = {
            "uid": badge_uid or "--",
            "full_name": name,
            "role": "visitor",
            "grade_sec": f"ID: {doc_id}",
            "time_str": now.strftime("%H:%M:%S"),
            "date_str": now.strftime("%Y-%m-%d"),
            "event_type": res.event_type,
            "status": res.status,
            "phone": "N/A",
            "avatar_initials": "".join([p[0] for p in name.split()[:2]]).upper() if name else "VI",
            "is_registered": True,
        }
        self.worker.scan_event.emit(payload)
        self.worker._log_terminal("VISIT", f"Visitor signed in: {name} ({doc_id}) | UID: {badge_uid or 'none'}")
        if badge_uid:
            done = tr("gui.visit.done", name=name, id=doc_id, uid=badge_uid)
        else:
            done = tr("gui.visit.done_no_badge", name=name, id=doc_id)
        QMessageBox.information(self, tr("gui.visit.done_title"), done)
        self.accept()

    def _cleanup_rfid(self):
        if getattr(self, "_rfid_connected", False):
            try:
                self.worker.badge_captured.disconnect(self.on_rfid_captured)
            except Exception:
                pass
            self._rfid_connected = False
            next_mode = resolve_post_dialog_rfid_mode(getattr(self, "previous_mode", None))
            self.worker.set_rfid_mode(next_mode)
            self.worker.send_idle_screen()

    def accept(self):
        self._cleanup_rfid()
        super().accept()

    def reject(self):
        self._cleanup_rfid()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_rfid()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Modal Dialog: Register a Badge by scanning it, with up to two Guardians
# (mother and father with phones and emails, plus the Family Code)
# ---------------------------------------------------------------------------
class RegisterBadgeDialog(QDialog):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.setWindowTitle(tr("gui.register.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(600)
        self.resize(600, 840)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        # Save previous mode and set CAPTURE mode
        self.previous_mode = self.worker.rfid_mode
        self._rfid_connected = True
        # While an Admin scans to approve a new Admin, that scan is not the Badge being registered.
        self._approving = False
        self.worker.badge_captured.connect(self.on_rfid_captured)
        self.worker.set_rfid_mode(RFIDMode.CAPTURE)
        self.worker.send_screen("lcd.badge_registration")

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(10)

        # Header Title
        title = QLabel(tr("gui.register.heading"))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        main_layout.addWidget(title)

        # Visual RFID Scanner Box
        self.scan_box = QFrame()
        self.scan_box.setObjectName("reg_scan_box")
        self.scan_box.setStyleSheet(f"""
            QFrame#reg_scan_box {{
                background-color: {COLOR_SURFACE_ALT};
                border: 2px dashed {COLOR_ACCENT};
                border-radius: 10px;
                padding: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        s_lay = QVBoxLayout(self.scan_box)
        s_lay.setAlignment(Qt.AlignCenter)

        self.lbl_scan_icon = QLabel(tr("gui.register.tap_badge"))
        self.lbl_scan_icon.setFont(QFont("Arial", 12, QFont.Bold))
        self.lbl_scan_icon.setAlignment(Qt.AlignCenter)
        self.lbl_scan_icon.setStyleSheet(f"color: {COLOR_ACCENT};")
        s_lay.addWidget(self.lbl_scan_icon)

        self.lbl_scan_status = QLabel(tr("gui.register.tap_hint"))
        self.lbl_scan_status.setAlignment(Qt.AlignCenter)
        self.lbl_scan_status.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        s_lay.addWidget(self.lbl_scan_status)
        main_layout.addWidget(self.scan_box)

        # Scrollable Form Area for student and both parents
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        form_layout = QVBoxLayout(scroll_content)
        form_layout.setContentsMargins(0, 0, 8, 0)
        form_layout.setSpacing(8)

        # SECTION 1: Badge holder's details
        student_box = QGroupBox(tr("gui.register.holder_box"))
        student_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        s_form = QFormLayout(student_box)
        s_form.setSpacing(6)

        # UID Field
        self.inp_uid = badge_uid_input(self.worker.settings, "gui.register.uid_placeholder")
        self.inp_uid.setFont(QFont("Arial", 12, QFont.Bold))
        self.inp_uid.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_ACCENT}; padding: 6px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        self.inp_uid.textChanged.connect(self.on_uid_text_changed)
        s_form.addRow(tr("gui.common.badge_uid"), self.inp_uid)

        self.lbl_uid_validation = QLabel("")
        self.lbl_uid_validation.setWordWrap(True)
        self.lbl_uid_validation.setStyleSheet("font-size: 11px; font-weight: bold;")
        s_form.addRow("", self.lbl_uid_validation)

        # Name Field
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText(tr("gui.register.name_placeholder"))
        self.inp_name.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        s_form.addRow(tr("gui.common.full_name"), self.inp_name)

        # Role Field
        self.combo_role = QComboBox()
        self.combo_role.addItems([role_text(r) for r in ("student", "teacher", "admin", "visitor")])
        self.combo_role.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        self.combo_role.currentIndexChanged.connect(self.on_role_changed)
        s_form.addRow(tr("gui.common.role"), self.combo_role)

        # Grade Field
        self.lbl_grade = QLabel(tr("gui.common.grade"))
        self.lbl_grade.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.combo_grade = QComboBox()
        fill_grade_combo(self.combo_grade)
        self.combo_grade.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        s_form.addRow(self.lbl_grade, self.combo_grade)

        # Section Field (Only for students; teachers teach the entire grade without section)
        self.lbl_sec = QLabel(tr("gui.common.section"))
        self.lbl_sec.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.combo_sec = QComboBox()
        fill_section_combo(self.combo_sec)
        self.combo_sec.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        s_form.addRow(self.lbl_sec, self.combo_sec)

        # Family ID Field (Auto-suggested correlative FAM-XXXX or sibling-linked)
        conn = database.connect(self.worker.settings.database_path)
        next_fam = database.get_next_family_id(conn)
        conn.close()

        self.lbl_family_id = QLabel(tr("gui.common.family_code"))
        self.lbl_family_id.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.inp_family_id = QLineEdit(next_fam)
        self.inp_family_id.setPlaceholderText(tr("gui.common.family_code_placeholder"))
        self.inp_family_id.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; font-weight: bold;"
        )
        s_form.addRow(self.lbl_family_id, self.inp_family_id)

        self.lbl_family_hint = QLabel(tr("gui.register.family_hint", code=next_fam))
        self.lbl_family_hint.setWordWrap(True)
        self.lbl_family_hint.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        s_form.addRow("", self.lbl_family_hint)

        form_layout.addWidget(student_box)

        # SECTION 2: Mother / Guardian 1 (primary)
        self.g1_box = QGroupBox(tr("gui.common.guardian1_title"))
        self.g1_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        g1_form = QFormLayout(self.g1_box)
        g1_form.setSpacing(6)

        self.inp_g1_name = QLineEdit()
        self.inp_g1_name.setPlaceholderText(tr("gui.register.guardian1_name_placeholder"))
        self.inp_g1_name.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        g1_form.addRow(tr("gui.common.name"), self.inp_g1_name)

        self.inp_g1_phone = QLineEdit()
        self.inp_g1_phone.setPlaceholderText(tr("gui.register.guardian1_phone_placeholder"))
        self.inp_g1_phone.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        self.inp_g1_phone.textChanged.connect(self._check_sibling_phone)
        g1_form.addRow(tr("gui.common.whatsapp_phone"), self.inp_g1_phone)

        self.inp_g1_email = QLineEdit()
        self.inp_g1_email.setPlaceholderText(tr("gui.register.guardian1_email_placeholder"))
        self.inp_g1_email.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        g1_form.addRow(tr("gui.common.email"), self.inp_g1_email)

        form_layout.addWidget(self.g1_box)

        # SECTION 3: Father / Guardian 2 (secondary, optional)
        self.g2_box = QGroupBox(tr("gui.common.guardian2_title"))
        self.g2_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        g2_form = QFormLayout(self.g2_box)
        g2_form.setSpacing(6)

        self.inp_g2_name = QLineEdit()
        self.inp_g2_name.setPlaceholderText(tr("gui.register.guardian2_name_placeholder"))
        self.inp_g2_name.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        g2_form.addRow(tr("gui.common.name"), self.inp_g2_name)

        self.inp_g2_phone = QLineEdit()
        self.inp_g2_phone.setPlaceholderText(tr("gui.register.guardian2_phone_placeholder"))
        self.inp_g2_phone.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        self.inp_g2_phone.textChanged.connect(self._check_sibling_phone)
        g2_form.addRow(tr("gui.common.whatsapp_phone"), self.inp_g2_phone)

        self.inp_g2_email = QLineEdit()
        self.inp_g2_email.setPlaceholderText(tr("gui.register.guardian2_email_placeholder"))
        self.inp_g2_email.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        g2_form.addRow(tr("gui.common.email"), self.inp_g2_email)

        form_layout.addWidget(self.g2_box)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        # Buttons Bar
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)

        self.btn_save = QPushButton(tr("gui.register.save"))
        self.btn_save.setFixedHeight(40)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: {COLOR_INPUT_BORDER}; }}
        """)
        self.btn_save.clicked.connect(self.save_user)
        self.btn_save.setEnabled(False)
        btn_box.addWidget(self.btn_save, stretch=2)

        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(40)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; font-weight: 500;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel, stretch=1)

        main_layout.addLayout(btn_box)

    def _check_sibling_phone(self):
        p1 = self.inp_g1_phone.text().strip()
        p2 = self.inp_g2_phone.text().strip()
        target_phone = p1 if len(p1) >= 8 else (p2 if len(p2) >= 8 else "")
        if target_phone:
            conn = database.connect(self.worker.settings.database_path)
            # Guardian phones are stored the way admin.add_user writes them.
            match = database.find_family_by_guardian_phone(conn, sms.format_global_phone(target_phone) or target_phone)
            conn.close()
            if match:
                self.inp_family_id.setText(match["family_id"])
                self.lbl_family_hint.setText(
                    tr("gui.register.family_linked", code=match["family_id"], sibling=match["sibling_name"])
                )
                self.lbl_family_hint.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: 11px; font-weight: bold;")

    @Slot(str)
    def on_rfid_captured(self, uid: str):
        if self._approving:
            return
        self.inp_uid.setText(uid)
        self.scan_box.setStyleSheet(f"""
            QFrame#reg_scan_box {{
                background-color: {COLOR_SUCCESS_BG};
                border: 2px solid {COLOR_SUCCESS};
                border-radius: 10px;
                padding: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_scan_icon.setText(tr("gui.register.badge_detected"))
        self.lbl_scan_icon.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT};")
        self.lbl_scan_status.setText(tr("gui.register.badge_captured", uid=uid))
        self.inp_name.setFocus()

    def on_uid_text_changed(self, text: str):
        uid = text.strip().upper()
        if not uid:
            self.lbl_uid_validation.setText("")
            self.btn_save.setEnabled(False)
            return

        conn = database.connect(self.worker.settings.database_path)
        existing = database.get_user_by_badge_uid(conn, uid)
        conn.close()

        if existing:
            self.lbl_uid_validation.setText(
                tr("gui.register.badge_taken", name=existing["full_name"], role=role_text(existing["role"]))
            )
            self.lbl_uid_validation.setStyleSheet(f"color: {COLOR_ERROR_TEXT}; font-size: 11px; font-weight: bold;")
            self.btn_save.setEnabled(False)
        else:
            self.lbl_uid_validation.setText(tr("gui.register.badge_free"))
            self.lbl_uid_validation.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT}; font-size: 11px; font-weight: bold;")
            self.btn_save.setEnabled(True)

    def on_role_changed(self, idx: int):
        is_student = idx == 0
        is_teacher = idx == 1

        # Grade is shown for students (their Grade) and teachers (the Grade they teach)
        self.lbl_grade.setVisible(is_student or is_teacher)
        self.combo_grade.setVisible(is_student or is_teacher)
        self.lbl_grade.setText(tr("gui.common.grade_taught") if is_teacher else tr("gui.common.grade"))

        # Section is ONLY for students; completely hidden for teachers, admins, and visitors
        self.lbl_sec.setVisible(is_student)
        self.combo_sec.setVisible(is_student)

        # Family ID and Guardians are ONLY for students
        self.lbl_family_id.setVisible(is_student)
        self.inp_family_id.setVisible(is_student)
        self.lbl_family_hint.setVisible(is_student)

        self.g1_box.setVisible(is_student)
        self.g2_box.setVisible(is_student)

    def save_user(self):
        uid = self.inp_uid.text().strip().upper()
        name = self.inp_name.text().strip()
        if not uid or not name:
            QMessageBox.warning(self, tr("gui.common.missing_fields"), tr("gui.register.required"))
            return

        role_map = {0: "student", 1: "teacher", 2: "admin", 3: "visitor"}
        role = role_map.get(self.combo_role.currentIndex(), "student")
        is_student = role == "student"
        is_teacher = role == "teacher"

        grade = self.combo_grade.currentData() if (is_student or is_teacher) else None
        section = self.combo_sec.currentData() if is_student else None
        family_id = self.inp_family_id.text().strip().upper() if is_student else None

        guardians: list[admin.GuardianData] = []
        if is_student:
            g1_name = self.inp_g1_name.text().strip()
            g1_phone = self.inp_g1_phone.text().strip()
            g1_email = self.inp_g1_email.text().strip()
            if g1_name and g1_phone:
                guardians.append(admin.GuardianData(name=g1_name, phone=g1_phone, email=g1_email))
            elif bool(g1_name) != bool(g1_phone):
                QMessageBox.warning(self, tr("gui.common.incomplete_data"), tr("gui.common.guardian1_incomplete"))
                return

            g2_name = self.inp_g2_name.text().strip()
            g2_phone = self.inp_g2_phone.text().strip()
            g2_email = self.inp_g2_email.text().strip()
            if g2_name and g2_phone:
                guardians.append(admin.GuardianData(name=g2_name, phone=g2_phone, email=g2_email))
            elif bool(g2_name) != bool(g2_phone):
                QMessageBox.warning(self, tr("gui.common.incomplete_data"), tr("gui.common.guardian2_incomplete"))
                return

        approving_uid = None
        if role == "admin" and self._school_has_an_admin():
            approving_uid = self._admin_scan_approval(name)
            if approving_uid is None:
                return

        conn = database.connect(self.worker.settings.database_path)
        res = admin.add_user(
            conn,
            self.worker.settings,
            badge_uid=uid,
            full_name=name,
            role=role,
            grade=grade if is_student else None,
            section=section if is_student else None,
            taught_grade=grade if is_teacher else None,
            guardians=guardians if is_student else [],
            approving_uid=approving_uid,
            family_id=family_id if is_student else None,
        )
        conn.close()

        if res.success:
            self.worker.send_screen("lcd.badge_added")
            QMessageBox.information(self, tr("gui.register.done_title"), tr("gui.register.done", uid=uid, name=name))
            self.accept()
        else:
            QMessageBox.critical(self, tr("gui.register.error_title"), res.error)

    def _school_has_an_admin(self) -> bool:
        conn = database.connect(self.worker.settings.database_path)
        try:
            return (
                conn.execute("SELECT 1 FROM users WHERE role = 'admin' AND is_active = 1 LIMIT 1").fetchone()
                is not None
            )
        finally:
            conn.close()

    def _admin_scan_approval(self, name: str) -> str | None:
        """The Badge UID of the Admin who scans to approve adding `name` as another Admin, or
        None if no one does; the Admin Secret Key cannot stand in for that scan."""
        self._approving = True
        try:
            auth = AdminAuthDialog(
                self.worker, self, tr("gui.register.add_admin_operation", name=name), allow_secret_key=False
            )
            approved = auth.exec() == QDialog.DialogCode.Accepted
            return auth.auth_token if approved else None
        finally:
            self._approving = False
            self.worker.set_rfid_mode(RFIDMode.CAPTURE)
            self.worker.send_screen("lcd.badge_registration")

    def _cleanup_rfid(self):
        if getattr(self, "_rfid_connected", False):
            try:
                self.worker.badge_captured.disconnect(self.on_rfid_captured)
            except Exception:
                pass
            self._rfid_connected = False
            next_mode = resolve_post_dialog_rfid_mode(getattr(self, "previous_mode", None))
            self.worker.set_rfid_mode(next_mode)
            self.worker.send_idle_screen()

    def accept(self):
        self._cleanup_rfid()
        super().accept()

    def reject(self):
        self._cleanup_rfid()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_rfid()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Modal Dialog: Edit a Badge / User after Admin Approval
# ---------------------------------------------------------------------------
class EditBadgeDialog(QDialog):
    def __init__(self, target_uid: str, approving_uid: str, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.target_uid = target_uid
        self.approving_uid = approving_uid
        self.worker = worker
        self.setWindowTitle(tr("gui.edit.window_title", uid=target_uid))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(600)
        self.resize(600, 840)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        self.previous_mode = self.worker.rfid_mode
        self._rfid_connected = True
        self.worker.badge_captured.connect(self.on_rfid_captured)
        self.worker.set_rfid_mode(RFIDMode.CAPTURE)
        self.worker.send_screen("lcd.badge_reassign")

        conn = database.connect(self.worker.settings.database_path)
        self.user_data = database.get_user_by_badge_uid(conn, target_uid)
        conn.close()

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(10)

        title = QLabel(tr("gui.edit.heading", uid=self.target_uid))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        main_layout.addWidget(title)

        # Badge Change Banner (Optional)
        self.scan_box = QFrame()
        self.scan_box.setObjectName("edit_scan_box")
        self.scan_box.setStyleSheet(f"""
            QFrame#edit_scan_box {{
                background-color: {COLOR_SURFACE_ALT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 10px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        s_lay = QVBoxLayout(self.scan_box)
        s_lay.setAlignment(Qt.AlignCenter)

        self.lbl_scan_info = QLabel(tr("gui.edit.reassign_hint"))
        self.lbl_scan_info.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        self.lbl_scan_info.setAlignment(Qt.AlignCenter)
        s_lay.addWidget(self.lbl_scan_info)
        main_layout.addWidget(self.scan_box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        form_layout = QVBoxLayout(scroll_content)
        form_layout.setContentsMargins(0, 0, 8, 0)
        form_layout.setSpacing(8)

        # Section 1: User Data
        user_box = QGroupBox(tr("gui.edit.holder_box"))
        user_box.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                margin-top: 6px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }}
        """)
        u_form = QFormLayout(user_box)
        u_form.setSpacing(6)

        self.inp_uid = badge_uid_input(self.worker.settings, "gui.register.uid_placeholder")
        self.inp_uid.setText(self.target_uid)
        self.inp_uid.setFont(QFont("Arial", 12, QFont.Bold))
        self.inp_uid.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_ACCENT}; padding: 6px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        u_form.addRow(tr("gui.common.badge_uid"), self.inp_uid)

        current_name = self.user_data.get("full_name", "") if self.user_data else ""
        self.inp_name = QLineEdit(current_name)
        self.inp_name.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        u_form.addRow(tr("gui.common.full_name"), self.inp_name)

        role = self.user_data.get("role", "student") if self.user_data else "student"
        lbl_role = QLabel(tr("gui.edit.current_role", role=role_text(role).upper()))
        lbl_role.setStyleSheet(f"color: {COLOR_SECONDARY}; font-weight: bold; padding: 4px 0;")
        u_form.addRow(tr("gui.common.role"), lbl_role)

        is_student = role == "student"
        is_teacher = role == "teacher"

        if is_student:
            self.combo_grade = QComboBox()
            fill_grade_combo(self.combo_grade, self.user_data.get("grade"))
            self.combo_grade.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            u_form.addRow(tr("gui.common.grade"), self.combo_grade)

            self.combo_sec = QComboBox()
            fill_section_combo(self.combo_sec, self.user_data.get("section"))
            self.combo_sec.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            u_form.addRow(tr("gui.common.section"), self.combo_sec)

            curr_fam = str(self.user_data.get("family_id") or "")
            self.inp_family_id = QLineEdit(curr_fam)
            self.inp_family_id.setPlaceholderText(tr("gui.common.family_code_placeholder"))
            self.inp_family_id.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; font-weight: bold;"
            )
            u_form.addRow(tr("gui.common.family_code"), self.inp_family_id)

        elif is_teacher:
            self.combo_grade = QComboBox()
            fill_grade_combo(self.combo_grade, self.user_data.get("taught_grade"))
            self.combo_grade.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            u_form.addRow(tr("gui.common.grade_taught"), self.combo_grade)

        form_layout.addWidget(user_box)

        # Guardians (for students)
        if is_student:
            guardians = self.user_data.get("guardians", []) if self.user_data else []
            g1 = guardians[0] if len(guardians) > 0 else {}
            g2 = guardians[1] if len(guardians) > 1 else {}

            g1_box = QGroupBox(tr("gui.common.guardian1_title"))
            g1_box.setStyleSheet(f"""
                QGroupBox {{
                    font-weight: bold;
                    color: {COLOR_PRIMARY};
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 8px;
                    margin-top: 6px;
                    padding-top: 10px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }}
            """)
            g1_form = QFormLayout(g1_box)
            g1_form.setSpacing(6)
            self.inp_g1_name = QLineEdit(g1.get("name", ""))
            self.inp_g1_name.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g1_form.addRow(tr("gui.common.name"), self.inp_g1_name)

            self.inp_g1_phone = QLineEdit(g1.get("phone", ""))
            self.inp_g1_phone.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g1_form.addRow(tr("gui.common.whatsapp_phone"), self.inp_g1_phone)

            self.inp_g1_email = QLineEdit(g1.get("email") or "")
            self.inp_g1_email.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g1_form.addRow(tr("gui.common.email"), self.inp_g1_email)
            form_layout.addWidget(g1_box)

            g2_box = QGroupBox(tr("gui.common.guardian2_title"))
            g2_box.setStyleSheet(f"""
                QGroupBox {{
                    font-weight: bold;
                    color: {COLOR_PRIMARY};
                    border: 1px solid {COLOR_BORDER};
                    border-radius: 8px;
                    margin-top: 6px;
                    padding-top: 10px;
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 4px;
                }}
            """)
            g2_form = QFormLayout(g2_box)
            g2_form.setSpacing(6)
            self.inp_g2_name = QLineEdit(g2.get("name", ""))
            self.inp_g2_name.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g2_form.addRow(tr("gui.common.name"), self.inp_g2_name)

            self.inp_g2_phone = QLineEdit(g2.get("phone", ""))
            self.inp_g2_phone.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g2_form.addRow(tr("gui.common.whatsapp_phone"), self.inp_g2_phone)

            self.inp_g2_email = QLineEdit(g2.get("email") or "")
            self.inp_g2_email.setStyleSheet(
                f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
            )
            g2_form.addRow(tr("gui.common.email"), self.inp_g2_email)
            form_layout.addWidget(g2_box)

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        # Buttons
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)

        self.btn_save = QPushButton(tr("gui.edit.save"))
        self.btn_save.setFixedHeight(40)
        self.btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        self.btn_save.clicked.connect(self.save_modifications)
        btn_box.addWidget(self.btn_save, stretch=2)

        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(40)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; font-weight: 500;"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel, stretch=1)

        main_layout.addLayout(btn_box)

    @Slot(str)
    def on_rfid_captured(self, uid: str):
        if uid != self.target_uid:
            self.inp_uid.setText(uid)
            self.lbl_scan_info.setText(tr("gui.edit.new_badge", uid=uid))
            self.lbl_scan_info.setStyleSheet(f"color: {COLOR_SUCCESS_TEXT}; font-weight: bold; font-size: 11px;")

    def save_modifications(self):
        new_uid = self.inp_uid.text().strip().upper()
        name = self.inp_name.text().strip()
        if not new_uid or not name:
            QMessageBox.warning(self, tr("gui.common.missing_fields"), tr("gui.edit.required"))
            return

        role = self.user_data.get("role", "student") if self.user_data else "student"
        grade = self.combo_grade.currentData() if hasattr(self, "combo_grade") else None
        section = self.combo_sec.currentData() if hasattr(self, "combo_sec") else None
        family_id = self.inp_family_id.text().strip().upper() if hasattr(self, "inp_family_id") else None

        guardians: list[admin.GuardianData] | None = None
        if role == "student":
            guardians = []
            g1_name = self.inp_g1_name.text().strip()
            g1_phone = self.inp_g1_phone.text().strip()
            g1_email = self.inp_g1_email.text().strip()
            if g1_name and g1_phone:
                guardians.append(admin.GuardianData(name=g1_name, phone=g1_phone, email=g1_email))
            elif bool(g1_name) != bool(g1_phone):
                QMessageBox.warning(self, tr("gui.common.incomplete_data"), tr("gui.common.guardian1_incomplete"))
                return

            g2_name = self.inp_g2_name.text().strip()
            g2_phone = self.inp_g2_phone.text().strip()
            g2_email = self.inp_g2_email.text().strip()
            if g2_name and g2_phone:
                guardians.append(admin.GuardianData(name=g2_name, phone=g2_phone, email=g2_email))
            elif bool(g2_name) != bool(g2_phone):
                QMessageBox.warning(self, tr("gui.common.incomplete_data"), tr("gui.common.guardian2_incomplete"))
                return

        conn = database.connect(self.worker.settings.database_path)
        res = admin.modify_user(
            conn,
            target_badge_uid=self.target_uid,
            approving_uid=self.approving_uid,
            new_name=name,
            new_grade=grade if role == "student" else None,
            new_section=section if role == "student" else None,
            new_taught_grade=grade if role == "teacher" else None,
            new_guardians=guardians,
            new_badge_uid=new_uid if new_uid != self.target_uid else None,
            new_family_id=family_id,
        )
        conn.close()

        if res.success:
            self.worker.send_screen("lcd.badge_updated")
            QMessageBox.information(self, tr("gui.edit.done_title"), tr("gui.edit.done", uid=self.target_uid))
            self.accept()
        else:
            QMessageBox.critical(self, tr("gui.edit.error_title"), res.error)

    def _cleanup_rfid(self):
        if getattr(self, "_rfid_connected", False):
            try:
                self.worker.badge_captured.disconnect(self.on_rfid_captured)
            except Exception:
                pass
            self._rfid_connected = False
            next_mode = resolve_post_dialog_rfid_mode(getattr(self, "previous_mode", None))
            self.worker.set_rfid_mode(next_mode)
            self.worker.send_idle_screen()

    def accept(self):
        self._cleanup_rfid()
        super().accept()

    def reject(self):
        self._cleanup_rfid()
        super().reject()

    def closeEvent(self, event):
        self._cleanup_rfid()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Dialog: School statistics
# ---------------------------------------------------------------------------
class StatisticsDialog(QDialog):
    def __init__(self, stats: admin.SystemStatistics, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("gui.stats.window_title"))
        self.setWindowIcon(get_app_icon())
        self.resize(440, 660)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel(tr("gui.stats.heading"))
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        by_role = [
            (tr(f"gui.stats.role.{role}"), stats.users_by_role.get(role, 0))
            for role in ("student", "teacher", "admin", "visitor")
        ]
        groups = [
            (
                "gui.stats.students_by_grade",
                [(grade_text(rank), count) for rank, count in sorted(stats.students_by_grade.items())],
            ),
            (
                "gui.stats.teachers_by_grade",
                [(grade_text(rank), count) for rank, count in sorted(stats.teachers_by_grade.items())],
            ),
            ("gui.stats.by_role", by_role + [(tr("gui.stats.role.graduate"), stats.graduates)]),
            (
                "gui.stats.recent_check_ins",
                [(show_date(day.isoformat()), count) for day, count in stats.recent_check_ins],
            ),
        ]
        rows: list[tuple[str, str, bool]] = [
            (tr("gui.stats.total_users"), str(stats.total_users), False),
            (tr("gui.stats.total_check_ins"), str(stats.total_check_ins), False),
        ]
        for heading_key, counts in groups:
            if counts:
                rows.append((tr(heading_key), "", True))
                rows.extend((label, str(count), False) for label, count in counts)

        self.table = QTableWidget(len(rows), 2)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; border-radius: 8px; }}"
        )
        for row, (label, value, is_heading) in enumerate(rows):
            label_item = QTableWidgetItem(label)
            value_item = QTableWidgetItem(value)
            value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if is_heading:
                bold = QFont("Arial", 11, QFont.Weight.Bold)
                label_item.setFont(bold)
                label_item.setBackground(QColor(COLOR_SURFACE_ALT))
                value_item.setBackground(QColor(COLOR_SURFACE_ALT))
            self.table.setItem(row, 0, label_item)
            self.table.setItem(row, 1, value_item)
        layout.addWidget(self.table, stretch=1)

        btn_close = QPushButton(tr("gui.common.ok"))
        btn_close.setFixedHeight(36)
        btn_close.setStyleSheet(
            f"background-color: {COLOR_ACCENT}; color: white; border-radius: 6px; font-weight: bold;"
        )
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


# ---------------------------------------------------------------------------
# Dialog: Wipe every Badge, or this station's attendance history, behind a backup
# ---------------------------------------------------------------------------
class WipeDialog(QDialog):
    def __init__(self, worker: HardwareWorker, kind: str, parent=None):
        super().__init__(parent)
        self.worker = worker
        self.kind = kind  # "users" or "history"
        self.setWindowTitle(tr(f"gui.wipe.{kind}.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setFixedWidth(460)
        self.setStyleSheet(f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        title = QLabel(tr(f"gui.wipe.{kind}.heading"))
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_ERROR_TEXT};")
        layout.addWidget(title)
        desc = QLabel(tr(f"gui.wipe.{kind}.description"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)

        field_style = f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 8px; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        form = QFormLayout()
        form.setSpacing(10)
        self.inp_password = QLineEdit()
        self.inp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_password.setStyleSheet(field_style)
        form.addRow(tr("gui.wipe.password_label"), self.inp_password)
        self.inp_confirm = QLineEdit()
        self.inp_confirm.setPlaceholderText(tr("admin.wipe.confirm_word"))
        self.inp_confirm.setStyleSheet(field_style)
        form.addRow(tr("gui.wipe.confirm_label", word=tr("admin.wipe.confirm_word")), self.inp_confirm)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.btn_wipe = QPushButton(tr(f"gui.wipe.{kind}.button"))
        self.btn_wipe.setFixedHeight(38)
        self.btn_wipe.setStyleSheet(f"""
            QPushButton {{ background-color: {COLOR_ERROR}; color: white; border-radius: 6px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #B91C1C; }}
        """)
        self.btn_wipe.clicked.connect(self.wipe)
        buttons.addWidget(self.btn_wipe, stretch=2)
        btn_cancel = QPushButton(tr("gui.common.cancel"))
        btn_cancel.setFixedHeight(38)
        btn_cancel.setStyleSheet(
            f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
        )
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel, stretch=1)
        layout.addLayout(buttons)

    def wipe(self):
        conn = database.connect(self.worker.settings.database_path)
        try:
            wipe = admin.wipe_users if self.kind == "users" else admin.wipe_history
            res = wipe(conn, self.worker.settings, self.inp_password.text(), self.inp_confirm.text())
        finally:
            conn.close()
        if not res.success or res.backup_path is None:
            QMessageBox.critical(self, tr("gui.wipe.error_title"), res.error)
            return
        QMessageBox.information(
            self, tr("gui.wipe.done_title"), tr(f"gui.wipe.{self.kind}.done", backup=res.backup_path.name)
        )
        self.accept()


# ---------------------------------------------------------------------------
# VIEW: Badge and User Directory
# ---------------------------------------------------------------------------
class BadgeManagementView(QWidget):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self._init_ui()
        self.refresh_users()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(tr("gui.badges.heading"))
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        sub = QLabel(tr("gui.badges.subheading"))
        sub.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box)

        header.addStretch()

        btn_add = QPushButton(tr("gui.badges.register"))
        btn_add.setFixedHeight(36)
        btn_add.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: white;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        btn_add.clicked.connect(self.add_user_dialog)
        header.addWidget(btn_add)

        btn_edit = QPushButton(tr("gui.badges.edit"))
        btn_edit.setFixedHeight(36)
        btn_edit.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_INPUT_BORDER};
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {COLOR_SURFACE_ALT}; }}
        """)
        btn_edit.clicked.connect(self.modify_selected_user)
        header.addWidget(btn_edit)

        btn_promote = QPushButton(tr("gui.badges.promote"))
        btn_promote.setFixedHeight(36)
        btn_promote.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_ACCENT};
                border: 1px solid {COLOR_ACCENT};
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {COLOR_SURFACE_ALT}; }}
        """)
        btn_promote.clicked.connect(self.promote_students)
        header.addWidget(btn_promote)

        btn_del = QPushButton(tr("gui.badges.delete"))
        btn_del.setFixedHeight(36)
        btn_del.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ERROR};
                color: white;
                border-radius: 6px;
                padding: 0 12px;
                font-weight: bold;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #B91C1C; }}
        """)
        btn_del.clicked.connect(self.delete_selected_user)
        header.addWidget(btn_del)

        layout.addLayout(header)

        tools = QHBoxLayout()
        tools.setSpacing(10)
        tools.addStretch()
        quiet_style = f"""
            QPushButton {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_SECONDARY};
                border: 1px solid {COLOR_INPUT_BORDER};
                border-radius: 6px;
                padding: 0 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {COLOR_SURFACE_ALT}; }}
        """
        danger_style = f"""
            QPushButton {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_ERROR_TEXT};
                border: 1px solid {COLOR_ERROR};
                border-radius: 6px;
                padding: 0 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ERROR_BG}; }}
        """
        self.btn_stats = QPushButton(tr("gui.badges.statistics"))
        self.btn_stats.setFixedHeight(30)
        self.btn_stats.setStyleSheet(quiet_style)
        self.btn_stats.clicked.connect(self.show_statistics)
        tools.addWidget(self.btn_stats)

        self.btn_wipe_history = QPushButton(tr("gui.badges.wipe_history"))
        self.btn_wipe_history.setFixedHeight(30)
        self.btn_wipe_history.setStyleSheet(danger_style)
        self.btn_wipe_history.clicked.connect(lambda: self.wipe("history"))
        tools.addWidget(self.btn_wipe_history)

        self.btn_wipe_users = QPushButton(tr("gui.badges.wipe_users"))
        self.btn_wipe_users.setFixedHeight(30)
        self.btn_wipe_users.setStyleSheet(danger_style)
        self.btn_wipe_users.clicked.connect(lambda: self.wipe("users"))
        tools.addWidget(self.btn_wipe_users)
        layout.addLayout(tools)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("gui.badges.filter_placeholder"))
        self.search_input.setFixedHeight(36)
        self.search_input.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 8px; padding: 0 12px;"
        )
        self.search_input.textChanged.connect(self.filter_users)
        layout.addWidget(self.search_input)

        # User Table (10 columns: Displays Family ID, student and both guardians)
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(
            [
                tr("gui.badges.column.uid"),
                tr("gui.badges.column.full_name"),
                tr("gui.badges.column.family"),
                tr("gui.badges.column.role"),
                tr("gui.badges.column.grade"),
                tr("gui.badges.column.section"),
                tr("gui.badges.column.guardian1"),
                tr("gui.badges.column.guardian1_phone"),
                tr("gui.badges.column.guardian2"),
                tr("gui.badges.column.guardian2_phone"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 65)
        self.table.setColumnWidth(5, 65)
        self.table.setColumnWidth(6, 140)
        self.table.setColumnWidth(7, 110)
        self.table.setColumnWidth(8, 140)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_PRIMARY};
                gridline-color: #EBF2F7;
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QHeaderView::section {{
                background-color: {COLOR_SURFACE_ALT};
                color: {COLOR_PRIMARY};
                font-weight: bold;
                border: none;
                padding: 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {COLOR_SURFACE_ALT};
                color: {COLOR_ACCENT};
            }}
        """)
        layout.addWidget(self.table)

    def refresh_users(self):
        conn = database.connect(self.worker.settings.database_path)
        cur = conn.cursor()
        cur.execute("SELECT id, badge_uid, full_name, role, is_active FROM users ORDER BY full_name ASC")
        users = cur.fetchall()

        self.table.setRowCount(len(users))
        for r_idx, u in enumerate(users):
            u_dict = database.get_user_by_badge_uid(conn, u["badge_uid"])
            if not u_dict:
                continue

            uid = u_dict["badge_uid"]
            name = u_dict["full_name"]
            fam_id = u_dict.get("family_id") or "--"
            role = u_dict["role"]
            is_grad = role == "graduate" or bool(u_dict.get("graduation_date"))
            grade_name = grade_text(u_dict.get("grade") or u_dict.get("taught_grade"))

            if is_grad:
                role_display = role_text("graduate")
                grade_display = tr("gui.badges.graduate_grade", grade=grade_name) if grade_name else role_display
                section = "--"
            elif not u_dict.get("is_active"):
                role_display = tr("gui.badges.inactive_role", role=role_text(role))
                grade_display = grade_name
                section = u_dict.get("section") or "--"
            elif role == "teacher":
                role_display = role_text("teacher")
                grade_display = tr("gui.badges.taught_grade", grade=grade_name) if grade_name else ""
                section = "--"
            else:
                role_display = role_text(role)
                grade_display = grade_name
                section = u_dict.get("section") or "--"

            gs = u_dict.get("guardians", [])
            g1_name = gs[0].get("name", "") if len(gs) > 0 else ""
            g1_phone = gs[0].get("phone", "") if len(gs) > 0 else ""
            g2_name = gs[1].get("name", "") if len(gs) > 1 else ""
            g2_phone = gs[1].get("phone", "") if len(gs) > 1 else ""

            row_values = [uid, name, fam_id, role_display, grade_display, section, g1_name, g1_phone, g2_name, g2_phone]
            for c_idx, val in enumerate(row_values):
                item = QTableWidgetItem(str(val))
                if c_idx == 0:
                    item.setForeground(QColor(COLOR_ACCENT))
                elif c_idx == 2 and val != "--":
                    item.setForeground(QColor(COLOR_PRIMARY))
                    item.setFont(QFont("Arial", 11, QFont.Bold))
                elif c_idx == 3 and is_grad:
                    item.setForeground(QColor(COLOR_SECONDARY))
                    item.setFont(QFont("Arial", 11, QFont.Bold))
                elif c_idx == 4 and is_grad or not u_dict.get("is_active"):
                    item.setForeground(QColor(COLOR_SECONDARY))
                self.table.setItem(r_idx, c_idx, item)

        conn.close()

    def filter_users(self, query: str):
        query = query.strip().lower()
        for r in range(self.table.rowCount()):
            match = False
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                if item and query in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(r, not match)

    def _ensure_normal_rfid_mode(self):
        next_mode = resolve_post_dialog_rfid_mode()
        self.worker.set_rfid_mode(next_mode)
        self.worker.send_idle_screen()

    def add_user_dialog(self):
        try:
            dlg = RegisterBadgeDialog(self.worker, self)
            if dlg.exec() == QDialog.Accepted:
                self.refresh_users()
        finally:
            self._ensure_normal_rfid_mode()

    def modify_selected_user(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, tr("gui.common.select_row"), tr("gui.badges.select_to_edit"))
            return

        uid = self.table.item(sel[0].row(), 0).text()
        name = self.table.item(sel[0].row(), 1).text()

        try:
            # Admin authorization required
            auth_dlg = AdminAuthDialog(self.worker, self, tr("gui.badges.edit_operation", name=name))
            if auth_dlg.exec() != QDialog.Accepted or not auth_dlg.auth_token:
                return

            edit_dlg = EditBadgeDialog(uid, auth_dlg.auth_token, self.worker, self)
            if edit_dlg.exec() == QDialog.Accepted:
                self.refresh_users()
        finally:
            self._ensure_normal_rfid_mode()

    def show_statistics(self):
        conn = database.connect_historical(self.worker.settings)
        try:
            stats = admin.get_statistics(conn)
        finally:
            conn.close()
        StatisticsDialog(stats, self).exec()

    def wipe(self, kind: str):
        if not self.worker.settings.wipe_password:
            QMessageBox.critical(self, tr("gui.wipe.error_title"), tr("admin.error.wipe_password_missing"))
            return
        if WipeDialog(self.worker, kind, self).exec() == QDialog.DialogCode.Accepted:
            self.refresh_users()

    def promote_students(self):
        try:
            # Admin authorization required
            auth_dlg = AdminAuthDialog(self.worker, self, tr("gui.badges.promote_operation"))
            if auth_dlg.exec() != QDialog.Accepted or not auth_dlg.auth_token:
                return

            conn = database.connect(self.worker.settings.database_path)
            preview = admin.preview_grade_promotion(conn)
            conn.close()

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("gui.badges.promote_confirm_title"))
            msg_box.setText(
                tr(
                    "gui.badges.promote_confirm",
                    promoted=preview.promoted_count,
                    graduated=preview.graduated_count,
                    final_grade=final_grade_text(),
                )
            )
            msg_box.setIcon(QMessageBox.Question)
            btn_yes = msg_box.addButton(tr("gui.badges.promote_yes"), QMessageBox.YesRole)
            btn_no = msg_box.addButton(tr("gui.common.no_cancel"), QMessageBox.NoRole)
            msg_box.setStyleSheet(f"""
                QMessageBox {{ background-color: {COLOR_SURFACE}; }}
                QLabel {{ color: {COLOR_PRIMARY}; font-size: 13px; }}
            """)
            btn_yes.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_ACCENT};
                    color: #FFFFFF;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    outline: none;
                }}
                QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
                QPushButton:focus {{ outline: none; border: none; }}
            """)
            btn_no.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_SURFACE_ALT};
                    color: {COLOR_PRIMARY};
                    border: 1px solid {COLOR_INPUT_BORDER};
                    border-radius: 6px;
                    padding: 8px 16px;
                    outline: none;
                }}
                QPushButton:hover {{ background-color: #E2E8F0; }}
                QPushButton:focus {{ outline: none; border: 1px solid {COLOR_INPUT_BORDER}; }}
            """)
            msg_box.setDefaultButton(btn_no)
            msg_box.exec()

            if msg_box.clickedButton() == btn_yes:
                conn = database.connect(self.worker.settings.database_path)
                res = admin.promote_grades(conn)
                conn.close()

                if res.success:
                    self.worker.send_screen("lcd.grade_promotion")
                    QMessageBox.information(
                        self,
                        tr("gui.badges.promote_done_title"),
                        tr(
                            "gui.badges.promote_done",
                            promoted=res.promoted_count,
                            graduated=res.graduated_count,
                            final_grade=final_grade_text(),
                        ),
                    )
                    self.refresh_users()
                else:
                    QMessageBox.critical(
                        self, tr("gui.badges.promote_error_title"), res.error or tr("gui.badges.promote_error")
                    )
        finally:
            self._ensure_normal_rfid_mode()

    def delete_selected_user(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, tr("gui.common.select_row"), tr("gui.badges.select_to_delete"))
            return

        uid = self.table.item(sel[0].row(), 0).text()
        name = self.table.item(sel[0].row(), 1).text()

        try:
            # Admin authorization required
            auth_dlg = AdminAuthDialog(self.worker, self, tr("gui.badges.delete_operation", name=name))
            if auth_dlg.exec() != QDialog.Accepted or not auth_dlg.auth_token:
                return

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(tr("gui.badges.delete_confirm_title"))
            msg_box.setText(tr("gui.badges.delete_confirm", uid=uid, name=name))
            msg_box.setIcon(QMessageBox.Question)
            btn_yes = msg_box.addButton(tr("gui.badges.delete_yes"), QMessageBox.YesRole)
            btn_no = msg_box.addButton(tr("gui.common.no_cancel"), QMessageBox.NoRole)
            msg_box.setStyleSheet(f"""
                QMessageBox {{ background-color: {COLOR_SURFACE}; }}
                QLabel {{ color: {COLOR_PRIMARY}; font-size: 13px; }}
            """)
            btn_yes.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_ERROR};
                    color: #FFFFFF;
                    font-weight: bold;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    outline: none;
                }}
                QPushButton:hover {{ background-color: #DC2626; }}
                QPushButton:focus {{ outline: none; border: none; }}
            """)
            btn_no.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLOR_SURFACE_ALT};
                    color: {COLOR_PRIMARY};
                    border: 1px solid {COLOR_INPUT_BORDER};
                    border-radius: 6px;
                    padding: 8px 16px;
                    outline: none;
                }}
                QPushButton:hover {{ background-color: #E2E8F0; }}
                QPushButton:focus {{ outline: none; border: 1px solid {COLOR_INPUT_BORDER}; }}
            """)
            msg_box.setDefaultButton(btn_no)
            msg_box.exec()

            if msg_box.clickedButton() == btn_yes:
                conn = database.connect(self.worker.settings.database_path)
                res = admin.delete_user(
                    conn,
                    target_badge_uid=uid,
                    approving_uid=auth_dlg.auth_token,
                    confirmed=True,
                )
                conn.close()

                if res.success:
                    self.worker.send_screen("lcd.badge_deleted")
                    QMessageBox.information(
                        self, tr("gui.badges.delete_done_title"), tr("gui.badges.delete_done", uid=uid, name=name)
                    )
                    self.refresh_users()
                else:
                    QMessageBox.critical(self, tr("gui.badges.delete_error_title"), res.error)
        finally:
            self._ensure_normal_rfid_mode()


STATUS_COLORS = {
    "on_time": COLOR_SUCCESS_TEXT,
    "late": COLOR_WARNING_TEXT,
    "absent": COLOR_ERROR_TEXT,
}

MARK_COLORS = {
    "present": COLOR_SUCCESS_TEXT,
    "late": COLOR_WARNING_TEXT,
    "absent": COLOR_ERROR_TEXT,
}


# ---------------------------------------------------------------------------
# VIEW: Search and Excel Reports (filters + direct export)
# ---------------------------------------------------------------------------
class UnifiedSearchReportsView(QWidget):
    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self._last_query_data: list[dict[str, Any]] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Header
        head_box = QVBoxLayout()
        title = QLabel(tr("gui.search.heading"))
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        sub = QLabel(tr("gui.search.subheading"))
        sub.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        head_box.addWidget(title)
        head_box.addWidget(sub)
        layout.addLayout(head_box)

        # Unified Filter Box Card
        filter_card = QFrame()
        filter_card.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
                padding: 12px;
            }}
        """)
        f_lay = QVBoxLayout(filter_card)
        f_lay.setSpacing(10)

        # Row 1: Query type
        row_type = QHBoxLayout()
        lbl_type = QLabel(tr("gui.search.type_label"))
        lbl_type.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_type.setStyleSheet(f"color: {COLOR_PRIMARY};")
        row_type.addWidget(lbl_type)

        self.combo_query_type = QComboBox()
        self.combo_query_type.addItems(
            [
                tr("gui.search.type.daily"),
                tr("gui.search.type.person"),
                tr("gui.search.type.matrix"),
                tr("gui.search.type.general"),
                tr("gui.search.type.others_day"),
                tr("gui.search.type.others_range"),
            ]
        )
        self.combo_query_type.setFixedHeight(34)
        self.combo_query_type.setStyleSheet(
            f"background-color: {COLOR_BG_LIGHT}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; font-weight: bold;"
        )
        self.combo_query_type.currentIndexChanged.connect(self.on_query_type_changed)
        row_type.addWidget(self.combo_query_type, stretch=2)
        row_type.addStretch()
        f_lay.addLayout(row_type)

        # Row 2: Dynamic Filter Controls
        self.row_filters = QHBoxLayout()
        self.row_filters.setSpacing(10)

        # Date Pickers
        self.lbl_date1 = QLabel(tr("gui.search.date"))
        self.lbl_date1.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.date_start = QDateEdit()
        self.date_start.setDate(QDate.currentDate())
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat(tr("gui.search.date_picker_format"))
        self.date_start.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 4px;"
        )
        self.row_filters.addWidget(self.lbl_date1)
        self.row_filters.addWidget(self.date_start)

        self.lbl_date2 = QLabel(tr("gui.search.end_date"))
        self.lbl_date2.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.date_end = QDateEdit()
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat(tr("gui.search.date_picker_format"))
        self.date_end.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 4px;"
        )
        self.lbl_date2.setVisible(False)
        self.date_end.setVisible(False)
        self.row_filters.addWidget(self.lbl_date2)
        self.row_filters.addWidget(self.date_end)

        # Role Filter (Teacher, Admin and Visitor searches)
        self.lbl_role = QLabel(tr("gui.common.role"))
        self.lbl_role.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.combo_role = QComboBox()
        for role in ("teacher", "admin", "visitor"):
            self.combo_role.addItem(role_text(role), role)
        self.combo_role.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 4px;"
        )
        self.combo_role.currentIndexChanged.connect(lambda _index: self._show_filters())
        self.lbl_role.setVisible(False)
        self.combo_role.setVisible(False)
        self.row_filters.addWidget(self.lbl_role)
        self.row_filters.addWidget(self.combo_role)

        # Grade Filter
        self.lbl_grade = QLabel(tr("gui.common.grade"))
        self.lbl_grade.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.combo_grade = QComboBox()
        self.combo_grade.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 4px;"
        )
        self.row_filters.addWidget(self.lbl_grade)
        self.row_filters.addWidget(self.combo_grade)

        # Section Filter
        self.lbl_sec = QLabel(tr("gui.common.section"))
        self.lbl_sec.setStyleSheet(f"color: {COLOR_PRIMARY}; font-weight: bold;")
        self.combo_sec = QComboBox()
        self.combo_sec.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 4px;"
        )
        self.row_filters.addWidget(self.lbl_sec)
        self.row_filters.addWidget(self.combo_sec)
        self.refresh_school_filters()

        # Search Text Input (Name / UID / Family Code)
        self.inp_search_text = QLineEdit()
        self.inp_search_text.setPlaceholderText(tr("gui.search.text_placeholder"))
        self.inp_search_text.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 5px;"
        )
        self.row_filters.addWidget(self.inp_search_text, stretch=1)

        self.btn_scan_badge = QPushButton(tr("gui.search.scan_badge"))
        self.btn_scan_badge.setStyleSheet(
            f"background-color: {COLOR_SURFACE_ALT}; color: {COLOR_ACCENT}; border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px; padding: 5px 12px; font-weight: 500;"
        )
        self.btn_scan_badge.clicked.connect(self.search_by_scan)
        self.btn_scan_badge.setVisible(False)
        self.row_filters.addWidget(self.btn_scan_badge)

        f_lay.addLayout(self.row_filters)

        # Row 3: Action Buttons (Search & Export to Excel)
        row_actions = QHBoxLayout()
        row_actions.setSpacing(10)

        self.btn_search = QPushButton(tr("gui.search.search"))
        self.btn_search.setFixedHeight(38)
        self.btn_search.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border-radius: 6px;
                padding: 0 16px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        self.btn_search.clicked.connect(self.execute_search)
        row_actions.addWidget(self.btn_search)

        self.btn_export = QPushButton(tr("gui.search.export"))
        self.btn_export.setFixedHeight(38)
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: #FFFFFF;
                border-radius: 6px;
                padding: 0 18px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #059669; }}
        """)
        self.btn_export.clicked.connect(self.export_to_excel)
        row_actions.addWidget(self.btn_export)

        btn_folder = QPushButton(tr("gui.search.open_folder"))
        btn_folder.setFixedHeight(38)
        btn_folder.setStyleSheet(
            f"background-color: {COLOR_SURFACE}; color: {COLOR_SECONDARY}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 0 14px; font-weight: 500;"
        )
        btn_folder.clicked.connect(self.open_reports_folder)
        row_actions.addWidget(btn_folder)

        row_actions.addStretch()

        self.lbl_stats = QLabel(tr("gui.search.total_none"))
        self.lbl_stats.setStyleSheet(f"color: {COLOR_SECONDARY}; font-weight: bold; font-size: 12px;")
        row_actions.addWidget(self.lbl_stats)

        f_lay.addLayout(row_actions)
        layout.addWidget(filter_card)

        # Results Table
        self.table = QTableWidget()
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_SURFACE};
                color: {COLOR_PRIMARY};
                gridline-color: #EBF2F7;
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QHeaderView::section {{
                background-color: {COLOR_SURFACE_ALT};
                color: {COLOR_PRIMARY};
                font-weight: bold;
                border: none;
                padding: 8px;
            }}
            QTableWidget::item:selected {{
                background-color: {COLOR_SURFACE_ALT};
                color: {COLOR_ACCENT};
            }}
        """)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Initial Search
        self.execute_search()

    def on_query_type_changed(self, idx: int):
        is_range = idx in (2, 5)
        is_person = idx == 1

        self.lbl_date2.setVisible(is_range)
        self.date_end.setVisible(is_range)
        self.lbl_date1.setText(tr("gui.search.start_date") if is_range else tr("gui.search.date"))
        self.btn_scan_badge.setVisible(is_person)
        self._show_filters()

        self.inp_search_text.setPlaceholderText(
            tr("gui.search.person_placeholder") if is_person else tr("gui.search.filter_placeholder")
        )

    def _searching_other_roles(self) -> bool:
        return self.combo_query_type.currentIndex() in (4, 5)

    def _show_filters(self):
        """Show the filters the chosen search uses: Teachers are filtered by the Grade they
        teach, and Admins and Visitors by neither Grade nor Section."""
        idx = self.combo_query_type.currentIndex()
        others = self._searching_other_roles()
        shows_grade = idx != 1 and (not others or self.combo_role.currentData() == "teacher")
        shows_section = idx != 1 and not others
        self.lbl_role.setVisible(others)
        self.combo_role.setVisible(others)
        self.lbl_grade.setVisible(shows_grade)
        self.combo_grade.setVisible(shows_grade)
        self.lbl_sec.setVisible(shows_section)
        self.combo_sec.setVisible(shows_section)

    def _selected_taught_grade(self) -> int | None:
        return self._selected_grade() if self.combo_role.currentData() == "teacher" else None

    def search_by_scan(self):
        """Search a person's history by scanning their Badge."""
        dialog = BadgeScanDialog(self.worker, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.badge_uid:
            self.inp_search_text.setText(dialog.badge_uid)
            self.execute_search()

    def refresh_school_filters(self):
        """Offer the School's current Grades and Sections, keeping the choice made if it is still there."""
        grade, section = self.combo_grade.currentData(), self.combo_sec.currentData()
        self.combo_grade.clear()
        self.combo_grade.addItem(tr("gui.search.all_grades"), search.ALL)
        for rank, label in enumerate(school_grades(), start=1):
            self.combo_grade.addItem(label, rank)
        self.combo_sec.clear()
        self.combo_sec.addItem(tr("gui.search.all_sections"), search.ALL)
        for name in school_sections():
            self.combo_sec.addItem(name, name)
        self.combo_grade.setCurrentIndex(max(self.combo_grade.findData(grade), 0))
        self.combo_sec.setCurrentIndex(max(self.combo_sec.findData(section), 0))

    def _selected_grade(self) -> int | None:
        value = self.combo_grade.currentData()
        return None if value == search.ALL else value

    def _selected_section(self) -> str | None:
        value = self.combo_sec.currentData()
        return None if value == search.ALL else value

    def _date_range(self) -> tuple[datetime, datetime] | None:
        """The chosen start and end dates, or None after telling the user they are reversed."""
        start = datetime.strptime(self.date_start.date().toString("yyyy-MM-dd"), "%Y-%m-%d")
        end = datetime.strptime(self.date_end.date().toString("yyyy-MM-dd"), "%Y-%m-%d")
        if start > end:
            QMessageBox.warning(self, tr("gui.search.bad_range_title"), tr("gui.search.bad_range"))
            return None
        return start, end

    def execute_search(self):
        idx = self.combo_query_type.currentIndex()
        conn = database.connect_historical(self.worker.settings)

        if idx == 0:
            # Daily Attendance
            self._search_daily(conn)
        elif idx == 1:
            # Person History
            self._search_person(conn)
        elif idx == 2:
            # Date Range Matrix
            self._search_matrix(conn)
        elif idx == 3:
            # General Records
            self._search_general(conn)
        elif idx == 4:
            self._search_others_day(conn)
        else:
            self._search_others_range(conn)

        conn.close()

    def _search_daily(self, conn):
        date_iso = self.date_start.date().toString("yyyy-MM-dd")
        grade = self._selected_grade()
        section = self._selected_section()

        day = search.search_all_students_by_date(conn, date_iso, load_school(self.worker.settings), grade, section)
        present, absent = day.present, day.absent

        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                tr("gui.search.column.date"),
                tr("gui.search.column.student"),
                tr("gui.search.column.grade_section"),
                tr("gui.search.column.check_in"),
                tr("gui.search.column.check_out"),
                tr("gui.search.column.status"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)

        rows = []
        for p in present:
            rows.append(
                {
                    "date": show_date(date_iso),
                    "name": p.name,
                    "grade_sec": grade_section_text(p.grade, p.section),
                    "in_time": show_time(p.arrival_time),
                    "out_time": show_time(p.departure_time) or "--",
                    "status": p.status,
                }
            )
        for a in absent:
            rows.append(
                {
                    "date": show_date(date_iso),
                    "name": a.name,
                    "grade_sec": grade_section_text(a.grade, a.section),
                    "in_time": "--",
                    "out_time": "--",
                    "status": "absent",
                }
            )

        # Apply search text filter if typed
        q = self.inp_search_text.text().strip().lower()
        if q:
            rows = [r for r in rows if q in r["name"].lower() or q in r["grade_sec"].lower()]

        self._last_query_data = rows
        self.table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            self.table.setItem(r_idx, 0, QTableWidgetItem(r["date"]))
            self.table.setItem(r_idx, 1, QTableWidgetItem(r["name"]))
            self.table.setItem(r_idx, 2, QTableWidgetItem(r["grade_sec"]))
            self.table.setItem(r_idx, 3, QTableWidgetItem(r["in_time"]))
            self.table.setItem(r_idx, 4, QTableWidgetItem(r["out_time"]))
            st_item = QTableWidgetItem(status_text(r["status"]))
            if r["status"] in STATUS_COLORS:
                st_item.setForeground(QColor(STATUS_COLORS[r["status"]]))
            self.table.setItem(r_idx, 5, st_item)

        self.lbl_stats.setText(tr("gui.search.total_daily", total=len(rows), present=len(present), absent=len(absent)))

    def _search_person(self, conn):
        query = self.inp_search_text.text().strip()
        if not query:
            cur = conn.cursor()
            cur.execute("SELECT badge_uid FROM users WHERE is_active = 1 LIMIT 1")
            first_user = cur.fetchone()
            query = first_user["badge_uid"] if first_user else ""

        results = []
        if query.upper().startswith("FAM-"):
            results = search.search_by_family_id(conn, query)

        if not results:
            results = search.search_by_name(conn, query)
        if not results and query:
            single = search.search_by_badge(conn, query)
            if single:
                results = [single]
        if not results and query:
            results = search.search_by_family_id(conn, query)

        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            [
                tr("gui.search.column.date"),
                tr("gui.search.column.person"),
                tr("gui.search.column.role"),
                tr("gui.search.column.check_in"),
                tr("gui.search.column.check_out"),
                tr("gui.search.column.punctuality"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)

        rows = []
        for r in results:
            user_name = r.user.get("full_name", "")
            user_role = r.user.get("role", "")
            for h in r.history:
                rows.append(
                    {
                        "date": show_date(h.date),
                        "name": user_name,
                        "role": role_text(user_role),
                        "in_time": show_time(h.arrival_time),
                        "out_time": show_time(h.departure_time) or "--",
                        "status": h.status,
                    }
                )

        self._last_query_data = rows
        self.table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            self.table.setItem(r_idx, 0, QTableWidgetItem(r["date"]))
            self.table.setItem(r_idx, 1, QTableWidgetItem(r["name"]))
            self.table.setItem(r_idx, 2, QTableWidgetItem(r["role"]))
            self.table.setItem(r_idx, 3, QTableWidgetItem(r["in_time"]))
            self.table.setItem(r_idx, 4, QTableWidgetItem(r["out_time"]))
            st_item = QTableWidgetItem(status_text(r["status"]))
            if r["status"] in STATUS_COLORS:
                st_item.setForeground(QColor(STATUS_COLORS[r["status"]]))
            self.table.setItem(r_idx, 5, st_item)

        self.lbl_stats.setText(tr("gui.search.total_person", days=len(rows), people=len(results)))

    def _search_matrix(self, conn):
        date_range = self._date_range()
        if date_range is None:
            return
        start_dt, end_dt = date_range
        grade = self._selected_grade()
        section = self._selected_section()

        school_days = search.school_days_on_record(
            conn, load_school(self.worker.settings), start_dt.date(), end_dt.date()
        )
        matrix_rows = search.compute_student_range_matrix(conn, school_days, grade, section)

        headers = [
            tr("gui.search.column.names"),
            tr("gui.search.column.grade_section_short"),
            tr("gui.search.column.present"),
            tr("gui.search.column.late"),
            tr("gui.search.column.absent"),
        ] + [show_short_date(d) for d in school_days]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 100)

        self.table.setRowCount(len(matrix_rows))
        for r_idx, r in enumerate(matrix_rows):
            self.table.setItem(r_idx, 0, QTableWidgetItem(r.name))
            self.table.setItem(r_idx, 1, QTableWidgetItem(grade_section_text(r.grade, r.section)))
            self.table.setItem(r_idx, 2, QTableWidgetItem(str(r.present_count)))
            self.table.setItem(r_idx, 3, QTableWidgetItem(str(r.late_count)))
            self.table.setItem(r_idx, 4, QTableWidgetItem(str(r.absent_count)))
            for d_idx, mark in enumerate(r.day_marks):
                item = QTableWidgetItem(tr(f"report.mark.{mark}") if mark else "")
                if mark in MARK_COLORS:
                    item.setForeground(QColor(MARK_COLORS[mark]))
                self.table.setItem(r_idx, 5 + d_idx, item)

        self.lbl_stats.setText(tr("gui.search.total_matrix", students=len(matrix_rows), days=len(school_days)))

    def _search_general(self, conn):
        date_iso = self.date_start.date().toString("yyyy-MM-dd")
        cur = conn.cursor()
        cur.execute(
            "SELECT id, date, time, name, role, grade, event_type, status FROM attendance_records WHERE date = ? ORDER BY id DESC",
            (date_iso,),
        )
        rows = cur.fetchall()

        q = self.inp_search_text.text().strip().lower()
        if q:
            rows = [r for r in rows if q in str(r["name"]).lower() or q in role_text(r["role"]).lower()]

        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            [
                tr("gui.search.column.time"),
                tr("gui.search.column.staff"),
                tr("gui.search.column.role"),
                tr("gui.search.column.grade"),
                tr("gui.search.column.event"),
                tr("gui.search.column.punctuality"),
                tr("gui.search.column.id"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 95)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 100)

        self.table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            self.table.setItem(r_idx, 0, QTableWidgetItem(show_time(str(r["time"]))))
            self.table.setItem(r_idx, 1, QTableWidgetItem(str(r["name"])))
            self.table.setItem(r_idx, 2, QTableWidgetItem(role_text(r["role"])))
            self.table.setItem(r_idx, 3, QTableWidgetItem(grade_text(r["grade"])))
            self.table.setItem(r_idx, 4, QTableWidgetItem(event_text(str(r["event_type"]))))
            st_item = QTableWidgetItem(status_text(r["status"]))
            if r["status"] in STATUS_COLORS:
                st_item.setForeground(QColor(STATUS_COLORS[r["status"]]))
            self.table.setItem(r_idx, 5, st_item)
            self.table.setItem(r_idx, 6, QTableWidgetItem(str(r["id"])))

        self.lbl_stats.setText(tr("gui.search.total_general", events=len(rows)))

    def _text_filtered(self, rows: list[Any]) -> list[Any]:
        q = self.inp_search_text.text().strip().lower()
        return [r for r in rows if q in r.name.lower()] if q else rows

    def _search_others_day(self, conn):
        """Teachers, Admins or Visitors who checked in on one date (E7)."""
        role = self.combo_role.currentData()
        date_iso = self.date_start.date().toString("yyyy-MM-dd")
        entries = self._text_filtered(
            search.search_other_role_by_date(conn, date_iso, role, self._selected_taught_grade())
        )

        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                tr("gui.search.column.check_in"),
                tr("gui.search.column.check_out"),
                tr("gui.search.column.names"),
                tr("gui.search.column.grade"),
                tr("gui.search.column.status"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(3, 80)

        self.table.setRowCount(len(entries))
        for r_idx, e in enumerate(entries):
            self.table.setItem(r_idx, 0, QTableWidgetItem(show_time(e.time)))
            self.table.setItem(r_idx, 1, QTableWidgetItem(show_time(e.departure_time) or "--"))
            self.table.setItem(r_idx, 2, QTableWidgetItem(e.name))
            self.table.setItem(r_idx, 3, QTableWidgetItem(grade_text(e.taught_grade)))
            st_item = QTableWidgetItem(status_text(e.status))
            if e.status in STATUS_COLORS:
                st_item.setForeground(QColor(STATUS_COLORS[e.status]))
            self.table.setItem(r_idx, 4, st_item)

        self.lbl_stats.setText(
            tr("gui.search.total_others_day", people=len(entries), role=tr(f"report.role_plural.{role}"))
        )

    def _search_others_range(self, conn):
        """Teachers', Admins' or Visitors' Check-in times across School Days (E8)."""
        date_range = self._date_range()
        if date_range is None:
            return
        start_dt, end_dt = date_range
        role = self.combo_role.currentData()
        school_days = search.school_days_on_record(
            conn, load_school(self.worker.settings), start_dt.date(), end_dt.date()
        )
        rows = self._text_filtered(
            search.compute_other_role_range_matrix(conn, school_days, role, self._selected_taught_grade())
        )

        headers = [tr("gui.search.column.names")] + [show_short_date(d) for d in school_days]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 200)

        self.table.setRowCount(len(rows))
        for r_idx, r in enumerate(rows):
            self.table.setItem(r_idx, 0, QTableWidgetItem(r.name))
            for d_idx, arrival in enumerate(r.day_times):
                self.table.setItem(r_idx, 1 + d_idx, QTableWidgetItem(show_time(arrival)))

        self.lbl_stats.setText(
            tr(
                "gui.search.total_others_range",
                people=len(rows),
                role=tr(f"report.role_plural.{role}"),
                days=len(school_days),
            )
        )

    def export_to_excel(self):
        idx = self.combo_query_type.currentIndex()
        school = load_school(self.worker.settings)
        conn = database.connect_historical(self.worker.settings)
        out_dir = self.worker.settings.reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            if idx == 0:
                # E2: the whole School on one date
                date_iso = self.date_start.date().toString("yyyy-MM-dd")
                day = date.fromisoformat(date_iso)
                grade = self._selected_grade()
                section = self._selected_section()

                present = search._get_students_for_date(conn, date_iso, grade=grade, section=section)
                if grade is not None:
                    exp = reports.export_e3(out_dir, school, day, grade, section, present)
                else:
                    exp = reports.export_e2(out_dir, school, day, present)
            elif idx == 1:
                # E1: one person's history
                q = self.inp_search_text.text().strip()
                res_list = search.search_by_name(conn, q) if q else []
                if not res_list and q:
                    single = search.search_by_badge(conn, q)
                    if single:
                        res_list = [single]
                if not res_list:
                    cur = conn.cursor()
                    cur.execute("SELECT badge_uid FROM users WHERE is_active = 1 LIMIT 1")
                    first_u = cur.fetchone()
                    if first_u:
                        res_list = [search.search_by_badge(conn, first_u["badge_uid"])]
                if res_list:
                    exp = reports.export_e1(out_dir, school, res_list[0])
                else:
                    QMessageBox.warning(self, tr("gui.search.no_results_title"), tr("gui.search.no_student"))
                    conn.close()
                    return
            elif idx == 2:
                # E4/E5/E6: attendance matrix
                date_range = self._date_range()
                if date_range is None:
                    conn.close()
                    return
                start_dt, end_dt = date_range
                grade = self._selected_grade()
                section = self._selected_section()

                start, end = start_dt.date(), end_dt.date()
                school_days = search.school_days_on_record(conn, school, start, end)
                matrix_rows = search.compute_student_range_matrix(conn, school_days, grade, section)
                if grade and section:
                    exp = reports.export_e6(out_dir, school, start, end, grade, section, school_days, matrix_rows)
                elif grade:
                    exp = reports.export_e5(out_dir, school, start, end, grade, school_days, matrix_rows)
                else:
                    exp = reports.export_e4(out_dir, school, start, end, school_days, matrix_rows)
            elif idx == 4:
                # E7: Teachers, Admins or Visitors on one date
                role = self.combo_role.currentData()
                date_iso = self.date_start.date().toString("yyyy-MM-dd")
                entries = search.search_other_role_by_date(conn, date_iso, role, self._selected_taught_grade())
                exp = reports.export_e7(out_dir, school, role, date.fromisoformat(date_iso), entries)
            elif idx == 5:
                # E8: Teachers, Admins or Visitors across School Days
                date_range = self._date_range()
                if date_range is None:
                    conn.close()
                    return
                start, end = date_range[0].date(), date_range[1].date()
                role = self.combo_role.currentData()
                school_days = search.school_days_on_record(conn, school, start, end)
                range_rows = search.compute_other_role_range_matrix(
                    conn, school_days, role, self._selected_taught_grade()
                )
                exp = reports.export_e8(out_dir, school, role, start, end, school_days, range_rows)
            else:
                # General table export via openpyxl
                import openpyxl

                date_iso = self.date_start.date().toString("yyyy-MM-dd")
                wb = openpyxl.Workbook()
                ws = wb.active
                ws.title = tr("gui.search.general_log_sheet")
                headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
                ws.append(headers)
                for r in range(self.table.rowCount()):
                    row_vals = [
                        self.table.item(r, c).text() if self.table.item(r, c) else ""
                        for c in range(self.table.columnCount())
                    ]
                    ws.append(row_vals)
                file_path = out_dir / reports.sanitize_filename(
                    tr("gui.search.general_log_file", date=date_iso) + ".xlsx"
                )
                wb.save(file_path)
                exp = reports.ExportResult(success=True, path=file_path)

            conn.close()

            if exp.success:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle(tr("gui.search.export_done_title"))
                msg.setText(tr("gui.search.export_done", file=exp.path.name))
                btn_open = msg.addButton(tr("gui.search.open_folder_button"), QMessageBox.ActionRole)
                msg.addButton(tr("gui.common.ok"), QMessageBox.AcceptRole)
                msg.exec()
                if msg.clickedButton() == btn_open:
                    self.open_reports_folder()
            else:
                QMessageBox.critical(
                    self, tr("gui.search.export_error_title"), exp.error or tr("gui.common.unknown_error")
                )

        except Exception as err:
            QMessageBox.critical(self, tr("gui.search.unexpected_title"), tr("gui.search.unexpected", error=err))

    def open_reports_folder(self):
        out_dir = self.worker.settings.reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir)))


# ---------------------------------------------------------------------------
# VIEW: School Settings (its editors also serve the first-run setup)
# ---------------------------------------------------------------------------
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

INPUT_STYLE = (
    f"background-color: {COLOR_SURFACE}; color: {COLOR_PRIMARY}; padding: 5px; "
    f"border: 1px solid {COLOR_INPUT_BORDER}; border-radius: 6px;"
)
GROUP_BOX_STYLE = f"""
    QGroupBox {{
        font-weight: bold;
        color: {COLOR_PRIMARY};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        margin-top: 6px;
        padding-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
"""
PRIMARY_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: bold;
    }}
    QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
"""
SECONDARY_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLOR_SURFACE};
        color: {COLOR_PRIMARY};
        border: 1px solid {COLOR_INPUT_BORDER};
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: bold;
    }}
    QPushButton:hover {{ background-color: {COLOR_SURFACE_ALT}; }}
"""
# The windows' background style sheets reach every check box, so the box is drawn here.
CHECK_BOX_STYLE = f"""
    QCheckBox {{ color: {COLOR_PRIMARY}; font-weight: normal; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {COLOR_INPUT_BORDER};
        border-radius: 4px;
        background-color: {COLOR_SURFACE};
    }}
    QCheckBox::indicator:checked {{ background-color: {COLOR_ACCENT}; border-color: {COLOR_ACCENT}; }}
"""


def hint_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px; font-weight: normal;")
    return label


def error_label() -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLOR_ERROR_TEXT}; font-size: 11px; font-weight: bold;")
    return label


def password_input() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setStyleSheet(INPUT_STYLE)
    return field


def cooldown_spin_box() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 24 * 60 * 60)
    spin.setSingleStep(30)
    spin.setSuffix(" s")
    spin.setStyleSheet(INPUT_STYLE)
    return spin


class NameListEditor(QWidget):
    """An ordered list of names, the School's Grades or its Sections. Double-click a name to
    rename it; new names go at the end. A Grade's place in the list is its rank, so the Grade
    list only ever loses its last name."""

    def __init__(self, placeholder_key: str, add_key: str, remove_key: str, remove_last_only: bool, parent=None):
        super().__init__(parent)
        self._keys = (placeholder_key, add_key, remove_key)
        self.remove_last_only = remove_last_only

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.list = QListWidget()
        self.list.setMinimumHeight(140)
        self.list.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        self.inp_name = QLineEdit()
        self.inp_name.setStyleSheet(INPUT_STYLE)
        self.inp_name.returnPressed.connect(self.add_name)
        row.addWidget(self.inp_name, stretch=1)
        self.btn_add = QPushButton()
        self.btn_add.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.btn_add.clicked.connect(self.add_name)
        row.addWidget(self.btn_add)
        self.btn_remove = QPushButton()
        self.btn_remove.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.btn_remove.clicked.connect(self.remove_name)
        row.addWidget(self.btn_remove)
        layout.addLayout(row)
        self.retranslate()

    def retranslate(self):
        placeholder_key, add_key, remove_key = self._keys
        self.inp_name.setPlaceholderText(tr(placeholder_key))
        self.btn_add.setText(tr(add_key))
        self.btn_remove.setText(tr(remove_key))

    def names(self) -> tuple[str, ...]:
        return tuple(self.list.item(row).text() for row in range(self.list.count()))

    def renamed(self) -> dict[str, str]:
        """Each name `set_names` showed that now reads differently: its old name, then its new one."""
        renames = {}
        for row in range(self.list.count()):
            item = self.list.item(row)
            original = item.data(Qt.ItemDataRole.UserRole)
            if original is not None and item.text().strip() != original:
                renames[original] = item.text().strip()
        return renames

    def set_names(self, names: tuple[str, ...]):
        self.list.clear()
        for name in names:
            self._append(name).setData(Qt.ItemDataRole.UserRole, name)

    def add_name(self):
        name = self.inp_name.text().strip()
        if name:
            self._append(name)
            self.inp_name.clear()

    def remove_name(self):
        row = self.list.count() - 1 if self.remove_last_only else self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def _append(self, name: str) -> QListWidgetItem:
        item = QListWidgetItem(name)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.addItem(item)
        return item


class WeekdayPicker(QWidget):
    """A check box for each day of the week, Monday first."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.boxes = [QCheckBox() for _ in WEEKDAYS]
        for day, box in enumerate(self.boxes):
            box.setStyleSheet(CHECK_BOX_STYLE)
            layout.addWidget(box, day // 4, day % 4)
        self.retranslate()

    def retranslate(self):
        for name, box in zip(WEEKDAYS, self.boxes, strict=True):
            box.setText(tr(f"gui.weekday.{name}"))

    def days(self) -> tuple[int, ...]:
        return tuple(day for day, box in enumerate(self.boxes) if box.isChecked())

    def set_days(self, days: tuple[int, ...]):
        for day, box in enumerate(self.boxes):
            box.setChecked(day in days)


class SchoolSettingsView(QWidget):
    """The School Settings, edited at this station. Saving takes Admin Approval, and Cloud
    Sync then pushes the change to Supabase."""

    saved = Signal(object)

    def __init__(self, worker: HardwareWorker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self._init_ui()
        self.show_school(load_school(worker.settings))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(tr("gui.settings.heading"))
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        sub = QLabel(tr("gui.settings.subheading"))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addLayout(title_box, stretch=1)

        self.btn_discard = QPushButton(tr("gui.settings.discard"))
        self.btn_discard.setFixedHeight(36)
        self.btn_discard.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.btn_discard.clicked.connect(lambda: self.show_school(self._school))
        header.addWidget(self.btn_discard)

        self.btn_save = QPushButton(tr("gui.settings.save"))
        self.btn_save.setFixedHeight(36)
        self.btn_save.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.btn_save.clicked.connect(self.save_settings)
        header.addWidget(self.btn_save)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        columns = QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 8, 0)
        columns.setSpacing(14)
        left = QVBoxLayout()
        right = QVBoxLayout()
        columns.addLayout(left, stretch=1)
        columns.addLayout(right, stretch=1)
        scroll.setWidget(content)
        layout.addWidget(scroll, stretch=1)

        box, box_layout = self._group("gui.settings.language")
        self.combo_language = QComboBox()
        for lang in i18n.LANGUAGES:
            self.combo_language.addItem(i18n.t(lang, "gui.wizard.language_name"), lang)
        self.combo_language.setStyleSheet(INPUT_STYLE)
        box_layout.addWidget(self.combo_language)
        left.addWidget(box)

        box, box_layout = self._group("gui.settings.grades")
        self.grades = NameListEditor(
            "gui.settings.grade_placeholder",
            "gui.settings.add_grade",
            "gui.settings.remove_last_grade",
            remove_last_only=True,
        )
        box_layout.addWidget(self.grades)
        box_layout.addWidget(hint_label(tr("gui.settings.grades_hint")))
        left.addWidget(box)

        box, box_layout = self._group("gui.settings.sections")
        self.sections = NameListEditor(
            "gui.settings.section_placeholder",
            "gui.settings.add_section",
            "gui.settings.remove_section",
            remove_last_only=False,
        )
        box_layout.addWidget(self.sections)
        box_layout.addWidget(hint_label(tr("gui.settings.sections_hint")))
        left.addWidget(box)
        left.addStretch()

        box, box_layout = self._group("gui.settings.weekdays")
        self.weekdays = WeekdayPicker()
        box_layout.addWidget(self.weekdays)
        right.addWidget(box)

        box, box_layout = self._group("gui.settings.holidays")
        row = QHBoxLayout()
        self.date_holiday = QDateEdit(QDate.currentDate())
        self.date_holiday.setCalendarPopup(True)
        self.date_holiday.setDisplayFormat(tr("gui.search.date_picker_format"))
        self.date_holiday.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.date_holiday, stretch=1)
        self.btn_add_holiday = QPushButton(tr("gui.settings.add_holiday"))
        self.btn_add_holiday.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.btn_add_holiday.clicked.connect(self.add_holiday)
        row.addWidget(self.btn_add_holiday)
        self.btn_remove_holiday = QPushButton(tr("gui.settings.remove_holiday"))
        self.btn_remove_holiday.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.btn_remove_holiday.clicked.connect(self.remove_holiday)
        row.addWidget(self.btn_remove_holiday)
        box_layout.addLayout(row)
        self.list_holidays = QListWidget()
        self.list_holidays.setMinimumHeight(120)
        self.list_holidays.setStyleSheet(INPUT_STYLE)
        box_layout.addWidget(self.list_holidays)
        box_layout.addWidget(hint_label(tr("gui.settings.holidays_hint")))
        right.addWidget(box)

        box, box_layout = self._group("gui.settings.schedule")
        form = QFormLayout()
        self.time_late = QTimeEdit()
        self.time_late.setDisplayFormat(tr("gui.settings.time_picker_format"))
        self.time_late.setStyleSheet(INPUT_STYLE)
        form.addRow(tr("gui.settings.late_threshold"), self.time_late)
        self.spin_cooldown = cooldown_spin_box()
        form.addRow(tr("gui.settings.cooldown"), self.spin_cooldown)
        box_layout.addLayout(form)
        right.addWidget(box)

        box, box_layout = self._group("gui.settings.secret_key")
        form = QFormLayout()
        self.inp_key = password_input()
        self.inp_confirm = password_input()
        form.addRow(tr("gui.settings.new_key"), self.inp_key)
        form.addRow(tr("gui.settings.confirm_key"), self.inp_confirm)
        box_layout.addLayout(form)
        box_layout.addWidget(hint_label(tr("gui.settings.key_hint", min=school_settings.ADMIN_SECRET_KEY_MIN_LENGTH)))
        right.addWidget(box)
        right.addStretch()

    def _group(self, title_key: str) -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(tr(title_key))
        box.setStyleSheet(GROUP_BOX_STYLE)
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(8)
        return box, box_layout

    def show_school(self, school: school_settings.SchoolSettings):
        """Show `school` in the form, dropping any unsaved edits."""
        self._school = school
        self.combo_language.setCurrentIndex(self.combo_language.findData(school.school_language))
        self.grades.set_names(school.grades)
        self.sections.set_names(school.sections)
        self.weekdays.set_days(school.active_weekdays)
        self._show_holidays(school.holidays)
        self.time_late.setTime(school.late_threshold)
        self.spin_cooldown.setValue(school.cooldown_seconds)
        self.inp_key.clear()
        self.inp_confirm.clear()

    def holidays(self) -> tuple[date, ...]:
        return tuple(
            date.fromisoformat(self.list_holidays.item(row).data(Qt.ItemDataRole.UserRole))
            for row in range(self.list_holidays.count())
        )

    def _show_holidays(self, days: tuple[date, ...]):
        self.list_holidays.clear()
        for day in sorted(set(days)):
            item = QListWidgetItem(show_date(day.isoformat()))
            item.setData(Qt.ItemDataRole.UserRole, day.isoformat())
            self.list_holidays.addItem(item)

    def add_holiday(self):
        self._show_holidays((*self.holidays(), self.date_holiday.date().toPython()))

    def remove_holiday(self):
        row = self.list_holidays.currentRow()
        if row >= 0:
            self.list_holidays.takeItem(row)

    def _edited_school(self) -> school_settings.SchoolSettings:
        return replace(
            self._school,
            school_language=self.combo_language.currentData(),
            grades=self.grades.names(),
            sections=self.sections.names(),
            active_weekdays=self.weekdays.days(),
            holidays=self.holidays(),
            late_threshold=self.time_late.time().toPython(),
            cooldown_seconds=self.spin_cooldown.value(),
        )

    def save_settings(self):
        school = self._edited_school()
        renamed_sections = self.sections.renamed()
        new_key = self.inp_key.text()
        conn = database.connect(self.worker.settings.database_path)
        try:
            # Refuse before asking for Admin Approval, so the Admin approves only a change that can be saved.
            if new_key or self.inp_confirm.text():
                school_settings.check_new_secret_key(new_key, self.inp_confirm.text())
            school_settings.check(conn, school, renamed_sections)
        except school_settings.SchoolSettingsError as error:
            self._refuse(error)
            return
        finally:
            conn.close()

        approval = AdminAuthDialog(self.worker, self, tr("gui.settings.save_operation"))
        if approval.exec() != QDialog.Accepted or not approval.auth_token:
            return
        if new_key:
            school = replace(school, admin_secret_key_hash=school_settings.hash_secret_key(new_key))

        conn = database.connect(self.worker.settings.database_path)
        try:
            saved = school_settings.save(conn, school, renamed_sections=renamed_sections)
        except school_settings.SchoolSettingsError as error:
            self._refuse(error)
            return
        finally:
            conn.close()
        self.saved.emit(saved)

    def _refuse(self, error: school_settings.SchoolSettingsError):
        QMessageBox.warning(self, tr("gui.settings.error_title"), tr(error.code, **error.params))


# ---------------------------------------------------------------------------
# MAIN OPERATOR WINDOW (PySide6)
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    # Cloud Sync pulled new School Settings (on its own thread).
    school_settings_changed = Signal(object)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        set_school(load_school(settings))
        self.setWindowTitle(tr("gui.main.window_title"))
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(1120, 720)
        self.resize(1200, 760)

        # Initialize Background Cloud Sync & SQLite Cache Manager
        self._sync_conn = database.connect(settings.database_path)
        self.sync_worker = cloud_sync.CloudSyncWorker(
            self._sync_conn, settings, on_school_settings_changed=self.school_settings_changed.emit
        )

        # Initialize Hardware Worker Thread
        self.worker = HardwareWorker(settings)
        self.school_settings_changed.connect(self._on_school_settings_changed)
        self.sync_worker.start()
        self.worker.start()

        # Dedicated Live Access Window instance (Created once, opened on demand)
        self.live_window = LiveAccessWindow(self.worker, parent=None)

        self._hardware_status: tuple[str, bool] | None = None
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setInterval(500)
        self._rebuild_timer.timeout.connect(self._rebuild_once_no_dialog_is_open)

        self._init_ui()

        # Connect status
        self.worker.status_changed.connect(self.on_hardware_status)
        self.worker.mode_changed.connect(self.on_mode_changed)

    def _init_ui(self):
        # Base Application Canvas (Soft anti-fatigue off-white with cool blue tint)
        canvas = QWidget()
        canvas.setStyleSheet(f"background-color: {COLOR_BG_LIGHT};")
        self.setCentralWidget(canvas)

        root_layout = QHBoxLayout(canvas)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ----------------- SIDEBAR NAVIGATION -----------------
        # Sidebar styled with the exact background color of the Quickpass logo (#A4D0E9)
        sidebar = QFrame()
        sidebar.setFixedWidth(264)
        sidebar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_SIDEBAR_BG};
                border-right: 1px solid {COLOR_SIDEBAR_BORDER};
            }}
        """)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(14, 18, 14, 18)
        sb_layout.setSpacing(12)

        # Dedicated Logo Container with smooth circular rounded corners
        logo_container = QFrame()
        logo_container.setStyleSheet("background: transparent; border: none; padding: 2px 0;")
        logo_lay = QVBoxLayout(logo_container)
        logo_lay.setContentsMargins(0, 0, 0, 0)
        logo_lay.setAlignment(Qt.AlignCenter)

        logo_file = LOGO_ROUNDED_PNG if LOGO_ROUNDED_PNG.exists() else (LOGO_PNG if LOGO_PNG.exists() else LOGO_PATH)
        if logo_file.exists():
            lbl_logo = QLabel()
            raw_pix = QPixmap(str(logo_file)).scaled(148, 148, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pix = get_rounded_pixmap(raw_pix, radius=34, border_color=COLOR_DARK_BLUE, border_width=3)
            lbl_logo.setPixmap(pix)
            lbl_logo.setAlignment(Qt.AlignCenter)
            logo_lay.addWidget(lbl_logo)
        else:
            lbl_logo = QLabel("QUICKPASS")
            lbl_logo.setFont(QFont("Arial", 20, QFont.Bold))
            lbl_logo.setStyleSheet(
                f"color: {COLOR_ACCENT}; border: 2px solid {COLOR_DARK_BLUE}; border-radius: 12px; padding: 6px;"
            )
            lbl_logo.setAlignment(Qt.AlignCenter)
            logo_lay.addWidget(lbl_logo)

        sb_layout.addWidget(logo_container)

        # Prominent Live Access Launcher Card on sidebar
        live_card = QFrame()
        live_card.setObjectName("liveCard")
        live_card.setStyleSheet(f"""
            QFrame#liveCard {{
                background-color: {COLOR_DARK_BLUE};
                border: 1px solid #1c3545;
                border-radius: 12px;
                padding: 12px;
            }}
        """)
        live_lay = QVBoxLayout(live_card)
        live_lay.setSpacing(8)

        self.lbl_live_indicator = QLabel(tr("gui.main.access_standby"))
        self.lbl_live_indicator.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_live_indicator.setStyleSheet(
            "color: #D1E5F2; font-weight: bold; background: transparent; border: none;"
        )
        live_lay.addWidget(self.lbl_live_indicator)

        self.btn_open_live = QPushButton(tr("gui.main.open_live"))
        self.btn_open_live.setFixedHeight(44)
        self.btn_open_live.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_ACCENT};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
        """)
        self.btn_open_live.clicked.connect(self.open_live_access_window)
        live_lay.addWidget(self.btn_open_live)

        self.btn_open_visit = QPushButton(tr("gui.live.register_visit"))
        self.btn_open_visit.setFixedHeight(38)
        self.btn_open_visit.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SUCCESS};
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-weight: bold;
                font-size: 13px;
                margin-top: 6px;
            }}
            QPushButton:hover {{ background-color: #059669; }}
        """)
        self.btn_open_visit.clicked.connect(self.open_register_visit_dialog)
        live_lay.addWidget(self.btn_open_visit)
        sb_layout.addWidget(live_card)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color: {COLOR_SIDEBAR_BORDER}; margin: 2px 0;")
        sb_layout.addWidget(div)

        # Larger Navigation Buttons
        self.nav_buttons: list[QPushButton] = []
        nav_items = [
            (tr("gui.main.nav.search"), 0),
            (tr("gui.main.nav.badges"), 1),
            (tr("gui.main.nav.settings"), 2),
        ]

        for text, idx in nav_items:
            btn = QPushButton(text)
            btn.setFixedHeight(52)
            btn.setFont(QFont("Arial", 13, QFont.Bold if idx == 0 else QFont.Normal))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {COLOR_PRIMARY};
                    border: none;
                    border-radius: 10px;
                    text-align: left;
                    padding-left: 20px;
                }}
                QPushButton:hover {{
                    background-color: {COLOR_SIDEBAR_HOVER};
                    color: #FFFFFF;
                }}
            """)
            btn.clicked.connect(lambda checked=False, i=idx: self.switch_view(i))
            sb_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sb_layout.addStretch()

        # Sidebar Hardware Status Badge
        self.lbl_hw_status = QLabel(tr("gui.main.searching"))
        self.lbl_hw_status.setStyleSheet(f"""
            background-color: {COLOR_WARNING_BG};
            color: {COLOR_WARNING_TEXT};
            border: 1px solid #FDE68A;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.lbl_hw_status.setAlignment(Qt.AlignCenter)
        sb_layout.addWidget(self.lbl_hw_status)

        root_layout.addWidget(sidebar)

        # ----------------- MAIN VIEW STACK -----------------
        self.view_stack = QStackedWidget()
        self.view_stack.setStyleSheet(f"background-color: {COLOR_BG_LIGHT};")

        # Views
        self.view_search_reports = UnifiedSearchReportsView(self.worker)
        self.view_badges = BadgeManagementView(self.worker)
        self.view_settings = SchoolSettingsView(self.worker)
        self.view_settings.saved.connect(self._on_settings_saved)

        self.view_stack.addWidget(self.view_search_reports)  # Index 0 (Default)
        self.view_stack.addWidget(self.view_badges)  # Index 1
        self.view_stack.addWidget(self.view_settings)  # Index 2

        root_layout.addWidget(self.view_stack, stretch=1)

        # Highlight default tab
        self._highlight_nav(0)

    def switch_view(self, index: int):
        self.view_stack.setCurrentIndex(index)
        self._highlight_nav(index)

    def _highlight_nav(self, active_idx: int):
        for idx, btn in enumerate(self.nav_buttons):
            if idx == active_idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {COLOR_SIDEBAR_HOVER};
                        color: #FFFFFF;
                        border-left: 5px solid {COLOR_ACCENT};
                        border-radius: 10px;
                        font-weight: bold;
                        font-size: 13px;
                        text-align: left;
                        padding-left: 16px;
                    }}
                    QPushButton:hover {{
                        background-color: {COLOR_SIDEBAR_HOVER};
                        color: #FFFFFF;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: transparent;
                        color: {COLOR_PRIMARY};
                        border: none;
                        border-radius: 10px;
                        font-weight: normal;
                        font-size: 13px;
                        text-align: left;
                        padding-left: 20px;
                    }}
                    QPushButton:hover {{
                        background-color: {COLOR_SIDEBAR_HOVER};
                        color: #FFFFFF;
                    }}
                """)

    def open_live_access_window(self):
        if self.live_window.isHidden():
            self.live_window.show()
        self.live_window.raise_()
        self.live_window.activateWindow()

    def open_register_visit_dialog(self):
        dlg = RegisterVisitDialog(self.worker, self)
        dlg.exec()

    def _on_school_settings_changed(self, school: school_settings.SchoolSettings):
        self.apply_school_settings(school)

    def _on_settings_saved(self, school: school_settings.SchoolSettings):
        self.sync_worker.request_sync()
        self.apply_school_settings(school)
        QMessageBox.information(self, tr("gui.settings.saved_title"), tr("gui.settings.saved"))

    def apply_school_settings(self, school: school_settings.SchoolSettings):
        """Show `school` in every window and on the gate screen; a new School Language rebuilds the windows."""
        language_changed = school.school_language != _language
        set_school(school)
        # The LCD screens read the School Language as they are built; the idle one is showing now.
        self.worker.send_idle_screen()
        if language_changed:
            self._rebuild_once_no_dialog_is_open()
        else:
            self.view_badges.refresh_users()
            self.view_search_reports.refresh_school_filters()
            self.view_settings.show_school(school)

    def _rebuild_once_no_dialog_is_open(self):
        # An open dialog may belong to one of the views a rebuild replaces.
        if QApplication.activeModalWidget() is None:
            self._rebuild_timer.stop()
            self.rebuild()
        elif not self._rebuild_timer.isActive():
            self._rebuild_timer.start()

    def rebuild(self):
        """Build both windows again, in the School Language now set."""
        view = self.view_stack.currentIndex()
        self.setWindowTitle(tr("gui.main.window_title"))
        self._init_ui()
        self.switch_view(view)
        self.on_mode_changed(self.worker.rfid_mode)
        if self._hardware_status is not None:
            self.on_hardware_status(*self._hardware_status)
        self.live_window.rebuild()

    def on_mode_changed(self, mode: str):
        if mode == RFIDMode.ACCESS_CONTROL:
            self.lbl_live_indicator.setText(tr("gui.main.access_active"))
            self.lbl_live_indicator.setStyleSheet(
                "color: #34D399; font-weight: bold; background: transparent; border: none;"
            )
        elif mode == RFIDMode.CAPTURE:
            self.lbl_live_indicator.setText(tr("gui.main.access_paused"))
            self.lbl_live_indicator.setStyleSheet(
                "color: #FCD34D; font-weight: bold; background: transparent; border: none;"
            )
        else:
            self.lbl_live_indicator.setText(tr("gui.main.access_standby"))
            self.lbl_live_indicator.setStyleSheet(
                "color: #D1E5F2; font-weight: bold; background: transparent; border: none;"
            )

    def on_hardware_status(self, msg: str, is_connected: bool):
        self._hardware_status = (msg, is_connected)
        if is_connected:
            self.lbl_hw_status.setText(tr("gui.main.arduino_connected"))
            self.lbl_hw_status.setStyleSheet(f"""
                background-color: {COLOR_SUCCESS_BG};
                color: {COLOR_SUCCESS_TEXT};
                padding: 8px 12px;
                border-radius: 8px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #A7F3D0;
            """)
        else:
            self.lbl_hw_status.setText(tr("gui.main.searching"))
            self.lbl_hw_status.setStyleSheet(f"""
                background-color: {COLOR_WARNING_BG};
                color: {COLOR_WARNING_TEXT};
                padding: 8px 12px;
                border-radius: 8px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #FDE68A;
            """)

    def closeEvent(self, event):
        self.worker.stop()
        if hasattr(self, "sync_worker") and self.sync_worker:
            self.sync_worker.stop()
        if hasattr(self, "_sync_conn") and self._sync_conn:
            self._sync_conn.close()
        if hasattr(self, "live_window") and self.live_window:
            self.live_window.close()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# First-Run Setup (Single-Screen Branded Station Initialization)
# ---------------------------------------------------------------------------
SETUP_LANGUAGE_PILL_STYLE = f"""
    QRadioButton {{
        background-color: {COLOR_BG_LIGHT};
        color: {COLOR_PRIMARY};
        border: 1.5px solid {COLOR_INPUT_BORDER};
        border-radius: 8px;
        padding: 7px 18px;
        font-size: 13px;
        font-weight: bold;
        spacing: 8px;
    }}
    QRadioButton:hover {{
        background-color: {COLOR_SURFACE_ALT};
        border-color: {COLOR_ACCENT};
    }}
    QRadioButton:checked {{
        background-color: {COLOR_ACCENT};
        color: #FFFFFF;
        border-color: {COLOR_ACCENT_HOVER};
    }}
    QRadioButton::indicator {{
        width: 12px;
        height: 12px;
        border-radius: 7.5px;
        border: 1.5px solid {COLOR_SECONDARY};
        background-color: {COLOR_SURFACE};
    }}
    QRadioButton::indicator:checked {{
        width: 10px;
        height: 10px;
        border-radius: 8px;
        border: 3px solid #FFFFFF;
        background-color: {COLOR_ACCENT_HOVER};
    }}
"""

SETUP_FINISH_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: #FFFFFF;
        border: none;
        border-radius: 8px;
        padding: 8px 22px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
    QPushButton:disabled {{
        background-color: #9CB4CC;
        color: #EDF4FA;
    }}
"""


class SetupWizard(QDialog):
    """Single-screen first-run setup. The School chooses its School Language, Grades, Sections,
    School Days, Late Threshold, Check-out wait, and Admin Secret Key in one view, framed by the
    Quickpass brand rail and a live station summary. Saving stores the School Settings locally,
    and Cloud Sync pushes them to Supabase."""

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._last_error: school_settings.SchoolSettingsError | None = None
        set_language(i18n.LANGUAGES[0])

        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(1080, 680)
        self.resize(1210, 750)
        self._init_ui()
        self._apply_texts()
        self._refresh_summary()

    def _init_ui(self):
        self.setObjectName("setupDialog")
        self.setStyleSheet(f"QDialog#setupDialog {{ background-color: {COLOR_BG_LIGHT}; }}")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Left Brand Rail (#A4D0E9 signature Quickpass sky blue) ----
        rail = QFrame()
        rail.setObjectName("setupBrandRail")
        rail.setFixedWidth(272)
        rail.setStyleSheet(f"""
            QFrame#setupBrandRail {{
                background-color: {COLOR_SIDEBAR_BG};
                border-right: 1px solid {COLOR_SIDEBAR_BORDER};
            }}
        """)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(20, 24, 20, 20)
        rail_layout.setSpacing(14)

        self.lbl_logo = QLabel()
        self.lbl_logo.setAlignment(Qt.AlignCenter)
        logo_file = LOGO_ROUNDED_PNG if LOGO_ROUNDED_PNG.exists() else (LOGO_PNG if LOGO_PNG.exists() else LOGO_PATH)
        if logo_file.exists():
            dpr = 2.0
            logo_px = 138
            raw_pix = QPixmap(str(logo_file)).scaled(
                int(logo_px * dpr),
                int(logo_px * dpr),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            pix = get_rounded_pixmap(
                raw_pix,
                radius=int(32 * dpr),
                border_color=COLOR_DARK_BLUE,
                border_width=int(3 * dpr),
            )
            pix.setDevicePixelRatio(dpr)
            self.lbl_logo.setPixmap(pix)
            self.lbl_logo.setFixedSize(logo_px, logo_px)
        else:
            self.lbl_logo.setText("QUICKPASS")
            self.lbl_logo.setFont(QFont("Arial", 18, QFont.Bold))
            self.lbl_logo.setStyleSheet(f"color: {COLOR_PRIMARY};")

        logo_wrap = QHBoxLayout()
        logo_wrap.addStretch()
        logo_wrap.addWidget(self.lbl_logo)
        logo_wrap.addStretch()
        rail_layout.addLayout(logo_wrap)

        self.lbl_rail_tagline = QLabel()
        self.lbl_rail_tagline.setWordWrap(True)
        self.lbl_rail_tagline.setAlignment(Qt.AlignCenter)
        self.lbl_rail_tagline.setStyleSheet(
            f"color: {COLOR_PRIMARY}; font-size: 12px; font-weight: bold; padding: 0 4px;"
        )
        rail_layout.addWidget(self.lbl_rail_tagline)

        # Live Station Summary Card in Technical Deep Navy (#122A42)
        summary_card = QFrame()
        summary_card.setObjectName("setupSummaryCard")
        summary_card.setStyleSheet(f"""
            QFrame#setupSummaryCard {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid #1E3A5A;
                border-radius: 12px;
            }}
        """)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 14, 14, 14)
        summary_layout.setSpacing(9)

        self.lbl_summary_title = QLabel()
        self.lbl_summary_title.setStyleSheet(f"color: {COLOR_SIDEBAR_BG}; font-size: 12px; font-weight: bold;")
        summary_layout.addWidget(self.lbl_summary_title)

        summary_div = QFrame()
        summary_div.setFixedHeight(1)
        summary_div.setStyleSheet("background-color: #244363;")
        summary_layout.addWidget(summary_div)

        self._summary_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("language", "grades", "sections", "weekdays", "late"):
            row_box = QVBoxLayout()
            row_box.setSpacing(2)
            lbl_k = QLabel()
            lbl_k.setStyleSheet("color: #8FB2CE; font-size: 10px;")
            lbl_v = QLabel()
            lbl_v.setStyleSheet("color: #FFFFFF; font-size: 12px; font-weight: bold;")
            row_box.addWidget(lbl_k)
            row_box.addWidget(lbl_v)
            summary_layout.addLayout(row_box)
            self._summary_rows[key] = (lbl_k, lbl_v)

        rail_layout.addWidget(summary_card)
        rail_layout.addStretch()

        self.lbl_rail_footer = QLabel()
        self.lbl_rail_footer.setWordWrap(True)
        self.lbl_rail_footer.setStyleSheet(f"color: {COLOR_DARK_BLUE}; font-size: 11px;")
        rail_layout.addWidget(self.lbl_rail_footer)

        root.addWidget(rail)

        # ---- Right Workspace ----
        workspace = QWidget()
        workspace.setObjectName("setupWorkspace")
        ws_layout = QVBoxLayout(workspace)
        ws_layout.setContentsMargins(26, 20, 26, 18)
        ws_layout.setSpacing(12)

        # Top Heading
        header_box = QVBoxLayout()
        header_box.setSpacing(3)
        self.lbl_heading = QLabel()
        self.lbl_heading.setFont(QFont("Arial", 20, QFont.Bold))
        self.lbl_heading.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 12px;")
        header_box.addWidget(self.lbl_heading)
        header_box.addWidget(self.lbl_subtitle)
        ws_layout.addLayout(header_box)

        # Language Selector Strip
        lang_bar = QFrame()
        lang_bar.setObjectName("setupLanguageBar")
        lang_bar.setStyleSheet(f"""
            QFrame#setupLanguageBar {{
                background-color: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 10px;
            }}
        """)
        lang_bar_layout = QHBoxLayout(lang_bar)
        lang_bar_layout.setContentsMargins(16, 11, 16, 11)
        lang_bar_layout.setSpacing(16)

        lang_text_box = QVBoxLayout()
        lang_text_box.setSpacing(2)
        self.lbl_lang_title = QLabel()
        self.lbl_lang_title.setFont(QFont("Arial", 13, QFont.Bold))
        self.lbl_lang_title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.lbl_lang_subtitle = QLabel()
        self.lbl_lang_subtitle.setWordWrap(True)
        self.lbl_lang_subtitle.setStyleSheet(f"color: {COLOR_SECONDARY}; font-size: 11px;")
        lang_text_box.addWidget(self.lbl_lang_title)
        lang_text_box.addWidget(self.lbl_lang_subtitle)
        lang_bar_layout.addLayout(lang_text_box, stretch=1)

        lang_group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        pills_row = QHBoxLayout()
        pills_row.setSpacing(10)
        for lang in i18n.LANGUAGES:
            button = QRadioButton(i18n.t(lang, "gui.wizard.language_name"))
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(SETUP_LANGUAGE_PILL_STYLE)
            button.toggled.connect(self._on_language_toggled)
            lang_group.addButton(button)
            pills_row.addWidget(button)
            self.buttons[lang] = button
        lang_bar_layout.addLayout(pills_row)
        ws_layout.addWidget(lang_bar)

        # Unified Two-Column Policy Sheet (inside scroll area for compact screens)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        sheet = QFrame()
        sheet.setObjectName("setupSheet")
        sheet.setStyleSheet(f"""
            QFrame#setupSheet {{
                background-color: {COLOR_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
        """)
        sheet_cols = QHBoxLayout(sheet)
        sheet_cols.setContentsMargins(20, 16, 20, 16)
        sheet_cols.setSpacing(20)

        # Left Column: Academic Structure (Grades & Sections)
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        self.lbl_structure_title = QLabel()
        self.lbl_structure_title.setFont(QFont("Arial", 13, QFont.Bold))
        self.lbl_structure_title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.lbl_structure_subtitle = hint_label()
        left_col.addWidget(self.lbl_structure_title)
        left_col.addWidget(self.lbl_structure_subtitle)

        self.lbl_grades = QLabel()
        self.lbl_grades.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px; font-weight: bold; margin-top: 4px;")
        self.grades = NameListEditor(
            "gui.settings.grade_placeholder",
            "gui.settings.add_grade",
            "gui.settings.remove_last_grade",
            remove_last_only=True,
        )
        self.grades.list.setFixedHeight(96)
        self.lbl_grades_hint = hint_label()
        left_col.addWidget(self.lbl_grades)
        left_col.addWidget(self.grades)
        left_col.addWidget(self.lbl_grades_hint)

        left_sep = QFrame()
        left_sep.setFixedHeight(1)
        left_sep.setStyleSheet(f"background-color: {COLOR_SURFACE_ALT}; margin: 2px 0;")
        left_col.addWidget(left_sep)

        self.lbl_sections = QLabel()
        self.lbl_sections.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px; font-weight: bold;")
        self.sections = NameListEditor(
            "gui.settings.section_placeholder",
            "gui.settings.add_section",
            "gui.settings.remove_section",
            remove_last_only=False,
        )
        self.sections.list.setFixedHeight(88)
        for editor in (self.grades, self.sections):
            editor.btn_add.setStyleSheet(PRIMARY_BUTTON_STYLE + "QPushButton { padding: 6px 10px; font-size: 12px; }")
            editor.btn_remove.setStyleSheet(
                SECONDARY_BUTTON_STYLE + "QPushButton { padding: 6px 10px; font-size: 12px; }"
            )
        self.lbl_sections_hint = hint_label()
        left_col.addWidget(self.lbl_sections)
        left_col.addWidget(self.sections)
        left_col.addWidget(self.lbl_sections_hint)
        left_col.addStretch()

        sheet_cols.addLayout(left_col, stretch=13)

        # Vertical Divider
        v_div = QFrame()
        v_div.setFixedWidth(1)
        v_div.setStyleSheet(f"background-color: {COLOR_BORDER};")
        sheet_cols.addWidget(v_div)

        # Right Column: School Days, Schedule, and Admin Secret Key
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        self.lbl_days_title = QLabel()
        self.lbl_days_title.setFont(QFont("Arial", 13, QFont.Bold))
        self.lbl_days_title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.lbl_days_subtitle = hint_label()
        right_col.addWidget(self.lbl_days_title)
        right_col.addWidget(self.lbl_days_subtitle)

        self.lbl_weekdays = QLabel()
        self.lbl_weekdays.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px; font-weight: bold; margin-top: 2px;")
        self.weekdays = WeekdayPicker()
        self.weekdays.set_days(school_settings.MONDAY_TO_FRIDAY)
        right_col.addWidget(self.lbl_weekdays)
        right_col.addWidget(self.weekdays)

        sched_form = QFormLayout()
        sched_form.setContentsMargins(0, 4, 0, 0)
        sched_form.setHorizontalSpacing(12)
        sched_form.setVerticalSpacing(8)
        self.lbl_late = QLabel()
        self.lbl_late.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px;")
        self.time_late = QTimeEdit(school_settings.DEFAULT_LATE_THRESHOLD)
        self.time_late.setStyleSheet(INPUT_STYLE)
        sched_form.addRow(self.lbl_late, self.time_late)

        self.lbl_cooldown = QLabel()
        self.lbl_cooldown.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px;")
        self.spin_cooldown = cooldown_spin_box()
        self.spin_cooldown.setValue(school_settings.DEFAULT_COOLDOWN_SECONDS)
        sched_form.addRow(self.lbl_cooldown, self.spin_cooldown)
        right_col.addLayout(sched_form)

        right_sep = QFrame()
        right_sep.setFixedHeight(1)
        right_sep.setStyleSheet(f"background-color: {COLOR_BORDER}; margin: 4px 0;")
        right_col.addWidget(right_sep)

        self.lbl_key_title = QLabel()
        self.lbl_key_title.setFont(QFont("Arial", 13, QFont.Bold))
        self.lbl_key_title.setStyleSheet(f"color: {COLOR_PRIMARY};")
        self.lbl_key_subtitle = hint_label()
        right_col.addWidget(self.lbl_key_title)
        right_col.addWidget(self.lbl_key_subtitle)

        key_form = QFormLayout()
        key_form.setContentsMargins(0, 2, 0, 0)
        key_form.setHorizontalSpacing(12)
        key_form.setVerticalSpacing(8)
        self.lbl_key = QLabel()
        self.lbl_key.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px;")
        self.inp_key = password_input()
        key_form.addRow(self.lbl_key, self.inp_key)

        self.lbl_confirm = QLabel()
        self.lbl_confirm.setStyleSheet(f"color: {COLOR_PRIMARY}; font-size: 12px;")
        self.inp_confirm = password_input()
        key_form.addRow(self.lbl_confirm, self.inp_confirm)
        right_col.addLayout(key_form)

        self.lbl_key_hint = hint_label()
        right_col.addWidget(self.lbl_key_hint)
        right_col.addStretch()

        sheet_cols.addLayout(right_col, stretch=10)

        scroll.setWidget(sheet)
        ws_layout.addWidget(scroll, stretch=1)

        # Pinned Bottom Action Bar
        footer = QHBoxLayout()
        footer.setSpacing(12)

        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("setupErrorBanner")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        self.lbl_error.setStyleSheet(f"""
            QLabel#setupErrorBanner {{
                background-color: {COLOR_ERROR_BG};
                color: {COLOR_ERROR_TEXT};
                border: 1px solid #FECACA;
                border-radius: 8px;
                padding: 7px 12px;
                font-size: 12px;
                font-weight: bold;
            }}
        """)
        footer.addWidget(self.lbl_error, stretch=1)

        footer_spacer = QWidget()
        footer_spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._footer_spacer = footer_spacer
        footer.addWidget(footer_spacer, stretch=1)

        self.btn_cancel = QPushButton()
        self.btn_cancel.setFixedHeight(40)
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_finish = QPushButton()
        self.btn_finish.setFixedHeight(40)
        self.btn_finish.setCursor(Qt.PointingHandCursor)
        self.btn_finish.setStyleSheet(SETUP_FINISH_BUTTON_STYLE)
        self.btn_finish.setEnabled(False)
        self.btn_finish.clicked.connect(self.finish_setup)
        footer.addWidget(self.btn_finish)

        ws_layout.addLayout(footer)
        root.addWidget(workspace, stretch=1)

        # Live summary connections
        for editor in (self.grades, self.sections):
            editor.list.model().rowsInserted.connect(lambda *_: self._refresh_summary())
            editor.list.model().rowsRemoved.connect(lambda *_: self._refresh_summary())
            editor.list.itemChanged.connect(lambda *_: self._refresh_summary())
        for box in self.weekdays.boxes:
            box.toggled.connect(lambda *_: self._refresh_summary())
        self.time_late.timeChanged.connect(lambda *_: self._refresh_summary())

    def language(self) -> str | None:
        return next((lang for lang, button in self.buttons.items() if button.isChecked()), None)

    def _on_language_toggled(self, checked: bool):
        lang = self.language()
        if checked and lang:
            self.use_language(lang)

    def use_language(self, lang: str):
        set_language(lang)
        self.btn_finish.setEnabled(True)
        self._apply_texts()
        self._refresh_summary()
        if self._last_error is not None:
            self._show_error(self._last_error)

    def _apply_texts(self):
        chosen = self.language()
        if chosen is None:
            self.setWindowTitle(in_every_language("gui.wizard.window_title"))
            self.lbl_heading.setText(in_every_language("gui.wizard.heading"))
            self.lbl_lang_title.setText(in_every_language("gui.wizard.language.title"))
            self.btn_cancel.setText(in_every_language("gui.common.cancel"))
            self.btn_finish.setText(in_every_language("gui.wizard.finish"))
        else:
            self.setWindowTitle(tr("gui.wizard.window_title"))
            self.lbl_heading.setText(tr("gui.wizard.heading"))
            self.lbl_lang_title.setText(tr("gui.wizard.language.title"))
            self.btn_cancel.setText(tr("gui.common.cancel"))
            self.btn_finish.setText(tr("gui.wizard.finish"))

        self.lbl_subtitle.setText(tr("gui.wizard.subtitle"))
        self.lbl_lang_subtitle.setText(tr("gui.wizard.language.subtitle"))
        self.lbl_rail_tagline.setText(tr("gui.wizard.rail_tagline"))
        self.lbl_rail_footer.setText(tr("gui.wizard.rail_footer"))
        self.lbl_summary_title.setText(tr("gui.wizard.preview.title"))

        self._summary_rows["language"][0].setText(tr("gui.settings.language"))
        self._summary_rows["grades"][0].setText(tr("gui.settings.grades"))
        self._summary_rows["sections"][0].setText(tr("gui.settings.sections"))
        self._summary_rows["weekdays"][0].setText(tr("gui.settings.weekdays"))
        self._summary_rows["late"][0].setText(tr("gui.settings.late_threshold").rstrip(":"))

        self.lbl_structure_title.setText(tr("gui.wizard.structure.title"))
        self.lbl_structure_subtitle.setText(tr("gui.wizard.structure.subtitle"))
        self.lbl_grades.setText(tr("gui.settings.grades"))
        self.grades.retranslate()
        self.lbl_grades_hint.setText(tr("gui.settings.grades_hint"))
        self.lbl_sections.setText(tr("gui.settings.sections"))
        self.sections.retranslate()
        self.lbl_sections_hint.setText(tr("gui.settings.sections_hint"))

        self.lbl_days_title.setText(tr("gui.wizard.days.title"))
        self.lbl_days_subtitle.setText(tr("gui.wizard.days.subtitle"))
        self.lbl_weekdays.setText(tr("gui.settings.weekdays"))
        self.weekdays.retranslate()
        self.lbl_late.setText(tr("gui.settings.late_threshold"))
        self.time_late.setLocale(QLocale())
        self.time_late.setDisplayFormat(tr("gui.settings.time_picker_format"))
        self.lbl_cooldown.setText(tr("gui.settings.cooldown"))

        self.lbl_key_title.setText(tr("gui.wizard.key.title"))
        self.lbl_key_subtitle.setText(tr("gui.wizard.key.subtitle"))
        self.lbl_key.setText(tr("gui.settings.new_key"))
        self.lbl_confirm.setText(tr("gui.settings.confirm_key"))
        self.lbl_key_hint.setText(tr("gui.wizard.key.hint", min=school_settings.ADMIN_SECRET_KEY_MIN_LENGTH))

    def _refresh_summary(self):
        chosen = self.language()
        unset = tr("gui.wizard.preview.unset")
        self._summary_rows["language"][1].setText(i18n.t(chosen, "gui.wizard.language_name") if chosen else unset)

        grades = [g.strip() for g in self.grades.names() if g.strip()]
        if grades:
            self._summary_rows["grades"][1].setText(
                tr("gui.wizard.preview.grades_count", first=grades[0], last=grades[-1], count=len(grades))
            )
        else:
            self._summary_rows["grades"][1].setText(unset)

        sections = [s.strip() for s in self.sections.names() if s.strip()]
        if sections:
            joined = ", ".join(sections)
            preview_names = joined if len(joined) <= 20 else f"{sections[0]} … {sections[-1]}"
            self._summary_rows["sections"][1].setText(
                tr("gui.wizard.preview.sections_count", names=preview_names, count=len(sections))
            )
        else:
            self._summary_rows["sections"][1].setText(unset)

        days = self.weekdays.days()
        self._summary_rows["weekdays"][1].setText(
            tr("gui.wizard.preview.weekdays_count", count=len(days)) if days else unset
        )
        self._summary_rows["late"][1].setText(show_time(self.time_late.time().toPython().strftime("%H:%M:%S")))

    def _show_error(self, error: school_settings.SchoolSettingsError):
        self._last_error = error
        self.lbl_error.setText(tr(error.code, **error.params))
        self.lbl_error.setVisible(True)
        self._footer_spacer.setVisible(False)

    def _clear_error(self):
        self._last_error = None
        self.lbl_error.clear()
        self.lbl_error.setVisible(False)
        self._footer_spacer.setVisible(True)

    def finish_setup(self) -> bool:
        try:
            lang = self.language() or ""
            if lang not in school_settings.SCHOOL_LANGUAGES:
                raise school_settings.SchoolSettingsError("settings.error.language")
            school_settings.validate_grades(self.grades.names())
            school_settings.validate_sections(self.sections.names())
            school_settings.validate_weekdays(self.weekdays.days())
            if self.spin_cooldown.value() < 0:
                raise school_settings.SchoolSettingsError("settings.error.cooldown")
            school_settings.check_new_secret_key(self.inp_key.text(), self.inp_confirm.text())
            self.save(school_settings.hash_secret_key(self.inp_key.text()), lang=lang)
        except school_settings.SchoolSettingsError as error:
            self._show_error(error)
            return False
        self._clear_error()
        self.accept()
        return True

    def save(self, admin_secret_key_hash: str, lang: str | None = None):
        """Store the School Settings typed in; raises SchoolSettingsError if they are refused."""
        school = school_settings.SchoolSettings(
            school_language=lang if lang is not None else (self.language() or ""),
            grades=self.grades.names(),
            sections=self.sections.names(),
            active_weekdays=self.weekdays.days(),
            late_threshold=self.time_late.time().toPython(),
            cooldown_seconds=self.spin_cooldown.value(),
            admin_secret_key_hash=admin_secret_key_hash,
        )
        conn = database.connect(self.settings.database_path)
        try:
            school_settings.save(conn, school)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
class SettingsDownloadFailed(Exception):
    """Cloud Sync could not reach Supabase to download the School Settings."""


def needs_first_run_setup(settings: Settings) -> bool:
    """Whether this station needs the first-run setup: it caches no School Settings, and Supabase
    (when Cloud Sync is set up) has none to download either."""
    conn = database.connect(settings.database_path)
    try:
        if school_settings.load(conn) is not None:
            return False
        result = cloud_sync.CloudSyncWorker(conn, settings).sync_school_settings()
        if result.failed:
            raise SettingsDownloadFailed(
                f"Quickpass could not download this School's settings from Supabase ({result.error}). "
                "Check the internet connection and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env, "
                "then start Quickpass again."
            )
        return school_settings.load(conn) is None
    finally:
        conn.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        settings = load_settings()
    except ConfigError as error:
        QMessageBox.critical(None, "Quickpass", str(error))
        sys.exit(1)

    # Set native application identity and icon (replaces default Python rocket icon in Dock)
    app.setApplicationName("Quickpass")
    app.setApplicationDisplayName("Quickpass")
    app_icon = get_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    # Set light application palette adhering to the brand tokens
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLOR_BG_LIGHT))
    palette.setColor(QPalette.WindowText, QColor(COLOR_PRIMARY))
    palette.setColor(QPalette.Base, QColor(COLOR_SURFACE))
    palette.setColor(QPalette.AlternateBase, QColor(COLOR_SURFACE_ALT))
    palette.setColor(QPalette.ToolTipBase, QColor(COLOR_PRIMARY))
    palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Text, QColor(COLOR_PRIMARY))
    palette.setColor(QPalette.Button, QColor(COLOR_SURFACE))
    palette.setColor(QPalette.ButtonText, QColor(COLOR_PRIMARY))
    palette.setColor(QPalette.BrightText, QColor(COLOR_ERROR))
    palette.setColor(QPalette.Highlight, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)

    try:
        setup_needed = needs_first_run_setup(settings)
    except SettingsDownloadFailed as error:
        QMessageBox.critical(None, "Quickpass", str(error))
        sys.exit(1)
    if setup_needed and SetupWizard(settings).exec() != QDialog.Accepted:
        sys.exit(0)

    win = MainWindow(settings)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
