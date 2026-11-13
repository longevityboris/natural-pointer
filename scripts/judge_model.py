"""Does boris.pth add anything over stroke replay? Measure it.

    python scripts/judge_model.py      # writes docs/model.png and docs/model.json

Needs torch, numpy and matplotlib.
"""

import json
import math
import os
import random

import numpy as np
import torch

from analyze import AQUA, BLUE, DOCS, INK, ROOT, SECOND, plt
from natural_pointer import strokes as S
from natural_pointer.models.neural_network import MouseMovementNN
from natural_pointer.utils.simulator import MouseSimulator

W, H = S.RECORDED_SCREEN


def features(points):
    out = []
    for p in points:
        out += [p["x"], p["y"], p["time"] / 1000.0, p["vx"], p["vy"], 1.0 if p["type"] == "click" else 0.0]
    return out


def next_point_test(model, events):
    """Guess the next report from the last five, on the data the model was trained on."""
    rows, truth, last, before = [], [], [], []
    for i in range(len(events) - 5):
        window = events[i:i + 6]
        if any(e["type"] != "move" for e in window) or any(e["time"] > 100 for e in window[1:]):
            continue   # inside a movement only: no clicks, scrolls or stops
        rows.append(features(window[:5]))
        truth.append([window[5]["x"] * W, window[5]["y"] * H, window[5]["time"] / 1000.0])
        last.append([window[4]["x"] * W, window[4]["y"] * H])
        before.append([window[3]["x"] * W, window[3]["y"] * H])
    with torch.no_grad():
        guess = model(torch.tensor(rows, dtype=torch.float32)).numpy()
    truth, last, before = np.array(truth), np.array(last), np.array(before)
    guess_pt = guess[:, :2] * [W, H]

    def miss(xy):
        d = np.hypot(*(xy - truth[:, :2]).T)
        return {"median_pt": round(float(np.median(d)), 2), "mean_pt": round(float(d.mean()), 2)}

    step = np.hypot(*(truth[:, :2] - last).T)
    return {
        "windows": len(rows),
        "true_step_median_pt": round(float(np.median(step)), 2),
        "position_error": {
            "boris.pth": miss(guess_pt),
            "stay where it is": miss(last),
            "repeat the last step": miss(2 * last - before),
        },
        "interval_error_ms": {
            "boris.pth": round(float(np.median(np.abs(guess[:, 2] - truth[:, 2]))) * 1000, 2),
            "always 8 ms": round(float(np.median(np.abs(0.008 - truth[:, 2]))) * 1000, 2),
        },
        "intervals_guessed_zero_or_negative": round(float((guess[:, 2] <= 0).mean()), 3),
    }


def simulator(model):
    sim = MouseSimulator.__new__(MouseSimulator)   # skip __init__: no pyautogui, no screen
    sim.screen_width, sim.screen_height, sim.model, sim.model_loaded = W, H, model, True
    return sim


def shape(t, x, y):
    """What a watcher would notice: how long, how jumpy, when it gets there."""
    t, x, y = np.array(t), np.array(x), np.array(y)
    dist = math.hypot(x[-1] - x[0], y[-1] - y[0])
    steps = np.hypot(np.diff(x), np.diff(y))
    togo = np.hypot(x - x[-1], y - y[-1])
    near = np.argmax(togo <= 0.1 * dist)           # first report within a tenth of the distance
    return {
        "duration": t[-1],
        "reports": len(t),
        "largest_step": steps.max() / dist,
        "last_step": steps[-1] / dist,
        "arrives": t[near] / t[-1] if t[-1] > 0 else 0,
        "backward_time": float((np.diff(t) <= 0).mean()),
    }


def rollouts(model, raw, seed):
    random.seed(seed)
    sim, out = simulator(model), []
    for s in raw:
        path = sim.generate_path(s.x[0], s.y[0], s.x[-1], s.y[-1])
        t = np.cumsum([p["time"] / 1000.0 for p in path])
        out.append((t - t[0], [p["x"] for p in path], [p["y"] for p in path]))
    return out


def summary(paths):
    rows = [shape(*p) for p in paths]
    return {k: round(float(np.median([r[k] for r in rows])), 3) for k in rows[0]}


