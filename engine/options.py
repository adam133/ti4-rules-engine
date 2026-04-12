"""
Player options engine – returns rules-allowable actions for a player.

Given a :class:`~models.state.GameState` and a ``player_id``, the
:func:`get_player_options` function returns a :class:`PlayerOptions` object
that lists every action the player is permitted to take under the rules of
Twilight Imperium 4th Edition.

The engine is **permissive**: it returns what is *allowed*, not what is
*optimal*.  Callers (e.g. Discord bots, web UIs) decide how to present and
enforce these options.

Example::

    from engine.options import get_player_options
    from models.state import GamePhase

    options = get_player_options(state, player_id="alice")
    print(options.phase, options.available_actions)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from models.objective import Objective
from models.planet import Planet
from models.state import AgendaPhaseStep, GamePhase, GameState, StatusPhaseStep
from models.technology import Technology


class PlayerAction(StrEnum):
    """Enumeration of rules-legal actions a player may take."""

    # --- Strategy Phase ---
    PICK_STRATEGY_CARD = "pick_strategy_card"
    """Choose one of the available strategy cards."""

    # --- Action Phase ---
    TACTICAL_ACTION = "tactical_action"
    """Activate a system: move units and optionally produce units."""

    STRATEGIC_ACTION = "strategic_action"
    """Use the primary ability of a held strategy card."""

    COMPONENT_ACTION = "component_action"
    """Play an Action Card or use a technology/faction ability with Action timing."""

    PASS = "pass"
    """End your participation in the Action Phase for this round."""

    # --- Status Phase ---
    SCORE_OBJECTIVE = "score_objective"
    """Score a public or secret objective (step 1)."""

    REVEAL_PUBLIC_OBJECTIVE = "reveal_public_objective"
    """Speaker reveals the next public objective card (step 2)."""

    DRAW_ACTION_CARDS = "draw_action_cards"
    """Each player draws action cards (step 3)."""

    REMOVE_COMMAND_TOKENS = "remove_command_tokens"
    """Each player removes their command tokens from the board (step 4)."""

    GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS = "gain_and_redistribute_command_tokens"
    """Each player gains 2 command tokens and may redistribute them (step 5)."""

    READY_CARDS = "ready_cards"
    """Ready exhausted planets and cards (step 6)."""

    REPAIR_UNITS = "repair_units"
    """Each player repairs all damaged units (step 7)."""

    RETURN_STRATEGY_CARDS = "return_strategy_cards"
    """Each player returns their strategy cards to the common area (step 8)."""

    # --- Agenda Phase ---
    REPLENISH_COMMODITIES = "replenish_commodities"
    """Each player replenishes commodities to their faction maximum (step 1)."""

    REVEAL_AGENDA = "reveal_agenda"
    """Speaker draws and reads the next agenda card aloud (step 2)."""

    CAST_VOTES = "cast_votes"
    """Vote on the current agenda using influence from exhausted planets (step 3)."""

    ABSTAIN = "abstain"
    """Abstain from voting on the current agenda (step 3 alternative)."""

    RESOLVE_OUTCOME = "resolve_outcome"
    """Tally votes and resolve the agenda outcome (step 4)."""

    READY_PLANETS = "ready_planets"
    """Ready all planets exhausted for voting during the Agenda Phase (after both agendas)."""


class PlayerOptions(BaseModel):
    """The set of rules-allowable options for a player at a given moment."""

    player_id: str = Field(description="The player these options apply to.")
    phase: GamePhase = Field(description="The current game phase.")
    available_actions: list[PlayerAction] = Field(
        default_factory=list,
        description="Ordered list of actions the player may legally take.",
    )
    passed: bool = Field(
        default=False,
        description="True if the player has already passed this Action Phase.",
    )

    @property
    def can_act(self) -> bool:
        """Return ``True`` if the player has at least one available action."""
        return len(self.available_actions) > 0


def get_player_options(state: GameState, player_id: str) -> PlayerOptions:
    """Return the rules-allowable options for *player_id* in *state*.

    Parameters
    ----------
    state:
        The current game state.
    player_id:
        The ID of the player to evaluate.

    Returns
    -------
    PlayerOptions
        Object containing the list of legal actions and relevant metadata.

    Raises
    ------
    KeyError
        If *player_id* is not present in *state*.

    Notes
    -----
    The logic follows standard TI4 rules:

    * **Strategy Phase** – a player may pick a strategy card only if they do
      not already hold one.
    * **Action Phase** – a player who has not yet passed may take a
      *tactical*, *strategic* (if they hold a strategy card), or *component*
      action, or they may pass.  A player who has already passed has no
      available actions.
    * **Status Phase** – all players advance through 8 ordered steps together.
      The current step is tracked on ``state.status_phase_step``.  Only the
      actions relevant to the current step are returned.  Speaker-only steps
      (REVEAL_PUBLIC_OBJECTIVE) are only returned for the speaker.
    * **Agenda Phase** – all players advance through ordered steps for each of
      two agendas per round.  The current step is tracked on
      ``state.agenda_phase_step``.  Speaker-only steps (REVEAL_AGENDA,
      RESOLVE_OUTCOME) are only returned for the speaker.  REPLENISH_COMMODITIES
      occurs once before the first agenda.
    """
    player = state.get_player(player_id)
    phase = state.phase
    actions: list[PlayerAction] = []
    is_speaker = (player_id == state.turn_order.speaker_id)

    if phase == GamePhase.STRATEGY:
        # A player picks a strategy card only if they do not yet hold one.
        if not player.strategy_card_ids:
            actions.append(PlayerAction.PICK_STRATEGY_CARD)

    elif phase == GamePhase.ACTION:
        if not player.passed:
            actions.append(PlayerAction.TACTICAL_ACTION)
            actions.append(PlayerAction.COMPONENT_ACTION)
            # Strategic action requires holding at least one strategy card.
            if player.strategy_card_ids:
                actions.append(PlayerAction.STRATEGIC_ACTION)
            actions.append(PlayerAction.PASS)

    elif phase == GamePhase.STATUS:
        step = state.status_phase_step

        if step == StatusPhaseStep.SCORE_OBJECTIVES:
            actions.append(PlayerAction.SCORE_OBJECTIVE)

        elif step == StatusPhaseStep.REVEAL_PUBLIC_OBJECTIVE:
            # Only the speaker reveals the next public objective.
            if is_speaker:
                actions.append(PlayerAction.REVEAL_PUBLIC_OBJECTIVE)

        elif step == StatusPhaseStep.DRAW_ACTION_CARDS:
            actions.append(PlayerAction.DRAW_ACTION_CARDS)

        elif step == StatusPhaseStep.REMOVE_COMMAND_TOKENS:
            actions.append(PlayerAction.REMOVE_COMMAND_TOKENS)

        elif step == StatusPhaseStep.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS:
            actions.append(PlayerAction.GAIN_AND_REDISTRIBUTE_COMMAND_TOKENS)

        elif step == StatusPhaseStep.READY_CARDS:
            actions.append(PlayerAction.READY_CARDS)

        elif step == StatusPhaseStep.REPAIR_UNITS:
            actions.append(PlayerAction.REPAIR_UNITS)

        elif step == StatusPhaseStep.RETURN_STRATEGY_CARDS:
            actions.append(PlayerAction.RETURN_STRATEGY_CARDS)

    elif phase == GamePhase.AGENDA:
        step = state.agenda_phase_step

        if step == AgendaPhaseStep.REPLENISH_COMMODITIES:
            actions.append(PlayerAction.REPLENISH_COMMODITIES)

        elif step == AgendaPhaseStep.REVEAL_AGENDA:
            # Only the speaker reveals the agenda card.
            if is_speaker:
                actions.append(PlayerAction.REVEAL_AGENDA)

        elif step == AgendaPhaseStep.VOTE:
            actions.append(PlayerAction.CAST_VOTES)
            actions.append(PlayerAction.ABSTAIN)

        elif step == AgendaPhaseStep.RESOLVE_OUTCOME:
            # Outcome resolution is handled by the speaker/facilitator.
            if is_speaker:
                actions.append(PlayerAction.RESOLVE_OUTCOME)

        elif step == AgendaPhaseStep.READY_PLANETS:
            actions.append(PlayerAction.READY_PLANETS)

    return PlayerOptions(
        player_id=player_id,
        phase=phase,
        available_actions=actions,
        passed=player.passed,
    )


class PublicPlayerInfo(BaseModel):
    """Publicly observable options and scoring potential for a player.

    Unlike :class:`PlayerOptions`, this object is derived from *public* game
    state only – it excludes information that is private to the player (action
    cards, promissory notes, secret objectives, faction abilities with Action
    timing).  It is suitable for representing what an opponent can *potentially*
    do or score as seen from the outside.
    """

    player_id: str = Field(description="The player these options apply to.")
    phase: GamePhase = Field(description="The current game phase.")
    available_actions: list[PlayerAction] = Field(
        default_factory=list,
        description=(
            "Ordered list of publicly observable actions the player may legally take. "
            "Does not include component_action as that requires knowledge of the "
            "player's private action cards."
        ),
    )
    passed: bool = Field(
        default=False,
        description="True if the player has already passed this Action Phase.",
    )
    scoreable_points: int = Field(
        default=0,
        description=(
            "Total VP the player can provably score from revealed public objectives right now."
        ),
    )
    scoreable_objective_ids: list[str] = Field(
        default_factory=list,
        description="IDs of revealed public objectives the player can provably score right now.",
    )

    @property
    def can_act(self) -> bool:
        """Return ``True`` if the player has at least one available public action."""
        return len(self.available_actions) > 0


def get_public_player_info(
    state: GameState,
    player_id: str,
    *,
    objectives: list[Objective] | None = None,
    planet_registry: dict[str, Planet] | None = None,
    tech_registry: dict[str, Technology] | None = None,
) -> PublicPlayerInfo:
    """Return publicly observable actions and scoring potential for *player_id*.

    Unlike :func:`get_player_options`, this function evaluates the player's
    state using **public information only** – it is suitable for generating
    what an opponent can potentially do or score as seen from the outside.

    Differences from :func:`get_player_options`:

    * ``component_action`` is *not* included in the Action Phase because it
      requires knowledge of the player's private action cards.
    * Scoring is evaluated only against **revealed public objectives** (those
      present in ``state.public_objectives``).  Secret objectives are excluded.

    Parameters
    ----------
    state:
        The current game state.
    player_id:
        The ID of the player to evaluate.
    objectives:
        Optional pool of :class:`~models.objective.Objective` objects to
        evaluate for scoring.  Only objectives whose IDs appear in
        ``state.public_objectives`` will be considered.  If ``None``, scoring
        fields are left at zero / empty.
    planet_registry:
        Optional mapping of ``planet_id → Planet``.  Required to evaluate
        planet-based scoring conditions.
    tech_registry:
        Optional mapping of ``tech_id → Technology``.  Required to evaluate
        technology-based scoring conditions.

    Returns
    -------
    PublicPlayerInfo
        Object containing publicly observable actions and scoring potential.

    Raises
    ------
    KeyError
        If *player_id* is not present in *state*.
    """
    from engine.scoring import can_score_objective

    base_opts = get_player_options(state, player_id)

    # Exclude component_action: requires private action card knowledge.
    public_actions = [
        a for a in base_opts.available_actions if a != PlayerAction.COMPONENT_ACTION
    ]

    # Scoring: evaluate only revealed public objectives.
    scoreable_points = 0
    scoreable_objective_ids: list[str] = []

    if objectives is not None:
        public_obj_ids = set(state.public_objectives)
        player = state.get_player(player_id)
        already_scored = set(player.scored_objectives)

        for obj in objectives:
            if obj.id not in public_obj_ids:
                continue
            if obj.id in already_scored:
                continue
            result = can_score_objective(
                obj,
                state,
                player_id,
                planet_registry=planet_registry,
                tech_registry=tech_registry,
            )
            if result is True:
                scoreable_points += obj.points
                scoreable_objective_ids.append(obj.id)

    return PublicPlayerInfo(
        player_id=player_id,
        phase=base_opts.phase,
        available_actions=public_actions,
        passed=base_opts.passed,
        scoreable_points=scoreable_points,
        scoreable_objective_ids=scoreable_objective_ids,
    )


def get_all_opponents_public_info(
    state: GameState,
    viewing_player_id: str,
    *,
    objectives: list[Objective] | None = None,
    planet_registry: dict[str, Planet] | None = None,
    tech_registry: dict[str, Technology] | None = None,
) -> dict[str, PublicPlayerInfo]:
    """Return publicly observable options and scoring potential for all opponents.

    Iterates over every player in *state* except *viewing_player_id* and calls
    :func:`get_public_player_info` for each.

    Parameters
    ----------
    state:
        The current game state.
    viewing_player_id:
        The player whose perspective we are representing.  This player is
        excluded from the returned mapping.
    objectives:
        Optional pool of :class:`~models.objective.Objective` objects to
        evaluate for scoring.  See :func:`get_public_player_info`.
    planet_registry:
        Optional mapping of ``planet_id → Planet``.  See
        :func:`get_public_player_info`.
    tech_registry:
        Optional mapping of ``tech_id → Technology``.  See
        :func:`get_public_player_info`.

    Returns
    -------
    dict[str, PublicPlayerInfo]
        Mapping of ``opponent_id → PublicPlayerInfo`` for every player other
        than *viewing_player_id*.

    Raises
    ------
    KeyError
        If *viewing_player_id* is not present in *state*.
    """
    # Validate that the viewing player exists.
    state.get_player(viewing_player_id)

    return {
        pid: get_public_player_info(
            state,
            pid,
            objectives=objectives,
            planet_registry=planet_registry,
            tech_registry=tech_registry,
        )
        for pid in state.players
        if pid != viewing_player_id
    }
