"""
TI4 Rules Engine – engine package.

Provides the ``RoundEngine`` (phase state machine), the ``GameHistory``
undo/redo manager, and the ``get_player_options`` player-options query.
"""

from engine.history import GameHistory
from engine.options import PlayerAction, PlayerOptions, get_player_options
from engine.round_engine import RoundEngine

__all__ = [
    "GameHistory",
    "PlayerAction",
    "PlayerOptions",
    "RoundEngine",
    "get_player_options",
]
