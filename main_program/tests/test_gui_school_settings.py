"""The first-run setup and the School Settings view: a School sets its policies at the
station, Cloud Sync carries them to Supabase, and a School Language switch reaches every
window and the gate screen at once."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import date, time
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import ADMIN_SECRET_KEY, make_school, store_school
from PySide6.QtCore import QDate, QLocale, Qt, QTime
from PySide6.QtWidgets import QApplication, QDialog

import admin
import arduino
import cloud_sync
import database
import gui
import school_settings
from gui import HardwareWorker, MainWindow
from school_settings import SchoolSettings

SPANISH_GRADES = tuple(f"{rank}°" for rank in range(1, 12))


@pytest.fixture(autouse=True)
def _windows_show_the_stored_school():
    gui.set_school(make_school())


@pytest.fixture(autouse=True)
def _no_serial_thread(monkeypatch):
    monkeypatch.setattr(HardwareWorker, "start", lambda self: None)


@pytest.fixture
def window(qapp, settings):
    win = MainWindow(settings)
    yield win
    win.close()
    win.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def wizard(qapp, settings):
    """The setup wizard on a station that has never been set up."""
    conn = database.connect(settings.database_path)
    with conn:
        conn.execute("DELETE FROM school_settings")
    conn.close()
    setup = gui.SetupWizard(settings)
    yield setup
    setup.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def computer_locale(qapp):
    """Sets the computer's own locale, which Quickpass must not follow."""
    before = QLocale()
    yield lambda name: QLocale.setDefault(QLocale(name))
    QLocale.setDefault(before)


def _stored(settings):
    conn = database.connect(settings.database_path)
    try:
        return school_settings.load_cached(conn)
    finally:
        conn.close()


def _texts(list_widget):
    return [list_widget.item(row).text() for row in range(list_widget.count())]


def _add(editor, *names):
    for name in names:
        editor.inp_name.setText(name)
        editor.btn_add.click()


# --- First-run setup ------------------------------------------------------------


def test_first_run_setup_starts_with_no_school_language_chosen(wizard):
    buttons = wizard.buttons

    assert wizard.lbl_logo.pixmap() is not None and not wizard.lbl_logo.pixmap().isNull()
    assert {lang: button.text() for lang, button in buttons.items()} == {"es": "Español", "en": "English"}
    assert not any(button.isChecked() for button in buttons.values())
    assert not wizard.btn_finish.isEnabled()
    assert wizard.btn_finish.text() == "Iniciar Quickpass / Start Quickpass"
    assert wizard.btn_cancel.text() == "Cancelar / Cancel"
    assert wizard.lbl_heading.text() == "Configure su colegio / Set up your School"

    buttons["en"].click()

    assert wizard.btn_finish.isEnabled()
    assert wizard.btn_finish.text() == "Start Quickpass"
    assert wizard.btn_cancel.text() == "Cancel"
    assert wizard.windowTitle() == "Quickpass - First-Run Setup"
    assert wizard.lbl_structure_title.text() == "Grades and Sections"
    assert wizard.lbl_days_title.text() == "School Days and Schedule"
    assert wizard.lbl_key_title.text() == "Admin Secret Key"


def test_first_run_setup_saves_the_school_settings_for_cloud_sync_to_push(wizard, settings):
    wizard.buttons["en"].click()

    _add(wizard.grades, "Kindergarten", "Grade 1", "Grade 2")
    _add(wizard.sections, "Blue", "Green")
    assert wizard._summary_rows["grades"][1].text() == "Kindergarten to Grade 2 (3)"
    assert wizard._summary_rows["sections"][1].text() == "Blue, Green (2)"

    assert [box.text() for box in wizard.weekdays.boxes] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    assert wizard.weekdays.days() == (0, 1, 2, 3, 4)
    wizard.weekdays.boxes[5].setChecked(True)
    wizard.time_late.setTime(QTime(7, 15))
    wizard.spin_cooldown.setValue(120)

    wizard.inp_key.setText("open-sesame-42")
    wizard.inp_confirm.setText("open-sesame-42")
    wizard.btn_finish.click()

    assert wizard.result() == QDialog.Accepted
    stored = _stored(settings)
    assert stored.synced is False
    assert replace(stored.school, admin_secret_key_hash="") == SchoolSettings(
        school_language="en",
        grades=("Kindergarten", "Grade 1", "Grade 2"),
        sections=("Blue", "Green"),
        active_weekdays=(0, 1, 2, 3, 4, 5),
        holidays=(),
        late_threshold=time(7, 15),
        cooldown_seconds=120,
        admin_secret_key_hash="",
    )
    assert school_settings.verify_secret_key("open-sesame-42", stored.school.admin_secret_key_hash)


