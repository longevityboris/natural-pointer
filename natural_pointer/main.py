"""
The public interface: plan a human pointer path, or move the real pointer along one.

``NaturalPointer.path`` needs the standard library only. Moving the real
pointer (``move_to``, ``click``...) needs ``pyautogui``; the retired next-point
network (``method="model"``) needs ``torch``.
"""

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .strokes import StrokeLibrary, position_at

TimedPath = List[Tuple[float, float, float]]   # (seconds from the start, x, y)


class NaturalPointer:
    """Natural pointer movement for automated tasks.

    ``method`` chooses how a path is made:

    - ``"stroke"`` (default): replay a recorded stroke turned and scaled onto
      start -> end. Falls back to ``"bezier"`` if the library cannot be read.
    - ``"bezier"``: a random bezier curve with eased timing.
    - ``"model"``: the next-point network in ``model_path`` (kept for
      comparison; see the README for why it is retired).
    """

    def __init__(self, model_path: str = "mouse_model.pth", method: str = "stroke",
                 library_path: Optional[str] = None, seed: Optional[int] = None):
        if method not in ("stroke", "bezier", "model"):
            raise ValueError(f"unknown method {method!r}")
        self.model_path = model_path
        self.method = method
        self.library: Optional[StrokeLibrary] = None
        self._simulator = None
        if method == "stroke":
            try:
                self.library = StrokeLibrary.load(library_path, seed=seed)
            except (OSError, ValueError, KeyError) as e:
                print(f"Stroke library not usable ({e}). Using bezier curves.")
                self.method = "bezier"

    @property
    def simulator(self):
        """The model-driven simulator, made on first use (needs torch and pyautogui)."""
        if self._simulator is None:
            from .utils.simulator import MouseSimulator
            self._simulator = MouseSimulator(model_path=self.model_path)
        return self._simulator

    def path(self, start: Sequence[float], end: Sequence[float],
             screen: Optional[Sequence[float]] = None) -> TimedPath:
        """A timed path from ``start`` to ``end``, both (x, y) in screen points.

        Returns a list of (t, x, y): ``t`` in seconds from the start of the
        move, first point ``start`` at t = 0, last point exactly ``end``.
        ``screen`` is (width, height); with it the path stays on the screen.
        """
        if self.method == "stroke":
            return self.library.path(start, end, screen)
        if self.method == "model":
            steps = self.simulator.generate_path(start[0], start[1], end[0], end[1])
        else:
            from .utils.simulator import bezier_path
            steps = bezier_path(start[0], start[1], end[0], end[1])
        out, t = [(0.0, float(start[0]), float(start[1]))], 0.0
        for p in steps:
            t += p["time"] / 1000.0
            out.append((t, float(p["x"]), float(p["y"])))
        out[-1] = (out[-1][0], float(end[0]), float(end[1]))
        return out

    def move_to(self, x: int, y: int, click: bool = False,
                right_click: bool = False, double_click: bool = False) -> None:
        """Move the mouse to (x, y) with natural motion, then click if asked."""
        import pyautogui

        path = self.path(pyautogui.position(), (x, y), pyautogui.size())
        total = path[-1][0]
        began = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - began
            if elapsed >= total:
                break
            px, py = position_at(path, elapsed)
            pyautogui.moveTo(px, py, _pause=False)
            time.sleep(0.004)
        pyautogui.moveTo(x, y, _pause=False)

        if double_click:
            pyautogui.doubleClick()
        elif click:
            pyautogui.click()
        elif right_click:
            pyautogui.rightClick()

    def click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Left-click at (x, y), or where the pointer is if no position is given."""
        if x is not None and y is not None:
            self.move_to(x, y, click=True)
        else:
            import pyautogui
            pyautogui.click()

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Right-click at (x, y), or where the pointer is if no position is given."""
        if x is not None and y is not None:
            self.move_to(x, y, right_click=True)
        else:
            import pyautogui
            pyautogui.rightClick()

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Double-click at (x, y), or where the pointer is if no position is given."""
        if x is not None and y is not None:
            self.move_to(x, y, double_click=True)
        else:
            import pyautogui
            pyautogui.doubleClick()

    def get_info(self) -> Dict[str, Any]:
        """The method in use, the screen size and the pointer position."""
        import pyautogui

        screen_width, screen_height = pyautogui.size()
        return {
            "method": self.method,
            "strokes": len(self.library.strokes) if self.library else 0,
            "model_path": self.model_path,
            "model_loaded": self.simulator.model_loaded if self.method == "model" else False,
            "screen_width": screen_width,
            "screen_height": screen_height,
            "current_position": pyautogui.position(),
        }
