"""Unit and regression tests for Quickpass GUI enhancements."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import gate_screen, make_school, store_school
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

import arduino
import database
import gui
from gui import (
    COLOR_DARK_BLUE,
    COLOR_SIDEBAR_HOVER,
    AdminAuthDialog,
    EditBadgeDialog,
    HardwareWorker,
    LiveAccessWindow,
    MainWindow,
    RegisterBadgeDialog,
    RFIDMode,
    get_rounded_pixmap,
    resolve_post_dialog_rfid_mode,
)


@pytest.fixture(autouse=True)
def _windows_show_the_stored_school():
    """The windows start each test with the School Settings conftest stores."""
    gui.set_school(make_school())


def _use_school(settings, school):
    conn = database.connect(settings.database_path)
    store_school(conn, school)
    conn.close()
    gui.set_school(school)
    return school


@pytest.fixture
def english_school(settings):
    """The School speaks English, in the windows and on the LCD."""
    return _use_school(settings, make_school(school_language="en"))


@pytest.fixture
def kinder_school(settings):
    """A School that names its own Grades and Sections."""
    return _use_school(settings, make_school(grades=("Pre-K", "Kinder", "1st"), sections=("Única", "Azul")))


def _items(combo):
    return [combo.itemText(i) for i in range(combo.count())]


def test_get_rounded_pixmap_with_border(qapp):
    pix = QPixmap(100, 100)
    pix.fill(QColor("blue"))

    rounded = get_rounded_pixmap(pix, radius=20, border_color="#27475c", border_width=3)
    assert not rounded.isNull()
    assert rounded.width() == 100
    assert rounded.height() == 100


def test_resolve_post_dialog_rfid_mode(qapp, settings):
    worker = HardwareWorker(settings)
    try:
        # When no LiveAccessWindow is visible
        assert resolve_post_dialog_rfid_mode(RFIDMode.STANDBY) == RFIDMode.STANDBY

        # When preferred is CAPTURE, should fallback
        assert resolve_post_dialog_rfid_mode(RFIDMode.CAPTURE) == RFIDMode.STANDBY

        # When LiveAccessWindow is open/visible
        live_win = LiveAccessWindow(worker)
        live_win.show()
        assert live_win.isVisible()
        assert resolve_post_dialog_rfid_mode(RFIDMode.STANDBY) == RFIDMode.ACCESS_CONTROL
        live_win.close()
        live_win.deleteLater()
        QApplication.processEvents()
    finally:
        worker.deleteLater()
        QApplication.processEvents()


def test_dialog_accept_restores_rfid_mode(qapp, settings):
    worker = HardwareWorker(settings)
    try:
        worker.rfid_mode = RFIDMode.STANDBY

        # 1. AdminAuthDialog
        auth_dlg = AdminAuthDialog(worker, None, "Test Operation")
        assert worker.rfid_mode == RFIDMode.CAPTURE
        assert auth_dlg._rfid_connected is True

        auth_dlg.accept()
        assert worker.rfid_mode == RFIDMode.STANDBY
        assert auth_dlg._rfid_connected is False
        auth_dlg.deleteLater()

        # 2. RegisterBadgeDialog
        reg_dlg = RegisterBadgeDialog(worker, None)
        assert worker.rfid_mode == RFIDMode.CAPTURE
        assert reg_dlg._rfid_connected is True

        reg_dlg.accept()
        assert worker.rfid_mode == RFIDMode.STANDBY
        assert reg_dlg._rfid_connected is False
        reg_dlg.deleteLater()
        QApplication.processEvents()
    finally:
        worker.deleteLater()
        QApplication.processEvents()


def test_sidebar_styles_and_hardware_status(qapp, settings, monkeypatch):
    monkeypatch.setattr(HardwareWorker, "start", lambda self: None)
    win = MainWindow(settings)
    try:
        # 1. Hardware status initial state (Buscando Conexión in yellow)
        assert "Buscando Conexión" in win.lbl_hw_status.text()
        assert "#FDE68A" in win.lbl_hw_status.styleSheet()

        # 2. On connected: should show "Arduino Conectado" without port in green
        win.on_hardware_status("Connected", True)
        assert win.lbl_hw_status.text() == "Arduino Conectado"
        assert "(" not in win.lbl_hw_status.text()
        assert "#A7F3D0" in win.lbl_hw_status.styleSheet()

        # 3. On disconnected: should return to "Buscando Conexión..." in yellow
        win.on_hardware_status("Disconnected", False)
        assert "Buscando Conexión" in win.lbl_hw_status.text()
        assert "#FDE68A" in win.lbl_hw_status.styleSheet()

        # 4. Sidebar nav buttons hover styles use COLOR_SIDEBAR_HOVER (#27475c)
        win._highlight_nav(0)
        inactive_btn = win.nav_buttons[1]
        assert COLOR_SIDEBAR_HOVER in inactive_btn.styleSheet()
        assert "#FFFFFF" in inactive_btn.styleSheet()

        # 5. Live card background is COLOR_DARK_BLUE (#27475c)
        live_card = win.findChild(gui.QFrame, "liveCard")
        assert live_card is not None
        assert COLOR_DARK_BLUE in live_card.styleSheet()
    finally:
        win.close()
        win.deleteLater()
        QApplication.processEvents()


def test_student_square_scan_banners(qapp):
    square = gui.StudentSquareWidget()
    try:
        # 1. Unregistered
        square.update_scan({"is_registered": False})
        assert square.status_banner.text() == "TARJETA NO REGISTRADA"
        assert gui.COLOR_ERROR in square.status_banner.styleSheet()

        # 2. Graduate denied
        square.update_scan({"is_registered": True, "event_type": "graduate_denied"})
        assert square.status_banner.text() == "ACCESO DENEGADO (GRADUADO)"
        assert gui.COLOR_ERROR in square.status_banner.styleSheet()

        # 3. Inactive denied
        square.update_scan({"is_registered": True, "event_type": "inactive_denied"})
        assert square.status_banner.text() == "ACCESO DENEGADO (INACTIVO)"
        assert gui.COLOR_ERROR in square.status_banner.styleSheet()

        # 4. Check out
        square.update_scan({"is_registered": True, "event_type": "check_out"})
        assert square.status_banner.text() == "SALIDA REGISTRADA"
        assert gui.COLOR_ACCENT in square.status_banner.styleSheet()

        # 5. On time
        square.update_scan({"is_registered": True, "status": "on_time"})
        assert square.status_banner.text() == "ENTRADA PUNTUAL"
        assert gui.COLOR_SUCCESS in square.status_banner.styleSheet()

        # 6. Late
        square.update_scan({"is_registered": True, "status": "late"})
        assert square.status_banner.text() == "ENTRADA TARDE"
        assert gui.COLOR_WARNING in square.status_banner.styleSheet()
    finally:
        square.deleteLater()
        QApplication.processEvents()


def test_badge_management_view_displays_graduates(qapp, settings):
    import admin
    import database
    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, badge_uid="EE112233", role="student", full_name="Alumno Once", grade=11, section="A")
    admin.add_user(conn, settings, badge_uid="EE445566", role="student", full_name="Graduado Test", grade=11, section="B")

    # Graduate one student
    with conn:
        conn.execute("UPDATE users SET role = 'graduate', is_active = 0 WHERE badge_uid = 'EE445566'")
        conn.execute("UPDATE student_details SET graduation_date = '2026-06-30' WHERE user_id = (SELECT id FROM users WHERE badge_uid = 'EE445566')")
    conn.close()

    worker = HardwareWorker(settings)
    view = gui.BadgeManagementView(worker)
    try:
        view.refresh_users()
        found_grad = False
        for r in range(view.table.rowCount()):
            if view.table.item(r, 0).text() == "EE445566":
                found_grad = True
                assert view.table.item(r, 3).text() == "Graduado"
                assert "Graduado" in view.table.item(r, 4).text()
                break
        assert found_grad is True, "Graduated student must appear in BadgeManagementView table"
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_live_access_table_status_text(qapp, settings):
    worker = HardwareWorker(settings)
    win = LiveAccessWindow(worker)
    try:
        win.on_scan_event({"event_type": "graduate_denied", "full_name": "Graduado Uno", "is_registered": True})
        assert win.feed_table.item(0, 4).text() == "Denegado (Graduado)"

        win.on_scan_event({"event_type": "check_out", "full_name": "Estudiante Dos", "is_registered": True})
        assert win.feed_table.item(0, 4).text() == "Salida"

        win.on_scan_event({"event_type": "check_in", "status": "on_time", "full_name": "Estudiante Tres", "is_registered": True})
        assert win.feed_table.item(0, 4).text() == "Puntual"
    finally:
        win.close()
        win.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_teacher_registration_and_display_has_no_section(qapp, settings):
    worker = HardwareWorker(settings)
    dlg = RegisterBadgeDialog(worker)
    dlg.show()
    try:
        # Initially Student (idx 0)
        assert dlg.lbl_grade.text() == "Grado:"
        assert dlg.lbl_sec.isVisible() is True
        assert dlg.combo_sec.isVisible() is True
        assert dlg.lbl_family_id.isVisible() is True
        assert dlg.inp_family_id.isVisible() is True

        # Switch to Teacher (idx 1)
        dlg.combo_role.setCurrentIndex(1)
        assert dlg.lbl_grade.text() == "Grado que Enseña:"
        assert dlg.lbl_grade.isVisible() is True
        assert dlg.combo_grade.isVisible() is True
        assert dlg.lbl_sec.isVisible() is False
        assert dlg.combo_sec.isVisible() is False
        assert dlg.lbl_family_id.isVisible() is False
        assert dlg.inp_family_id.isVisible() is False
        assert dlg.lbl_family_hint.isVisible() is False
        assert dlg.g1_box.isVisible() is False
        assert dlg.g2_box.isVisible() is False

        # Add teacher to database and verify BadgeManagementView displays '--' for section
        import admin
        import database
        conn = database.connect(settings.database_path)
        admin.add_user(
            conn,
            settings,
            badge_uid="AA889900",
            role="teacher",
            full_name="Profesor Ciencias",
            taught_grade=6,
        )
        conn.close()

        bm_view = gui.BadgeManagementView(worker)
        try:
            bm_view.refresh_users()
            found_teacher = False
            for r in range(bm_view.table.rowCount()):
                if bm_view.table.item(r, 0).text() == "AA889900":
                    found_teacher = True
                    assert bm_view.table.item(r, 3).text() == "Profesor"
                    assert "6° (Enseña)" in bm_view.table.item(r, 4).text()
                    assert bm_view.table.item(r, 5).text() == "--"
                    break
            assert found_teacher is True, "Teacher AA889900 should be in badge management table"
        finally:
            bm_view.deleteLater()
    finally:
        dlg.close()
        dlg.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_all_sections_choice_searches_every_section_whatever_its_label(qapp, settings):
    import access_control
    import admin
    import database

    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, badge_uid="AA000001", role="student", full_name="Ana Seccion A", grade=3, section="A")
    admin.add_user(conn, settings, badge_uid="BB000002", role="student", full_name="Beto Seccion B", grade=3, section="B")
    scan_time = datetime(2026, 10, 5, 6, 30, 0)
    access_control.process_scan_line(conn, settings, "SCAN AA000001", now=scan_time)
    access_control.process_scan_line(conn, settings, "SCAN BB000002", now=scan_time)
    conn.close()

    worker = HardwareWorker(settings)
    view = gui.UnifiedSearchReportsView(worker)
    try:
        view.date_start.setDate(QDate(2026, 10, 5))
        view.combo_sec.setCurrentIndex(0)
        view.combo_sec.setItemText(0, "Every Section")

        view.execute_search()

        names = {view.table.item(r, 1).text() for r in range(view.table.rowCount())}
        assert {"Ana Seccion A", "Beto Seccion B"} <= names
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_scan_tile_shows_24_hour_time(qapp, settings):
    import admin
    import database

    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, badge_uid="CC000003", role="student", full_name="Carla Tarde", grade=5, section="A")
    conn.close()

    worker = HardwareWorker(settings)
    square = gui.StudentSquareWidget()
    payloads: list[dict] = []
    worker.scan_event.connect(payloads.append)
    try:
        worker.process_uid("CC000003", now=datetime(2026, 10, 5, 14, 5, 9))

        square.update_scan(payloads[0])

        assert square.lbl_time.text() == "Registrado: 14:05:09 (05/10/2026)"
    finally:
        square.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_english_school_sees_english_banners_feed_and_12_hour_times(qapp, settings, english_school):
    worker = HardwareWorker(settings)
    win = LiveAccessWindow(worker)
    try:
        win.on_scan_event({
            "is_registered": True, "event_type": "check_in", "status": "late", "role": "student",
            "full_name": "Ana Morales", "time_str": "14:05:09", "date_str": "2026-10-05",
        })
        assert win.student_square.status_banner.text() == "LATE CHECK-IN"
        assert win.student_square.lbl_time.text() == "Recorded: 02:05:09 PM (10/05/2026)"
        assert [win.feed_table.item(0, c).text() for c in (0, 2, 4)] == ["02:05:09 PM", "Student", "Late"]

        win.on_scan_event({"is_registered": True, "event_type": "repeat_scan", "full_name": "Ana Morales"})
        assert win.feed_table.item(0, 4).text() == "Repeat Scan"

        win.on_scan_event({"is_registered": False})
        assert win.student_square.status_banner.text() == "UNREGISTERED BADGE"
        assert win.feed_table.item(0, 4).text() == "Denied (Unregistered)"
    finally:
        win.close()
        win.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_english_daily_search_shows_english_dates_times_and_statuses(qapp, settings, english_school):
    import access_control
    import admin

    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, badge_uid="AA000001", role="student", full_name="Ana Morales", grade=3, section="A")
    admin.add_user(conn, settings, badge_uid="BB000002", role="student", full_name="Beto Ruiz", grade=3, section="A")
    with conn:
        conn.execute("UPDATE users SET created_at = '2026-09-01'")
    access_control.process_scan_line(conn, settings, "SCAN AA000001", now=datetime(2026, 10, 5, 6, 30, 0))
    conn.close()

    worker = HardwareWorker(settings)
    view = gui.UnifiedSearchReportsView(worker)
    try:
        view.date_start.setDate(QDate(2026, 10, 5))
        view.execute_search()

        rows = {
            view.table.item(r, 1).text(): [view.table.item(r, c).text() for c in (0, 3, 5)]
            for r in range(view.table.rowCount())
        }
        assert rows == {
            "Ana Morales": ["10/05/2026", "06:30:00 AM", "On Time"],
            "Beto Ruiz": ["10/05/2026", "--", "Absent"],
        }
        assert view.lbl_stats.text() == "Total: 2 Students (1 present, 1 absent)"
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_searches_count_only_the_schools_school_days(qapp, settings, school):
    import access_control
    import admin

    conn = database.connect(settings.database_path)
    store_school(conn, replace(school, holidays=(date(2026, 10, 6),)))
    admin.add_user(conn, settings, badge_uid="AA000001", role="student", full_name="Ana Morales", grade=3, section="A")
    admin.add_user(conn, settings, badge_uid="AA000002", role="student", full_name="Beto Cruz", grade=3, section="B")
    with conn:
        conn.execute("UPDATE users SET created_at = '2026-09-01'")
    access_control.process_scan_line(conn, settings, "SCAN AA000001", now=datetime(2026, 10, 5, 6, 30, 0))
    access_control.process_scan_line(conn, settings, "SCAN AA000002", now=datetime(2026, 10, 7, 6, 30, 0))
    conn.close()

    worker = HardwareWorker(settings)
    view = gui.UnifiedSearchReportsView(worker)
    try:
        view.date_start.setDate(QDate(2026, 10, 6))
        view.execute_search()
        assert view.table.rowCount() == 0
        assert view.lbl_stats.text() == "Total: 0 estudiantes (0 presentes, 0 ausentes)"

        # The range runs past the last day with scans, which the web portal's Year View leaves out too
        view.combo_query_type.setCurrentIndex(2)
        view.date_start.setDate(QDate(2026, 10, 5))
        view.date_end.setDate(QDate(2026, 10, 9))
        view.execute_search()
        headers = [view.table.horizontalHeaderItem(c).text() for c in range(view.table.columnCount())]
        assert headers[5:] == ["05/10", "07/10"]
        assert [view.table.item(0, c).text() for c in range(2, 7)] == ["1", "0", "1", "P", "A"]
        assert view.lbl_stats.text() == "Total: 2 estudiantes en matriz (2 días de clase)"
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_gate_screens_follow_the_school_language_without_reflashing(qapp, settings):
    worker = HardwareWorker(settings)
    try:
        worker._handle_serial_line(arduino.READY_LINE)
        worker.trigger_unlock()
        assert [gate_screen(c) for c in worker._pending_commands] == [
            ("IDLE", "QUICKPASS", "Acerque Carnet"),
            ("UNLOCK", "Acceso Remoto", "Puerta Abierta"),
        ]

        conn = database.connect(settings.database_path)
        store_school(conn, make_school(school_language="en"))
        conn.close()
        worker._pending_commands.clear()

        worker._handle_serial_line(arduino.READY_LINE)
        worker.trigger_unlock()
        assert [gate_screen(c) for c in worker._pending_commands] == [
            ("IDLE", "QUICKPASS", "Tap your badge"),
            ("UNLOCK", "Remote Access", "Door Open"),
        ]
    finally:
        worker.deleteLater()
        QApplication.processEvents()


def test_scans_outside_access_control_show_a_screen_and_old_protocol_lines_are_ignored(qapp, settings, english_school):
    worker = HardwareWorker(settings)
    try:
        worker._handle_serial_line("SCAN aa:bb:cc:dd")
        worker.set_rfid_mode(RFIDMode.CAPTURE)
        worker._handle_serial_line("SCAN AABBCCDD")
        worker._handle_serial_line("SCAN:AABBCCDD")

        assert [gate_screen(c) for c in worker._pending_commands] == [
            ("MSG", "Quickpass Ready", "Please go ahead"),
            ("MSG", "Badge Read", "AABBCCDD"),
        ]
    finally:
        worker.deleteLater()
        QApplication.processEvents()


def test_pulled_school_settings_change_the_idle_screen_at_once(qapp, settings, monkeypatch):
    monkeypatch.setattr(HardwareWorker, "start", lambda self: None)
    win = MainWindow(settings)
    try:
        win.worker._pending_commands.clear()
        conn = database.connect(settings.database_path)
        english = store_school(conn, make_school(school_language="en"))
        conn.close()

        win.school_settings_changed.emit(english)
        QApplication.processEvents()

        assert win.worker._pending_commands == [arduino.idle_screen("en")]
    finally:
        win.close()
        win.deleteLater()
        QApplication.processEvents()


def test_visitor_sign_in_opens_the_gate_showing_their_name_and_id(qapp, settings, english_school, monkeypatch):
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *args, **kwargs: None)
    worker = HardwareWorker(settings)
    dlg = gui.RegisterVisitDialog(worker)
    try:
        worker._pending_commands.clear()
        dlg.inp_name.setText("Carlos Ramirez")
        dlg.inp_id.setText("X1234567")

        dlg.submit_visit()

        assert [gate_screen(c) for c in worker._pending_commands] == [
            ("GRANT", "Visitor: Carlos", "ID: X1234567"),
            ("IDLE", "QUICKPASS", "Tap your badge"),
        ]
    finally:
        dlg.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()




def test_registration_offers_the_schools_grades_and_sections(qapp, settings, kinder_school, monkeypatch):
    monkeypatch.setattr(gui.QMessageBox, "information", lambda *args, **kwargs: None)
    worker = HardwareWorker(settings)
    dlg = RegisterBadgeDialog(worker)
    try:
        assert _items(dlg.combo_grade) == ["Pre-K", "Kinder", "1st"]
        assert _items(dlg.combo_sec) == ["Única", "Azul"]

        dlg.inp_uid.setText("AB12CD34")
        dlg.inp_name.setText("Lucía Kinder")
        dlg.combo_grade.setCurrentText("Kinder")
        dlg.combo_sec.setCurrentText("Azul")
        dlg.save_user()

        conn = database.connect(settings.database_path)
        student = database.get_user_by_badge_uid(conn, "AB12CD34")
        conn.close()
        assert (student["grade"], student["section"]) == (2, "Azul")
    finally:
        dlg.close()
        dlg.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_editing_keeps_a_grade_the_school_no_longer_lists(qapp, settings, kinder_school):
    import admin
    conn = database.connect(settings.database_path)
    store_school(conn, make_school())
    admin.add_user(conn, settings, "AB12CD34", "student", "Lucía Once", grade=11, section="D")
    store_school(conn, kinder_school)
    conn.close()

    worker = HardwareWorker(settings)
    dlg = EditBadgeDialog("AB12CD34", "AD000001", worker)
    try:
        assert _items(dlg.combo_grade) == ["Pre-K", "Kinder", "1st", "11"]
        assert dlg.combo_grade.currentText() == "11"
        assert _items(dlg.combo_sec) == ["Única", "Azul", "D"]
        assert dlg.combo_sec.currentText() == "D"
    finally:
        dlg.close()
        dlg.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()


def test_grade_names_show_everywhere_and_follow_a_rename(qapp, settings, kinder_school, monkeypatch):
    import admin
    monkeypatch.setattr(HardwareWorker, "start", lambda self: None)
    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, "AA000001", "student", "Ana Kinder", grade=2, section="Única")
    admin.add_user(conn, settings, "BB000001", "teacher", "Beto Profe", taught_grade=3)
    conn.close()

    window = MainWindow(settings)
    try:
        def grade_cells():
            table = window.view_badges.table
            return {table.item(r, 0).text(): table.item(r, 4).text() for r in range(table.rowCount())}

        window.view_badges.refresh_users()
        assert grade_cells() == {"AA000001": "Kinder", "BB000001": "1st (Enseña)"}
        assert _items(window.view_search_reports.combo_grade) == ["Todos los Grados", "Pre-K", "Kinder", "1st"]
        assert _items(window.view_search_reports.combo_sec) == ["Todas", "Única", "Azul"]

        renamed = make_school(grades=("Nursery", "Reception", "Year 1"), sections=("Única", "Azul", "Roja"))
        window.school_settings_changed.emit(renamed)

        assert grade_cells() == {"AA000001": "Reception", "BB000001": "Year 1 (Enseña)"}
        assert _items(window.view_search_reports.combo_grade) == ["Todos los Grados", "Nursery", "Reception", "Year 1"]
        assert _items(window.view_search_reports.combo_sec) == ["Todas", "Única", "Azul", "Roja"]
    finally:
        window.close()
        window.deleteLater()
        QApplication.processEvents()


def test_a_badge_read_again_counts_once_until_5_seconds_have_passed_or_the_rfid_mode_changes(qapp, settings):
    import admin
    conn = database.connect(settings.database_path)
    admin.add_user(conn, settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    conn.close()
    readings = iter([100.0, 103.0, 104.9, 104.9, 105.0, 106.0, 110.0])
    worker = HardwareWorker(settings, clock=lambda: next(readings))
    try:
        scans, captured = [], []
        worker.scan_event.connect(lambda payload: scans.append(payload["uid"]))
        worker.badge_captured.connect(captured.append)

        worker.set_rfid_mode(RFIDMode.ACCESS_CONTROL)
        for line in ("SCAN AA000001", "SCAN AA000001", "SCAN AA000001", "SCAN BB000002", "SCAN AA000001"):
            worker._handle_serial_line(line)
        worker.set_rfid_mode(RFIDMode.CAPTURE)
        worker._handle_serial_line(arduino.READY_LINE)
        worker._handle_serial_line("SCAN AA000001")
        worker._handle_serial_line("SCAN AA000001")

        assert scans == ["AA000001", "BB000002", "AA000001"]
        assert captured == ["AA000001"]
    finally:
        worker.deleteLater()
        QApplication.processEvents()


def test_a_bad_env_file_shows_the_startup_error_instead_of_a_traceback(qapp, monkeypatch, messages):
    from config import ConfigError

    def bad_env():
        raise ConfigError("Invalid value for DEMO_MODE in .env: 'maybe' (expected true or false).")

    monkeypatch.setattr(gui, "load_settings", bad_env)

    with pytest.raises(SystemExit) as stopped:
        gui.main()

    assert stopped.value.code == 1
    assert messages == [("critical", "Invalid value for DEMO_MODE in .env: 'maybe' (expected true or false).")]


@pytest.mark.parametrize(
    ("platform", "icon"), [("darwin", "logo.icns"), ("win32", "logo_rounded.png"), ("linux", "logo_rounded.png")]
)
def test_only_macos_gets_the_macos_app_icon(platform, icon):
    assert gui.app_icon_path(platform).name == icon


def test_open_reports_folder_asks_the_desktop_to_open_it_whatever_the_os(qapp, settings, monkeypatch):
    opened_folders = []
    monkeypatch.setattr(gui.QDesktopServices, "openUrl", lambda url: opened_folders.append(url.toLocalFile()) or True)
    worker = HardwareWorker(settings)
    view = gui.UnifiedSearchReportsView(worker)
    try:
        view.open_reports_folder()

        assert opened_folders == [str(settings.reports_dir)]
        assert settings.reports_dir.is_dir()
    finally:
        view.deleteLater()
        worker.deleteLater()
        QApplication.processEvents()
