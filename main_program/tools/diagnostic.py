"""Serial diagnostic tool: lists ports, monitors Arduino output, and sends commands.

Usage:
    python main_program/tools/diagnostic.py [--port PORT] [--baud BAUD]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

_main_dir = Path(__file__).resolve().parent.parent
if str(_main_dir) not in sys.path:
    sys.path.insert(0, str(_main_dir))

import serial
import serial.tools.list_ports

import arduino
from config import load_settings

_SCREEN_COMMANDS = {
    "idle": arduino.IDLE,
    "grant": arduino.GRANT,
    "deny": arduino.DENY,
    "unlock": arduino.UNLOCK,
    "msg": arduino.MSG,
}


def list_available_ports() -> list[str]:
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports


def build_line(typed: str) -> str:
    """The line sent to the Arduino for one typed command, such as `grant Hello|World`."""
    word, _, rest = typed.partition(" ")
    if word.lower() == "raw":
        return rest.strip()
    name = _SCREEN_COMMANDS.get(word.lower())
    if name is None:
        return typed
    if name == arduino.UNLOCK and not rest.strip():
        return arduino.UNLOCK
    line1, _, line2 = rest.partition("|")
    return arduino.command(name, line1.strip(), line2.strip())


def run_diagnostic(port: str, baud: int) -> int:
    print("=== Quickpass Serial Diagnostic ===")
    print(f"Connecting to {port} at {baud} baud...")

    try:
        ser = serial.Serial(port, baud, timeout=0.1)
    except (serial.SerialException, OSError) as error:
        print(f"❌ Could not open {port}: {error}")
        available = list_available_ports()
        if available:
            print("\nSerial ports available on this computer:")
            for p in available:
                print(f"  - {p}")
        else:
            print("\nNo serial ports were detected.")
        return 1

    print(f"✅ Connected to {port}. Listening for Arduino lines...")
    print("Commands:")
    print("  idle <l1>|<l2>     -> Sends IDLE <l1>|<l2> (the standby screen)")
    print("  grant <l1>|<l2>    -> Sends GRANT <l1>|<l2> (opens the door)")
    print("  deny <l1>|<l2>     -> Sends DENY <header>|<reason>")
    print("  unlock [<l1>|<l2>] -> Sends UNLOCK (opens the door)")
    print("  msg <l1>|<l2>      -> Sends MSG <l1>|<l2> (shows the lines for a moment)")
    print("  raw <text>         -> Sends the text as typed")
    print("  q / exit           -> Quit\n")

    stop_event = threading.Event()

    def reader():
        while not stop_event.is_set():
            try:
                if ser.in_waiting > 0:
                    raw = ser.readline()
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        print(f"[ARDUINO -> HOST] {line}")
                else:
                    time.sleep(0.05)
            except Exception as e:
                if not stop_event.is_set():
                    print(f"❌ Error reading the serial port: {e}")
                break

    read_thread = threading.Thread(target=reader, daemon=True)
    read_thread.start()

    try:
        while True:
            cmd = input().strip()
            if not cmd:
                continue
            if cmd.lower() in ("q", "quit", "exit"):
                break
            line = build_line(cmd)
            print(f"[HOST -> ARDUINO] {line}")
            ser.write((line + "\n").encode("ascii", errors="replace"))
            ser.flush()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop_event.set()
        read_thread.join(timeout=0.5)
        ser.close()
        print("\nDisconnected.")

    return 0


def main() -> int:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Serial diagnostic tool for the Quickpass Arduino.")
    parser.add_argument("--port", type=str, default=settings.serial_port or "", help="Serial port")
    parser.add_argument("--baud", type=int, default=settings.serial_baudrate, help="Baud rate")
    args = parser.parse_args()

    port = args.port or settings.serial_port or ""
    if not port:
        print("⚠️ No serial port was given in .env or on the command line.")
        available = list_available_ports()
        if available:
            print("Available ports:")
            for p in available:
                print(f"  - {p}")
        return 1

    return run_diagnostic(port, args.baud)


if __name__ == "__main__":
    sys.exit(main())
