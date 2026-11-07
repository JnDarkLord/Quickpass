"""Quickpass: school access control and attendance.

Usage, from the repository root inside the virtual environment:
    python main_program/main.py
"""

import sys

try:
    import gui
except ModuleNotFoundError as error:
    sys.stderr.write(
        f"Missing Python package '{error.name}'. Activate the virtual environment and install the dependencies first:\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate      # Windows: .venv\\Scripts\\activate\n"
        "  pip install -r requirements.txt\n"
    )
    sys.exit(1)

if __name__ == "__main__":
    gui.main()
