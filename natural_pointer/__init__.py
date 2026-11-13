"""Natural Pointer: move the pointer the way a recorded human hand moved it."""

__version__ = '0.2.0'

from .main import NaturalPointer
from .strokes import StrokeLibrary, position_at

__all__ = ["NaturalPointer", "StrokeLibrary", "position_at"]
