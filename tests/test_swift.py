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


GUARDS = '''
import Foundation
func check(_ ok: Bool, _ what: String) { if !ok { print("FAIL: " + what); exit(1) } }
let good = #"{"id":0,"angle":0,"t":[0,1000,2000],"a":[0,500,1000],"b":[0,20,0]}"#
func library(_ strokes: String) throws -> HumanStrokeLibrary {
    try HumanStrokeLibrary(data: Data(("{\\"strokes\\":[" + strokes + "]}").utf8), seed: 1)
}
// a file with nothing to replay is refused, not loaded as a teleporter
for bad in ["", #"{"id":0,"angle":0,"t":[0,5000,100],"a":[0,500,1000],"b":[0,20,0]}"#,
            #"{"id":0,"angle":0,"t":[0,1000,2000],"a":[0,500,0],"b":[0,20,0]}"#] {
    check((try? library(bad)) == nil, "loaded a library with no usable stroke")
}
// duplicate ids, a null dwell and a missing fit are all fine
var hand = try library(good + "," + good.replacingOccurrences(of: "\\"angle\\":0", with: "\\"angle\\":0,\\"dwell\\":null"))
for _ in 0..<6 {
    let p = hand.path(from: (0, 0), to: (80, 10))
    check(p.x.last == 80 && p.y.last == 10 && p.t.allSatisfy { $0.isFinite }, "twin strokes")
}
// places that are not numbers give a plain jump, never a path of NaN
for bad in [Double.nan, Double.infinity, 1e200] {
    let p = hand.path(from: (bad, 100), to: (500, 500))
    check(p.t == [0, 0] && p.x.last == 500 && p.y.last == 500, "non-finite start")
}
// a jump is over at once; a time that is not a number reads as the end
let jump = hand.path(from: (5, 5), to: (5.2, 5))
check(jump.position(at: 0).x == 5.2, "jump at 0")
let path = hand.path(from: (0, 0), to: (300, 200))
check(path.position(at: .nan).x == 300 && path.position(at: path.duration).y == 200, "end of path")
check(path.position(at: -1).x == 0 && path.position(at: 0).y == 0, "start of path")
print("ok")
'''


@pytest.mark.skipif(shutil.which("swiftc") is None, reason="no Swift compiler")
def test_swift_guards_against_bad_input(tmp_path):
    main = tmp_path / "main.swift"
    main.write_text(GUARDS)
    binary = str(tmp_path / "guards")
    subprocess.run(["swiftc", os.path.join(ROOT, "swift", "HumanStroke.swift"), str(main), "-o", binary], check=True)
    done = subprocess.run([binary], capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stdout + done.stderr


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
    assert done.stdout.startswith("ok: 45 paths")