def test_first_run_setup_stays_open_until_every_setting_is_valid(wizard, settings):
    wizard.buttons["es"].click()
    assert wizard.lbl_structure_title.text() == "Grados y secciones"

    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == "Agregue al menos un grado."

    _add(wizard.grades, "1°", "1°")
    _add(wizard.sections, "ALL")
    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == "Hay dos grados con el mismo nombre."

    wizard.grades.list.item(1).setText("2°")
    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == '"ALL" no puede ser el nombre de una sección.'

    wizard.sections.list.item(0).setText("A")
    for box in wizard.weekdays.boxes:
        box.setChecked(False)
    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == "Elija al menos un día de clases."

    wizard.weekdays.boxes[0].setChecked(True)
    wizard.inp_key.setText("corta")
    wizard.inp_confirm.setText("corta")
    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == "La clave secreta debe tener al menos 8 caracteres."

    wizard.inp_key.setText("clave-larga-1")
    wizard.inp_confirm.setText("clave-larga-2")
    wizard.btn_finish.click()
    assert wizard.lbl_error.text() == "Las dos claves no coinciden."

    wizard.buttons["en"].click()
    assert wizard.lbl_error.text() == "The two keys do not match."

    assert wizard.result() != QDialog.Accepted
    assert _stored(settings) is None


def test_first_run_setup_shows_times_in_the_chosen_language_whatever_the_computers_locale(
    qapp, settings, computer_locale
):
    computer_locale("es_ES")
    setup = gui.SetupWizard(settings)
    try:
        setup.buttons["en"].click()
        setup.time_late.setTime(QTime(13, 5))
        assert setup.time_late.text() == "01:05:00 PM"
    finally:
        setup.deleteLater()
        QApplication.processEvents()


def test_the_setup_runs_only_when_neither_the_station_nor_supabase_has_school_settings(settings, monkeypatch):
    class FakeSupabase:
        answer: object = None

        def __init__(self, *args, **kwargs):
            pass

        def fetch_school_settings(self):
            if isinstance(FakeSupabase.answer, Exception):
                raise FakeSupabase.answer
            return FakeSupabase.answer

        def upsert_school_settings(self, row):
            raise AssertionError("a station that was never set up has nothing to push")

    monkeypatch.setattr(cloud_sync, "SupabaseSyncClient", FakeSupabase)
    with_cloud_sync = replace(settings, supabase_url="https://school.supabase.co", supabase_service_role_key="key")

    assert gui.needs_first_run_setup(settings) is False

    conn = database.connect(settings.database_path)
    with conn:
        conn.execute("DELETE FROM school_settings")
    conn.close()
    assert gui.needs_first_run_setup(settings) is True
    assert gui.needs_first_run_setup(with_cloud_sync) is True

    FakeSupabase.answer = OSError("network is unreachable")
    with pytest.raises(gui.SettingsDownloadFailed):
        gui.needs_first_run_setup(with_cloud_sync)

    FakeSupabase.answer = school_settings.to_cloud_row(make_school(school_language="en"), "2026-10-05T07:00:00+00:00")
    assert gui.needs_first_run_setup(with_cloud_sync) is False
    assert _stored(settings).school == make_school(school_language="en")


# --- School Settings view --------------------------------------------------------


def test_school_settings_view_shows_the_schools_settings(qapp, settings):
    conn = database.connect(settings.database_path)
    store_school(
        conn,
        make_school(
            grades=("Pre-K", "Kinder", "1st"),
            sections=("Única", "Azul"),
            active_weekdays=(0, 1, 2, 3, 4, 5),
            holidays=(date(2026, 12, 25),),
            late_threshold=time(7, 15),
            cooldown_seconds=120,
        ),
    )
    conn.close()
    worker = HardwareWorker(settings)
    view = gui.SchoolSettingsView(worker)
    try:
        assert view.combo_language.currentData() == "es"
        assert view.grades.names() == ("Pre-K", "Kinder", "1st")
        assert view.sections.names() == ("Única", "Azul")
        assert view.weekdays.days() == (0, 1, 2, 3, 4, 5)
        assert _texts(view.list_holidays) == ["25/12/2026"]
        assert view.time_late.time() == QTime(7, 15)
        assert view.spin_cooldown.value() == 120
        assert view.inp_key.text() == view.inp_confirm.text() == ""
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


@pytest.mark.parametrize(
    ("language", "computer", "late_threshold", "october"),
    [("en", "es_ES", "01:05:00 PM", "October"), ("es", "en_US", "13:05:00", "octubre")],
)
def test_date_and_time_pickers_follow_the_school_language_not_the_computers_locale(
    settings, computer_locale, language, computer, late_threshold, october
):
    computer_locale(computer)
    conn = database.connect(settings.database_path)
    school = store_school(conn, make_school(school_language=language, late_threshold=time(13, 5)))
    conn.close()
    gui.set_school(school)
    worker = HardwareWorker(settings)
    view = gui.SchoolSettingsView(worker)
    try:
        assert view.time_late.text() == late_threshold
        assert view.date_holiday.calendarWidget().locale().monthName(10) == october
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_saving_school_settings_needs_admin_approval(settings, window, approval, messages):
    panel = window.view_settings
    panel.date_holiday.setDate(QDate(2026, 10, 12))
    panel.btn_add_holiday.click()
    approval.key = "not-the-key"

    panel.btn_save.click()

    assert approval.asked == 1
    assert _stored(settings).school.holidays == ()
    assert messages == []


