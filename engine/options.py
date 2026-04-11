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

from models.state import GamePhase, GameState


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
    """Score a public or secret objective."""

    READY_CARDS = "ready_cards"
    """Ready exhausted planets and units; return strategy card(s)."""

    # --- Agenda Phase ---
    CAST_VOTES = "cast_votes"
    """Vote on the current agenda using influence from exhausted planets."""

    ABSTAIN = "abstain"
    """Abstain from voting on the current agenda."""


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
    * **Status Phase** – all players may score objectives and ready their
      cards/units simultaneously.
    * **Agenda Phase** – all players may cast votes or abstain.
    """
    player = state.get_player(player_id)
    phase = state.phase
    actions: list[PlayerAction] = []

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
        actions.append(PlayerAction.SCORE_OBJECTIVE)
        actions.append(PlayerAction.READY_CARDS)

    elif phase == GamePhase.AGENDA:
        actions.append(PlayerAction.CAST_VOTES)
        actions.append(PlayerAction.ABSTAIN)

    return PlayerOptions(
        player_id=player_id,
        phase=phase,
        available_actions=actions,
        passed=player.passed,
    )
