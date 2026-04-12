"""Game state model – the root serialisable object for a TI4 session."""

from __future__ import annotations

import copy
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class GamePhase(StrEnum):
    """The high-level phases of a TI4 round."""

    STRATEGY = "strategy"
    ACTION = "action"
    STATUS = "status"
    AGENDA = "agenda"


class StatusPhaseStep(StrEnum):
    """
    The eight ordered steps of the TI4 Status Phase.

    Sequence (per the Living Rules Reference):
    1. SCORE_OBJECTIVES
    2. REVEAL_PUBLIC_OBJECTIVE
    3. DRAW_ACTION_CARDS
    4. REMOVE_COMMAND_TOKENS
    5. GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS
    6. READY_CARDS
    7. REPAIR_UNITS
    8. RETURN_STRATEGY_CARDS
    """

    SCORE_OBJECTIVES = "score_objectives"
    REVEAL_PUBLIC_OBJECTIVE = "reveal_public_objective"
    DRAW_ACTION_CARDS = "draw_action_cards"
    REMOVE_COMMAND_TOKENS = "remove_command_tokens"
    GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS = "gain_and_redistribute_command_tokens"
    READY_CARDS = "ready_cards"
    REPAIR_UNITS = "repair_units"
    RETURN_STRATEGY_CARDS = "return_strategy_cards"


# Ordered sequence used to advance through the Status Phase.
STATUS_PHASE_STEPS: list[StatusPhaseStep] = [
    StatusPhaseStep.SCORE_OBJECTIVES,
    StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE,
    StatusPhaseStep.DRAW_ACTION_CARDS,
    StatusPhaseStep.REMOVE_COMMAND_TOKENS,
    StatusPhaseStep.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS,
    StatusPhaseStep.READY_CARDS,
    StatusPhaseStep.REPAIR_UNITS,
    StatusPhaseStep.RETURN_STRATEGY_CARDS,
]


class AgendaPhaseStep(StrEnum):
    """
    The ordered steps of the TI4 Agenda Phase.

    The Agenda Phase resolves two agendas per round.  Each agenda follows
    the sub-sequence REPLENISH_COMMODITIES → REVEAL_AGENDA → VOTE →
    RESOLVE_OUTCOME; READY_PLANETS is performed once after both agendas.

    Sequence (per the Living Rules Reference):
    1. REPLENISH_COMMODITIES  (once, before first agenda)
    2. REVEAL_AGENDA          (before each agenda vote)
    3. VOTE                   (each agenda)
    4. RESOLVE_OUTCOME        (each agenda)
    5. READY_PLANETS          (once, after both agendas)
    """

    REPLENISH_COMMODITIES = "replenish_commodities"
    REVEAL_AGENDA = "reveal_agenda"
    VOTE = "vote"
    RESOLVE_OUTCOME = "resolve_outcome"
    READY_PLANETS = "ready_planets"


# Ordered sequence used to advance through one agenda cycle.
# REPLENISH_COMMODITIES appears only once (before the first agenda).
AGENDA_PHASE_STEPS: list[AgendaPhaseStep] = [
    AgendaPhaseStep.REPLENISH_COMMODITIES,
    AgendaPhaseStep.REVEAL_AGENDA,
    AgendaPhaseStep.VOTE,
    AgendaPhaseStep.RESOLVE_OUTCOME,
]


class TurnOrder(BaseModel):
    """Encapsulates speaker position and the ordered list of player IDs."""

    speaker_id: str = Field(description="Player ID of the current speaker.")
    order: list[str] = Field(
        description="Player IDs in clockwise order, starting with the speaker."
    )

    @model_validator(mode="after")
    def speaker_must_be_in_order(self) -> "TurnOrder":
        if self.speaker_id not in self.order:
            raise ValueError(
                f"speaker_id '{self.speaker_id}' must be present in the turn order list."
            )
        return self


