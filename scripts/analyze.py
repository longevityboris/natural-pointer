"""Measure the recorded strokes and draw the README figures.

    python scripts/analyze.py          # writes docs/*.png and docs/stats.json

Needs numpy and matplotlib (the dev group).
"""

import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from natural_pointer import strokes as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# One look for every figure: recorded strokes blue, the minimum-jerk glide orange,
# the network aqua; ink and grid recede.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, SECOND, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "text.color": INK, "axes.labelcolor": SECOND, "axes.edgecolor": AXIS,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": SECOND, "ytick.labelcolor": SECOND,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "lines.linewidth": 2, "figure.dpi": 100, "savefig.dpi": 160,
})


def even(s, dt=S.REPORT):
    """A stroke on an even time grid: t, a, b."""
    n = max(2, int(round(s.duration / dt)) + 1)
    t = np.arange(n) * dt
    return t, np.interp(t, s.t, s.a), np.interp(t, s.t, s.b)


def glide(dist, duration, bow=0.06, dt=S.REPORT):
    """The minimum-jerk path with a sine bow that the presser used: t, a, b."""
    n = max(2, int(round(duration / dt)) + 1)
    u = np.arange(n) / (n - 1)
    s = 10 * u**3 - 15 * u**4 + 6 * u**5
    return u * duration, dist * s, np.round(dist * bow * np.sin(np.pi * s), 1)


