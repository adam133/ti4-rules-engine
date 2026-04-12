"""Tests for the player options engine."""

from __future__ import annotations

import pytest

from engine.options import (
    PlayerAction,
    PlayerOptions,
    PublicPlayerInfo,
    get_all_opponents_public_info,
    get_player_options,
    get_public_player_info,
)
from models.objective import Objective, ObjectiveType, ScoringCondition, ScoringConditionType
from models.planet import Planet
from models.state import AgendaPhaseStep, GamePhase, GameState, StatusPhaseStep

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
        game_state.status_phase_step = StatusPhaseStep.READY_CARDS
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
        game_state.agenda_phase_step = AgendaPhaseStep.VOTE
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.CAST_VOTES in opts.available_actions

    def test_abstain_available(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.VOTE
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.ABSTAIN in opts.available_actions

    def test_no_tactical_action(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.VOTE
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


# ---------------------------------------------------------------------------
# PublicPlayerInfo / get_public_player_info
# ---------------------------------------------------------------------------


class TestGetPublicPlayerInfo:
    def test_returns_public_player_info_instance(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert isinstance(info, PublicPlayerInfo)

    def test_tactical_action_included(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.TACTICAL_ACTION in info.available_actions

    def test_strategic_action_included_when_card_held(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].strategy_card_ids = ["technology"]
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.STRATEGIC_ACTION in info.available_actions

    def test_strategic_action_excluded_without_card(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].strategy_card_ids = []
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.STRATEGIC_ACTION not in info.available_actions

    def test_pass_included(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.PASS in info.available_actions

    def test_component_action_included_in_action_phase(self, game_state: GameState) -> None:
        # component_action is included because public sources (tech action abilities,
        # faction agents) are observable by opponents.
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.COMPONENT_ACTION in info.available_actions

    def test_passed_player_has_no_actions(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].passed = True
        info = get_public_player_info(game_state, "player_1")
        assert info.available_actions == []
        assert info.passed is True

    def test_can_act_false_when_passed(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_1"].passed = True
        info = get_public_player_info(game_state, "player_1")
        assert info.can_act is False

    def test_can_act_true_when_not_passed(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert info.can_act is True

    def test_phase_reflected(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_1")
        assert info.phase == GamePhase.ACTION

    def test_player_id_reflected(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        info = get_public_player_info(game_state, "player_2")
        assert info.player_id == "player_2"

    def test_missing_player_raises(self, game_state: GameState) -> None:
        with pytest.raises(KeyError, match="player_999"):
            get_public_player_info(game_state, "player_999")

    def test_no_scoring_when_objectives_not_provided(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        info = get_public_player_info(game_state, "player_1")
        assert info.scoreable_points == 0
        assert info.scoreable_objective_ids == []

    def test_scoring_only_counts_public_objectives(self, game_state: GameState) -> None:
        """Objectives not listed in state.public_objectives are ignored."""
        game_state.phase = GamePhase.STATUS
        game_state.players["player_1"].controlled_planets = ["mecatol_rex"]
        # revealed public objective
        game_state.public_objectives = ["control_mecatol"]
        mecatol_obj = Objective(
            id="control_mecatol",
            name="Control Mecatol Rex",
            objective_type=ObjectiveType.STAGE_1,
            points=1,
            description="Control Mecatol Rex.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_MECATOL_REX,
            ),
        )
        secret_obj = Objective(
            id="my_secret",
            name="My Secret",
            objective_type=ObjectiveType.SECRET,
            points=1,
            description="Secret objective.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_MECATOL_REX,
            ),
        )
        info = get_public_player_info(
            game_state, "player_1", objectives=[mecatol_obj, secret_obj]
        )
        assert info.scoreable_points == 1
        assert "control_mecatol" in info.scoreable_objective_ids
        assert "my_secret" not in info.scoreable_objective_ids

    def test_scoring_skips_already_scored(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.players["player_1"].controlled_planets = ["mecatol_rex"]
        game_state.players["player_1"].scored_objectives = ["control_mecatol"]
        game_state.public_objectives = ["control_mecatol"]
        mecatol_obj = Objective(
            id="control_mecatol",
            name="Control Mecatol Rex",
            objective_type=ObjectiveType.STAGE_1,
            points=1,
            description="Control Mecatol Rex.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_MECATOL_REX,
            ),
        )
        info = get_public_player_info(
            game_state, "player_1", objectives=[mecatol_obj]
        )
        assert info.scoreable_points == 0
        assert info.scoreable_objective_ids == []

    def test_scoring_unmet_condition_not_counted(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        # player does NOT control mecatol_rex
        game_state.public_objectives = ["control_mecatol"]
        mecatol_obj = Objective(
            id="control_mecatol",
            name="Control Mecatol Rex",
            objective_type=ObjectiveType.STAGE_1,
            points=1,
            description="Control Mecatol Rex.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_MECATOL_REX,
            ),
        )
        info = get_public_player_info(
            game_state, "player_1", objectives=[mecatol_obj]
        )
        assert info.scoreable_points == 0

    def test_scoring_with_planet_registry(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.players["player_1"].controlled_planets = ["planet_a", "planet_b", "planet_c"]
        game_state.public_objectives = ["tech_skips_obj"]
        planet_registry = {
            "planet_a": Planet(
                id="planet_a", name="A", resources=1, influence=1, system_id="s1",
                tech_skip="biotic",
            ),
            "planet_b": Planet(
                id="planet_b", name="B", resources=1, influence=1, system_id="s2",
                tech_skip="cybernetic",
            ),
            "planet_c": Planet(
                id="planet_c", name="C", resources=1, influence=1, system_id="s3",
            ),
        }
        tech_skips_obj = Objective(
            id="tech_skips_obj",
            name="Tech Skips",
            objective_type=ObjectiveType.STAGE_1,
            points=1,
            description="Control 2 planets with tech specialties.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_N_PLANETS_WITH_TECH_SKIP,
                threshold=2,
            ),
        )
        info = get_public_player_info(
            game_state,
            "player_1",
            objectives=[tech_skips_obj],
            planet_registry=planet_registry,
        )
        assert info.scoreable_points == 1
        assert "tech_skips_obj" in info.scoreable_objective_ids

    def test_strategy_phase_no_component_action(self, game_state: GameState) -> None:
        # During strategy phase, component_action is not returned by get_player_options
        # at all (wrong phase), so it is not present in public info either.
        info = get_public_player_info(game_state, "player_1")
        assert PlayerAction.COMPONENT_ACTION not in info.available_actions


# ---------------------------------------------------------------------------
# get_all_opponents_public_info
# ---------------------------------------------------------------------------


class TestGetAllOpponentsPublicInfo:
    def test_excludes_viewing_player(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opponents = get_all_opponents_public_info(game_state, "player_1")
        assert "player_1" not in opponents

    def test_includes_all_other_players(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opponents = get_all_opponents_public_info(game_state, "player_1")
        assert "player_2" in opponents
        assert "player_3" in opponents

    def test_returns_public_player_info_instances(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        opponents = get_all_opponents_public_info(game_state, "player_1")
        for info in opponents.values():
            assert isinstance(info, PublicPlayerInfo)

    def test_opponent_has_component_action(self, game_state: GameState) -> None:
        # component_action is included for opponents because public sources
        # (tech action abilities, faction agents) are observable.
        game_state.phase = GamePhase.ACTION
        opponents = get_all_opponents_public_info(game_state, "player_1")
        for info in opponents.values():
            assert PlayerAction.COMPONENT_ACTION in info.available_actions

    def test_passed_opponent_has_no_actions(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.ACTION
        game_state.players["player_2"].passed = True
        opponents = get_all_opponents_public_info(game_state, "player_1")
        assert opponents["player_2"].available_actions == []

    def test_missing_viewing_player_raises(self, game_state: GameState) -> None:
        with pytest.raises(KeyError, match="player_999"):
            get_all_opponents_public_info(game_state, "player_999")

    def test_two_player_game_single_opponent(self, game_state: GameState) -> None:
        from models.state import TurnOrder

        game_state.phase = GamePhase.ACTION
        game_state.turn_order = TurnOrder(speaker_id="player_1", order=["player_1", "player_2"])
        game_state.players = {
            "player_1": game_state.players["player_1"],
            "player_2": game_state.players["player_2"],
        }
        opponents = get_all_opponents_public_info(game_state, "player_1")
        assert list(opponents.keys()) == ["player_2"]

    def test_scoring_propagated_to_opponents(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.players["player_2"].controlled_planets = ["mecatol_rex"]
        game_state.public_objectives = ["control_mecatol"]
        mecatol_obj = Objective(
            id="control_mecatol",
            name="Control Mecatol Rex",
            objective_type=ObjectiveType.STAGE_1,
            points=1,
            description="Control Mecatol Rex.",
            condition=ScoringCondition(
                condition_type=ScoringConditionType.CONTROL_MECATOL_REX,
            ),
        )
        opponents = get_all_opponents_public_info(
            game_state, "player_1", objectives=[mecatol_obj]
        )
        assert opponents["player_2"].scoreable_points == 1
        assert "control_mecatol" in opponents["player_2"].scoreable_objective_ids
        assert opponents["player_3"].scoreable_points == 0
