"""
TI4 Rules Engine – engine package.

Provides the ``RoundEngine`` (phase state machine), the ``GameHistory``
undo/redo manager, the ``get_player_options`` player-options query,
movement range evaluation, and Monte Carlo combat simulation.
"""

from ti4_rules_engine.engine.combat import CombatGroup, CombatResult, CombatUnit, simulate_combat
from ti4_rules_engine.engine.history import GameHistory
from ti4_rules_engine.engine.movement import get_fleet_move, get_reachable_systems
from ti4_rules_engine.engine.options import (
    PlayerAction,
    PlayerOptions,
    PublicPlayerInfo,
    get_all_opponents_public_info,
    get_player_options,
    get_public_player_info,
)
from ti4_rules_engine.engine.round_engine import RoundEngine
from ti4_rules_engine.engine.scoring import can_score_objective, score_points_available

__all__ = [
    "CombatGroup",
    "CombatResult",
    "CombatUnit",
    "GameHistory",
    "PlayerAction",
    "PlayerOptions",
    "PublicPlayerInfo",
    "RoundEngine",
    "can_score_objective",
    "get_all_opponents_public_info",
    "get_fleet_move",
    "get_player_options",
    "get_public_player_info",
    "get_reachable_systems",
    "score_points_available",
    "simulate_combat",
]
