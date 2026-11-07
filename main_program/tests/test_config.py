from pathlib import Path

import pytest

from config import ConfigError, Settings, load_settings, REPO_ROOT


def write_env(tmp_path: Path, text: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def test_defaults_when_env_file_is_empty(tmp_path):
    settings = load_settings(write_env(tmp_path, ""), environ={})

    assert settings.serial_port is None
    assert settings.serial_baudrate == 9600
    assert settings.database_path == REPO_ROOT / "quickpass.db"
    assert settings.demo_mode is False
    assert settings.twilio_enabled is False
    assert settings.twilio_account_sid == ""
    assert settings.twilio_auth_token == ""
    assert settings.twilio_from_number == ""
    assert settings.admin_alert_phone == ""
    assert settings.wipe_password is None
    assert settings.reports_dir == REPO_ROOT / "Reports"


def test_reads_values_from_env_file(tmp_path):
    env_file = write_env(
        tmp_path,
        "\n".join(
            [
                "SERIAL_PORT=COM3",
                "SERIAL_BAUDRATE=115200",
                "DATABASE_PATH=data/escuela.db",
                "DEMO_MODE=true",
                "TWILIO_ENABLED=True",
                "TWILIO_ACCOUNT_SID=AC123",
                "TWILIO_AUTH_TOKEN=tok",
                "TWILIO_FROM_NUMBER=+15550000",
                "ADMIN_ALERT_PHONE=+15551111",
                "WIPE_PASSWORD=borrar",
                "REPORTS_DIR=/tmp/reportes",
            ]
        ),
    )

    settings = load_settings(env_file, environ={})

    assert settings.serial_port == "COM3"
    assert settings.serial_baudrate == 115200
    assert settings.database_path == REPO_ROOT / "data" / "escuela.db"
    assert settings.demo_mode is True
    assert settings.twilio_enabled is True
    assert settings.twilio_account_sid == "AC123"
    assert settings.twilio_auth_token == "tok"
    assert settings.twilio_from_number == "+15550000"
    assert settings.admin_alert_phone == "+15551111"
    assert settings.wipe_password == "borrar"
    assert settings.reports_dir == Path("/tmp/reportes")


def test_process_environment_overrides_env_file(tmp_path):
    env_file = write_env(tmp_path, "SERIAL_BAUDRATE=9600\n")

    settings = load_settings(env_file, environ={"SERIAL_BAUDRATE": "115200"})

    assert settings.serial_baudrate == 115200


def test_old_keys_are_ignored(tmp_path):
    # School policy moved to School Settings, so these keys no longer configure anything.
    env_file = write_env(
        tmp_path,
        "\n".join(
            [
                "DOOR_DWELL_SECONDS=10",
                "ATTENDANCE_LATE_THRESHOLD=tarde",
                "COOLDOWN_SECONDS=cinco",
                "ADMIN_SECRET_KEY=admin123",
            ]
        ),
    )

    settings = load_settings(env_file, environ={})

    assert settings == Settings()


def test_database_url_is_loaded(tmp_path):
    env_file = write_env(
        tmp_path,
        "DATABASE_URL=postgresql://localhost:5432/quickpass\n",
    )

    settings = load_settings(env_file, environ={})

    assert settings.database_url == "postgresql://localhost:5432/quickpass"


def test_missing_env_file_gives_defaults(tmp_path):
    settings = load_settings(tmp_path / "does-not-exist.env", environ={})

    assert settings == Settings()


def test_env_example_loads_clean_offline_defaults():
    settings = load_settings(REPO_ROOT / ".env.example", environ={})

    assert settings == Settings()


def test_empty_serial_port_means_no_port(tmp_path):
    settings = load_settings(write_env(tmp_path, "SERIAL_PORT=\n"), environ={})

    assert settings.serial_port is None


@pytest.mark.parametrize(
    "line, key",
    [
        ("SERIAL_BAUDRATE=0", "SERIAL_BAUDRATE"),
        ("SERIAL_BAUDRATE=rapido", "SERIAL_BAUDRATE"),
        ("DEMO_MODE=quizas", "DEMO_MODE"),
        ("TWILIO_ENABLED=2", "TWILIO_ENABLED"),
    ],
)
def test_invalid_values_stop_with_a_clear_message(tmp_path, line, key):
    with pytest.raises(ConfigError) as error:
        load_settings(write_env(tmp_path, line + "\n"), environ={})

    assert key in str(error.value)


@pytest.mark.parametrize(
    "line, message",
    [
        ("DEMO_MODE=maybe", "Invalid value for DEMO_MODE in .env: 'maybe' (must be true or false)."),
        ("SERIAL_BAUDRATE=fast", "Invalid value for SERIAL_BAUDRATE in .env: 'fast' (must be a whole number)."),
    ],
)
def test_invalid_value_error_is_english_and_names_the_key(tmp_path, line, message):
    with pytest.raises(ConfigError) as error:
        load_settings(write_env(tmp_path, line + "\n"), environ={})

    assert str(error.value) == message
