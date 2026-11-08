# Contributing to Quickpass

Thank you for helping improve Quickpass. Participation in this project follows our [Code of Conduct](CODE_OF_CONDUCT.md). This guide covers how to report problems, how to propose a change, the branch and commit rules, the tests to run, and the rules for text in Spanish and English.

## Reporting a problem

Open an issue that says what you did, what you expected, and what happened instead. Include the Quickpass commit you run, your operating system, and your Python or Node.js version. For security vulnerabilities, do not open a public issue—follow the [Security Policy](SECURITY.md) instead.

Quickpass handles Students' personal data. **Never put real names, phone numbers, emails, Badge UIDs, database files, or `.env` contents in an issue**, and never share Supabase or Twilio keys. Use made-up examples instead; the test data generator makes realistic ones.

## Setting up

- The desktop program: [Desktop Setup](docs/desktop-setup.md).
- The web portal: [Web Portal Setup](docs/web-portal-setup.md#5-try-the-portal-on-your-computer).
- The tests, including the PostgreSQL test database: [Testing](docs/testing.md).
- How the parts fit together: [Architecture](docs/architecture.md).

On macOS or Linux, `make setup` creates `.venv`, installs the Python packages with the test and lint tools (`requirements-dev.txt`), and installs `web/frontend`'s npm dependencies in one step. Elsewhere, run `pip install -r requirements-dev.txt` in your environment.

## Branches and pull requests

- `main` is always releasable: every commit on it passes every test suite. [CI](.github/workflows/ci.yml) runs the lint, the three suites, and an Arduino Uno compile of the sketch on every pull request, and must pass before merging.
- Make each change on its own branch, started from an up-to-date `main` and named for the change, such as `feat/holiday-import`, `fix/late-threshold-midnight`, or `docs/nginx-https`.
- Keep a pull request to one change. Before asking for a review, rebase it on the latest `main`, and run the tests.
- Describe what changed and why, and how you checked it. For changes to the window, the LCD screens, or the portal, add screenshots in both languages.
- Never commit `.env` files, databases, reports, backups, or keys. `.gitignore` covers the usual ones.

### Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/): a type, a colon, and a short summary in the imperative or present tense.

```
fix: a Check-in exactly at the Late Threshold counts as On Time

- Explain what changed and why, in a few bullet points.
```

The types are `feat`, `fix`, `docs`, `test`, `refactor`, and `chore`. Add `!` after the type for a change that needs action from Schools when they update, such as a new migration or a new firmware upload: `feat!: ...`.

## Lint and formatting

Python follows [Ruff](https://docs.astral.sh/ruff/)'s formatter and lint rules, configured in `pyproject.toml`; the web portal uses oxlint. `make lint` checks both, and `make format` fixes what Ruff can. Without `make`:

```bash
ruff check --fix && ruff format
cd web/frontend && npm run lint && cd ../..
```

## Running the tests

Run all three suites before opening a pull request (`make test` on macOS/Linux, after running `make test-db` once). [Testing](docs/testing.md) explains each one, and how to set up the PostgreSQL test database.

```bash
# Python, from the repository root. Always set these variables, so the tests never use .env's databases.
export QT_QPA_PLATFORM=offscreen DATABASE_URL=postgresql://localhost/quickpass_test SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY=
python -m pytest

# Web portal
cd web/frontend && npm test && npm run typecheck && npm run lint && cd ../..

# Firmware
make -C main_program/tests test
```

Add tests with your change: a test that fails without the fix, for a bug, or tests of the new behavior, for a feature.

## Guidelines

- **Match the code around you:** its naming, its comment style, and its structure.
- **Use Quickpass's words**, in the code, the text, and the docs, as the guides do. A **Badge** has a **Badge UID**. A tap at the **Door Gate** is a **Check-in**, a **Check-out**, or a **Repeat Scan**. A Student's **Grade** and **Section** come from the School's lists. A **School Day** is a day with classes, and an **Absence** is a School Day without a Check-in. Protected changes need **Admin Approval**.
- **New dependencies:** ask in an issue first. Every dependency must have a license that allows distributing Quickpass under the MIT License, and goes in `requirements.txt` (or `requirements-dev.txt`, for test and lint tools) or `web/frontend/package.json`.
- **Firmware:** keep School-facing text out of the sketch; the desktop program sends every LCD line. Put logic in `command_parser.h` or `door_logic.h`, where the C++ tests reach it. Hardware changes, such as a new pin, also update the [Hardware Guide](docs/hardware.md).
- **Supabase database:** change it with a new numbered file in `supabase/migrations/`, such as `0006_holiday_names.sql`, and never edit one that has shipped. A migration must be safe to run twice, because the tests apply every migration on each run, and a School may run them again. Anything a migration exposes to the portal needs Row-Level Security, with tests in `main_program/tests/test_supabase_rls_and_rpc.py`.
- **Station database:** a change to the SQLite schema in `database.py` must also upgrade an existing station's database when it opens it, as the existing column additions do.
- **Secrets:** the Service Role Key stays on the stations. Nothing in `web/frontend/` may need it.

## Text in Spanish and English

Quickpass runs in the School Language, Spanish or English, and both languages ship together. Every change keeps the two in step:

- Text the School's people see comes from a catalog, never from a string in the code:
  - the desktop program: `main_program/locales/es.json` and `en.json`, through `i18n.t(language, "key")`, or `tr("key")` in the window;
  - the web portal: `web/frontend/src/locales/es.json` and `en.json`.
- **Add every new key to both files**, with the same `{placeholders}`. Remove keys you no longer use from both files. The tests fail when the two files differ, when a text is empty, or when the desktop program uses a key that doesn't exist.
- **LCD screens** are a pair of keys, `<key>.line1` and `<key>.line2`, each at most 16 characters in both languages. Accents are removed on the way to the LCD, so check that the text still reads well without them.
- **Store codes, not words.** Save language-neutral values, such as `on_time`, `check_in`, or `student`, and translate them only when showing them.
- **Format dates and times with the i18n helpers**, which write Spanish as `31/12/2026 14:05:00` and English as `12/31/2026 02:05:00 PM`. Don't depend on the computer's locale.
- **Write both languages well.** If you don't speak one of them, say so in the pull request, and a reviewer will check the translation.
- Text for installers and maintainers, such as `.env` errors, log lines, the tools' output, and code comments, is always English and doesn't go in the catalogs.

## License

Quickpass is released under the [MIT License](LICENSE). By contributing, you agree that your contributions are released under the same license.
