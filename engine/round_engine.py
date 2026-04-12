"""
Round engine – phase state machine for a TI4 game round.

Uses the *transitions* library to model the legal phase transitions:

    STRATEGY → ACTION → STATUS → AGENDA → STRATEGY (next round)

The engine operates on a :class:`~models.state.GameState` and emits
structured log entries via *structlog*.
"""

from __future__ import annotations

import structlog
from transitions import Machine

from models.state import (
    AGENDA_PHASE_STEPS,
    STATUS_PHASE_STEPS,
    AgendaPhaseStep,
    GamePhase,
    GameState,
    StatusPhaseStep,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Phase transition table
# Use string values (not StrEnum members) so that the `transitions` library
# can look up states correctly in its internal registry.
# ---------------------------------------------------------------------------

_TRANSITIONS: list[dict] = [
    {
        "trigger": "begin_action_phase",
        "source": GamePhase.STRATEGY.value,
        "dest": GamePhase.ACTION.value,
    },
    {
        "trigger": "begin_status_phase",
        "source": GamePhase.ACTION.value,
        "dest": GamePhase.STATUS.value,
    },
    {
        "trigger": "begin_agenda_phase",
        "source": GamePhase.STATUS.value,
        "dest": GamePhase.AGENDA.value,
    },
    {
        "trigger": "begin_strategy_phase",
        "source": [GamePhase.STATUS.value, GamePhase.AGENDA.value],
        "dest": GamePhase.STRATEGY.value,
    },
]


class RoundEngine:
    """
    Drives the phase progression of a TI4 round.

    The engine holds a reference to the mutable ``GameState`` and advances
    the phase on valid triggers.  Illegal transitions raise
    ``transitions.core.MachineError``.

    Example usage::

        state = GameState(game_id="game-1", round_number=1, turn_order=...)
        engine = RoundEngine(state)

        engine.begin_action_phase()   # STRATEGY → ACTION
        engine.begin_status_phase()   # ACTION   → STATUS
        engine.begin_agenda_phase()   # STATUS   → AGENDA
        engine.begin_strategy_phase() # AGENDA   → STRATEGY (round 2)
    """

    def __init__(self, game_state: GameState) -> None:
        self.game_state = game_state

        self._machine = Machine(
            model=self,
            states=[p.value for p in GamePhase],
            transitions=_TRANSITIONS,
            initial=game_state.phase.value,
            auto_transitions=False,
            ignore_invalid_triggers=False,
        )

    # ------------------------------------------------------------------
    # Internal callbacks invoked by the state machine on entry/exit
    # ------------------------------------------------------------------

    def on_enter_action(self) -> None:
        self._sync_phase(GamePhase.ACTION)
        logger.info(
            "phase_transition",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
            new_phase=GamePhase.ACTION,
        )

    def on_enter_status(self) -> None:
        self._sync_phase(GamePhase.STATUS)
        self.game_state.status_phase_step = StatusPhaseStep.SCORE_OBJECTIVES
        logger.info(
            "phase_transition",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
            new_phase=GamePhase.STATUS,
        )

    def on_enter_agenda(self) -> None:
        self._sync_phase(GamePhase.AGENDA)
        self.game_state.agenda_phase_step = AgendaPhaseStep.REPLENISH_COMMODITIES
        self.game_state.agendas_resolved = 0
        logger.info(
            "phase_transition",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
            new_phase=GamePhase.AGENDA,
        )

    def on_enter_strategy(self) -> None:
        self._increment_round()
        self._sync_phase(GamePhase.STRATEGY)
        logger.info(
            "phase_transition",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
            new_phase=GamePhase.STRATEGY,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sync_phase(self, phase: GamePhase) -> None:
        """Write the new phase back onto the ``GameState``."""
        self.game_state.phase = phase

    def _increment_round(self) -> None:
        """Increment the round counter when entering a new Strategy Phase."""
        current_round = self.game_state.round_number
        # Only increment if we are not in the very first strategy phase
        if self.game_state.phase != GamePhase.STRATEGY:
            self.game_state.round_number = current_round + 1

    # ------------------------------------------------------------------
    # Turn helpers
    # ------------------------------------------------------------------

    def set_active_player(self, player_id: str | None) -> None:
        """Set the currently active player (or clear it with ``None``)."""
        if player_id is not None and player_id not in self.game_state.players:
            raise ValueError(f"Player '{player_id}' is not in this game.")
        self.game_state.active_player_id = player_id

    def pass_player(self, player_id: str) -> None:
        """Mark a player as having passed during the Action Phase."""
        player = self.game_state.get_player(player_id)
        player.passed = True
        logger.info(
            "player_passed",
            game_id=self.game_state.game_id,
            player_id=player_id,
        )

    # ------------------------------------------------------------------
    # Status Phase step helpers
    # ------------------------------------------------------------------

    def advance_status_step(self) -> StatusPhaseStep | None:
        """Advance the Status Phase to the next step.

        Returns
        -------
        StatusPhaseStep | None
            The new current step, or ``None`` if all steps are complete (the
            caller should then call :meth:`begin_agenda_phase` or
            :meth:`begin_strategy_phase` to proceed).

        Raises
        ------
        ValueError
            If the current game phase is not STATUS.
        """
        if self.game_state.phase != GamePhase.STATUS:
            raise ValueError(
                f"advance_status_step called outside of Status Phase "
                f"(current phase: {self.game_state.phase!r})."
            )
        current = self.game_state.status_phase_step
        idx = STATUS_PHASE_STEPS.index(current)
        if idx + 1 < len(STATUS_PHASE_STEPS):
            next_step = STATUS_PHASE_STEPS[idx + 1]
            self.game_state.status_phase_step = next_step
            logger.info(
                "status_step_advanced",
                game_id=self.game_state.game_id,
                round=self.game_state.round_number,
                new_step=next_step,
            )
            return next_step
        # All 8 steps complete – signal the caller.
        logger.info(
            "status_phase_complete",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
        )
        return None

    # ------------------------------------------------------------------
    # Agenda Phase step helpers
    # ------------------------------------------------------------------

    def advance_agenda_step(self) -> AgendaPhaseStep | None:
        """Advance the Agenda Phase to the next step.

        The Agenda Phase resolves **two** agendas per round.  After
        RESOLVE_OUTCOME the engine checks whether a second agenda remains.
        If so it loops back to REVEAL_AGENDA; if both agendas are done it
        advances to READY_PLANETS.

        Returns
        -------
        AgendaPhaseStep | None
            The new current step, or ``None`` once READY_PLANETS is also
            complete (the caller should then call
            :meth:`begin_strategy_phase`).

        Raises
        ------
        ValueError
            If the current game phase is not AGENDA.
        """
        if self.game_state.phase != GamePhase.AGENDA:
            raise ValueError(
                f"advance_agenda_step called outside of Agenda Phase "
                f"(current phase: {self.game_state.phase!r})."
            )
        current = self.game_state.agenda_phase_step

        # REPLENISH_COMMODITIES always leads to REVEAL_AGENDA.
        if current == AgendaPhaseStep.REPLENISH_COMMODITIES:
            next_step = AgendaPhaseStep.REVEAL_AGENDA

        elif current == AgendaPhaseStep.REVEAL_AGENDA:
            next_step = AgendaPhaseStep.VOTE

        elif current == AgendaPhaseStep.VOTE:
            next_step = AgendaPhaseStep.RESOLVE_OUTCOME

        elif current == AgendaPhaseStep.RESOLVE_OUTCOME:
            self.game_state.agendas_resolved += 1
            if self.game_state.agendas_resolved < 2:
                # Start second agenda cycle.
                next_step = AgendaPhaseStep.REVEAL_AGENDA
            else:
                # Both agendas done – ready planets then finish.
                next_step = AgendaPhaseStep.READY_PLANETS

        elif current == AgendaPhaseStep.READY_PLANETS:
            # Agenda Phase fully complete.
            logger.info(
                "agenda_phase_complete",
                game_id=self.game_state.game_id,
                round=self.game_state.round_number,
            )
            return None

        else:  # pragma: no cover
            raise ValueError(f"Unexpected agenda phase step: {current!r}")

        self.game_state.agenda_phase_step = next_step
        logger.info(
            "agenda_step_advanced",
            game_id=self.game_state.game_id,
            round=self.game_state.round_number,
            new_step=next_step,
        )
        return next_step
