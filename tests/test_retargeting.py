"""Turning a recorded stroke onto a new start -> end."""

import math
import sys

import pytest

from natural_pointer import NaturalPointer, StrokeLibrary, position_at
from natural_pointer.strokes import Stroke, _at


def test_path_starts_and_ends_exactly_where_asked():
    lib = StrokeLibrary.load(seed=1)
    for start, end in [((100, 100), (900, 500)), ((1500, 900), (40, 60)), ((300, 300), (305, 298)),
                       ((0, 0), (2559, 1439))]:
        path = lib.path(start, end)
        assert path[0] == (0.0, *map(float, start))
        assert path[-1][1:] == tuple(map(float, end))
        times = [p[0] for p in path]
        assert times == sorted(times) and times[-1] > 0.03


def test_the_same_seed_gives_the_same_path():
    a, b = StrokeLibrary.load(seed=42), StrokeLibrary.load(seed=42)
    assert a.path((10, 10), (400, 300)) == b.path((10, 10), (400, 300))
    assert a.path((10, 10), (400, 300)) != StrokeLibrary.load(seed=43).path((10, 10), (400, 300))


def test_no_stroke_is_replayed_twice_in_a_row():
    lib = StrokeLibrary.load(seed=3)
    used = []
    for _ in range(200):
        lib.path((200, 200), (700, 450))
        used.append(lib.recent[-1])
    assert all(a != b for a, b in zip(used, used[1:]))
    assert all(len(set(used[i:i + lib.RECENT + 1])) == lib.RECENT + 1 for i in range(len(used) - lib.RECENT))
    assert len(set(used)) >= lib.CHOICES


def test_the_chosen_stroke_is_of_similar_length_and_direction():
    lib = StrokeLibrary.load(seed=5)
    by_id = {s.id: s for s in lib.strokes}
    for dist, angle in [(60, 0.0), (300, math.pi / 2), (300, -2.5), (600, 3.0)]:
        end = (900 + dist * math.cos(angle), 600 + dist * math.sin(angle))
        for _ in range(10):
            lib.path((900, 600), end)
            s = by_id[lib.recent[-1]]
            assert 0.5 < s.dist / dist < 2.0
            assert abs(math.remainder(s.angle - angle, 2 * math.pi)) < math.pi / 2


def test_retargeting_keeps_the_strokes_shape_and_timing():
    # one stroke: a bow of 10 to the left of travel with a hesitation in the middle
    stroke = Stroke(0, 100.0, 0.0, [0.0, 0.1, 0.3, 0.4], [0.0, 40.0, 60.0, 100.0], [0.0, -10.0, -10.0, 0.0])
    lib = StrokeLibrary([stroke], {"a": 0.4, "b": 0.0}, seed=9)
    path = lib.path((0, 0), (0, 200))            # twice as long, turned a quarter turn
    pace = path[-1][0] / 0.4
    assert 0.93 <= pace <= 1.09
    # along the new chord (down the screen) the shape is the recorded one, doubled
    assert [round(p[2], 6) for p in path] == [0, 80, 120, 200]
    bows = [p[1] for p in path]
    assert bows[0] == 0 and bows[3] == 0 and bows[1] == pytest.approx(bows[2])
    assert 0.85 * 20 <= bows[1] <= 1.15 * 20     # left of travel when heading down is +x
    # the hesitation is still half of the whole, give or take the lean
    assert (path[2][0] - path[1][0]) / path[-1][0] == pytest.approx(0.5, abs=0.05)


def test_one_stroke_alone_is_still_usable():
    stroke = Stroke(0, 100.0, 0.0, [0.0, 0.1, 0.2], [0.0, 50.0, 100.0], [0.0, 2.0, 0.0])
    lib = StrokeLibrary([stroke], seed=1)
    assert lib.path((0, 0), (50, 0))[-1][1:] == (50.0, 0.0)
    assert lib.path((0, 0), (50, 0))[-1][1:] == (50.0, 0.0)


def test_the_path_stays_on_the_screen():
    lib = StrokeLibrary.load(seed=11)
    for _ in range(50):
        for _, x, y in lib.path((5, 400), (795, 3), screen=(800, 600)):
            assert 0 <= x <= 799 and 0 <= y <= 599


def test_no_move_and_tiny_moves():
    lib = StrokeLibrary.load(seed=2)
    assert lib.path((5, 5), (5, 5)) == [(0.0, 5.0, 5.0)]
    assert lib.path((5, 5), (5.2, 5))[-1] == (0.0, 5.2, 5.0)


def test_position_at_runs_straight_between_samples():
    path = [(0.0, 0.0, 0.0), (0.1, 10.0, 0.0), (0.3, 10.0, 20.0)]
    assert position_at(path, -1) == (0.0, 0.0)
    assert position_at(path, 0.05) == pytest.approx((5.0, 0.0))
    assert position_at(path, 0.2) == pytest.approx((10.0, 10.0))
    assert position_at(path, 9) == (10.0, 20.0)
    assert _at([0.0, 0.0], [1.0, 2.0], [3.0, 4.0], 0.0) == (1.0, 3.0)


def test_dwell_is_one_of_the_recorded_waits():
    lib = StrokeLibrary.load(seed=4)
    waits = {s.meta["dwell"] for s in lib.strokes if "dwell" in s.meta}
    assert len(waits) > 20
    assert all(lib.dwell() in waits for _ in range(30))


def test_natural_pointer_plans_paths_without_torch_or_pyautogui():
    pointer = NaturalPointer(seed=8)
    assert pointer.method == "stroke" and pointer.model_path == "mouse_model.pth"
    path = pointer.path((100, 100), (640, 480), screen=(1280, 800))
    assert path[0] == (0.0, 100.0, 100.0) and path[-1][1:] == (640.0, 480.0)
    assert "torch" not in sys.modules and "pyautogui" not in sys.modules


def test_bezier_is_the_fallback():
    pointer = NaturalPointer(library_path="/nonexistent/strokes.json")
    assert pointer.method == "bezier"
    path = pointer.path((100, 100), (640, 480))
    assert path[0] == (0.0, 100.0, 100.0) and path[-1][1:] == (640.0, 480.0)
    assert [p[0] for p in path] == sorted(p[0] for p in path)
    assert NaturalPointer(method="bezier").path((0, 0), (10, 10))[-1][1:] == (10.0, 10.0)
    with pytest.raises(ValueError):
        NaturalPointer(method="teleport")
