"""
Adapter for the AsyncTI4 Discord bot JSON game-state format.

The AsyncTI4 bot exports a JSON snapshot of each game to S3 at::

    https://s3.us-east-1.amazonaws.com/asyncti4.com/webdata/{gameId}/{gameId}.json

This module provides:

* :class:`AsyncTI4Player` – Pydantic model for a single player entry in the
  AsyncTI4 JSON.
* :class:`AsyncTI4GameData` – Pydantic model for the full AsyncTI4 game
  snapshot.
* :func:`from_asyncti4` – converts an :class:`AsyncTI4GameData` (or raw
  ``dict``) into the engine's :class:`~models.state.GameState`.

Example::

    import json
    from adapters.asyncti4 import from_asyncti4

    with open("pbd22295.json") as fh:
        raw = json.load(fh)

    state = from_asyncti4(raw)
    print(state.game_id, state.phase, state.round_number)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from models.state import GamePhase, GameState, PlayerState, TurnOrder

# ---------------------------------------------------------------------------
# Phase mapping – AsyncTI4 uses lowercase strings identical to the engine's
# GamePhase StrEnum values, but we normalise to guard against casing drift.
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[str, GamePhase] = {
    "strategy": GamePhase.STRATEGY,
    "action": GamePhase.ACTION,
    "status": GamePhase.STATUS,
    "agenda": GamePhase.AGENDA,
}


# ---------------------------------------------------------------------------
# AsyncTI4 Pydantic schemas
# ---------------------------------------------------------------------------


class AsyncTI4Player(BaseModel):
    """Per-player data as exported by the AsyncTI4 bot."""

    userName: str = Field(description="Discord username – used as the player ID.")
    faction: str = Field(description="Faction slug, e.g. 'nekro_virus'.")
    color: str | None = Field(default=None, description="Player token colour.")
    victoryPoints: int = Field(default=0, ge=0)
    strategyCards: list[str] = Field(
        default_factory=list,
        description="IDs of strategy cards currently held by this player.",
    )
    passed: bool = Field(
        default=False,
        description="True if the player has passed during the current Action Phase.",
    )
    tg: int = Field(default=0, ge=0, description="Current trade-goods count.")
    commodities: int = Field(default=0, ge=0, description="Current commodities count.")
    actionCards: list[str] = Field(
        default_factory=list,
        description="IDs of Action Cards in hand (may be absent in older exports).",
    )
    planets: list[str] = Field(
        default_factory=list, description="IDs of planets controlled by this player."
    )
    exhaustedPlanets: list[str] = Field(
        default_factory=list, description="IDs of planets that are currently exhausted."
    )
    technologies: list[str] = Field(
        default_factory=list, description="IDs of technologies researched by this player."
    )
    promissoryNotesInHand: list[str] = Field(
        default_factory=list, description="IDs of Promissory Notes currently in hand."
    )
    scoredSecrets: list[str] = Field(
        default_factory=list,
        description="IDs of Secret Objectives this player has scored.",
    )


class AsyncTI4GameData(BaseModel):
    """Top-level AsyncTI4 game-state snapshot schema."""

    gameId: str = Field(description="Unique game identifier, e.g. 'pbd22295'.")
    round: int = Field(default=1, ge=1, description="Current game round (1-indexed).")
    phase: str = Field(default="strategy", description="Current game phase string.")
    speaker: str = Field(description="userName of the current speaker.")
    players: list[AsyncTI4Player] = Field(
        default_factory=list, description="All players in turn order."
    )
    laws: list[str] = Field(
        default_factory=list, description="IDs of laws currently in effect."
    )
    publicObjectives: list[str] = Field(
        default_factory=list, description="IDs of revealed public objective cards."
    )
    scoredSecretObjectives: list[str] = Field(
        default_factory=list,
        description="IDs of all scored secret objectives across all players.",
    )
    activePlayerName: str | None = Field(
        default=None,
        description="userName of the currently active player, if any.",
    )

    @field_validator("phase", mode="before")
    @classmethod
    def normalise_phase(cls, v: Any) -> str:
        """Normalise phase to lower-case so casing differences are handled."""
        return str(v).lower()


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def from_asyncti4(data: dict[str, Any] | AsyncTI4GameData) -> GameState:
    """Convert AsyncTI4 JSON data into the engine's :class:`~models.state.GameState`.

    Parameters
    ----------
    data:
        Either a raw dictionary (as produced by ``json.load``) or a
        pre-validated :class:`AsyncTI4GameData` instance.

    Returns
    -------
    GameState
        An engine-native game state ready to be passed to :class:`~engine.RoundEngine`
        or :func:`~engine.options.get_player_options`.

    Raises
    ------
    pydantic.ValidationError
        If *data* does not conform to the :class:`AsyncTI4GameData` schema.
    ValueError
        If the speaker is not present in the player list.
    """
    if isinstance(data, dict):
        data = AsyncTI4GameData.model_validate(data)

    phase = _PHASE_MAP.get(data.phase, GamePhase.STRATEGY)

    # Build player states keyed by userName
    players: dict[str, PlayerState] = {}
    for p in data.players:
        players[p.userName] = PlayerState(
            player_id=p.userName,
            faction_id=p.faction,
            victory_points=p.victoryPoints,
            strategy_card_ids=p.strategyCards,
            passed=p.passed,
            trade_goods=p.tg,
            commodities=p.commodities,
            action_cards=p.actionCards,
            controlled_planets=p.planets,
            exhausted_planets=p.exhaustedPlanets,
            researched_technologies=p.technologies,
            promissory_notes=p.promissoryNotesInHand,
            scored_objectives=p.scoredSecrets,
        )

    player_ids = [p.userName for p in data.players]

    # Validate that the speaker is in the player list before building TurnOrder
    if data.speaker not in player_ids:
        raise ValueError(
            f"Speaker '{data.speaker}' is not present in the player list: {player_ids}"
        )

    turn_order = TurnOrder(speaker_id=data.speaker, order=player_ids)

    return GameState(
        game_id=data.gameId,
        round_number=data.round,
        phase=phase,
        turn_order=turn_order,
        players=players,
        active_player_id=data.activePlayerName,
        law_ids=data.laws,
        public_objectives=data.publicObjectives,
        secret_objectives_scored=data.scoredSecretObjectives,
    )
