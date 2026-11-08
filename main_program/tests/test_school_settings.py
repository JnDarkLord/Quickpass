"""School Settings: the local cache, validation, and the Admin Secret Key hash."""

from dataclasses import replace
from datetime import date, datetime, time

import pytest
from conftest import make_school

import database
import school_settings
from admin import add_user, promote_grades
from school_settings import SchoolSettings, SchoolSettingsError


def test_settings_round_trip_through_the_local_cache(tmp_path, now):
    conn = database.connect(tmp_path / "fresh.db")
    school = SchoolSettings(
        school_language="en",
        grades=("Pre-K", "Kinder", "Grade 1"),
        sections=("Red", "Blue"),
        active_weekdays=(0, 1, 2, 3, 4, 5),
        holidays=(date(2026, 12, 25), date(2026, 11, 26)),
        late_threshold=time(7, 30, 15),
        cooldown_seconds=120,
        admin_secret_key_hash=school_settings.hash_secret_key("open-sesame", iterations=1000),
    )

    school_settings.save(conn, school, now=now)

    loaded = school_settings.load(conn)
    assert loaded == replace(school, holidays=(date(2026, 11, 26), date(2026, 12, 25)))
    conn.close()


def test_a_fresh_database_has_no_school_settings(tmp_path):
    conn = database.connect(tmp_path / "fresh.db")

    assert school_settings.load(conn) is None
    with pytest.raises(school_settings.SchoolSettingsMissing):
        school_settings.require(conn)
    conn.close()


def test_saving_again_replaces_the_single_settings_row(conn, school, now):
    school_settings.save(conn, replace(school, school_language="en", cooldown_seconds=60), now=now)

    loaded = school_settings.load(conn)
    assert loaded.school_language == "en"
    assert loaded.cooldown_seconds == 60
    assert conn.execute("SELECT COUNT(*) FROM school_settings").fetchone()[0] == 1


def test_grade_labels_follow_the_configured_order(school):
    custom = replace(school, grades=("Pre-K", "Kinder", "1st"))

    assert [custom.grade_label(rank) for rank in (1, 2, 3)] == ["Pre-K", "Kinder", "1st"]
    assert custom.final_grade == 3


@pytest.mark.parametrize(
    "changes, code",
    [
        ({"school_language": "fr"}, "settings.error.language"),
        ({"school_language": ""}, "settings.error.language"),
        ({"grades": ()}, "settings.error.grades_empty"),
        ({"grades": ("1°", "  ")}, "settings.error.grade_blank"),
        ({"grades": ("1°", "2°", "1°")}, "settings.error.grade_duplicate"),
        ({"sections": ()}, "settings.error.sections_empty"),
        ({"sections": ("A", "")}, "settings.error.section_blank"),
        ({"sections": ("A", "a")}, "settings.error.section_duplicate"),
        ({"sections": ("A", "All")}, "settings.error.section_reserved"),
        ({"sections": ("A", "Seccion Larga")}, "settings.error.section_too_long"),
        ({"active_weekdays": ()}, "settings.error.weekdays"),
        ({"active_weekdays": (0, 7)}, "settings.error.weekdays"),
        ({"cooldown_seconds": -1}, "settings.error.cooldown"),
        ({"admin_secret_key_hash": ""}, "settings.error.secret_key"),
    ],
)
def test_invalid_settings_are_refused_with_a_message_key(conn, school, now, changes, code):
    with pytest.raises(SchoolSettingsError) as error:
        school_settings.save(conn, replace(school, **changes), now=now)

    assert error.value.code == code
    assert school_settings.load(conn) == school


def test_dropping_a_grade_that_active_students_or_teachers_hold_is_refused(conn, settings, school, now):
    add_user(conn, settings, "AA0011", "est", "Ana Once", grade=11, section="A", now=now)
    add_user(conn, settings, "BB0010", "prof", "Beto Diez", taught_grade=10, now=now)

    with pytest.raises(SchoolSettingsError) as error:
        school_settings.save(conn, replace(school, grades=school.grades[:9]), now=now)

    assert error.value.code == "settings.error.grade_in_use"
    assert error.value.params == {"grade": "10°", "count": 1}
    assert school_settings.load(conn) == school


def test_a_grade_left_only_to_graduates_and_inactive_badges_can_be_dropped(conn, settings, school, now):
    add_user(conn, settings, "AA0011", "est", "Ana Once", grade=11, section="A", now=now)
    promote_grades(conn, now=now)
    add_user(conn, settings, "AA0010", "est", "Beto Diez", grade=10, section="B", now=now)
    with conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE badge_uid = 'AA0010'")

    school_settings.save(conn, replace(school, grades=school.grades[:9]), now=now)

    assert school_settings.load(conn).final_grade == 9


