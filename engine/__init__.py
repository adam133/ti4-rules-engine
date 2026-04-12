"""
TI4 Rules Engine – engine package.

Provides the ``RoundEngine`` (phase state machine), the ``GameHistory``
undo/redo manager, the ``get_player_options`` player-options query,
movement range evaluation, and Monte Carlo combat simulation.
"""

from engine.combat import CombatGroup, CombatResult, CombatUnit, simulate_combat
from engine.history import GameHistory
from engine.movement import get_fleet_move, get_reachable_systems
from engine.options import PlayerAction, PlayerOptions, get_player_options
from engine.round_engine import RoundEngine
from engine.scoring import can_score_objective, score_points_available

__all__ = [
    "CombatGroup",
    "CombatResult",
    "CombatUnit",
    "GameHistory",
    "PlayerAction",
    "PlayerOptions",
    "RoundEngine",
    "can_score_objective",
    "get_fleet_move",
    "get_player_options",
    "get_reachable_systems",
    "score_points_available",
    "simulate_combat",
]
