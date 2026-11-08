# Changelog

All notable changes to Quickpass are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **Web portal exports:** replaced the npm `xlsx` package (SheetJS 0.18.5, with unpatched high-severity advisories) with `write-excel-file`. CSV exports now carry a UTF-8 byte order mark and guard against formula injection.

### Added

- **Continuous integration:** GitHub Actions runs Ruff, the Python tests (3.10 and 3.14, with PostgreSQL 16), the web portal's tests, lint, build, and audit, the firmware tests, and an Arduino Uno compile.
- **Repository tooling:** Ruff lint and formatting (`pyproject.toml`, `make lint`, `make format`), `requirements-dev.txt`, Dependabot, CODEOWNERS, `.editorconfig`, `.python-version`, and `web/frontend/.nvmrc`.

## [1.0.0] - 2026-11-06

### Added

- **Door Gate firmware (`main_program/main_program.ino`):** Arduino Uno sketch driving an RC522 RFID reader, I2C 16x2 LCD (`0x27` / `0x3F`), status LEDs, and a 28BYJ-48 stepper motor over a 9600-baud line protocol (`IDLE`, `GRANT`, `DENY`, `UNLOCK`, `MSG`), with host-tested C++17 parser and door timing headers.
- **Offline-first desktop program (`main_program/`):** PySide6 station window with first-run setup wizard, Live Access entrance view, Badge Management, Admin Approval (Admin Badge tap or PBKDF2-hashed Admin Secret Key), School Settings (School Language, Grades, Sections, school weekdays, holidays, Late Threshold, and Check-out wait), and end-of-year Grade Promotion.
- **Attendance search & Excel reports (`search.py`, `reports.py`):** Official `.xlsx` workbooks E1 through E8 covering daily, individual, Grade, Section, date-range matrix, and staff/visitor attendance, counting Absences strictly on School Days.
- **Guardian & Admin notifications (`sms.py`):** Background SMS and WhatsApp notifications via Twilio in the School Language for Student Check-ins, Check-outs, and first-of-day unregistered Badge alerts.
- **Cloud Sync (`cloud_sync.py`):** Background replication of scans, Badges, and School Settings between station SQLite databases and Supabase, with automatic offline retry backoff.
- **Web portal & database security (`supabase/migrations/`, `web/frontend/`):** Serverless React + Vite + Tailwind CSS portal on Supabase Auth and PostgreSQL Row-Level Security, with Authorized Email enforcement and Day/Year Views scoped to Guardians (Family Code), Teachers (Grade), and Admins (whole School, including Excel export and Role preview).
- **Spanish and English parity (`locales/`):** Full runtime switching between Spanish and English across the desktop window, 16x2 LCD screens, Excel reports, text messages, and web portal using language-neutral database codes.
- **Documentation & test suites (`docs/`, `main_program/tests/`, `web/frontend/src/__tests__/`):** Hardware, desktop setup, web portal setup, school administration, architecture, and testing guides with dual-theme SVG diagrams, backed by Python (`pytest`), frontend (`Vitest`), and C++17 firmware test suites.

[Unreleased]: https://github.com/JnDarkLord/Quickpass/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/JnDarkLord/Quickpass/releases/tag/v1.0.0