class PlayerState(BaseModel):
    """Snapshot of a single player's in-game status."""

    player_id: str
    faction_id: str
    victory_points: int = Field(default=0, ge=0)
    strategy_card_ids: list[str] = Field(default_factory=list)
    passed: bool = Field(default=False, description="True if the player has passed this round.")
    commodities: int = Field(default=0, ge=0)
    commodities_cap: int = Field(
        default=3,
        ge=0,
        description="Maximum commodities this player can hold (faction-dependent).",
    )
    trade_goods: int = Field(default=0, ge=0)
    command_tokens: int = Field(
        default=0,
        ge=0,
        description="Number of command tokens on this player's command sheet.",
    )
    action_cards: list[str] = Field(default_factory=list, description="Hand of Action Card IDs.")
    promissory_notes: list[str] = Field(
        default_factory=list, description="Promissory Note card IDs in hand."
    )
    researched_technologies: list[str] = Field(
        default_factory=list, description="IDs of researched technologies."
    )
    controlled_planets: list[str] = Field(
        default_factory=list, description="IDs of planets controlled by this player."
    )
    exhausted_planets: list[str] = Field(
        default_factory=list, description="IDs of planets that are currently exhausted."
    )
    scored_objectives: list[str] = Field(
        default_factory=list, description="IDs of objectives this player has scored."
    )


class GameState(BaseModel):
    """
    Root serialisable object for a complete TI4 game session.

    Designed to be fully JSON-round-trippable via ``model_dump`` / ``model_validate``
    to support undo/redo and async play persistence.
    """

    game_id: str = Field(description="Unique identifier for this game session.")
    round_number: int = Field(default=1, ge=1, description="Current game round (1-indexed).")
    phase: GamePhase = Field(default=GamePhase.STRATEGY, description="Current game phase.")
    status_phase_step: StatusPhaseStep = Field(
        default=StatusPhaseStep.SCORE_OBJECTIVES,
        description="Current step within the Status Phase.",
    )
    agenda_phase_step: AgendaPhaseStep = Field(
        default=AgendaPhaseStep.REPLENISH_COMMODITIES,
        description="Current step within the Agenda Phase.",
    )
    agendas_resolved: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of agendas resolved so far in the current Agenda Phase. "
            "Two agendas are resolved per round."
        ),
    )
    turn_order: TurnOrder
    players: dict[str, PlayerState] = Field(
        default_factory=dict,
        description="Map of player_id → PlayerState for all players in the game.",
    )
    active_player_id: str | None = Field(
        default=None,
        description="Player ID whose turn it currently is. None between turns.",
    )
    agenda_phase_enabled: bool = Field(
        default=True, description="False if the Agenda phase is disabled (rarely used variant)."
    )
    law_ids: list[str] = Field(
        default_factory=list, description="IDs of laws currently in effect."
    )
    public_objectives: list[str] = Field(
        default_factory=list, description="IDs of revealed public objective cards."
    )
    secret_objectives_scored: list[str] = Field(
        default_factory=list, description="IDs of all scored secret objectives (any player)."
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Extensible bag for variant rules or bot-specific metadata "
            "that does not fit into the core schema."
        ),
    )

    # ------------------------------------------------------------------
    # Undo / Redo support
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-copy JSON-safe snapshot of the current state."""
        return self.model_dump(mode="json")

    @classmethod
    def restore(cls, snapshot: dict[str, Any]) -> "GameState":
        """Reconstruct a ``GameState`` from a previously taken snapshot."""
        return cls.model_validate(snapshot)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> "GameState":
        """Return a *new* ``GameState`` built from ``snapshot`` (immutable style)."""
        return GameState.restore(copy.deepcopy(snapshot))

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_player(self, player_id: str) -> PlayerState:
        """Return the ``PlayerState`` for *player_id*, raising ``KeyError`` if absent."""
        try:
            return self.players[player_id]
        except KeyError:
            raise KeyError(f"No player with id '{player_id}' in this game.") from None

    def all_players_passed(self) -> bool:
        """Return True when every player has passed (end of Action Phase)."""
        return all(p.passed for p in self.players.values())
