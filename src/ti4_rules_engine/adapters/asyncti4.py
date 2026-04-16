"""
Adapter for the AsyncTI4 Discord bot JSON game-state format.

Game data is fetched from the asyncti4 bot web-data API::

    https://bot.asyncti4.com/api/public/game/{gameId}/web-data

The web-data API returns a payload (see ``versionSchema``) that wraps public
objectives in a nested ``objectives`` dict (with ``stage1Objectives``,
``stage2Objectives``, ``allObjectives``, etc.) and derives per-faction scored
public objectives from each objective's ``scoredFactions`` list.

This module provides:

* :class:`AsyncTI4Player` – Pydantic model for a single player entry in the
  AsyncTI4 JSON (``playerData`` array).
* :class:`AsyncTI4GameData` – Pydantic model for the full AsyncTI4 game
  snapshot.
* :func:`from_asyncti4` – converts an :class:`AsyncTI4GameData` (or raw
  ``dict``) into the engine's :class:`~models.state.GameState`.

AsyncTI4 JSON structure notes
------------------------------
* The game identifier is stored in ``gameName``.
* The round number is stored in ``gameRound``.
* There is **no explicit phase field** in the export; the current phase is
  inferred from strategy-card state (see :func:`_infer_phase`).
* The speaker and active player are indicated per-player via the boolean
  ``isSpeaker`` and ``active`` fields respectively.
* Strategy cards held by a player are stored as a list of initiative numbers
  (integers) in the ``scs`` field.
* Technologies are stored in the ``techs`` field.
* Victory points are stored in ``totalVps``.
* Action card IDs are **not** exposed by the export (only ``acCount``).
* Scored secret objectives are the keys of the ``secretsScored`` dict.

Example::

    import json
    from ti4_rules_engine.adapters.asyncti4 import from_asyncti4

    with open("pbd22295.json") as fh:
        raw = json.load(fh)

    state = from_asyncti4(raw)
    print(state.game_id, state.phase, state.round_number)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from ti4_rules_engine.models.state import GamePhase, GameState, PlayerState, TurnOrder

# ---------------------------------------------------------------------------
# Phase mapping
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[str, GamePhase] = {
    "strategy": GamePhase.STRATEGY,
    "action": GamePhase.ACTION,
    "status": GamePhase.STATUS,
    "agenda": GamePhase.AGENDA,
}

_STRATEGY_CARD_SET_KEYS: tuple[str, ...] = (
    "strategyCardSet",
    "strategyCardSetAlias",
    "strategyCardSetId",
    "strategyCardSetID",
    "scSetId",
    "scSetID",
)


# ---------------------------------------------------------------------------
# AsyncTI4 Pydantic schemas – field names match the raw JSON exactly
# ---------------------------------------------------------------------------


class AsyncTI4Player(BaseModel):
    """Per-player data as exported by the AsyncTI4 bot (``playerData`` entry)."""

    userName: str = Field(description="Discord username – used as the player ID.")
    faction: str = Field(description="Faction slug, e.g. 'jolnar'.")
    color: str | None = Field(default=None, description="Player token colour slug.")
    totalVps: int = Field(default=0, ge=0, description="Current victory point total.")
    scs: list[int] = Field(
        default_factory=list,
        description="Initiative numbers of strategy cards held by this player.",
    )
    passed: bool = Field(
        default=False,
        description="True if the player has passed during the current Action Phase.",
    )
    tg: int = Field(default=0, ge=0, description="Current trade-goods count.")
    commodities: int = Field(default=0, ge=0, description="Current commodities count.")
    planets: list[str] = Field(
        default_factory=list, description="IDs of planets controlled by this player."
    )
    exhaustedPlanets: list[str] = Field(
        default_factory=list, description="IDs of planets that are currently exhausted."
    )
    techs: list[str] = Field(
        default_factory=list, description="IDs of technologies researched by this player."
    )
    secretsScored: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Map of secret-objective ID → scoring metadata. "
            "The keys are the IDs of scored secret objectives."
        ),
    )
    isSpeaker: bool = Field(
        default=False, description="True if this player is the current speaker."
    )
    active: bool = Field(
        default=False,
        description="True if this is the currently active player.",
    )

    # Fields present in the export but not directly mapped to PlayerState
    acCount: int = Field(
        default=0,
        ge=0,
        description="Number of Action Cards in hand (IDs are not exposed).",
    )
    eliminated: bool = Field(default=False, description="True if the player has been eliminated.")
    tacticalCC: int = Field(
        default=0,
        ge=0,
        description="Number of command tokens in the player's tactic zone.",
    )
    fleetCC: int = Field(
        default=0,
        ge=0,
        description="Number of command tokens in the player's fleet pool.",
    )
    strategicCC: int = Field(
        default=0,
        ge=0,
        description="Number of command tokens in the player's strategy zone.",
    )
    leaders: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Leader cards (agents, commanders, heroes) held by this player. "
            "Each entry is a dict with at minimum 'id' and optionally 'exhausted', "
            "'locked', and 'type' fields."
        ),
    )
    scoredPublicObjectives: list[str] = Field(
        default_factory=list,
        description="IDs of public objectives this player has scored.",
    )


class AsyncTI4StrategyCard(BaseModel):
    """A single strategy card entry from the top-level ``strategyCards`` array."""

    id: str = Field(description="Card ID, e.g. 'pok1leadership'.")
    initiative: int = Field(description="Initiative value 1–8.")
    picked: bool = Field(default=False, description="True if a player has selected this card.")
    played: bool = Field(
        default=False,
        description="True if the primary ability has been used this round.",
    )


class AsyncTI4GameData(BaseModel):
    """Top-level AsyncTI4 game-state snapshot schema.

    The field names match the raw JSON keys exported by the AsyncTI4 bot.
    Notable differences from the engine's native :class:`~models.state.GameState`:

    * ``gameName`` → ``game_id``
    * ``gameRound`` → ``round_number``
    * ``playerData`` → ``players`` dict
    * ``lawsInPlay`` → ``law_ids``
    * Phase, speaker, and active player are derived from nested player data.
    """

    gameName: str = Field(description="Unique game identifier, e.g. 'pbd22295'.")
    gameRound: int = Field(default=1, ge=1, description="Current game round (1-indexed).")
    playerData: list[AsyncTI4Player] = Field(
        default_factory=list, description="All players in the game."
    )
    lawsInPlay: list[str] = Field(
        default_factory=list, description="IDs of laws currently in effect."
    )

    @field_validator("lawsInPlay", mode="before")
    @classmethod
    def _normalize_laws_in_play(cls, v: object) -> list[str]:
        """Accept both string IDs and full law-object dicts in ``lawsInPlay``.

        Newer AsyncTI4 exports store each law as a dict containing (among
        other fields) an ``"id"`` key.  Older exports (and the engine's own
        test fixtures) store plain string IDs.  This validator normalizes
        both shapes to a plain ``list[str]``.
        """
        if not isinstance(v, list):
            return v  # let Pydantic emit the type error
        result: list[str] = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                if "id" not in item:
                    raise ValueError(
                        f"Law object in 'lawsInPlay' is missing required 'id' field: {item!r}"
                    )
                result.append(str(item["id"]))
            else:
                result.append(item)  # let Pydantic emit the type error
        return result

    strategyCards: list[AsyncTI4StrategyCard] = Field(
        default_factory=list,
        description="Top-level strategy card metadata used to infer the current phase.",
    )
    strategyCardIdMap: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional initiative→strategy-card-id map from AsyncTI4 web-data exports. "
            "Keys are initiative values represented as strings."
        ),
    )
    tileUnitData: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-tile unit and command-counter data keyed by tile position string "
            "(e.g. '211', '000', 'br').  Each value is a dict with 'space', 'planets', "
            "'ccs', and 'anomaly' fields."
        ),
    )
    tilePositions: list[str] = Field(
        default_factory=list,
        description=(
            "Map of tile positions to tile IDs, encoded as 'pos:tileId' strings "
            "(e.g. '212:42').  Used to resolve anomaly subtypes and wormhole adjacency."
        ),
    )
    publicObjectives: list[str] = Field(
        default_factory=list,
        description="IDs of public objective cards that have been revealed during the game.",
    )

    objectives: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Nested objectives structure from the web-data API.  Contains "
            "'allObjectives', 'stage1Objectives', 'stage2Objectives', and "
            "'customObjectives' sub-lists, each holding full objective objects "
            "with 'key', 'revealed', and 'scoredFactions' fields.  When present "
            "and 'publicObjectives' is empty, the revealed stage-I and stage-II "
            "objective IDs are extracted automatically."
        ),
    )

    @model_validator(mode="after")
    def _populate_public_objectives_from_nested(self) -> AsyncTI4GameData:
        """Derive ``publicObjectives`` from the web-data ``objectives`` block when absent.

        Older S3 snapshots supply ``publicObjectives`` directly as a flat list
        of string IDs.  The newer web-data API omits that field but exposes the
        same information via ``objectives.stage1Objectives`` and
        ``objectives.stage2Objectives`` (each entry has a ``key`` field and a
        ``revealed`` boolean).  This validator bridges the two formats so that
        downstream code always sees a populated ``publicObjectives`` list.
        """
        if self.publicObjectives:
            return self  # already populated from the legacy S3 format
        stage1: list[Any] = self.objectives.get("stage1Objectives", [])
        stage2: list[Any] = self.objectives.get("stage2Objectives", [])
        self.publicObjectives = [
            obj["key"]
            for obj in (stage1 + stage2)
            if isinstance(obj, dict) and obj.get("revealed") and obj.get("key")
        ]
        return self


# ---------------------------------------------------------------------------
# Phase inference
# ---------------------------------------------------------------------------


def _infer_phase(data: AsyncTI4GameData) -> GamePhase:
    """Infer the current game phase from strategy-card state.

    The AsyncTI4 export does not include an explicit phase field.
    The heuristic used here:

    * If no strategy cards exist in the export → **STRATEGY** phase (default).
    * If any strategy card has been played (primary ability used) → **ACTION** phase.
    * If picked card count reached the expected total for the current player
      count (allowing unpicked skipped cards) → **ACTION** phase.
    * If all strategy cards have been picked → **ACTION** phase.
    * Otherwise → **STRATEGY** phase (picking still in progress).

    The heuristic cannot distinguish between the Action, Status, and Agenda
    phases once picking is complete.  Callers that need precise phase
    information should override ``phase`` on the returned ``GameState``.
    """
    if not data.strategyCards:
        return GamePhase.STRATEGY

    # If any card's primary ability has been used, we're in the action phase
    if any(sc.played for sc in data.strategyCards):
        return GamePhase.ACTION

    # In many games not all 8 cards are picked (some are skipped based on player
    # count). Infer expected picks from non-eliminated, non-neutral players.
    picked_cards = [sc for sc in data.strategyCards if sc.picked]
    unpicked_cards = [sc for sc in data.strategyCards if not sc.picked]

    active_players = [
        p
        for p in data.playerData
        if not p.eliminated and p.faction.lower() != "neutral"
    ]
    player_count = len(active_players)
    if player_count > 0:
        # Assumes standard TI4-style equal picks per player for the current
        # player count (with remainder cards skipped).
        cards_per_player = len(data.strategyCards) // player_count
        expected_picks = cards_per_player * player_count
        if expected_picks > 0 and len(picked_cards) >= expected_picks:
            return GamePhase.ACTION

    # Fallback when expected picks cannot be inferred.
    if picked_cards and not unpicked_cards:
        return GamePhase.ACTION

    return GamePhase.STRATEGY


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
        If no player has ``isSpeaker: true`` in the export.

    Notes
    -----
    * Action card IDs are **not** exposed by the AsyncTI4 export;
      ``PlayerState.action_cards`` will always be an empty list.
    * Promissory notes in hand are similarly not exposed;
      ``PlayerState.promissory_notes`` will always be an empty list.
    * The game phase is inferred (see :func:`_infer_phase`).
      Override ``GameState.phase`` after conversion if needed.
    """
    strategy_card_set: str | None = None
    if isinstance(data, dict):
        strategy_card_set = _extract_strategy_card_set_identifier(data)
        data = AsyncTI4GameData.model_validate(data)

    phase = _infer_phase(data)

    # Identify speaker and active player from per-player flags.
    # The "neutral" faction is used by the Dicecord dice-rolling service, which
    # is not a real player and must be excluded from the analysis.
    speaker_id: str | None = None
    active_player_id: str | None = None
    for p in data.playerData:
        if p.faction == "neutral":
            continue
        if p.isSpeaker:
            speaker_id = p.userName
        if p.active:
            active_player_id = p.userName

    if speaker_id is None:
        raise ValueError(
            "No player has 'isSpeaker: true' in the AsyncTI4 export. "
            "Cannot determine the speaker."
        )

    # Build player states keyed by userName, skipping eliminated players and
    # the Dicecord service account (faction == "neutral").

    # The web-data API does not store scored public objectives per player;
    # instead, each objective entry records which factions scored it via a
    # ``scoredFactions`` list.  Build a faction → [obj_id, …] map from the
    # stage-I and stage-II sub-lists so that players whose per-player
    # ``scoredPublicObjectives`` list is empty can still have their scored
    # public objectives populated correctly.
    faction_scored_public: dict[str, list[str]] = {}
    if data.objectives:
        stage1: list[Any] = data.objectives.get("stage1Objectives", [])
        stage2: list[Any] = data.objectives.get("stage2Objectives", [])
        for obj in stage1 + stage2:
            if not isinstance(obj, dict):
                continue
            key = obj.get("key")
            if not key:
                continue
            for faction in obj.get("scoredFactions", []):
                faction_scored_public.setdefault(str(faction), []).append(key)

    players: dict[str, PlayerState] = {}
    player_colors: dict[str, str] = {}
    player_leaders: dict[str, list[dict[str, Any]]] = {}
    for p in data.playerData:
        if p.eliminated:
            continue
        if p.faction == "neutral":
            continue
        # Prefer per-player scoredPublicObjectives (legacy S3 format); fall back
        # to the faction-keyed map derived from the web-data objectives block.
        scored_public = p.scoredPublicObjectives or faction_scored_public.get(p.faction, [])
        # Combine scored secrets and scored public objectives into one list
        scored = list(p.secretsScored.keys()) + list(scored_public)
        players[p.userName] = PlayerState(
            player_id=p.userName,
            faction_id=p.faction,
            victory_points=p.totalVps,
            # scs are initiative numbers (ints); convert to strings for GameState
            strategy_card_ids=[str(sc) for sc in p.scs],
            passed=p.passed,
            trade_goods=p.tg,
            commodities=p.commodities,
            # Action card IDs are private in AsyncTI4 exports
            action_cards=[],
            controlled_planets=p.planets,
            exhausted_planets=p.exhaustedPlanets,
            researched_technologies=p.techs,
            # Promissory notes in hand are private in AsyncTI4 exports
            promissory_notes=[],
            # secretsScored keys + scoredPublicObjectives
            scored_objectives=scored,
            tactical_tokens=p.tacticalCC,
            fleet_tokens=p.fleetCC,
            strategy_tokens=p.strategicCC,
        )
        if p.color:
            player_colors[p.userName] = p.color
        if p.leaders:
            player_leaders[p.userName] = p.leaders

    player_ids = list(players.keys())

    if speaker_id not in player_ids:
        raise ValueError(
            f"Speaker '{speaker_id}' is not present in the (non-eliminated) player list: "
            f"{player_ids}"
        )

    turn_order = TurnOrder(speaker_id=speaker_id, order=player_ids)

    # Extract full objective display data (name, description, points) from the
    # web-data API objectives block.  The API uses "pointValue" instead of
    # "points" and includes "name" and optionally "description" for each entry.
    # This data is stored in extra["objective_data"] so that analyze_game.py can
    # show proper names and descriptions for objectives not present in the
    # bundled public_objectives.json (e.g. expansion/custom objectives).
    api_objective_data: dict[str, dict[str, Any]] = {}
    if data.objectives:
        for sublist_key in ("stage1Objectives", "stage2Objectives", "customObjectives"):
            obj_type = {
                "stage1Objectives": "stage_1",
                "stage2Objectives": "stage_2",
            }.get(sublist_key, "custom")
            for obj in data.objectives.get(sublist_key, []):
                if not isinstance(obj, dict):
                    continue
                key = obj.get("key")
                if not key:
                    continue
                if key not in api_objective_data:
                    entry: dict[str, Any] = {"id": key, "type": obj_type}
                    if "name" in obj:
                        entry["name"] = obj["name"]
                    # The API uses "pointValue"; normalise to "points"
                    pts = obj.get("pointValue") or obj.get("points")
                    if pts is not None:
                        entry["points"] = pts
                    else:
                        # Fallback: Stage I objectives are 1 VP, Stage II are 2 VP
                        # per the base game rules.
                        entry["points"] = 2 if obj_type == "stage_2" else 1
                    if "description" in obj:
                        entry["description"] = obj["description"]
                    api_objective_data[key] = entry

    strategy_card_id_map: dict[str, str] = {
        str(initiative): str(card_id)
        for initiative, card_id in data.strategyCardIdMap.items()
        if str(card_id).strip()
    }
    for card in data.strategyCards:
        if card.initiative > 0 and card.id:
            strategy_card_id_map.setdefault(str(card.initiative), card.id)

    return GameState(
        game_id=data.gameName,
        round_number=data.gameRound,
        phase=phase,
        turn_order=turn_order,
        players=players,
        active_player_id=active_player_id,
        law_ids=data.lawsInPlay,
        public_objectives=data.publicObjectives,
        extra={
            "player_colors": player_colors,
            "player_leaders": player_leaders,
            "tile_unit_data": data.tileUnitData,
            "tile_positions": {
                pos: tile_id
                for entry in data.tilePositions
                if ":" in entry
                for pos, tile_id in [entry.split(":", 1)]
            },
            "objective_data": api_objective_data,
            "strategy_card_id_map": strategy_card_id_map,
            "strategy_card_set": strategy_card_set,
        },
    )


def _extract_strategy_card_set_identifier(raw_data: dict[str, Any]) -> str | None:
    """Extract strategy-card set identifier from known AsyncTI4 payload keys."""
    for key in _STRATEGY_CARD_SET_KEYS:
        value = raw_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("alias", "id", "name"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return None
