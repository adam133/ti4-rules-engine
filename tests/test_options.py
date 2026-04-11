"""Tests for the player options engine."""

from __future__ import annotations

import pytest

from engine.options import PlayerAction, PlayerOptions, get_player_options
from models.state import GamePhase, GameState

# ---------------------------------------------------------------------------
# Strategy Phase
# ---------------------------------------------------------------------------


class TestStrategyPhase:
    def test_no_strategy_card_can_pick(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.PICK_STRATEGY_CARD in opts.available_actions

    def test_has_strategy_card_cannot_pick(self, game_state: GameState) -> None:
        game_state.players["player_1"].strategy_card_ids = ["technology"]
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.PICK_STRATEGY_CARD not in opts.available_actions
        assert opts.available_actions == []

    def test_phase_reflected(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_1")
        assert opts.phase == GamePhase.STRATEGY

    def test_no_action_phase_options_during_strategy(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.TACTICAL_ACTION not in opts.available_actions
        assert PlayerAction.PASS not in opts.available_actions


# ---------------------------------------------------------------------------
# Action Phase
# ---------------------------------------------------------------------------


class TestActionPhase:
    def test_tactical_action_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.TACTICAL_ACTION in opts.available_actions

    def test_component_action_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.COMPONENT_ACTION in opts.available_actions

    def test_pass_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.PASS in opts.available_actions

    def test_strategic_action_with_strategy_card(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].strategy_card_ids = ["technology"]
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.STRATEGIC_ACTION in opts.available_actions

    def test_no_strategic_action_without_strategy_card(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].strategy_card_ids = []
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.STRATEGIC_ACTION not in opts.available_actions

    def test_passed_player_has_no_actions(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].passed = True
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == []

    def test_passed_flag_set(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].passed = True
        opts = get_player_options(game_state, "player_1")
        assert opts.passed is True

    def test_can_act_false_when_passed(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].passed = True
        opts = get_player_options(game_state, "player_1")
        assert opts.can_act is False

    def test_not_passed_flag(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opts = get_player_options(game_state, "player_1")
        assert opts.passed is False

    def test_no_pick_strategy_card_during_action(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.PICK_STRATEGY_CARD not in opts.available_actions


# ---------------------------------------------------------------------------
# Status Phase
# ---------------------------------------------------------------------------


class TestStatusPhase:
    def test_score_objective_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.SCORE_OBJECTIVE in opts.available_actions

    def test_ready_cards_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.READY_CARDS in opts.available_actions

    def test_no_action_phase_options(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.TACTICAL_ACTION not in opts.available_actions
        assert PlayerAction.PASS not in opts.available_actions


# ---------------------------------------------------------------------------
# Agenda Phase
# ---------------------------------------------------------------------------


class TestAgendaPhase:
    def test_cast_votes_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.CAST_VOTES in opts.available_actions

    def test_abstain_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.ABSTAIN in opts.available_actions

    def test_no_tactical_action(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.TACTICAL_ACTION not in opts.available_actions


# ---------------------------------------------------------------------------
# General / edge cases
# ---------------------------------------------------------------------------


class TestPlayerOptionsMisc:
    def test_missing_player_raises(self, game_state: GameState) -> None:
        with pytest.raises(KeyError, match="player_999"):
            get_player_options(game_state, "player_999")

    def test_can_act_true_when_options_available(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_1")
        assert opts.can_act is True

    def test_can_act_false_when_no_options(self, game_state: GameState) -> None:
        # Strategy phase with a card already held → no options
        game_state.players["player_1"].strategy_card_ids = ["technology"]
        opts = get_player_options(game_state, "player_1")
        assert opts.can_act is False

    def test_player_id_in_options(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_2")
        assert opts.player_id == "player_2"

    def test_returns_player_options_instance(self, game_state: GameState) -> None:
        opts = get_player_options(game_state, "player_1")
        assert isinstance(opts, PlayerOptions)
