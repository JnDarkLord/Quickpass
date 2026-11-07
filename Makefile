PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
TEST_DB_NAME ?= quickpass_test
TEST_DATABASE_URL ?= postgresql://localhost/$(TEST_DB_NAME)

.PHONY: help setup demo run test test-offline test-python test-web test-firmware test-db

help:
	@echo "Quickpass developer commands:"
	@echo "  make setup          Create .venv, install Python deps, and install web/frontend npm deps"
	@echo "  make demo           Start Quickpass in Demo Mode using an isolated demo.db"
	@echo "  make run            Start Quickpass using .env"
	@echo "  make test-db        Create and initialize the local '$(TEST_DB_NAME)' PostgreSQL test database"
	@echo "  make test           Run all test suites (Python + PostgreSQL RLS, web portal, and C++ firmware)"
	@echo "  make test-offline   Run all offline tests (no PostgreSQL needed: SQLite/GUI, web, and C++ firmware)"

setup:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install -r requirements.txt
	npm --prefix web/frontend ci

demo:
	test -x $(VENV_PYTHON) && $(VENV_PYTHON) -c "import PySide6" 2>/dev/null || ($(PYTHON) -m venv $(VENV) && $(VENV_PIP) install -r requirements.txt)
	test -f .env || cp .env.example .env
	DEMO_MODE=true DATABASE_PATH=demo.db SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= DATABASE_URL= $(VENV_PYTHON) main_program/main.py

run:
	test -x $(VENV_PYTHON) && $(VENV_PYTHON) -c "import PySide6" 2>/dev/null || ($(PYTHON) -m venv $(VENV) && $(VENV_PIP) install -r requirements.txt)
	test -f .env || cp .env.example .env
	$(VENV_PYTHON) main_program/main.py

test-db:
	createdb $(TEST_DB_NAME) 2>/dev/null || true
	psql -d $(TEST_DB_NAME) -v ON_ERROR_STOP=1 -c "CREATE SCHEMA IF NOT EXISTS auth; CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY, email text);"
	psql -d $(TEST_DB_NAME) -v ON_ERROR_STOP=1 -c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF; IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF; IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN; END IF; END \$$\$$;"

test-python:
	QT_QPA_PLATFORM=offscreen DATABASE_URL="$(TEST_DATABASE_URL)" SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= $(VENV_PYTHON) -m pytest

test-web:
	npm --prefix web/frontend test
	npm --prefix web/frontend run typecheck
	npm --prefix web/frontend run lint

test-firmware:
	$(MAKE) -C main_program/tests test

test: test-python test-web test-firmware

test-offline:
	QT_QPA_PLATFORM=offscreen DATABASE_URL="$(TEST_DATABASE_URL)" SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= $(VENV_PYTHON) -m pytest -k "not supabase and not postgres and not e2e"
	$(MAKE) test-web
	$(MAKE) test-firmware
