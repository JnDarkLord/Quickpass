# Testing

How to run Quickpass's automated tests: the Python suite for the desktop program and the database, the web portal's Vitest suite, and the firmware's C++ tests.

| Suite | Command | Needs |
|:---|:---|:---|
| Python | `python -m pytest`, from the repository root | The Python environment, a PostgreSQL test database, and Qt's `offscreen` platform without a display |
| Web portal | `npm test`, in `web/frontend` | Node.js 22.12 or newer |
| Firmware | `make -C main_program/tests test` | `make` and a C++17 compiler |

On macOS or Linux, the root `Makefile` wraps these commands safely: `make test-db` creates and initializes `quickpass_test`, `make test` runs all three suites, and `make test-offline` runs the SQLite/GUI, web portal, and C++17 firmware tests without needing PostgreSQL.

![Quickpass Automated Test Suites](images/test-suites-tree.svg)

## Python

Activate the Python environment ([Desktop Setup](desktop-setup.md)), then run, from the repository root:

```bash
export QT_QPA_PLATFORM=offscreen
export DATABASE_URL=postgresql://localhost/quickpass_test
export SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY=
python -m pytest
```

- `pytest.ini` points pytest at `main_program/tests/`. Pass a file to run just that one, such as `python -m pytest main_program/tests/test_access_control.py`.
- `QT_QPA_PLATFORM=offscreen` lets the window's tests run without a screen, as on a server. On a computer with a screen, it's optional.
- Most tests use temporary SQLite databases and fake hardware, so they need no Arduino.
- `test_cpp.py` also runs the firmware's C++ tests, and skips them if `make` or a C++ compiler is missing.

> [!WARNING]
> The tests read `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_ROLE_KEY` from the environment first, and from `.env` otherwise. They apply the Supabase migrations, and write and delete test rows. **Always set these variables when you run the tests**, as above, so they never reach the School's real Supabase project through `.env`.

### The PostgreSQL test database

The tests of the Supabase schema, its Row-Level Security policies, and its functions (`test_supabase_rls_and_rpc.py`, plus a test in `test_database.py`) run against a real PostgreSQL database. They apply every file in `supabase/migrations/` at the start of each run.

On Supabase, the `auth` schema and the `anon`, `authenticated`, and `service_role` roles already exist. A plain PostgreSQL database needs stand-ins for them. Create the database once (PostgreSQL 16 is tested):

```bash
createdb quickpass_test
psql -d quickpass_test -v ON_ERROR_STOP=1 <<'SQL'
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text);

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN;
    END IF;
END
$$;
SQL
```

Then point `DATABASE_URL` at it, such as `postgresql://localhost/quickpass_test`, or `postgresql://postgres@localhost:5432/quickpass_test` with a user name and port. The tests connect as that user and switch to the `authenticated` role, so use a superuser, which a local installation's default user is.

### The Cloud Sync end-to-end test

`test_e2e_cloud_sync.py` records a scan in a local SQLite database, sends it to a real Supabase project through Cloud Sync, and checks what Row-Level Security lets the portal read. It runs only when `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set, with `DATABASE_URL` pointing at the same project's database, and skips otherwise. It writes and deletes test records, so use a Supabase project made for testing, never the School's.

## Web portal

```bash
cd web/frontend
npm install
npm test             # Vitest with jsdom
npm run typecheck    # TypeScript (tsc -b)
npm run lint         # oxlint
npm run build        # type-checks and builds into dist/
```

The tests replace the Supabase connection with a fake backend, so they need no keys and no network. Pass a file to run just that one, such as `npx vitest run src/__tests__/i18n.test.ts`.

## Firmware

```bash
make -C main_program/tests test
```

This compiles `test_parser.cpp` and `test_door_logic.cpp` with `-std=c++17 -Wall -Wextra -Werror` and runs them. They cover the command parser (`command_parser.h`) and the Door Gate's timing (`door_logic.h`), which hold the firmware's logic as plain C++. Set `CXX` to choose the compiler, such as `make -C main_program/tests test CXX=g++`.

To check that the sketch itself compiles for the board, with the libraries from the [Hardware Guide](hardware.md#arduino-libraries) installed:

```bash
arduino-cli compile --fqbn arduino:avr:uno main_program
```

## Translation checks

Both apps have Spanish and English catalogs, and tests keep them in step:

- `main_program/tests/test_i18n.py` checks that `main_program/locales/es.json` and `en.json` have the same keys, that every text is filled in and uses the same `{placeholders}` in both languages, that every LCD line fits the display's 16 characters, and that every key the desktop program uses exists.
- `web/frontend/src/__tests__/i18n.test.ts` checks the same key and placeholder rules for the portal's catalogs in `web/frontend/src/locales/`.

## Checking by hand

Some things are checked by hand rather than by tests:

- **The serial link** (`arduino.py`'s `ArduinoLink`) and the hardware: use the diagnostic tool and the steps in the [Hardware Guide](hardware.md#checking-the-board).
- **The window's flows:** start Quickpass with `DEMO_MODE=true` and a separate `DATABASE_PATH`, such as `demo.db`, to type Badge UIDs instead of tapping Badges. The test data generator can fill that database ([Desktop Setup](desktop-setup.md#other-tools)).
