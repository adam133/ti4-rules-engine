"""Tests for Status Phase and Agenda Phase step tracking."""

from __future__ import annotations

import pytest
from transitions import MachineError

from engine.options import PlayerAction, get_player_options
from engine.round_engine import RoundEngine
from models.state import (
    AGENDA_PHASE_STEPS,
    STATUS_PHASE_STEPS,
    AgendaPhaseStep,
    GamePhase,
    GameState,
    StatusPhaseStep,
)


# ---------------------------------------------------------------------------
# Status Phase Step Ordering
# ---------------------------------------------------------------------------


class TestStatusPhaseStepOrdering:
    """STATUS_PHASE_STEPS list captures the correct order."""

    def test_first_step_is_score_objectives(self) -> None:
        assert STATUS_PHASE_STEPS[0] == StatusPhaseStep.SCORE_OBJECTIVES

    def test_last_step_is_return_strategy_cards(self) -> None:
        assert STATUS_PHASE_STEPS[-1] == StatusPhaseStep.RETURN_STRATEGY_CARDS

    def test_exactly_eight_steps(self) -> None:
        assert len(STATUS_PHASE_STEPS) == 8

    def test_full_sequence(self) -> None:
        expected = [
            StatusPhaseStep.SCORE_OBJECTIVES,
            StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE,
            StatusPhaseStep.DRAW_ACTION_CARDS,
            StatusPhaseStep.REMOVE_COMMAND_TOKENS,
            StatusPhaseStep.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS,
            StatusPhaseStep.READY_CARDS,
            StatusPhaseStep.REPAIR_UNITS,
            StatusPhaseStep.RETURN_STRATEGY_CARDS,
        ]
        assert STATUS_PHASE_STEPS == expected


# ---------------------------------------------------------------------------
# Agenda Phase Step Ordering
# ---------------------------------------------------------------------------


class TestAgendaPhaseStepOrdering:
    """AGENDA_PHASE_STEPS list captures the correct agenda cycle."""

    def test_first_step_is_replenish_commodities(self) -> None:
        assert AGENDA_PHASE_STEPS[0] == AgendaPhaseStep.REPLENISH_COMMODITIES

    def test_last_step_of_agenda_cycle_is_resolve_outcome(self) -> None:
        assert AGENDA_PHASE_STEPS[-1] == AgendaPhaseStep.RESOLVE_OUTCOME

    def test_four_steps_in_single_agenda_cycle(self) -> None:
        assert len(AGENDA_PHASE_STEPS) == 4


# ---------------------------------------------------------------------------
# RoundEngine – Status Phase step advancement
# ---------------------------------------------------------------------------


