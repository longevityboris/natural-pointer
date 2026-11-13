"""Cutting a recording into strokes."""

import json
import math
import os

import pytest

from natural_pointer import strokes as S

SCREEN = (1000, 1000)
ROOT = os.path.dirname(os.path.dirname(__file__))


def move(t, x, y):
    return {"type": "move", "x": x / SCREEN[0], "y": y / SCREEN[1], "rel_time": t}


def click(t, x, y, pressed):
    return {"type": "click", "x": x / SCREEN[0], "y": y / SCREEN[1], "rel_time": t,
            "pressed": pressed, "button": "Button.left"}


def reach(t0, x0, y0, x1, y1, n=30, dt=0.008):
    """A smooth move from (x0, y0) to (x1, y1) starting just after t0."""
    out = []
    for i in range(1, n + 1):
        u = i / n
        s = 10 * u**3 - 15 * u**4 + 6 * u**5
        out.append(move(t0 + i * dt, x0 + (x1 - x0) * s, y0 + (y1 - y0) * s))
    return out


def test_a_long_stop_separates_two_strokes():
    events = [move(0.0, 100, 100)] + reach(1.0, 100, 100, 500, 100) + reach(3.0, 500, 100, 500, 600)
    found = S.segment(events, SCREEN)
    assert len(found) == 2
    first, second = found
    assert (first.x[0], first.y[0]) == pytest.approx((100, 100))
    assert (first.x[-1], first.y[-1]) == pytest.approx((500, 100))
    assert (second.x[-1], second.y[-1]) == pytest.approx((500, 600))
    assert first.t[0] == 0 and first.duration == pytest.approx(30 * 0.008)


def test_a_stroke_starts_from_the_resting_point():
    events = [move(0.0, 100, 100)] + reach(1.0, 100, 100, 500, 100)
    (stroke,) = S.segment(events, SCREEN)
    # the first report already shows movement; the stroke begins one report earlier, at rest
    assert stroke.x[0] == pytest.approx(100)
    assert stroke.t[1] - stroke.t[0] == pytest.approx(S.REPORT)


def test_a_small_move_after_a_short_stop_is_a_correction():
    main = reach(1.0, 100, 100, 500, 100)
    end = main[-1]["rel_time"]
    fix = reach(end + 0.2, 500, 100, 512, 104, n=8)
    (stroke,) = S.segment([move(0.0, 100, 100)] + main + fix, SCREEN)
    assert stroke.parts == 2
    assert (stroke.x[-1], stroke.y[-1]) == pytest.approx((512, 104))
    assert max(b - a for a, b in zip(stroke.t, stroke.t[1:])) == pytest.approx(0.2 + 0.008)


def test_a_large_move_after_a_short_stop_is_a_new_stroke():
    main = reach(1.0, 100, 100, 500, 100)
    end = main[-1]["rel_time"]
    events = [move(0.0, 100, 100)] + main + reach(end + 0.2, 500, 100, 900, 400)
    assert [s.parts for s in S.segment(events, SCREEN)] == [1, 1]


def test_a_click_ends_the_stroke_and_records_the_dwell():
    main = reach(1.0, 100, 100, 500, 100)
    end = main[-1]["rel_time"]
    events = ([move(0.0, 100, 100)] + main + [click(end + 0.07, 500, 100, True), click(end + 0.17, 500, 100, False)]
              + reach(end + 0.2, 500, 100, 510, 100, n=8))
    found = S.segment(events, SCREEN)
    assert len(found) == 2          # the move after the click is not a correction of the first
    assert found[0].clicked and found[0].dwell == pytest.approx(0.07)
    assert not found[1].clicked


def test_moves_with_the_button_held_are_left_out():
    main = reach(1.0, 100, 100, 500, 100)
    end = main[-1]["rel_time"]
    drag = reach(end + 0.1, 500, 100, 800, 300)
    events = ([move(0.0, 100, 100)] + main + [click(end + 0.05, 500, 100, True)] + drag
              + [click(drag[-1]["rel_time"] + 0.05, 800, 300, False)])
    found = S.segment(events, SCREEN)
    assert len(found) == 1 and found[0].x[-1] == pytest.approx(500)


def test_a_chain_without_a_stop_is_cut_where_the_hand_all_but_stops():
    # out and most of the way back with no 100 ms stop: two moves, not one
    out = reach(1.0, 100, 100, 500, 100)
    back = reach(out[-1]["rel_time"], 500, 100, 150, 100)
    found = S.segment([move(0.0, 100, 100)] + out + back, SCREEN)
    assert len(found) == 2
    assert found[0].x[-1] == pytest.approx(500, abs=1)
    assert found[1].x[-1] == pytest.approx(150, abs=1)


def test_clean_drops_what_cannot_be_retargeted():
    good = S.RawStroke([i * 0.008 for i in range(20)], [100 + 10 * i for i in range(20)], [100.0] * 20)
    tiny = S.RawStroke([i * 0.008 for i in range(20)], [100 + 0.1 * i for i in range(20)], [100.0] * 20)
    edge = S.RawStroke([i * 0.008 for i in range(20)], [100 + 10 * i for i in range(20)], [0.0] * 20)
    loop = S.RawStroke([i * 0.008 for i in range(40)],
                       [300 + 200 * math.cos(i / 39 * 5.5) for i in range(40)],
                       [300 + 200 * math.sin(i / 39 * 5.5) for i in range(40)])
    assert S.clean([good, tiny, edge, loop], SCREEN) == [good]


def test_normalise_puts_the_stroke_on_the_x_axis():
    raw = S.RawStroke([i * 0.008 for i in range(11)], [100 + 30 * i for i in range(11)],
                      [200 + 40 * i + (5 if i == 5 else 0) for i in range(11)])
    s = S.normalise(raw, 0)
    assert s.dist == pytest.approx(500)
    assert s.angle == pytest.approx(math.atan2(4, 3), abs=1e-4)
    assert (s.a[0], s.b[0]) == (0, 0) and (s.a[-1], s.b[-1]) == (500, 0)
    assert s.b[5] == pytest.approx(3.0)      # 5 points down, seen across a 3-4-5 chord
    assert s.meta["straight"] > 0.99 and s.meta["subs"] == 1


def test_submovements_counts_bursts_of_speed():
    bell = [math.sin(math.pi * i / 20) for i in range(21)]
    assert S.submovements(bell) == 1
    assert S.submovements(bell + [0.3 * v for v in bell]) == 2
    assert S.submovements([1.0, 0.98, 1.0, 0.97, 1.0]) == 1   # ripple is not a second move


def test_the_recording_gives_the_shipped_library():
    with open(os.path.join(ROOT, "mouse_data.json")) as f:
        events = json.load(f)
    built = S.build_library(events).to_json()
    with open(S.DEFAULT_LIBRARY) as f:
        shipped = json.load(f)
    assert built == shipped
    assert len(built["strokes"]) > 200
    for s in built["strokes"]:
        assert s["t"][0] == 0 and s["t"] == sorted(s["t"])
        assert (s["a"][0], s["b"][0], s["b"][-1]) == (0, 0, 0)
        assert s["a"][-1] == round(s["dist"] * 10)
