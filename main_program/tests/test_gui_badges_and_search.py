"""A School's everyday work in the desktop window: statistics, wiping every Badge or all
attendance history behind a backup, adding another Admin, the name and phone checks, walk-in
Visitors, the Teacher, Admin and Visitor searches, searching by scanning a Badge, and Badge UIDs
typed and scans simulated only in Demo Mode."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog

import access_control
import admin
import database
import gui
from conftest import ADMIN_SECRET_KEY, make_school, store_school
from gui import HardwareWorker, RFIDMode


@pytest.fixture(autouse=True)
def _windows_show_the_stored_school():
    gui.set_school(make_school())


@pytest.fixture
def worker(qapp, settings, request):
    """The station's hardware worker, in Demo Mode when a test passes True through `indirect`."""
    hardware = HardwareWorker(replace(settings, demo_mode=getattr(request, "param", False)))
    yield hardware
    hardware.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def opened(worker):
    """Keeps each window a test opens, to close and delete it before the worker goes."""
    windows = []

    def keep(window):
        windows.append(window)
        return window

    yield keep
    for window in reversed(windows):
        window.close()
        window.deleteLater()
    QApplication.processEvents()


def _add(settings, badge_uid, role, full_name, **details):
    conn = database.connect(settings.database_path)
    try:
        result = admin.add_user(conn, settings, badge_uid, role, full_name, **details)
    finally:
        conn.close()
    assert result.success, result.error
    return result.user


def _scan(settings, badge_uid, at):
    conn = database.connect(settings.database_path)
    try:
        access_control.process_scan_line(conn, settings, f"SCAN {badge_uid}", now=at)
    finally:
        conn.close()