class TestRoundEngineStatusSteps:
    def test_enter_status_resets_step(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        assert game_state.status_phase_step == StatusPhaseStep.SCORE_OBJECTIVES

    def test_advance_status_step_progresses(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        result = engine.advance_status_step()
        assert result == StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE
        assert game_state.status_phase_step == StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE

    def test_advance_through_all_status_steps(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()

        results = []
        step = engine.advance_status_step()
        while step is not None:
            results.append(step)
            step = engine.advance_status_step()

        assert results == STATUS_PHASE_STEPS[1:]  # all steps after the first

    def test_advance_status_step_returns_none_when_done(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()

        # Advance to the final step manually.
        game_state.status_phase_step = StatusPhaseStep.RETURN_STRATEGY_CARDS
        result = engine.advance_status_step()
        assert result is None

    def test_advance_status_step_outside_status_raises(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        # Phase is STRATEGY at start.
        with pytest.raises(ValueError, match="Status Phase"):
            engine.advance_status_step()

    def test_status_step_reset_on_new_round(self, game_state: GameState) -> None:
        """Step resets to SCORE_OBJECTIVES when entering STATUS in a subsequent round."""
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        # Advance several steps.
        engine.advance_status_step()
        engine.advance_status_step()
        # Move to next round.
        engine.begin_strategy_phase()
        engine.begin_action_phase()
        engine.begin_status_phase()
        assert game_state.status_phase_step == StatusPhaseStep.SCORE_OBJECTIVES


# ---------------------------------------------------------------------------
# RoundEngine – Agenda Phase step advancement
# ---------------------------------------------------------------------------


class TestRoundEngineAgendaSteps:
    def test_enter_agenda_resets_step_and_count(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        assert game_state.agenda_phase_step == AgendaPhaseStep.REPLENISH_COMMODITIES
        assert game_state.agendas_resolved == 0

    def test_replenish_leads_to_reveal(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        result = engine.advance_agenda_step()
        assert result == AgendaPhaseStep.REVEAL_AGENDA

    def test_reveal_leads_to_vote(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        engine.advance_agenda_step()  # → REVEAL_AGENDA
        result = engine.advance_agenda_step()  # → VOTE
        assert result == AgendaPhaseStep.VOTE

    def test_vote_leads_to_resolve(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        engine.advance_agenda_step()  # → REVEAL_AGENDA
        engine.advance_agenda_step()  # → VOTE
        result = engine.advance_agenda_step()  # → RESOLVE_OUTCOME
        assert result == AgendaPhaseStep.RESOLVE_OUTCOME

    def test_resolve_first_agenda_loops_to_reveal(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        engine.advance_agenda_step()  # → REVEAL_AGENDA
        engine.advance_agenda_step()  # → VOTE
        engine.advance_agenda_step()  # → RESOLVE_OUTCOME
        result = engine.advance_agenda_step()  # → REVEAL_AGENDA (second agenda)
        assert result == AgendaPhaseStep.REVEAL_AGENDA
        assert game_state.agendas_resolved == 1

    def test_resolve_second_agenda_leads_to_ready_planets(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        # First agenda cycle.
        engine.advance_agenda_step()  # → REVEAL_AGENDA
        engine.advance_agenda_step()  # → VOTE
        engine.advance_agenda_step()  # → RESOLVE_OUTCOME
        engine.advance_agenda_step()  # → REVEAL_AGENDA (second)
        # Second agenda cycle.
        engine.advance_agenda_step()  # → VOTE
        engine.advance_agenda_step()  # → RESOLVE_OUTCOME
        result = engine.advance_agenda_step()  # → READY_PLANETS
        assert result == AgendaPhaseStep.READY_PLANETS
        assert game_state.agendas_resolved == 2

    def test_ready_planets_returns_none(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        engine.begin_action_phase()
        engine.begin_status_phase()
        engine.begin_agenda_phase()
        game_state.agenda_phase_step = AgendaPhaseStep.READY_PLANETS
        result = engine.advance_agenda_step()
        assert result is None

    def test_advance_agenda_step_outside_agenda_raises(self, game_state: GameState) -> None:
        engine = RoundEngine(game_state)
        with pytest.raises(ValueError, match="Agenda Phase"):
            engine.advance_agenda_step()


# ---------------------------------------------------------------------------
# get_player_options – Status Phase step-awareness
# ---------------------------------------------------------------------------


class TestStatusPhaseStepOptions:
    def test_score_objectives_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.SCORE_OBJECTIVES
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.SCORE_OBJECTIVE]

    def test_reveal_public_objective_speaker_only(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE
        # player_1 is the speaker in the test fixture
        opts_speaker = get_player_options(game_state, "player_1")
        opts_non_speaker = get_player_options(game_state, "player_2")
        assert PlayerAction.REVEAL_PUBLIC_OBJECTIVE in opts_speaker.available_actions
        assert PlayerAction.REVEAL_PUBLIC_OBJECTIVE not in opts_non_speaker.available_actions

    def test_draw_action_cards_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.DRAW_ACTION_CARDS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.DRAW_ACTION_CARDS]

    def test_remove_command_tokens_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.REMOVE_COMMAND_TOKENS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.REMOVE_COMMAND_TOKENS]

    def test_gain_and_redistribute_command_tokens_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS]

    def test_ready_cards_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.READY_CARDS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.READY_CARDS]

    def test_repair_units_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.REPAIR_UNITS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.REPAIR_UNITS]

    def test_return_strategy_cards_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.STATUS
        game_state.status_phase_step = StatusPhaseStep.RETURN_STRATEGY_CARDS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.RETURN_STRATEGY_CARDS]


# ---------------------------------------------------------------------------
# get_player_options – Agenda Phase step-awareness
# ---------------------------------------------------------------------------


class TestAgendaPhaseStepOptions:
    def test_replenish_commodities_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.REPLENISH_COMMODITIES
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.REPLENISH_COMMODITIES]

    def test_reveal_agenda_speaker_only(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.REVEAL_AGENDA
        # player_1 is the speaker
        opts_speaker = get_player_options(game_state, "player_1")
        opts_non_speaker = get_player_options(game_state, "player_2")
        assert PlayerAction.REVEAL_AGENDA in opts_speaker.available_actions
        assert PlayerAction.REVEAL_AGENDA not in opts_non_speaker.available_actions

    def test_vote_step_cast_votes_and_abstain(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.VOTE
        opts = get_player_options(game_state, "player_1")
        assert PlayerAction.CAST_VOTES in opts.available_actions
        assert PlayerAction.ABSTAIN in opts.available_actions

    def test_resolve_outcome_speaker_only(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.RESOLVE_OUTCOME
        opts_speaker = get_player_options(game_state, "player_1")
        opts_non_speaker = get_player_options(game_state, "player_2")
        assert PlayerAction.RESOLVE_OUTCOME in opts_speaker.available_actions
        assert PlayerAction.RESOLVE_OUTCOME not in opts_non_speaker.available_actions

    def test_ready_planets_step(self, game_state: GameState) -> None:
        game_state.phase = GamePhase.AGENDA
        game_state.agenda_phase_step = AgendaPhaseStep.READY_PLANETS
        opts = get_player_options(game_state, "player_1")
        assert opts.available_actions == [PlayerAction.READY_PLANETS]


# ---------------------------------------------------------------------------
# PlayerState new fields
# ---------------------------------------------------------------------------


class TestPlayerStateNewFields:
    def test_command_tokens_default_zero(self, game_state: GameState) -> None:
        assert game_state.players["player_1"].command_tokens == 0

    def test_command_tokens_assignable(self, game_state: GameState) -> None:
        game_state.players["player_1"].command_tokens = 5
        assert game_state.players["player_1"].command_tokens == 5

    def test_commodities_cap_default(self, game_state: GameState) -> None:
        assert game_state.players["player_1"].commodities_cap == 3

    def test_commodities_cap_assignable(self, game_state: GameState) -> None:
        game_state.players["player_1"].commodities_cap = 4
        assert game_state.players["player_1"].commodities_cap == 4


# ---------------------------------------------------------------------------
# GameState new fields
# ---------------------------------------------------------------------------


class TestGameStateNewFields:
    def test_status_phase_step_default(self, game_state: GameState) -> None:
        assert game_state.status_phase_step == StatusPhaseStep.SCORE_OBJECTIVES

    def test_agenda_phase_step_default(self, game_state: GameState) -> None:
        assert game_state.agenda_phase_step == AgendaPhaseStep.REPLENISH_COMMODITIES

    def test_agendas_resolved_default(self, game_state: GameState) -> None:
        assert game_state.agendas_resolved == 0

    def test_snapshot_includes_new_fields(self, game_state: GameState) -> None:
        snap = game_state.snapshot()
        assert "status_phase_step" in snap
        assert "agenda_phase_step" in snap
        assert "agendas_resolved" in snap

    def test_restore_round_trips_new_fields(self, game_state: GameState) -> None:
        game_state.status_phase_step = StatusPhaseStep.REPAIR_UNITS
        game_state.agenda_phase_step = AgendaPhaseStep.VOTE
        game_state.agendas_resolved = 1
        snap = game_state.snapshot()
        restored = GameState.restore(snap)
        assert restored.status_phase_step == StatusPhaseStep.REPAIR_UNITS
        assert restored.agenda_phase_step == AgendaPhaseStep.VOTE
        assert restored.agendas_resolved == 1