def welch(series, n=32):
    """Mean power spectrum of many short series: frequencies (Hz), power."""
    window = np.hanning(n)
    total, count = np.zeros(n // 2 + 1), 0
    for x in series:
        for i in range(0, len(x) - n + 1, n // 2):
            seg = x[i:i + n]
            total += np.abs(np.fft.rfft((seg - seg.mean()) * window)) ** 2
            count += 1
    freqs = np.fft.rfftfreq(n, S.REPORT)
    return freqs, total / max(count, 1) / (window ** 2).sum() * 2 * S.REPORT


def pct(values, qs=(10, 25, 50, 75, 90)):
    return [round(float(v), 4) for v in np.percentile(values, qs)]


def measure(events, lib):
    strokes = lib.strokes
    raw = S.segment(events)
    dist = np.array([s.dist for s in strokes])
    dur = np.array([s.duration for s in strokes])
    peak = np.array([s.meta["peak"] for s in strokes])
    over = np.array([s.meta["over"] for s in strokes])
    subs = np.array([s.meta["subs"] for s in strokes])
    bow = np.array([s.meta["bow"] for s in strokes])
    gaps = [max(b - a for a, b in zip(s.t, s.t[1:])) for s in strokes]

    power = np.polyfit(np.log(dist), np.log(peak), 1)
    r2_power = float(np.corrcoef(np.log(dist), np.log(peak))[0, 1] ** 2)

    # sideways tremor: what is left of b after a smooth trend (5-report mean) is taken out
    wobble = []
    for s in strokes:
        _, _, b = even(s)
        if len(b) >= 9:
            wobble.append(np.sqrt(np.mean((b - np.convolve(b, np.ones(5) / 5, "same"))[2:-2] ** 2)))

    # clicks: how long the button is held when the pointer stays put
    holds, down = [], None
    for e in events:
        if e["type"] == "click":
            if e["pressed"]:
                down = e
            elif down is not None:
                moved = math.hypot((e["x"] - down["x"]) * lib.screen[0], (e["y"] - down["y"]) * lib.screen[1])
                if moved < 3:
                    holds.append(e["rel_time"] - down["rel_time"])
                down = None

    # rests between one stroke and the next (sessions and long breaks left out)
    rests = [b.start_time - (a.start_time + a.duration) for a, b in zip(raw, raw[1:])]
    rests = [r for r in rests if 0 < r < 5]

    moves = sum(1 for e in events if e["type"] == "move")
    return {
        "recording": {"events": len(events), "moves": moves, "seconds": round(events[-1]["rel_time"], 1),
                      "screen": list(lib.screen)},
        "strokes": {"cut": len(raw), "kept": len(strokes), "samples_kept": int(sum(len(s.t) for s in strokes)),
                    "ended_in_click": int(sum(s.meta["clicked"] for s in strokes)),
                    "with_correction_after_a_stop": int(sum(s.meta["parts"] > 1 for s in strokes))},
        "distance_pt": pct(dist), "duration_s": pct(dur), "peak_speed_pt_s": pct(peak),
        "duration_fit": lib.fit,
        "peak_speed_power_law": {"exponent": round(float(power[0]), 3), "r2": round(r2_power, 3)},
        "time_of_peak_speed": pct([s.meta["peak_at"] for s in strokes]),
        "straightness": pct([s.meta["straight"] for s in strokes]),
        "bow_abs": pct(np.abs(bow)), "bow_left_share": round(float((bow < 0).mean()), 3),
        "overshoot": {"share": round(float((over > 2).mean()), 3), "pt": pct(over[over > 2])},
        "submovements": {str(k): int((subs == k).sum()) for k in sorted(set(subs))},
        "hesitation_share": round(float(np.mean([g >= 0.03 for g in gaps])), 3),
        "sideways_tremor_pt_rms": pct(wobble),
        "dwell_before_click_s": pct([s.dwell for s in strokes if s.dwell is not None]),
        "click_hold_s": pct(holds),
        "rest_between_strokes_s": pct(rests),
    }


def figure_strokes(lib):
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.25, 1]})
    for s in lib.strokes:
        left.plot(np.array(s.a) / s.dist, np.array(s.b) / s.dist, color=BLUE, lw=0.7, alpha=0.35)
    left.plot([0, 1], [0, 0], "o", color=INK, ms=5)
    left.annotate("start", (0, 0), (-6, -14), textcoords="offset points", ha="right", color=SECOND)
    left.annotate("end", (1, 0), (6, -14), textcoords="offset points", color=SECOND)
    left.set_aspect("equal")
    left.set_xlim(-0.12, 1.34)
    left.set_ylim(0.28, -0.28)
    left.set_title(f"All {len(lib.strokes)} strokes, each turned onto start -> end")
    left.set_xlabel("along start -> end (share of the distance)")
    left.set_ylabel("across (share of the distance)")

    hand = S.StrokeLibrary.load(seed=5)
    start, end = (240.0, 620.0), (1180.0, 260.0)
    for _ in range(7):
        path = hand.path(start, end)
        right.plot([p[1] for p in path], [p[2] for p in path], color=BLUE, lw=1.1, alpha=0.8)
    dx, dy = end[0] - start[0], end[1] - start[1]
    d = math.hypot(dx, dy)
    _, a, b = glide(d, 0.5, bow=0.06)
    gx, gy = start[0] + a * dx / d - b * dy / d, start[1] + a * dy / d + b * dx / d
    right.plot(gx, gy, color=ORANGE)
    right.plot([start[0], end[0]], [start[1], end[1]], "o", color=INK, ms=5)
    right.annotate("minimum-jerk glide", (gx[len(gx) // 2], gy[len(gy) // 2]), (0.62, 0.12),
                   textcoords="axes fraction", color=SECOND, arrowprops={"arrowstyle": "-", "color": ORANGE})
    right.annotate("7 replayed strokes", (path[len(path) // 3][1], path[len(path) // 3][2]), (0.05, 0.9),
                   textcoords="axes fraction", color=SECOND, arrowprops={"arrowstyle": "-", "color": BLUE})
    right.set_aspect("equal")
    right.invert_yaxis()
    right.set_title("One request, answered seven times")
    right.set_xlabel("x (points)")
    right.set_ylabel("y (points)")
    fig.tight_layout()
    fig.savefig(os.path.join(DOCS, "strokes.png"))
    plt.close(fig)


def figure_distance(lib, stats):
    dist = np.array([s.dist for s in lib.strokes])
    dur = np.array([s.duration for s in lib.strokes])
    peak = np.array([s.meta["peak"] for s in lib.strokes])
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4))
    xs = np.geomspace(dist.min(), dist.max(), 100)

    left.scatter(dist, dur, s=14, color=BLUE, alpha=0.55, lw=0)
    fit = lib.fit
    left.plot(xs, fit["a"] + fit["b"] * np.log2(1 + xs), color=INK, lw=1.5)
    left.annotate(f"{fit['a']:.3f} + {fit['b']:.3f} log2(1 + d),  R² = {fit['r2']:.2f}",
                  (xs[30], fit["a"] + fit["b"] * math.log2(1 + xs[30])), (0.04, 0.72), textcoords="axes fraction",
                  color=SECOND, arrowprops={"arrowstyle": "-", "color": AXIS})
    left.set_xscale("log")
    left.set_title("Time barely depends on distance")
    left.set_xlabel("distance (points)")
    left.set_ylabel("duration (s)")

    right.scatter(dist, peak, s=14, color=BLUE, alpha=0.55, lw=0)
    p = stats["peak_speed_power_law"]
    k = math.exp(np.mean(np.log(peak) - p["exponent"] * np.log(dist)))
    right.plot(xs, k * xs ** p["exponent"], color=INK, lw=1.5)
    right.annotate(f"speed ∝ distance^{p['exponent']:.2f},  R² = {p['r2']:.2f}", (xs[45], k * xs[45] ** p["exponent"]),
                   (0.45, 0.14), textcoords="axes fraction", color=SECOND, arrowprops={"arrowstyle": "-", "color": AXIS})
    right.set_xscale("log")
    right.set_yscale("log")
    right.set_title("Peak speed grows in step with distance")
    right.set_xlabel("distance (points)")
    right.set_ylabel("peak speed (points/s)")
    fig.tight_layout()
    fig.savefig(os.path.join(DOCS, "distance.png"))
    plt.close(fig)


def figure_speed(lib):
    grid = np.linspace(0, 1, 101)
    shapes = []
    for s in lib.strokes:
        v = np.array(S.speed_profile(s))
        shapes.append(np.interp(grid, np.linspace(0, 1, len(v)), v / v.max()))
    shapes = np.array(shapes)
    lo, mid, hi = np.percentile(shapes, [25, 50, 75], axis=0)

    fig = plt.figure(figsize=(11, 4.4))
    spec = fig.add_gridspec(3, 2, width_ratios=[1.15, 1])
    left = fig.add_subplot(spec[:, 0])
    left.fill_between(grid, lo, hi, color=BLUE, alpha=0.2, lw=0)
    left.plot(grid, mid, color=BLUE)
    jerk = 30 * grid**2 * (1 - grid) ** 2 / 1.875
    left.plot(grid, jerk, color=ORANGE)
    left.annotate("minimum jerk", (0.62, jerk[62]), (26, 14), textcoords="offset points", color=SECOND)
    left.annotate("recorded: median,\nmiddle half shaded", (0.2, mid[20]), (-8, 40), textcoords="offset points",
                  ha="center", color=SECOND, arrowprops={"arrowstyle": "-", "color": BLUE})
    left.set_title("The hand peaks early and trails off; the curve is a symmetric bell")
    left.set_xlabel("share of the stroke's time")
    left.set_ylabel("speed (share of its peak)")
    left.set_ylim(0, 1.05)

    # three single strokes: a clean one, one with a correction after a stop, one that overshoots
    def first(test):
        return next(s for s in lib.strokes if 250 < s.dist < 700 and test(s))
    picks = [
        ("one clean move", first(lambda s: s.meta["subs"] == 1 and s.meta["parts"] == 1 and s.meta["over"] == 0)),
        ("a stop, then a correction", first(lambda s: s.meta["parts"] > 1)),
        ("overshoot and return", first(lambda s: s.meta["over"] > 12 and s.meta["parts"] == 1)),
    ]
    for row, (label, s) in enumerate(picks):
        ax = fig.add_subplot(spec[row, 1])
        v = S.speed_profile(s)
        ax.plot(np.linspace(0, s.duration, len(v)), v, color=BLUE, lw=1.5)
        ax.set_ylim(0, None)
        ax.text(0.99, 0.82, f"{label} ({s.dist:.0f} points)", transform=ax.transAxes, ha="right", color=SECOND)
        if row == 0:
            ax.set_title("Three recorded strokes")
        if row == 1:
            ax.set_ylabel("speed (points/s)")
        if row == 2:
            ax.set_xlabel("time (s)")
    fig.tight_layout()
    fig.savefig(os.path.join(DOCS, "speed.png"))
    plt.close(fig)


def sideways_speed(t, b):
    return np.diff(b) / np.diff(t)


def figure_tremor(lib, extra=None):
    """Spectrum of the sideways speed. ``extra`` adds a (label, colour, series) line."""
    long = [s for s in lib.strokes if s.duration >= 0.3]
    hand, curve = [], []
    for s in long:
        t, _, b = even(s)
        hand.append(sideways_speed(t, b))
        t, _, b = glide(s.dist, s.duration)
        curve.append(sideways_speed(t, b))
    fig, ax = plt.subplots(figsize=(7.5, 4))
    f, p_hand = welch(hand)
    _, p_curve = welch(curve)
    ax.plot(f[1:], p_hand[1:], color=BLUE)
    ax.plot(f[1:], p_curve[1:], color=ORANGE)
    ax.annotate("recorded strokes", (f[5], p_hand[5]), (12, 10), textcoords="offset points", color=SECOND)
    ax.annotate("minimum-jerk glide", (f[9], p_curve[9]), (0, 12), textcoords="offset points", color=SECOND)
    if extra:
        label, colour, series = extra
        _, p_extra = welch(series)
        ax.plot(f[1:], p_extra[1:], color=colour)
        ax.annotate(label, (f[11], p_extra[11]), (10, 10), textcoords="offset points", color=SECOND)
    ax.set_yscale("log")
    ax.set_xlim(0, 62.5)
    ax.set_title("Above 10 Hz the hand still wobbles sideways; the curve is silent")
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("power of sideways speed ((points/s)²/Hz)")
    fig.tight_layout()
    fig.savefig(os.path.join(DOCS, "tremor.png"))
    plt.close(fig)
    band = (f >= 8) & (f <= 40)
    return {"hand_over_glide_8_40_hz": round(float(p_hand[band].sum() / max(p_curve[band].sum(), 1e-12)), 1),
            "strokes": len(long)}


def main():
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(ROOT, "mouse_data.json")) as f:
        events = json.load(f)
    lib = S.StrokeLibrary.load(seed=1)
    stats = measure(events, lib)
    figure_strokes(lib)
    figure_distance(lib, stats)
    figure_speed(lib)
    stats["tremor_spectrum"] = figure_tremor(lib)
    with open(os.path.join(DOCS, "stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
        f.write("\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
