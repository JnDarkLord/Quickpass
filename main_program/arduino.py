"""The Arduino link: the serial port, the line protocol and the LCD text.

Protocol (9600 baud, one line each). The Arduino sends `SCAN <UID>` for each
badge, plus English boot lines such as `LCD_OK:0x27` and `QUICKPASS_READY`.
The computer sends every LCD line, in the School Language:

- `IDLE <line 1>|<line 2>`: the standby screen between scans.
- `GRANT <line 1>|<line 2>`: opens the door and shows the lines.
- `DENY <header>|<reason>`: lights the red LED and shows the lines.
- `UNLOCK <line 1>|<line 2>`: opens the door at a staff member's request.
- `MSG <line 1>|<line 2>`: shows the lines for a moment; the door stays shut.

Only one program can hold the port, so the Arduino IDE's Serial Monitor must
be closed while the program runs.
"""

from __future__ import annotations

import time
import unicodedata
from typing import Any

import serial

import database
import i18n
from config import Settings

# The Arduino resets when the port opens; give it time to boot.
BOOT_WAIT_SECONDS = 2.0
READ_TIMEOUT_SECONDS = 0.1

IDLE = "IDLE"
GRANT = "GRANT"
DENY = "DENY"
UNLOCK = "UNLOCK"
MSG = "MSG"
READY_LINE = "QUICKPASS_READY"

LCD_WIDTH = 16
_LINE_SEPARATOR = "|"


def lcd_text(text: str) -> str:
    """Text the 16x2 LCD can show: plain ASCII, no line separator, at most 16 characters."""
    decomposed = unicodedata.normalize("NFD", text.replace(_LINE_SEPARATOR, " "))
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(plain.encode("ascii", "ignore").decode().split())[:LCD_WIDTH]


def command(name: str, line1: str = "", line2: str = "") -> str:
    """One line for the Arduino: the command name and both LCD lines, centered."""
    return f"{name} {lcd_text(line1).center(LCD_WIDTH)}{_LINE_SEPARATOR}{lcd_text(line2).center(LCD_WIDTH)}"


def screen(name: str, lang: str, key: str, **params: Any) -> str:
    """The command that shows the catalog's two-line screen `key` (`<key>.line1` and `<key>.line2`)."""
    return command(name, i18n.t(lang, f"{key}.line1", **params), i18n.t(lang, f"{key}.line2", **params))


def idle_screen(lang: str) -> str:
    return screen(IDLE, lang, "lcd.idle")


def unlock_screen(lang: str) -> str:
    return screen(UNLOCK, lang, "lcd.unlock")


def parse_scan(line: str) -> str | None:
    """The normalized badge UID of a `SCAN <UID>` line, or None for any other line."""
    name, _, uid = line.strip().partition(" ")
    if name != "SCAN":
        return None
    return database.normalize_badge_uid(uid) or None


class ArduinoError(Exception):
    """The port could not be opened or stopped working."""


class ArduinoLink:
    """Owns the serial port. Thin by design: checked by hand, not by tests."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._port: serial.Serial | None = None
        self._buffer = b""

    @property
    def connected(self) -> bool:
        return self._port is not None and self._port.is_open

    def connect(self) -> str:
        """Try to open the port. Returns a status message; never raises."""
        port_name = self._settings.serial_port
        if not port_name:
            return "SERIAL_PORT is not set in .env; running without the Arduino."
        self.close()
        try:
            self._port = serial.Serial(port_name, self._settings.serial_baudrate, timeout=READ_TIMEOUT_SECONDS)
        except (serial.SerialException, OSError, ValueError) as error:
            self._port = None
            return f"Could not open {port_name}: {error}"
        time.sleep(BOOT_WAIT_SECONDS)
        return f"Arduino connected on {port_name}."

    def ensure_connected(self) -> str | None:
        """Reconnect if needed. Returns an error message, or None when connected."""
        if self.connected:
            return None
        message = self.connect()
        return None if self.connected else message

    def discard_input(self) -> None:
        """Drop everything the Arduino sent while nobody was listening."""
        self._buffer = b""
        if self._port is None:
            return
        try:
            self._port.reset_input_buffer()
        except (serial.SerialException, OSError) as error:
            self._lost(error)

    def read_line(self, timeout: float) -> str | None:
        """Return the next non-empty line, or None if none arrives within `timeout`."""
        if self._port is None:
            raise ArduinoError("The Arduino is not connected.")
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self._buffer:
                raw, _, self._buffer = self._buffer.partition(b"\n")
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    return line
            if time.monotonic() >= deadline:
                return None
            try:
                waiting = self._port.in_waiting
                self._buffer += self._port.read(max(1, waiting))
            except (serial.SerialException, OSError) as error:
                self._lost(error)

    def send(self, line: str) -> None:
        if self._port is None:
            raise ArduinoError("The Arduino is not connected.")
        try:
            self._port.write((line + "\n").encode("ascii", errors="replace"))
            self._port.flush()
        except (serial.SerialException, OSError) as error:
            self._lost(error)

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except (serial.SerialException, OSError):
                pass
        self._port = None
        self._buffer = b""

    def _lost(self, error: Exception) -> None:
        self.close()
        raise ArduinoError(f"Lost the connection to the Arduino: {error}")
