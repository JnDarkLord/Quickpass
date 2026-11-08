"""Excel export catalogue (E1 through E8).

Built with openpyxl. Files are written to reports_dir. Headers, sheet names,
file names, dates, times and statuses follow the School Language (the
`report.*` catalog keys). Errors return an ExportResult rather than raising
exceptions.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl

import i18n
from school_settings import SchoolSettings
from search import (
    OtherRoleAttendanceDay,
    PersonSearchResult,
    PresentStudent,
    StudentRangeMatrixRow,
    UserRangeRow,
)


@dataclass
class ExportResult:
    success: bool
    path: Path | None = None
    error: str = ""


def sanitize_filename(filename: str) -> str:
    """Replace forbidden characters with dashes, matching legacy behavior."""
    for c in r'/\:*?"<>|':
        filename = filename.replace(c, "-")
    return filename


class _Texts:
    """The School Language pieces every report needs."""

    def __init__(self, school: SchoolSettings) -> None:
        self.school = school
        self.lang = school.school_language

    def __call__(self, key: str, **params: Any) -> str:
        return i18n.t(self.lang, f"report.{key}", **params)

    def date(self, value: date | str) -> str:
        return i18n.format_date(self.lang, value) if value else ""

    def time(self, value: str) -> str:
        return i18n.format_time(self.lang, value) if value else ""

    def status(self, code: str) -> str:
        return i18n.t(self.lang, f"status.{code}") if code else ""

    def role(self, role: str) -> str:
        return i18n.t(self.lang, f"role.{role}")

    def grade(self, rank: Any) -> str:
        """The School's name for a Grade rank."""
        return self.school.grade_label(int(rank)) if rank else ""

    def grade_section(self, rank: Any, section: Any) -> str:
        return " ".join(part for part in (self.grade(rank), section or "") if part)


