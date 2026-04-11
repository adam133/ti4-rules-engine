"""
TI4 Rules Engine – engine package.

Provides the ``RoundEngine`` (phase state machine) and the ``GameHistory``
undo/redo manager.
"""

from engine.history import GameHistory
from engine.round_engine import RoundEngine

__all__ = ["GameHistory", "RoundEngine"]
