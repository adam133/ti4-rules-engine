"""
Effect registry – modifier/effect query system.

Implements the modifier design described in the problem statement:

    "Instead of writing hardcoded logic for 'Morale Boost' … create an
    Effect registry where the engine can query all active effects for a
    specific player without preventing the player from ignoring the rule."

Example usage::

    registry = EffectRegistry()
    registry.add_effect(Effect(
        name="Morale Boost",
        trigger=TriggerType.COMBAT_ROLL,
        modifier=1,
        source="Morale Boost Action Card",
        owner_id="player_1",
    ))

    bonuses = registry.query(TriggerType.COMBAT_ROLL, owner_id="player_1")
    total = sum(e.modifier for e in bonuses)
"""

from __future__ import annotations

from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class TriggerType(StrEnum):
    """Game events that can trigger an effect modifier."""

    COMBAT_ROLL = "combat_roll"
    ANTI_FIGHTER_BARRAGE = "anti_fighter_barrage"
    BOMBARDMENT = "bombardment"
    SPACE_CANNON = "space_cannon"
    PRODUCTION = "production"
    MOVEMENT = "movement"
    COST = "cost"
    AGENDA_VOTE = "agenda_vote"
    TRADE_GOODS = "trade_goods"
    FIGHTER_CAPACITY = "fighter_capacity"
    GENERAL = "general"


class Effect(BaseModel):
    """
    A named, typed game modifier that can be applied to any relevant trigger.

    Designed to be **permissive but aware**: the engine surfaces all active
    effects for a given trigger without enforcing them, leaving the decision
    to the consuming controller.
    """

    name: str = Field(description="Human-readable name, e.g. 'Morale Boost'.")
    trigger: TriggerType = Field(description="The game event this effect applies to.")
    modifier: int = Field(
        description=(
            "Numeric value added to (positive) or subtracted from (negative) "
            "the relevant roll or stat."
        )
    )
    source: str = Field(description="Where this effect originates, e.g. 'Morale Boost Action Card'.")
    owner_id: str | None = Field(
        default=None,
        description="Player ID this effect belongs to. None means it applies globally.",
    )
    expires_after_use: bool = Field(
        default=True,
        description="If True, the effect is removed from the registry after the first query.",
    )

    model_config = {"frozen": True}


class EffectRegistry:
    """
    Tracks all currently active ``Effect`` instances for a game session.

    Effects can be scoped to a specific player (``owner_id``) or applied
    globally (``owner_id=None``).  When ``expires_after_use`` is True the
    effect is consumed on first query.
    """

    def __init__(self) -> None:
        self._effects: list[Effect] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_effect(self, effect: Effect) -> None:
        """Register a new active effect."""
        self._effects.append(effect)
        logger.debug(
            "effect_added",
            name=effect.name,
            trigger=effect.trigger,
            owner_id=effect.owner_id,
        )

    def remove_effect(self, name: str, owner_id: str | None = None) -> int:
        """
        Remove all effects matching *name* (and optionally *owner_id*).

        Returns the number of effects removed.
        """
        before = len(self._effects)
        self._effects = [
            e
            for e in self._effects
            if not (e.name == name and (owner_id is None or e.owner_id == owner_id))
        ]
        removed = before - len(self._effects)
        if removed:
            logger.debug("effect_removed", name=name, owner_id=owner_id, count=removed)
        return removed

    def clear(self) -> None:
        """Remove all active effects."""
        self._effects.clear()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        trigger: TriggerType,
        *,
        owner_id: str | None = None,
        include_global: bool = True,
    ) -> list[Effect]:
        """
        Return all active effects that match *trigger*.

        Parameters
        ----------
        trigger:
            The ``TriggerType`` to filter by.
        owner_id:
            When provided, only effects belonging to this player are returned
            (global effects are included when ``include_global`` is True).
        include_global:
            When True (default), effects with ``owner_id=None`` are included
            regardless of the *owner_id* filter.

        Effects with ``expires_after_use=True`` are consumed (removed from
        the registry) after they are returned.
        """
        matched: list[Effect] = []
        remaining: list[Effect] = []

        for effect in self._effects:
            # Filter by trigger
            if effect.trigger != trigger:
                remaining.append(effect)
                continue

            # Filter by owner
            is_global = effect.owner_id is None
            is_owner_match = owner_id is not None and effect.owner_id == owner_id

            if not (is_owner_match or (include_global and is_global)):
                remaining.append(effect)
                continue

            matched.append(effect)
            if not effect.expires_after_use:
                remaining.append(effect)

        self._effects = remaining
        return matched

    def total_modifier(
        self,
        trigger: TriggerType,
        *,
        owner_id: str | None = None,
        include_global: bool = True,
    ) -> int:
        """
        Convenience method: return the sum of all matched effect modifiers.

        Effects are consumed according to ``expires_after_use`` (same as
        ``query``).
        """
        effects = self.query(trigger, owner_id=owner_id, include_global=include_global)
        return sum(e.modifier for e in effects)

    def all_effects(self) -> list[Effect]:
        """Return a snapshot of all currently active effects (does not consume them)."""
        return list(self._effects)

    def __len__(self) -> int:
        return len(self._effects)