def _write(
    reports_dir: Path,
    file_name: str,
    sheet_title: str,
    headers: list[Any],
    rows: Iterable[list[Any]],
    texts: _Texts,
) -> ExportResult:
    reports_dir = Path(reports_dir)
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return ExportResult(success=False, error=texts("error.folder", error=e))

    file_path = reports_dir / sanitize_filename(f"{file_name}.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_title
    ws.append(headers)
    for row in rows:
        ws.append(row)

    try:
        wb.save(file_path)
    except Exception as e:
        return ExportResult(success=False, error=texts("error.file", error=e))

    return ExportResult(success=True, path=file_path)


def export_e1(
    reports_dir: Path,
    school: SchoolSettings,
    person_result: PersonSearchResult,
    file_prefix: str | None = None,
) -> ExportResult:
    """Export one person's attendance history (E1)."""
    texts = _Texts(school)
    role = person_result.user["role"]
    headers = [
        texts("header.check_in_date"),
        texts("header.check_in_time"),
        texts("header.check_out_time"),
        texts("header.role"),
    ]
    if role == "student":
        headers.append(texts("header.grade_section"))
    elif role == "teacher":
        headers.append(texts("header.grade_taught"))
    headers.append(texts("header.status"))

    rows = []
    for day in person_result.history:
        row: list[Any] = [
            texts.date(day.date),
            texts.time(day.arrival_time),
            texts.time(day.departure_time),
            texts.role(role),
        ]
        if role == "student":
            row.append(texts.grade_section(day.grade, day.section))
        elif role == "teacher":
            row.append(texts.grade(day.grade or person_result.user.get("taught_grade")))
        row.append(texts.status(day.status))
        rows.append(row)

    name = file_prefix or person_result.user["full_name"]
    return _write(reports_dir, texts("file.e1", name=name), texts("sheet.list"), headers, rows, texts)


def _day_list(
    reports_dir: Path,
    texts: _Texts,
    file_name: str,
    students: list[PresentStudent],
) -> ExportResult:
    headers = [
        texts("header.check_in_time"),
        texts("header.check_out_time"),
        texts("header.names"),
        texts("header.grade_section"),
        texts("header.status"),
    ]
    rows = (
        [
            texts.time(s.arrival_time),
            texts.time(s.departure_time),
            s.name,
            texts.grade_section(s.grade, s.section),
            texts.status(s.status),
        ]
        for s in students
    )
    return _write(reports_dir, file_name, texts("sheet.list"), headers, rows, texts)


def export_e2(
    reports_dir: Path,
    school: SchoolSettings,
    day: date,
    students: list[PresentStudent],
) -> ExportResult:
    """Export the whole School's Check-ins on one date (E2)."""
    texts = _Texts(school)
    if not students:
        return ExportResult(success=False, error=texts("error.no_data"))
    return _day_list(reports_dir, texts, texts("file.e2", date=texts.date(day)), students)


def export_e3(
    reports_dir: Path,
    school: SchoolSettings,
    day: date,
    grade: int,
    section: str | None,
    students: list[PresentStudent],
) -> ExportResult:
    """Export one Grade's (or Grade and Section's) Check-ins on one date (E3)."""
    texts = _Texts(school)
    if not students:
        return ExportResult(success=False, error=texts("error.no_data"))
    file_name = texts("file.e3", date=texts.date(day), grade=texts.grade_section(grade, section))
    return _day_list(reports_dir, texts, file_name, students)


def _export_matrix_report(
    reports_dir: Path,
    texts: _Texts,
    file_name: str,
    school_days: Sequence[date],
    matrix_rows: list[StudentRangeMatrixRow],
) -> ExportResult:
    """Helper to build and save matrix reports E4, E5, and E6, with one column per School Day."""
    headers = [
        texts("header.full_name"),
        texts("header.grade_section"),
        texts("header.times_present"),
        texts("header.times_late"),
        texts("header.times_absent"),
    ] + [texts.date(d) for d in school_days]
    rows = (
        [r.name, texts.grade_section(r.grade, r.section), r.present_count, r.late_count, r.absent_count]
        + [texts(f"mark.{mark}") if mark else "" for mark in r.day_marks]
        for r in matrix_rows
    )
    return _write(reports_dir, file_name, texts("sheet.matrix"), headers, rows, texts)


def export_e4(
    reports_dir: Path,
    school: SchoolSettings,
    start: date,
    end: date,
    school_days: Sequence[date],
    matrix_rows: list[StudentRangeMatrixRow],
) -> ExportResult:
    """Export every Grade's attendance matrix across a date range (E4)."""
    texts = _Texts(school)
    file_name = texts("file.e4", start=texts.date(start), end=texts.date(end))
    return _export_matrix_report(reports_dir, texts, file_name, school_days, matrix_rows)


def export_e5(
    reports_dir: Path,
    school: SchoolSettings,
    start: date,
    end: date,
    grade: int,
    school_days: Sequence[date],
    matrix_rows: list[StudentRangeMatrixRow],
) -> ExportResult:
    """Export one Grade's attendance matrix across a date range (E5)."""
    texts = _Texts(school)
    if not matrix_rows:
        return ExportResult(success=False, error=texts("error.no_students", grade=texts.grade(grade)))
    file_name = texts("file.e5", grade=texts.grade(grade), start=texts.date(start), end=texts.date(end))
    return _export_matrix_report(reports_dir, texts, file_name, school_days, matrix_rows)


def export_e6(
    reports_dir: Path,
    school: SchoolSettings,
    start: date,
    end: date,
    grade: int,
    section: str,
    school_days: Sequence[date],
    matrix_rows: list[StudentRangeMatrixRow],
) -> ExportResult:
    """Export one Grade and Section's attendance matrix across a date range (E6)."""
    texts = _Texts(school)
    grade_section = texts.grade_section(grade, section)
    if not matrix_rows:
        return ExportResult(success=False, error=texts("error.no_students", grade=grade_section))
    file_name = texts("file.e6", grade=grade_section, start=texts.date(start), end=texts.date(end))
    return _export_matrix_report(reports_dir, texts, file_name, school_days, matrix_rows)


def export_e7(
    reports_dir: Path,
    school: SchoolSettings,
    role: str,
    day: date,
    entries: list[OtherRoleAttendanceDay],
) -> ExportResult:
    """Export one non-student role's Check-ins on one date (E7)."""
    texts = _Texts(school)
    if not entries:
        return ExportResult(success=False, error=texts("error.no_data"))

    headers = [
        texts("header.names"),
        texts("header.date"),
        texts("header.time"),
        texts("header.check_out_time"),
        texts("header.status"),
    ]
    rows = (
        [r.name, texts.date(day), texts.time(r.time), texts.time(r.departure_time), texts.status(r.status)]
        for r in entries
    )
    file_name = texts("file.e7", role=texts(f"role_plural.{role}"), date=texts.date(day))
    return _write(reports_dir, file_name, texts("sheet.list"), headers, rows, texts)


def export_e8(
    reports_dir: Path,
    school: SchoolSettings,
    role: str,
    start: date,
    end: date,
    school_days: Sequence[date],
    rows: list[UserRangeRow],
) -> ExportResult:
    """Export one non-student role's Check-in times across a date range (E8)."""
    texts = _Texts(school)
    if not rows:
        return ExportResult(success=False, error=texts("error.no_data"))

    headers = [texts("header.name")] + [texts.date(d) for d in school_days]
    table = ([r.name, *(texts.time(t) or None for t in r.day_times)] for r in rows)
    file_name = texts("file.e8", role=texts(f"role_plural.{role}"), start=texts.date(start), end=texts.date(end))
    return _write(reports_dir, file_name, texts("sheet.matrix"), headers, table, texts)
