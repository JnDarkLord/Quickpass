"""Test-data generator: fills a database with realistic fake people and attendance history.

Uses Faker with Spanish names and numbers. All entities and scans are generated
through the program's core add_user and process_scan_line functions to ensure
compliance with all domain rules.
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

_main_dir = Path(__file__).resolve().parent.parent
if str(_main_dir) not in sys.path:
    sys.path.insert(0, str(_main_dir))

from faker import Faker

import access_control
import admin
import database
import school_settings
from config import Settings, load_settings


def _get_recent_school_days(school: school_settings.SchoolSettings, end_date: datetime, count: int) -> list[datetime]:
    """Return `count` School Days ending at or before `end_date`, in chronological order."""
    days: list[datetime] = []
    current = end_date
    while len(days) < count:
        if school.is_school_day(current):
            days.append(current)
        current -= timedelta(days=1)
    days.reverse()
    return days


def generate_test_data(
    conn: sqlite3.Connection,
    settings: Settings,
    num_students: int = 30,
    num_teachers: int = 6,
    num_admins: int = 2,
    num_visitors: int = 4,
    days: int = 5,
    end_date: datetime | None = None,
    seed: int | None = 42,
) -> None:
    """Generate fake users, guardians, check-ins, check-outs and security incidents."""
    if seed is not None:
        random.seed(seed)
        Faker.seed(seed)

    fake = Faker("es_ES")
    school = school_settings.require(conn)
    end_dt = end_date or datetime.now()
    school_days = _get_recent_school_days(school, end_dt, days)
    start_dt = school_days[0] if school_days else end_dt

    existing_uids: set[str] = set()

    def make_uid() -> str:
        while True:
            candidate = f"{random.randint(0x10000000, 0xFFFFFFFF):08X}"
            if candidate not in existing_uids:
                existing_uids.add(candidate)
                return candidate

    # 1. Add Admins
    admin_uids: list[str] = []
    for _ in range(num_admins):
        uid = make_uid()
        name = fake.name()
        approver = admin_uids[0] if admin_uids else None
        res = admin.add_user(
            conn=conn,
            settings=settings,
            badge_uid=uid,
            role="admin",
            full_name=name,
            approving_uid=approver,
            now=start_dt - timedelta(days=10),
        )
        if res.success and res.user:
            admin_uids.append(uid)

    # 2. Add Teachers
    teacher_uids: list[str] = []
    for i in range(num_teachers):
        uid = make_uid()
        name = fake.name()
        taught = (i % school.final_grade) + 1
        res = admin.add_user(
            conn=conn,
            settings=settings,
            badge_uid=uid,
            role="prof",
            full_name=f"Prof. {name}",
            taught_grade=taught,
            now=start_dt - timedelta(days=10),
        )
        if res.success and res.user:
            teacher_uids.append(uid)

    # 3. Add Students
    student_uids: list[str] = []
    sections = school.sections[:3]
    for i in range(num_students):
        uid = make_uid()
        name = fake.name()
        grade = (i % school.final_grade) + 1
        sec = sections[i % len(sections)]

        num_g = random.choice([1, 2])
        guardians: list[admin.GuardianData] = []
        for _ in range(num_g):
            g_name = fake.name()
            g_phone = f"+1809{random.randint(1000000, 9999999)}"
            g_email = f"{g_name.lower().replace(' ', '.')}@example.com"
            guardians.append(admin.GuardianData(name=g_name, phone=g_phone, email=g_email))

        res = admin.add_user(
            conn=conn,
            settings=settings,
            badge_uid=uid,
            role="est",
            full_name=name,
            grade=grade,
            section=sec,
            guardians=guardians,
            now=start_dt - timedelta(days=10),
        )
        if res.success and res.user:
            student_uids.append(uid)

    # 4. Add Visitors
    visitor_uids: list[str] = []
    for _ in range(num_visitors):
        uid = make_uid()
        name = fake.name()
        res = admin.add_user(
            conn=conn,
            settings=settings,
            badge_uid=uid,
            role="vist",
            full_name=name,
            now=start_dt - timedelta(days=10),
        )
        if res.success and res.user:
            visitor_uids.append(uid)

    all_users = student_uids + teacher_uids + admin_uids

    # 5. Simulate Daily Attendance over School Days
    for day in school_days:
        date_base = datetime(day.year, day.month, day.day)

        # Scans for registered users
        for uid in all_users:
            # 85% attendance rate (15% absent)
            if random.random() < 0.15:
                continue

            # Check-in time: 70% on time, 30% late
            if random.random() < 0.70:
                minute = random.randint(30, 49)
                second = random.randint(0, 59)
                in_time = date_base.replace(hour=6, minute=minute, second=second)
            else:
                minute = random.randint(51, 59)
                second = random.randint(0, 59)
                in_time = date_base.replace(hour=6, minute=minute, second=second)

            access_control.process_scan_line(conn, settings, f"SCAN {uid}", now=in_time)

            # Check-out time: 80% check-out in the afternoon
            if random.random() < 0.80:
                out_hour = random.randint(13, 15)
                out_minute = random.randint(0, 59)
                out_second = random.randint(0, 59)
                out_time = date_base.replace(hour=out_hour, minute=out_minute, second=out_second)
                access_control.process_scan_line(conn, settings, f"SCAN {uid}", now=out_time)

        # Unregistered badge scans (1 to 2 incidents per day)
        num_incidents = random.randint(1, 2)
        for _ in range(num_incidents):
            stranger_uid = f"BADGE{random.randint(1000, 9999):04X}"
            inc_hour = random.randint(8, 14)
            inc_minute = random.randint(0, 59)
            inc_time = date_base.replace(hour=inc_hour, minute=inc_minute, second=0)
            access_control.process_scan_line(conn, settings, f"SCAN {stranger_uid}", now=inc_time)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test-data generator for Quickpass")
    parser.add_argument("--db", type=str, default="", help="Database path (defaults to the one in .env)")
    parser.add_argument("--students", type=int, default=30, help="Number of Students")
    parser.add_argument("--teachers", type=int, default=6, help="Number of Teachers")
    parser.add_argument("--days", type=int, default=5, help="Number of recent School Days to generate")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    settings = load_settings()
    db_path = Path(args.db) if args.db else settings.database_path

    if not args.yes:
        confirm = input(f"Generate test data in '{db_path}'? (y/N): ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return 0

    conn = database.connect(db_path)
    try:
        if school_settings.load(conn) is None:
            print("School Settings are not set up yet. Open Quickpass once to set up the School, then try again.")
            return 1
        print(f"Generating test data in {db_path}...")
        generate_test_data(
            conn=conn,
            settings=settings,
            num_students=args.students,
            num_teachers=args.teachers,
            days=args.days,
        )
        print("✅ Test data generated.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
