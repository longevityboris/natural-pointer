"""
Stroke replay: move the pointer the way the recorded hand moved it.

A recording (``mouse_data.json``) is cut into strokes: one aimed movement from
rest to rest, with its hesitations, overshoot and small corrections kept. Each
stroke is stored in its own frame (start at the origin, end on the +x axis), so
it can be turned and scaled onto any new start -> end while its timing and
tremor stay as recorded.

This module uses the standard library only. ``swift/HumanStroke.swift`` is a
line-for-line port of ``StrokeLibrary``: the same library file and the same
seed give the same path in both.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# The screen mouse_data.json was recorded on, in points. The recorder stores
# positions as fractions of the screen; the finest steps in the file are
# 1/(1800*256) and 1/(1169*256), which fixes the size.
RECORDED_SCREEN = (1800, 1169)

DEFAULT_LIBRARY = os.path.join(os.path.dirname(__file__), "data", "strokes.json")

# --- segmentation ---------------------------------------------------------

GAP = 0.100            # s without a report: the hand has stopped
CORRECTION_GAP = 0.450  # a stop shorter than this may be followed by a correction
CORRECTION_SHARE = 0.35  # ...if that next move is small next to the main one
CORRECTION_MAX = 60.0   # ...and no longer than this many points on its own
REPORT = 0.008         # s between two reports of the recording mouse
STRAIGHT = 0.75        # start -> end distance / path length below this: not one aimed move
NEAR_REST = 40.0       # points/s: under a third of a point a report, the hand has all but stopped


@dataclass
class RawStroke:
    """A stroke as recorded: seconds from its start, points on the screen."""

    t: list[float]
    x: list[float]
    y: list[float]
    start_time: float = 0.0      # s since the recording began
    clicked: bool = False        # a button press ended it
    dwell: Optional[float] = None  # s between the last report and that press
    parts: int = 1               # the main move plus the corrections joined to it

    @property
    def chord(self) -> float:
        return math.hypot(self.x[-1] - self.x[0], self.y[-1] - self.y[0])

    @property
    def duration(self) -> float:
        return self.t[-1] - self.t[0]

    @property
    def path_length(self) -> float:
        return sum(
            math.hypot(self.x[i + 1] - self.x[i], self.y[i + 1] - self.y[i])
            for i in range(len(self.x) - 1)
        )


def _runs(events: Sequence[dict], screen: tuple[float, float]):
    """Cut the events into runs of moves with no stop, click or drag inside.

    Yields (times, xs, ys, clicked, dwell). Each run starts from the resting
    point the hand left, one report before its first move.
    """
    w, h = screen
    run: list[tuple[float, float, float]] = []
    held = False                    # a button is down: moves are a drag
    rest: Optional[tuple[float, float, float]] = None  # last known position

    def close(clicked=False, press_time=None):
        nonlocal run
        if len(run) >= 2:
            dwell = press_time - run[-1][0] if press_time is not None else None
            out = ([p[0] for p in run], [p[1] for p in run], [p[2] for p in run], clicked, dwell)
            run = []
            return out
        run = []
        return None

    for e in events:
        kind = e.get("type")
        now = e["rel_time"]
        px, py = e["x"] * w, e["y"] * h
        if kind == "move":
            if held:
                rest = (now, px, py)
                continue
            if run and now - run[-1][0] >= GAP:
                done = close()
                if done:
                    yield done
            if not run and rest is not None and math.hypot(px - rest[1], py - rest[2]) < 40:
                # the hand was at rest here one report ago
                run.append((now - REPORT, rest[1], rest[2]))
            run.append((now, px, py))
            rest = (now, px, py)
        elif kind == "click":
            if e.get("pressed"):
                done = close(clicked=True, press_time=now)
                held = True
            else:
                done = close()
                held = False
            if done:
                yield done
            rest = (now, px, py)
        # scroll events carry no movement and never fall inside a run
    done = close()
    if done:
        yield done


def segment(
    events: Sequence[dict], screen: tuple[float, float] = RECORDED_SCREEN
) -> list[RawStroke]:
    """Cut recorder events into strokes, in points on ``screen``.

    A stroke runs from rest to rest. A stop of under ``CORRECTION_GAP`` followed
    by a small move is a correction and stays in the stroke, since landing on a
    target is one act; a longer stop, a click or a large second move starts a
    new stroke. Drags (moves with a button held) are left out.
    """
    strokes: list[RawStroke] = []
    last: Optional[RawStroke] = None
    last_end = 0.0
    for t, x, y, clicked, dwell in _runs(events, screen):
        size = math.hypot(x[-1] - x[0], y[-1] - y[0])
        if (
            last is not None
            and not last.clicked
            and t[0] - last_end < CORRECTION_GAP
            and math.hypot(x[0] - last.x[-1], y[0] - last.y[-1]) < 1.0
            and size <= CORRECTION_MAX
            and size <= CORRECTION_SHARE * max(last.chord, 1e-9)
        ):
            t0 = last.start_time
            last.t.extend(v - t0 for v in t[1:])
            last.x.extend(x[1:])
            last.y.extend(y[1:])
            last.clicked, last.dwell = clicked, dwell
            last.parts += 1
        else:
            last = RawStroke([v - t[0] for v in t], list(x), list(y), t[0], clicked, dwell)
            strokes.append(last)
        last_end = t[-1]
    out: list[RawStroke] = []
    for s in strokes:
        if s.chord / max(s.path_length, 1e-9) < STRAIGHT:
            out.extend(_cut_at_rests(s))
        else:
            out.append(s)
    return out


def _cut_at_rests(s: RawStroke) -> list[RawStroke]:
    """Cut a chain of moves made without a clear stop where the hand all but stops.

    Some recorded runs are several moves in a row with no 100 ms stop between
    them. Between two such moves the pointer still slows to under ``NEAR_REST``;
    each piece between two of those points is a stroke of its own.
    """
    n = len(s.t)
    slow = [
        math.hypot(s.x[k + 1] - s.x[k], s.y[k + 1] - s.y[k]) / max(s.t[k + 1] - s.t[k], 1e-4) < NEAR_REST
        for k in range(n - 1)
    ]
    pieces, start, k = [], 0, 0
    while k < n - 1:
        if slow[k]:
            j = k
            while j < n - 1 and slow[j]:
                j += 1
            if k - start >= 4:
                pieces.append((start, k))
            start = max(k, j - 1)
            k = j
        else:
            k += 1
    if n - 1 - start >= 4:
        pieces.append((start, n - 1))
    out = [
        RawStroke([v - s.t[a] for v in s.t[a:b + 1]], s.x[a:b + 1], s.y[a:b + 1], s.start_time + s.t[a])
        for a, b in pieces
    ]
    if out and pieces[-1][1] == n - 1:
        out[-1].clicked, out[-1].dwell = s.clicked, s.dwell
    return out


def clean(strokes: Iterable[RawStroke], screen: tuple[float, float] = RECORDED_SCREEN) -> list[RawStroke]:
    """Keep the strokes that are one aimed movement and safe to retarget."""
    w, h = screen
    kept = []
    for s in strokes:
        chord = s.chord
        if len(s.t) < 5 or chord < 4.0 or not 0.04 <= s.duration <= 3.0:
            continue
        if min(s.y) <= 0.5 or max(s.y) >= h - 1.5 or min(s.x) <= 0.5 or max(s.x) >= w - 1.5:
            continue  # pinned against a screen edge: not the hand's own path
        if chord / s.path_length < STRAIGHT:
            continue  # wandering, not aiming
        a, b = _to_frame(s)
        if min(a) < -0.08 * chord or max(a) > 1.3 * chord or max(abs(v) for v in b) > 0.25 * chord:
            continue  # backs away first, flies far past, or swings wide: odd when aimed elsewhere
        kept.append(s)
    return kept


def _to_frame(s: RawStroke) -> tuple[list[float], list[float]]:
    """The stroke in its own frame: start at (0, 0), end at (chord, 0)."""
    dx, dy = s.x[-1] - s.x[0], s.y[-1] - s.y[0]
    chord = math.hypot(dx, dy)
    cx, cy = dx / chord, dy / chord
    a = [(x - s.x[0]) * cx + (y - s.y[0]) * cy for x, y in zip(s.x, s.y)]
    b = [-(x - s.x[0]) * cy + (y - s.y[0]) * cx for x, y in zip(s.x, s.y)]
    return a, b


# --- the library ----------------------------------------------------------


@dataclass
class Stroke:
    """A stroke in its own frame. ``a`` runs along start -> end, ``b`` across it."""

    id: int
    dist: float        # points from start to end on the recording screen
    angle: float       # direction of start -> end, radians, y down
    t: list[float]     # s from the start
    a: list[float]     # points along the chord: 0 at the start, dist at the end
    b: list[float]     # points across the chord
    dwell: Optional[float] = None  # s it then rested before a click, if a click ended it
    meta: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.t[-1]


def normalise(s: RawStroke, id: int) -> Stroke:
    """Put a raw stroke in its own frame, rounded as the library file stores it."""
    a, b = _to_frame(s)
    dx, dy = s.x[-1] - s.x[0], s.y[-1] - s.y[0]
    stroke = Stroke(
        id=id,
        dist=round(s.chord * 10) / 10,
        angle=round(math.atan2(dy, dx) * 1e4) / 1e4,
        t=[round(v * 1e4) / 1e4 for v in s.t],
        a=[round(v * 10) / 10 for v in a],
        b=[round(v * 10) / 10 for v in b],
        dwell=None if s.dwell is None else round(s.dwell * 1e4) / 1e4,
    )
    stroke.a[0] = stroke.b[0] = stroke.b[-1] = 0.0
    stroke.a[-1] = stroke.dist
    stroke.meta = describe(stroke)
    stroke.meta["clicked"] = s.clicked
    stroke.meta["parts"] = s.parts
    return stroke


def speed_profile(s: Stroke, step: float = REPORT) -> list[float]:
    """Speed in points/s on an even time grid, lightly smoothed."""
    n = max(2, int(round(s.duration / step)) + 1)
    pts = [_at(s.t, s.a, s.b, i * s.duration / (n - 1)) for i in range(n)]
    dt = s.duration / (n - 1)
    raw = [math.hypot(q[0] - p[0], q[1] - p[1]) / dt for p, q in zip(pts, pts[1:])]
    out = []
    for i in range(len(raw)):
        lo, hi = max(0, i - 1), min(len(raw), i + 2)
        out.append(sum(raw[lo:hi]) / (hi - lo))
    return out


def submovements(speed: Sequence[float]) -> int:
    """Count the bursts of speed: the main move and each correction after it."""
    if not speed:
        return 0
    top = max(speed)
    count, peak, valley, rising = 0, 0.0, 0.0, True
    for v in speed:
        if rising:
            if v >= peak:
                peak = v
            elif v < 0.6 * peak and peak > 0.12 * top:
                count += 1
                rising, valley = False, v
        else:
            if v < valley:
                valley = v
            elif v > max(0.12 * top, 1.6 * valley + 1e-9):
                rising, peak = True, v
    if rising and peak > 0.12 * top:
        count += 1
    return max(count, 1)


def describe(s: Stroke) -> dict:
    """The numbers the README reports for each stroke."""
    speed = speed_profile(s)
    peak = max(speed)
    path = sum(
        math.hypot(s.a[i + 1] - s.a[i], s.b[i + 1] - s.b[i]) for i in range(len(s.a) - 1)
    )
    bow = max(s.b, key=abs)
    return {
        "dist": s.dist,                                      # points
        "dur": round(s.duration, 4),                         # s
        "peak": round(peak, 1),                              # points/s
        "peak_at": round(speed.index(peak) / max(1, len(speed) - 1), 3),
        "straight": round(s.dist / path, 4),                 # chord / path length
        "bow": round(bow / s.dist, 4),                       # largest sideways drift / chord
        "over": round(max(0.0, max(s.a) - s.dist), 1),       # points past the target
        "subs": submovements(speed),
    }


def _at(t: Sequence[float], a: Sequence[float], b: Sequence[float], when: float) -> tuple[float, float]:
    """Position at time ``when``, straight between the two nearest samples."""
    if when <= t[0]:
        return a[0], b[0]
    if when >= t[-1]:
        return a[-1], b[-1]
    lo, hi = 0, len(t) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if t[mid] <= when:
            lo = mid
        else:
            hi = mid
    f = (when - t[lo]) / (t[hi] - t[lo]) if t[hi] > t[lo] else 1.0
    return a[lo] + (a[hi] - a[lo]) * f, b[lo] + (b[hi] - b[lo]) * f


class SplitMix64:
    """A small seeded generator, the same in Python and Swift."""

    MASK = (1 << 64) - 1

    def __init__(self, seed: int):
        self.state = seed & self.MASK

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return z ^ (z >> 31)

    def unit(self) -> float:
        """A float in [0, 1)."""
        return (self.next() >> 11) / 9007199254740992.0

    def between(self, lo: float, hi: float) -> float:
        return lo + (hi - lo) * self.unit()


class StrokeLibrary:
    """Recorded strokes, and the retargeting of one onto a new start -> end."""

    CHOICES = 6        # pick among this many best-matching strokes
    RECENT = 4         # ...none of which was among the last this many used
    ANGLE_WEIGHT = 0.5  # a 90 degree turn costs as much as this many e-folds of length

    def __init__(self, strokes: Sequence[Stroke], fit: Optional[dict] = None,
                 screen: tuple[float, float] = RECORDED_SCREEN, seed: Optional[int] = None):
        self.strokes = list(strokes)
        self.fit = fit or {"a": 0.0, "b": 0.0}
        self.screen = tuple(screen)
        if seed is None:
            seed = int.from_bytes(os.urandom(8), "little")
        self.rng = SplitMix64(seed)
        self.recent: list[int] = []

    # -- file format --
    # What a reader needs to replay a stroke is whole numbers, so every reader
    # sees the same values: the chord length is the last ``a``. ``meta`` is
    # there to be read by people and by the analysis.

    def to_json(self) -> dict:
        def one(s: Stroke) -> dict:
            out = {"id": s.id, "angle": round(s.angle * 1e4)}
            if s.dwell is not None:
                out["dwell"] = round(s.dwell * 1e4)
            out["meta"] = s.meta
            out["t"] = [round(v * 1e4) for v in s.t]
            out["a"] = [round(v * 10) for v in s.a]
            out["b"] = [round(v * 10) for v in s.b]
            return out

        return {
            "version": 1,
            "screen": list(self.screen),
            "units": {"t": "1e-4 s", "a": "0.1 pt", "b": "0.1 pt", "angle": "1e-4 rad", "dwell": "1e-4 s"},
            "fit": self.fit,
            "strokes": [one(s) for s in self.strokes],
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_json(), f, separators=(",", ":"))
            f.write("\n")

    @classmethod
    def load(cls, path: Optional[str] = None, seed: Optional[int] = None) -> "StrokeLibrary":
        with open(path or DEFAULT_LIBRARY) as f:
            doc = json.load(f)
        strokes = [
            Stroke(
                id=s["id"],
                dist=s["a"][-1] / 10,
                angle=s["angle"] / 1e4,
                t=[v / 1e4 for v in s["t"]],
                a=[v / 10 for v in s["a"]],
                b=[v / 10 for v in s["b"]],
                dwell=s["dwell"] / 1e4 if "dwell" in s else None,
                meta=s.get("meta", {}),
            )
            for s in doc["strokes"]
        ]
        return cls(strokes, doc.get("fit"), tuple(doc.get("screen", RECORDED_SCREEN)), seed)

    # -- retargeting --

    def expected_duration(self, dist: float) -> float:
        """The fitted time for a move of ``dist`` points: a + b*log2(1 + dist)."""
        return max(0.05, self.fit["a"] + self.fit["b"] * math.log2(1.0 + dist))

    def choose(self, dist: float, angle: float) -> Stroke:
        """A recorded stroke of about this length and direction, not used lately."""
        scored = []
        for i, s in enumerate(self.strokes):
            turn = abs(math.remainder(angle - s.angle, 2 * math.pi))
            cost = abs(math.log(dist / s.dist)) + self.ANGLE_WEIGHT * turn / (math.pi / 2)
            scored.append((cost, i))
        scored.sort()
        pool = [i for _, i in scored if self.strokes[i].id not in self.recent][: self.CHOICES]
        stroke = self.strokes[pool[int(self.rng.unit() * len(pool))]]
        # never the same stroke twice running, nor any of the last few;
        # always leave at least one stroke to choose from
        self.recent.append(stroke.id)
        keep = min(self.RECENT, len(self.strokes) - 1)
        self.recent = self.recent[max(0, len(self.recent) - keep):]
        return stroke

    def dwell(self) -> float:
        """Seconds to rest on the target before pressing: one of the recorded waits."""
        waits = [s.dwell for s in self.strokes if s.dwell is not None]
        if not waits:
            return 0.05
        return waits[int(self.rng.unit() * len(waits))]

    def path(self, start: Sequence[float], end: Sequence[float],
             screen: Optional[Sequence[float]] = None) -> list[tuple[float, float, float]]:
        """A timed path from ``start`` to ``end`` (points): a list of (t, x, y).

        ``t`` is seconds from the start of the move. The first point is
        ``start`` at t = 0 and the last is exactly ``end``. With ``screen``
        (width, height) the path is kept on the screen, as a real pointer is.
        """
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        dx, dy = ex - sx, ey - sy
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.5 or not self.strokes:
            return [(0.0, sx, sy), (0.0, ex, ey)] if dist > 0 else [(0.0, sx, sy)]
        stroke = self.choose(dist, math.atan2(dy, dx))

        # Variety that stays inside what the hand does: a few percent on the
        # pace, a slight shift of where the speed peaks, a little more or less bow.
        pace = self.rng.between(0.93, 1.09)
        lean = self.rng.between(-0.10, 0.10)
        bow = self.rng.between(0.85, 1.15)

        scale = dist / stroke.dist
        # A longer or shorter reach than the recorded one takes the time the
        # hand's own distance/time law says, not a plain multiple.
        base = self.expected_duration(stroke.dist)
        stretch = self.expected_duration(dist) / base if base > 0 else 1.0
        stretch = min(2.0, max(0.5, stretch)) * pace
        total = stroke.duration
        cx, cy = dx / dist, dy / dist

        out = []
        for i in range(len(stroke.t)):
            u = stroke.t[i] / total
            when = total * stretch * (u + lean * math.sin(2 * math.pi * u) / (2 * math.pi))
            a = stroke.a[i] * scale
            b = stroke.b[i] * scale * bow
            x = sx + a * cx - b * cy
            y = sy + a * cy + b * cx
            if screen is not None:
                x = min(max(x, 0.0), float(screen[0]) - 1.0)
                y = min(max(y, 0.0), float(screen[1]) - 1.0)
            out.append((when, x, y))
        out[0] = (0.0, sx, sy)
        out[-1] = (out[-1][0], ex, ey)
        return out


def position_at(path: Sequence[tuple[float, float, float]], when: float) -> tuple[float, float]:
    """Where the pointer is ``when`` seconds into a path from ``StrokeLibrary.path``."""
    return _at([p[0] for p in path], [p[1] for p in path], [p[2] for p in path], when)


def build_library(events: Sequence[dict], screen: tuple[float, float] = RECORDED_SCREEN) -> StrokeLibrary:
    """Segment, clean and normalise a recording into a library."""
    raw = clean(segment(events, screen), screen)
    strokes = [normalise(s, i) for i, s in enumerate(raw)]
    return StrokeLibrary(strokes, fit_duration(strokes), screen)


def fit_duration(strokes: Sequence[Stroke]) -> dict:
    """Least squares for duration = a + b*log2(1 + dist), with its R squared."""
    xs = [math.log2(1.0 + s.dist) for s in strokes]
    ys = [s.duration for s in strokes]
    n = len(xs)
    if n < 2:
        return {"a": 0.0, "b": 0.0, "r2": 0.0}
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx if sxx else 0.0
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return {"a": round(a, 5), "b": round(b, 5), "r2": round(1 - ss_res / ss_tot, 4) if ss_tot else 0.0}


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Build a stroke library from a recording: ``python -m natural_pointer``."""
    import argparse

    parser = argparse.ArgumentParser(description="Build a stroke library from a recording.")
    parser.add_argument("recording", nargs="?", default="mouse_data.json",
                        help="events from recorder.py (default: mouse_data.json)")
    parser.add_argument("-o", "--output", default=DEFAULT_LIBRARY,
                        help="library file to write (default: the one the package loads)")
    parser.add_argument("--screen", nargs=2, type=float, default=RECORDED_SCREEN,
                        metavar=("WIDTH", "HEIGHT"),
                        help="size in points of the screen the recording was made on")
    args = parser.parse_args(argv)
    with open(args.recording) as f:
        events = json.load(f)
    library = build_library(events, tuple(args.screen))
    library.save(args.output)
    print(f"{len(library.strokes)} strokes -> {args.output} ({os.path.getsize(args.output) // 1024} kB)")
