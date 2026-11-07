# Security Policy

Quickpass manages physical Door Gate access and Students' attendance records, Guardian contact details, and Role-scoped web accounts. Security bugs in any layer are taken seriously.

## Supported Versions

Security fixes apply to the latest `main` branch:

| Version | Supported |
|:---|:---|
| `main` (1.x) | Yes |

## Reporting a Vulnerability

**Do not open a public GitHub issue for a security vulnerability.**

Instead, report it privately through [**GitHub Private Vulnerability Reporting**](https://github.com/JnDarkLord/Quickpass/security/advisories/new) on this repository.

Please include:

1. Which component is affected: the desktop program (`main_program/`), the Arduino firmware, the Supabase schema / Row-Level Security (`supabase/migrations/`), or the web portal (`web/frontend/`).
2. Clear steps or a minimal proof of concept to reproduce the issue.
3. What an attacker could read, modify, or bypass (for example, Row-Level Security isolation between Family Codes or Grades, Admin Approval, or physical gate control).

> [!IMPORTANT]
> Never include real Students' or Guardians' names, phone numbers, emails, Badge UIDs, `.db` files, or live Supabase / Twilio keys in a report. Use synthetic test data instead.

## Scope & Deployment Boundaries

When evaluating Quickpass's security model, keep its documented deployment boundaries in mind ([Architecture](docs/architecture.md) and [Web Portal Setup](docs/web-portal-setup.md#keys-and-security)):

- **Station secrets:** `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `TWILIO_AUTH_TOKEN`, and `WIPE_PASSWORD` belong exclusively in a station computer's local `.env` file, never in `web/frontend/.env` or a static host's build variables.
- **Public portal keys:** `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are public by design; data isolation in the web portal is enforced in PostgreSQL via Row-Level Security, `SECURITY DEFINER` RPCs, and the `check_authorized_email` trigger.
- **Physical RFID tags:** Standard 13.56 MHz UID-only tags (such as MIFARE Classic UID reads on RC522) identify Badges by their UID; high-security physical facilities should secure the Door Gate controller and USB link inside the entrance station.