def test_dropping_a_section_that_active_students_hold_is_refused(conn, settings, school, now):
    add_user(conn, settings, "AA0001", "est", "Ana", grade=3, section="D", now=now)
    add_user(conn, settings, "AA0002", "est", "Beto", grade=4, section="D", now=now)

    with pytest.raises(SchoolSettingsError) as error:
        school_settings.save(conn, replace(school, sections=("A", "B", "C")), now=now)

    assert error.value.code == "settings.error.section_in_use"
    assert error.value.params == {"section": "D", "count": 2}
    assert school_settings.load(conn) == school


def test_renaming_grades_keeps_every_student_in_their_rank(conn, settings, school, now):
    add_user(conn, settings, "AA0003", "est", "Ana", grade=3, section="A", now=now)

    school_settings.save(conn, replace(school, grades=tuple(f"Grade {rank}" for rank in range(1, 12))), now=now)

    student = database.get_user_by_badge_uid(conn, "AA0003")
    assert student["grade"] == 3
    assert school_settings.load(conn).grade_label(student["grade"]) == "Grade 3"


def _sections_and_sync_flags(conn) -> dict[str, tuple[str, int]]:
    rows = conn.execute(
        "SELECT u.full_name, sd.section, u.is_synced FROM users u JOIN student_details sd ON sd.user_id = u.id"
    )
    return {row["full_name"]: (row["section"], row["is_synced"]) for row in rows}


def test_renaming_a_section_moves_its_students_to_the_new_name_for_cloud_sync_to_push(conn, settings, school, now):
    add_user(conn, settings, "AA0001", "est", "Ana", grade=3, section="A", now=now)
    add_user(conn, settings, "AA0002", "est", "Beto", grade=4, section="B", now=now)
    with conn:
        conn.execute("UPDATE users SET is_synced = 1")

    school_settings.save(conn, replace(school, sections=("Azul", "B", "C", "D")), now=now, renamed_sections={"A": "Azul"})

    assert school_settings.load(conn).sections == ("Azul", "B", "C", "D")
    assert _sections_and_sync_flags(conn) == {"Ana": ("Azul", 0), "Beto": ("B", 1)}


def test_two_sections_can_swap_names(conn, settings, school, now):
    add_user(conn, settings, "AA0001", "est", "Ana", grade=3, section="A", now=now)
    add_user(conn, settings, "AA0002", "est", "Beto", grade=4, section="B", now=now)

    school_settings.save(
        conn, replace(school, sections=("B", "A", "C", "D")), now=now, renamed_sections={"A": "B", "B": "A"}
    )

    assert _sections_and_sync_flags(conn) == {"Ana": ("B", 0), "Beto": ("A", 0)}


def test_admin_secret_key_is_stored_only_as_a_hash():
    stored = school_settings.hash_secret_key("clave-maestra", iterations=1000)

    assert "clave-maestra" not in stored
    assert school_settings.verify_secret_key("clave-maestra", stored) is True
    assert school_settings.verify_secret_key("  clave-maestra  ", stored) is True
    assert school_settings.verify_secret_key("otra-clave", stored) is False
    assert school_settings.verify_secret_key("", stored) is False
    assert school_settings.verify_secret_key("clave-maestra", "not-a-hash") is False


@pytest.mark.parametrize(
    "key, confirmation, code",
    [
        ("corta", "corta", "settings.error.secret_key_short"),
        ("clave-larga-1", "clave-larga-2", "settings.error.secret_key_mismatch"),
    ],
)
def test_a_new_admin_secret_key_is_long_enough_and_typed_the_same_twice(key, confirmation, code):
    with pytest.raises(SchoolSettingsError) as error:
        school_settings.check_new_secret_key(key, confirmation)

    assert error.value.code == code
    school_settings.check_new_secret_key("clave-larga-1", " clave-larga-1 ")


def test_two_hashes_of_the_same_key_differ():
    first = school_settings.hash_secret_key("clave-maestra", iterations=1000)
    second = school_settings.hash_secret_key("clave-maestra", iterations=1000)

    assert first != second


def test_school_days_are_the_active_weekdays_that_are_not_holidays():
    school = make_school(holidays=(date(2026, 10, 14),))
    monday_to_sunday = (date(2026, 10, 12), date(2026, 10, 18))

    assert school.school_days(*monday_to_sunday) == [
        date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 15), date(2026, 10, 16),
    ]
    assert replace(school, active_weekdays=(0, 1, 2, 3, 4, 5)).school_days(*monday_to_sunday)[-1] == date(2026, 10, 17)
    assert date(2026, 10, 14) in replace(school, holidays=()).school_days(*monday_to_sunday)
    assert school.school_days(date(2026, 10, 29), date(2026, 11, 3)) == [
        date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3),
    ]
    assert school.school_days(date(2026, 10, 16), date(2026, 10, 12)) == []

    assert school.is_school_day(date(2026, 10, 13))
    assert not school.is_school_day(datetime(2026, 10, 14, 7, 30))
    assert not school.is_school_day(date(2026, 10, 17))