def figure(raw, trained):
    # a mid-length single move that runs on a slant, so the panel has some height
    pick = next(i for i, s in enumerate(raw) if 300 < s.chord < 700 and s.parts == 1 and 0.2 < s.duration < 0.6
                and 0.45 < abs(s.y[-1] - s.y[0]) / max(abs(s.x[-1] - s.x[0]), 1e-9) < 1.5)
    s = raw[pick]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4))
    left.plot(s.x, s.y, color=BLUE)
    right.plot(s.t, 1 - np.hypot(np.array(s.x) - s.x[-1], np.array(s.y) - s.y[-1]) / s.chord, color=BLUE)
    for k in range(3):
        random.seed(100 + k)
        path = simulator(trained).generate_path(s.x[0], s.y[0], s.x[-1], s.y[-1])
        t = np.cumsum([p["time"] / 1000.0 for p in path])
        x, y = np.array([p["x"] for p in path]), np.array([p["y"] for p in path])
        left.plot(x, y, "-o", color=AQUA, lw=1.2, ms=3.5, alpha=0.9)
        right.plot(t - t[0], 1 - np.hypot(x - s.x[-1], y - s.y[-1]) / s.chord, "-o", color=AQUA, lw=1.2, ms=3.5, alpha=0.9)
    left.plot([s.x[0], s.x[-1]], [s.y[0], s.y[-1]], "o", color=INK, ms=5)
    left.set_aspect("equal")
    left.invert_yaxis()
    left.margins(0.12)
    left.annotate("the recorded stroke", (s.x[len(s.x) // 2], s.y[len(s.y) // 2]), (0.04, 0.5),
                  textcoords="axes fraction", color=SECOND, arrowprops={"arrowstyle": "-", "color": BLUE})
    left.annotate("boris.pth, three tries", (x[5], y[5]), (0.55, 0.5),
                  textcoords="axes fraction", color=SECOND, arrowprops={"arrowstyle": "-", "color": AQUA})
    left.set_title(f"The same {s.chord:.0f}-point move")
    left.set_xlabel("x (points)")
    left.set_ylabel("y (points)")
    right.annotate("the recorded stroke", (s.t[len(s.t) // 2], 0.6), (0.55, 0.45), textcoords="axes fraction",
                   color=SECOND, arrowprops={"arrowstyle": "-", "color": BLUE})
    right.annotate("boris.pth: there in a few jumps,\nthen waits, then snaps on", (0.05, 0.86), (0.25, 0.12),
                   textcoords="axes fraction", color=SECOND)
    right.set_title("Share of the way covered, against time")
    right.set_xlabel("time (s)")
    right.set_ylabel("share of the distance covered")
    fig.tight_layout()
    fig.savefig(os.path.join(DOCS, "model.png"))
    plt.close(fig)


def main():
    with open(os.path.join(ROOT, "mouse_data.json")) as f:
        events = json.load(f)
    trained = MouseMovementNN()
    trained.load_state_dict(torch.load(os.path.join(ROOT, "boris.pth")))
    trained.eval()
    torch.manual_seed(0)
    untrained = MouseMovementNN().eval()

    raw = S.clean(S.segment(events))
    with_trained, with_untrained = rollouts(trained, raw, 1), rollouts(untrained, raw, 1)
    # same random draws, different weights: how far apart do the two paths end up?
    apart = [
        float(np.mean(np.hypot(np.array(a[1]) - np.array(b[1]), np.array(a[2]) - np.array(b[2]))) / s.chord)
        for a, b, s in zip(with_trained, with_untrained, raw) if len(a[1]) == len(b[1])
    ]
    result = {
        "next_point": next_point_test(trained, events),
        "paths": {
            "recorded strokes": summary([(s.t, s.x, s.y) for s in raw]),
            "boris.pth": summary(with_trained),
            "the same code with untrained weights": summary(with_untrained),
        },
        "trained_vs_untrained_mean_gap_share_of_distance": round(float(np.median(apart)), 3),
    }
    figure(raw, trained)
    with open(os.path.join(DOCS, "model.json"), "w") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