def test_a_holiday_saved_in_school_settings_goes_to_cloud_sync(settings, window, approval, messages, monkeypatch):
    sync_requests = []
    monkeypatch.setattr(window.sync_worker, "request_sync", lambda: sync_requests.append(True))
    panel = window.view_settings
    panel.date_holiday.setDate(QDate(2026, 10, 12))
    panel.btn_add_holiday.click()
    assert _texts(panel.list_holidays) == ["12/10/2026"]

    panel.btn_save.click()

    stored = _stored(settings)
    assert stored.school.holidays == (date(2026, 10, 12),)
    assert stored.synced is False
    assert sync_requests == [True]
    assert messages == [("information", "La configuración del colegio se guardó.")]


def test_switching_the_school_language_rebuilds_every_window_and_the_gate_screen(window, approval, messages):
    window.switch_view(2)
    panel = window.view_settings
    panel.combo_language.setCurrentIndex(panel.combo_language.findData("en"))
    window.worker._pending_commands.clear()

    panel.btn_save.click()

    assert window.windowTitle() == "Quickpass - School Attendance and Access Control"
    assert [button.text() for button in window.nav_buttons] == [
        "Search and Reports",
        "Badge Management",
        "School Settings",
    ]
    assert window.lbl_hw_status.text() == "Searching for the Arduino..."
    assert window.view_stack.currentIndex() == 2
    assert window.view_settings.combo_language.currentData() == "en"
    assert window.live_window.windowTitle() == "Quickpass - Live Access Control"
    assert window.worker._pending_commands[-1] == arduino.idle_screen("en")
    assert messages == [("information", "The School Settings were saved.")]


def test_a_school_language_pulled_by_cloud_sync_rebuilds_the_windows(settings, window):
    conn = database.connect(settings.database_path)
    english = store_school(conn, make_school(school_language="en"))
    conn.close()

    window.school_settings_changed.emit(english)
    QApplication.processEvents()

    assert window.nav_buttons[0].text() == "Search and Reports"
    assert window.view_settings.combo_language.currentData() == "en"


def test_the_grade_list_renames_in_place_adds_at_the_end_and_removes_only_the_last(window):
    grades = window.view_settings.grades
    assert all(grades.list.item(row).flags() & Qt.ItemIsEditable for row in range(grades.list.count()))

    grades.list.item(0).setText("Primero")
    grades.list.setCurrentRow(1)
    _add(grades, "12°")
    assert grades.names() == ("Primero", *SPANISH_GRADES[1:], "12°")

    grades.btn_remove.click()
    grades.btn_remove.click()
    assert grades.names() == ("Primero", *SPANISH_GRADES[1:10])


def test_removing_a_grade_that_people_hold_is_refused_before_approval(settings, window, approval, messages):
    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, "AA0011", "student", "Ana Once", grade=11, section="D")
    conn.close()
    panel = window.view_settings
    panel.grades.btn_remove.click()

    panel.btn_save.click()

    assert messages == [
        (
            "warning",
            'El grado "11°" aún tiene 1 estudiantes o profesores activos. Muévalos a otro grado antes de quitarlo.',
        )
    ]
    assert approval.asked == 0
    assert _stored(settings).school.grades == SPANISH_GRADES


def test_renaming_a_section_keeps_its_students_in_it_under_the_new_name(settings, window, approval, messages):
    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, "AA0012", "student", "Ana Azul", grade=3, section="A")
    conn.close()
    panel = window.view_settings
    panel.sections.list.item(0).setText("Azul")

    panel.btn_save.click()

    assert messages == [("information", "La configuración del colegio se guardó.")]
    assert _stored(settings).school.sections == ("Azul", "B", "C", "D")
    conn = database.connect(settings.database_path)
    try:
        assert database.get_user_by_badge_uid(conn, "AA0012")["section"] == "Azul"
    finally:
        conn.close()


def test_a_new_admin_secret_key_replaces_the_old_one(settings, window, approval, messages):
    panel = window.view_settings
    panel.inp_key.setText("clave-nueva-2026")
    panel.inp_confirm.setText("clave-nueva-2027")
    panel.btn_save.click()
    assert messages == [("warning", "Las dos claves no coinciden.")]
    assert approval.asked == 0

    messages.clear()
    panel.inp_confirm.setText("clave-nueva-2026")
    panel.btn_save.click()

    stored_hash = _stored(settings).school.admin_secret_key_hash
    assert school_settings.verify_secret_key("clave-nueva-2026", stored_hash)
    assert not school_settings.verify_secret_key(ADMIN_SECRET_KEY, stored_hash)
    assert window.view_settings.inp_key.text() == ""
