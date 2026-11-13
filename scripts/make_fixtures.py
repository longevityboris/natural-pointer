"""Write swift/SelfTest/fixtures.json: paths from the Python package for fixed seeds.

The Swift self-test replays the same calls and must get the same numbers.

    python scripts/make_fixtures.py
"""

import json
import os

from natural_pointer.strokes import StrokeLibrary, position_at

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "swift", "SelfTest", "fixtures.json")

# (start, end, screen): long, short, every direction, repeats of one request
# (the recent-stroke rule), a path squeezed by a small screen, and no move at all.
CALLS = [
    ((100, 100), (900, 500), None),
    ((900, 500), (880, 512), None),
    ((880, 512), (300, 900), (1800, 1169)),
    ((300, 900), (300, 200), None),
    ((640.5, 360.25), (1200.75, 380.5), (1280, 720)),
    ((640.5, 360.25), (1200.75, 380.5), (1280, 720)),
    ((640.5, 360.25), (1200.75, 380.5), (1280, 720)),
    "dwell",
    ((5, 400), (795, 3), (800, 600)),
    ((2000, 1200), (20, 30), (2560, 1440)),
    ((50, 50), (50, 50), None),
    ((50, 50), (50.2, 50), None),
    ((50, 50), (56, 47), None),
    "dwell",
]


def main():
    cases = []
    for seed in (1, 20261113, 2**64 - 1):
        lib = StrokeLibrary.load(seed=seed)
        calls = []
        for call in CALLS:
            if call == "dwell":
                calls.append({"dwell": lib.dwell()})
                continue
            start, end, screen = call
            before = list(lib.recent)
            path = lib.path(start, end, screen)
            total = path[-1][0]
            probes = [-0.01, 0.0, total * 0.137, total * 0.5, total * 0.912, total, total + 1]
            calls.append({
                "start": list(start), "end": list(end), "screen": list(screen) if screen else None,
                "stroke": lib.recent[-1] if lib.recent != before else -1,
                "t": [p[0] for p in path], "x": [p[1] for p in path], "y": [p[2] for p in path],
                "at": [[w, *position_at(path, w)] for w in probes],
            })
        cases.append({"seed": seed, "calls": calls})
    with open(OUT, "w") as f:
        json.dump({"tolerance": 1e-9, "cases": cases}, f, separators=(",", ":"))
        f.write("\n")
    print(f"{sum(len(c['calls']) for c in cases)} calls -> {OUT} ({os.path.getsize(OUT) // 1024} kB)")


if __name__ == "__main__":
    main()