def _query(settings, sql):
    conn = database.connect(settings.database_path)
    try:
        return [tuple(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _rows(table):
    return [
        tuple(table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount()))
        for r in range(table.rowCount())
    ]


def _headers(table):
    return [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]


# --- Statistics -------------------------------------------------------------------


def test_statistics_count_people_by_the_schools_grade_names_and_by_role(settings, worker, opened, monkeypatch):
    kinder = make_school(grades=("Pre-K", "Kinder", "1st"), sections=("Azul",))
    conn = database.connect(settings.database_path)
    store_school(conn, kinder)
    conn.close()
    gui.set_school(kinder)
    _add(settings, "AA000001", "student", "Ana Kinder", grade=2, section="Azul")
    _add(settings, "AA000002", "student", "Luis Kinder", grade=2, section="Azul")
    _add(settings, "BB000001", "teacher", "Beto Profe", taught_grade=3)
    _add(settings, "AD000001", "admin", "Clara Admin")
    _scan(settings, "AA000001", datetime(2026, 10, 5, 6, 40))
    _scan(settings, "AA000001", datetime(2026, 10, 6, 6, 40))
    _scan(settings, "BB000001", datetime(2026, 10, 6, 6, 45))
    shown = []
    monkeypatch.setattr(gui.StatisticsDialog, "exec", lambda dialog: shown.append(_rows(dialog.table)) or 0)

    opened(gui.BadgeManagementView(worker)).btn_stats.click()

    assert shown == [[
        ("Personas registradas", "4"),
        ("Entradas registradas", "3"),
        ("Estudiantes por grado", ""),
        ("Kinder", "2"),
        ("Profesores por grado que enseñan", ""),
        ("1st", "1"),
        ("Personas por rol", ""),
        ("Estudiantes", "2"),
        ("Profesores", "1"),
        ("Administradores", "1"),
        ("Visitantes", "0"),
        ("Graduados", "0"),
        ("Entradas de los últimos días", ""),
        ("05/10/2026", "1"),
        ("06/10/2026", "2"),
    ]]


# --- Wipes ------------------------------------------------------------------------


def test_wiping_every_badge_needs_the_wipe_password_and_the_confirmation_word_and_keeps_a_backup(
    settings, worker, opened, messages
):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    _scan(settings, "AA000001", datetime(2026, 10, 5, 6, 40))
    dialog = opened(gui.WipeDialog(worker, "users"))

    dialog.inp_password.setText("no-es-la-clave")
    dialog.inp_confirm.setText("ELIMINAR")
    dialog.btn_wipe.click()
    dialog.inp_password.setText("clave-de-prueba")
    dialog.inp_confirm.setText("BORRAR")
    dialog.btn_wipe.click()
    dialog.inp_confirm.setText("ELIMINAR")
    dialog.btn_wipe.click()

    (backup,) = (settings.database_path.parent / "backups").iterdir()
    assert messages == [
        ("critical", "Contraseña incorrecta. Operación cancelada."),
        ("critical", "Confirmación no válida. Operación cancelada."),
        ("information", f"Se borraron todas las tarjetas. La copia de seguridad quedó en {backup.name}."),
    ]
    assert dialog.result() == QDialog.Accepted
    assert _query(settings, "SELECT COUNT(*) FROM users") == [(0,)]
    assert _query(settings, "SELECT COUNT(*) FROM attendance_records") == [(1,)]


def test_wiping_the_attendance_history_keeps_every_badge_and_a_backup(settings, worker, opened, messages, monkeypatch):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    _scan(settings, "AA000001", datetime(2026, 10, 5, 6, 40))

    def exec_typing_the_password(dialog):
        dialog.inp_password.setText("clave-de-prueba")
        dialog.inp_confirm.setText("eliminar")
        dialog.btn_wipe.click()
        return dialog.result()

    monkeypatch.setattr(gui.WipeDialog, "exec", exec_typing_the_password)
    view = opened(gui.BadgeManagementView(worker))

    view.btn_wipe_history.click()

    (backup,) = (settings.database_path.parent / "backups").iterdir()
    assert messages == [
        ("information", f"Se borró el historial de entradas de esta estación. La copia de seguridad quedó en {backup.name}.")
    ]
    assert _query(settings, "SELECT COUNT(*) FROM attendance_records") == [(0,)]
    assert [view.table.item(r, 0).text() for r in range(view.table.rowCount())] == ["AA000001"]


# --- Adding another Admin -----------------------------------------------------------


def _fill_admin(dialog, badge_uid, name):
    dialog.on_rfid_captured(badge_uid)
    dialog.inp_name.setText(name)
    dialog.combo_role.setCurrentIndex(2)


def test_the_first_admin_needs_no_approval_but_another_admin_needs_an_admin_to_scan_their_badge(
    settings, worker, opened, approval, messages
):
    first = opened(gui.RegisterBadgeDialog(worker))
    _fill_admin(first, "AD000001", "Ana Admin")
    first.save_user()
    asked_for_the_first = approval.asked

    second = opened(gui.RegisterBadgeDialog(worker))
    _fill_admin(second, "AD000002", "Beto Admin")
    approval.badge = "AD000001"
    second.save_user()

    assert (asked_for_the_first, approval.asked, approval.key_offered) == (0, 1, False)
    assert second.inp_uid.text() == "AD000002"
    assert [kind for kind, _ in messages] == ["information", "information"]
    assert _query(settings, "SELECT badge_uid, role FROM users ORDER BY badge_uid") == [
        ("AD000001", "admin"),
        ("AD000002", "admin"),
    ]


def test_neither_the_admin_secret_key_nor_another_roles_badge_approves_adding_an_admin(
    settings, worker, opened, approval, messages
):
    _add(settings, "AD000001", "admin", "Ana Admin")
    _add(settings, "BB000001", "teacher", "Beto Profe", taught_grade=3)
    dialog = opened(gui.RegisterBadgeDialog(worker))
    _fill_admin(dialog, "AD000002", "Carla Admin")

    dialog.save_user()
    approval.badge = "BB000001"
    dialog.save_user()

    assert approval.asked == 2
    assert messages == []
    assert _query(settings, "SELECT badge_uid FROM users WHERE role = 'admin'") == [("AD000001",)]
    assert (dialog.inp_uid.text(), worker.rfid_mode) == ("AD000002", RFIDMode.CAPTURE)


# --- Name and phone checks ----------------------------------------------------------


def test_registration_refuses_a_name_without_letters_and_a_phone_without_its_country_code(
    settings, worker, opened, messages
):
    dialog = opened(gui.RegisterBadgeDialog(worker))
    dialog.on_rfid_captured("AA000001")

    dialog.inp_name.setText("12345")
    dialog.save_user()
    dialog.inp_name.setText("Luis Torres")
    dialog.inp_g1_name.setText("Ana Torres")
    dialog.inp_g1_phone.setText("88888888")
    dialog.save_user()
    dialog.inp_g1_phone.setText("+505 8888-8888")
    dialog.save_user()

    assert messages[:2] == [
        ("critical", "El nombre debe tener al menos una letra."),
        (
            "critical",
            "Escriba el teléfono de cada acudiente con + y el código del país, un espacio y el número (ej: +505 88888888).",
        ),
    ]
    assert _query(settings, "SELECT name, phone FROM guardians") == [("Ana Torres", "+505 88888888")]


def test_a_guardian_phone_typed_another_way_still_finds_the_siblings_family(settings, worker, opened):
    _add(
        settings, "AA000001", "student", "Ana Torres", grade=3, section="A",
        guardians=[admin.GuardianData(name="Rosa Torres", phone="+505 88881234")], family_id="FAM-0007",
    )
    dialog = opened(gui.RegisterBadgeDialog(worker))

    dialog.inp_g1_phone.setText("+505 8888-1234")

    assert dialog.inp_family_id.text() == "FAM-0007"


# --- Walk-in Visitors ---------------------------------------------------------------


def test_a_walk_in_visitor_without_a_badge_is_recorded_by_name_alone(settings, worker, opened, messages):
    dialog = opened(gui.RegisterVisitDialog(worker))
    dialog.inp_name.setText("Carlos Ramírez")
    dialog.inp_id.setText("X1234567")

    dialog.submit_visit()

    assert _query(settings, "SELECT badge_uid, user_id, name, role, status, section FROM attendance_records") == [
        ("", None, "Carlos Ramírez", "visitor", "visit", "")
    ]
    assert _query(settings, "SELECT COUNT(*) FROM users") == [(0,)]
    assert messages == [(
        "information",
        "Visita registrada exitosamente:\n\n• Visitante: Carlos Ramírez\n• Documento / ID: X1234567\n"
        "• Sin tarjeta\n\nLa puerta ha sido abierta.",
    )]


def test_a_walk_in_visitor_can_carry_a_temporary_badge_but_not_one_that_belongs_to_someone_else(
    settings, worker, opened, messages
):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    refused = opened(gui.RegisterVisitDialog(worker))
    refused.on_rfid_captured("AA000001")
    refused.inp_name.setText("Carlos Ramírez")
    refused.inp_id.setText("X1234567")
    refused.submit_visit()
    lent = opened(gui.RegisterVisitDialog(worker))
    lent.on_rfid_captured("7E571701")
    lent.inp_name.setText("Carlos Ramírez")
    lent.inp_id.setText("X1234567")
    lent.submit_visit()

    assert messages[0] == ("critical", "La tarjeta AA000001 es de Ana Torres (Estudiante), no de un visitante.")
    assert _query(settings, "SELECT badge_uid, name, role FROM attendance_records") == [
        ("7E571701", "Carlos Ramírez", "visitor")
    ]


# --- Teacher, Admin and Visitor searches ---------------------------------------------


def test_teachers_admins_and_visitors_are_searched_on_a_date_and_exported(settings, worker, opened, messages):
    _add(settings, "BB000001", "teacher", "Beto Profe", taught_grade=3)
    _add(settings, "BB000002", "teacher", "Carla Profe", taught_grade=5)
    _add(settings, "AD000001", "admin", "Clara Admin")
    _scan(settings, "BB000001", datetime(2026, 10, 5, 6, 40))
    _scan(settings, "BB000001", datetime(2026, 10, 5, 14, 0))
    _scan(settings, "BB000002", datetime(2026, 10, 5, 7, 5))
    _scan(settings, "AD000001", datetime(2026, 10, 5, 7, 10))
    conn = database.connect(settings.database_path)
    access_control.sign_in_visitor(conn, "Pedro Mena", "X1234567", now=datetime(2026, 10, 5, 9, 0))
    conn.close()
    view = opened(gui.UnifiedSearchReportsView(worker))

    view.combo_query_type.setCurrentIndex(4)
    view.date_start.setDate(QDate(2026, 10, 5))
    view.combo_role.setCurrentIndex(view.combo_role.findData("teacher"))
    view.execute_search()
    teachers = _rows(view.table)
    view.combo_grade.setCurrentIndex(view.combo_grade.findData(3))
    view.execute_search()
    grade_3_teachers = _rows(view.table)
    view.combo_role.setCurrentIndex(view.combo_role.findData("visitor"))
    view.execute_search()
    visitors = _rows(view.table)
    view.combo_role.setCurrentIndex(view.combo_role.findData("admin"))
    view.execute_search()
    view.export_to_excel()

    assert teachers == [
        ("06:40:00", "14:00:00", "Beto Profe", "3°", "Puntual"),
        ("07:05:00", "--", "Carla Profe", "5°", "Tarde"),
    ]
    assert grade_3_teachers == [("06:40:00", "14:00:00", "Beto Profe", "3°", "Puntual")]
    assert visitors == [("09:00:00", "--", "Pedro Mena", "", "Visita")]
    assert _rows(view.table) == [("07:10:00", "--", "Clara Admin", "", "Tarde")]
    assert (view.combo_grade.isHidden(), view.combo_sec.isHidden()) == (True, True)
    assert view.lbl_stats.text() == "Total: 1 admins"
    (report,) = settings.reports_dir.glob("*.xlsx")
    assert report.name.startswith("Busqueda de admins")
    assert messages == [("box", f"El libro oficial de Excel ha sido generado con éxito:\n\n{report.name}")]


def test_teachers_admins_and_visitors_are_searched_over_school_days_and_exported(settings, worker, opened, messages):
    _add(settings, "BB000001", "teacher", "Beto Profe", taught_grade=3)
    _add(settings, "BB000002", "teacher", "Carla Profe", taught_grade=5)
    _scan(settings, "BB000001", datetime(2026, 10, 5, 6, 40))
    _scan(settings, "BB000002", datetime(2026, 10, 7, 6, 30))
    _scan(settings, "BB000002", datetime(2026, 10, 10, 8, 0))
    view = opened(gui.UnifiedSearchReportsView(worker))

    view.combo_query_type.setCurrentIndex(5)
    view.combo_role.setCurrentIndex(view.combo_role.findData("teacher"))
    view.date_start.setDate(QDate(2026, 10, 5))
    view.date_end.setDate(QDate(2026, 10, 10))
    view.execute_search()
    view.export_to_excel()

    assert _headers(view.table) == ["Nombres", "05/10", "06/10", "07/10", "08/10", "09/10"]
    assert _rows(view.table) == [
        ("Beto Profe", "06:40:00", "", "", "", ""),
        ("Carla Profe", "", "", "06:30:00", "", ""),
    ]
    assert view.lbl_stats.text() == "Total: 2 profesores en 5 días de clase"
    (report,) = settings.reports_dir.glob("*.xlsx")
    assert report.name.startswith("Busqueda de profesores desde")


# --- Searching by scanning a Badge -----------------------------------------------------


def test_scanning_a_badge_searches_that_persons_history(settings, worker, opened, monkeypatch):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    _add(settings, "AA000002", "student", "Luis Torres", grade=3, section="A")
    _scan(settings, "AA000002", datetime(2026, 10, 5, 6, 40))

    def exec_scanning(dialog):
        dialog.worker.badge_captured.emit("AA000002")
        return dialog.result()

    monkeypatch.setattr(gui.BadgeScanDialog, "exec", exec_scanning)
    view = opened(gui.UnifiedSearchReportsView(worker))
    hidden_for_the_daily_search = view.btn_scan_badge.isHidden()

    view.combo_query_type.setCurrentIndex(1)
    view.btn_scan_badge.click()

    assert (hidden_for_the_daily_search, view.btn_scan_badge.isHidden()) == (True, False)
    assert view.inp_search_text.text() == "AA000002"
    assert _rows(view.table) == [("05/10/2026", "Luis Torres", "Estudiante", "06:40:00", "--", "Puntual")]
    assert worker.rfid_mode == RFIDMode.STANDBY


# --- Demo Mode ------------------------------------------------------------------------


@pytest.mark.parametrize("worker", [False, True], indirect=True, ids=["outside_demo_mode", "in_demo_mode"])
def test_badge_uids_are_typed_and_scans_simulated_only_in_demo_mode(settings, worker, opened):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    typing_allowed = worker.settings.demo_mode

    registration = opened(gui.RegisterBadgeDialog(worker))
    editing = opened(gui.EditBadgeDialog("AA000001", ADMIN_SECRET_KEY, worker))
    visit = opened(gui.RegisterVisitDialog(worker))
    approval = opened(gui.AdminAuthDialog(worker))
    badge_scan = opened(gui.BadgeScanDialog(worker))
    live = opened(gui.LiveAccessWindow(worker))

    assert [d.inp_uid.isReadOnly() for d in (registration, editing, visit)] == [not typing_allowed] * 3
    assert [d.typed_badge.isHidden() for d in (approval, badge_scan)] == [not typing_allowed] * 2
    assert live.sim_frame.isHidden() is not typing_allowed


@pytest.mark.parametrize("worker", [True], indirect=True, ids=["in_demo_mode"])
def test_in_demo_mode_a_typed_uid_simulates_a_scan_at_the_live_window(settings, worker, opened):
    _add(settings, "AA000001", "student", "Ana Torres", grade=3, section="A")
    live = opened(gui.LiveAccessWindow(worker))
    scans = []
    worker.scan_event.connect(lambda payload: scans.append((payload["uid"], payload["event_type"])))

    live.typed_badge.inp_uid.setText("aa:00:00:01")
    live.typed_badge.btn_use.click()
    live.btn_sim_unregistered.click()

    assert scans == [("AA000001", "check_in"), ("99887766", "unregistered")]


@pytest.mark.parametrize("worker", [True], indirect=True, ids=["in_demo_mode"])
def test_in_demo_mode_typing_an_admin_badge_uid_approves_as_scanning_it_would(settings, worker, opened):
    _add(settings, "AD000001", "admin", "Ana Admin")
    dialog = opened(gui.AdminAuthDialog(worker, None, "Prueba", allow_secret_key=False))

    dialog.typed_badge.inp_uid.setText("ad000001")
    dialog.typed_badge.btn_use.click()

    assert (dialog.result(), dialog.auth_token) == (QDialog.Accepted, "AD000001")
