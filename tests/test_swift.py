"""The Swift port gives the paths the Python package gives."""

import importlib.util
import json
import os
import shutil
import subprocess

import pytest

from natural_pointer.strokes import DEFAULT_LIBRARY

ROOT = os.path.dirname(os.path.dirname(__file__))
FIXTURES = os.path.join(ROOT, "swift", "SelfTest", "fixtures.json")


def test_the_fixtures_are_what_python_gives_now(tmp_path):
    spec = importlib.util.spec_from_file_location("make_fixtures", os.path.join(ROOT, "scripts", "make_fixtures.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = str(tmp_path / "fixtures.json")
    module.main()
    with open(module.OUT) as new, open(FIXTURES) as shipped:
        assert json.load(new) == json.load(shipped), "run scripts/make_fixtures.py"


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="no Swift compiler")
def test_swift_matches_python(tmp_path):
    binary = str(tmp_path / "selftest")
    subprocess.run(
        ["swiftc", os.path.join(ROOT, "swift", "HumanStroke.swift"),
         os.path.join(ROOT, "swift", "SelfTest", "main.swift"), "-o", binary],
        check=True,
    )
    done = subprocess.run([binary, DEFAULT_LIBRARY, FIXTURES], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("ok: 36 paths")
