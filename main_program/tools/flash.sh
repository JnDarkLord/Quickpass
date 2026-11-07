#!/usr/bin/env bash
# Quickpass Arduino Firmware Flasher
# Usage: ./main_program/tools/flash.sh [PORT]

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH_PATH="$REPO_DIR/main_program/main_program.ino"
FQBN="arduino:avr:uno"

# Resolve port: from argument, or .env, or arduino-cli auto-detect
PORT="$1"
if [ -z "$PORT" ] && [ -f "$REPO_DIR/.env" ]; then
    PORT=$(grep "^SERIAL_PORT=" "$REPO_DIR/.env" | cut -d '=' -f2 | tr -d ' "\r')
fi

if [ -z "$PORT" ]; then
    PORT=$(arduino-cli board list | grep "Arduino UNO" | awk '{print $1}' | head -n 1)
fi

if [ -z "$PORT" ]; then
    echo "❌ No Arduino port was detected. Connect the board or give the port:"
    echo "   $0 /dev/cu.usbmodem11101"
    exit 1
fi

echo "========================================="
echo "⚡ Quickpass: compiling and uploading firmware"
echo "   Sketch: $SKETCH_PATH"
echo "   Port:   $PORT"
echo "   Board:  Arduino Uno ($FQBN)"
echo "========================================="

arduino-cli compile --fqbn "$FQBN" "$SKETCH_PATH"
echo "✅ Compiled."

echo "Uploading to the Arduino..."
arduino-cli upload -p "$PORT" --fqbn "$FQBN" "$SKETCH_PATH"
echo "✅ Firmware uploaded to $PORT."
