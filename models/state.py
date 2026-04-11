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
    trade_goods: int = Field(default=0, ge=0)
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
