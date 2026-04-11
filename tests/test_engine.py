"""Tests for the RoundEngine phase state machine."""

from __future__ import annotations

import pytest
from transitions import MachineError

from engine.round_engine import RoundEngine
from models.state import GamePhase, GameState


class TestRoundEnginePhaseTransitions:
    def test_initial_state_is_strategy(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        assert game_state.phase == GamePhase.STRATEGY

    def test_strategy_to_action(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        assert game_state.phase == GamePhase.ACTION

    def test_action_to_status(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        assert game_state.phase == GamePhase.STATUS

    def test_status_to_agenda(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        assert game_state.phase == GamePhase.AGENDA

    def test_agenda_to_strategy(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        engine.begin_strategy_phase()
        assert game_state.phase == GamePhase.STRATEGY

    def test_full_round_increments_round_number(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        assert game_state.round_number == 1
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        engine.begin_strategy_phase()
        assert game_state.round_number == 2

    def test_skip_agenda_status_to_strategy(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_strategy_phase()
        assert game_state.phase == GamePhase.STRATEGY

    def test_invalid_transition_raises(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        # Can't jump directly from STRATEGY to STATUS
        with pytest.raises(MachineError):
            engine.begin_status_phase()


class TestRoundEngineTurnHelpers:
    def test_set_active_player(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.set_active_player("player_1")
        assert game_state.active_player_id == "player_1"

    def test_clear_active_player(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.set_active_player("player_1")
        engine.set_active_player(None)
        assert game_state.active_player_id is None

    def test_set_active_player_invalid(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        with pytest.raises(ValueError, match="player_999"):
            engine.set_active_player("player_999")

    def test_pass_player(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.pass_player("player_1")
        assert game_state.players["player_1"].passed is True

    def test_pass_player_unknown(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        with pytest.raises(KeyError):
            engine.pass_player("player_999")
