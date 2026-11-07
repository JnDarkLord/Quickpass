"""Runs the sketch's C++ tests (command parser, door logic) through make."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

CPP_TESTS_DIR = Path(__file__).resolve().parent


def _find_compiler() -> str | None:
    for candidate in (os.environ.get("CXX"), "c++", "clang++", "g++"):
        if candidate and shutil.which(candidate):
            return candidate
    return None


def test_cpp_suites_pass():
    make = shutil.which("make")
    compiler = _find_compiler()
    if make is None or compiler is None:
        pytest.skip("Skipping the C++ tests: make or a C++ compiler is missing.")

    result = subprocess.run(
        [make, "-C", str(CPP_TESTS_DIR), "test", f"CXX={compiler}"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"C++ tests failed:\n{result.stdout}\n{result.stderr}"
    assert "All firmware parser tests passed successfully!" in result.stdout
    assert "All door logic tests passed successfully!" in result.stdout

