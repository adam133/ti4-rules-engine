"""
Component registry – a searchable lookup database for all TI4 game components.

Users can register components (Technologies, Action Cards, Strategy Cards,
Factions, Planets, Units) and then query them by ID, name substring, or type.

Example usage::

    registry = ComponentRegistry()
    registry.register_technology(neural_motivator)
    result = registry.get("neural_motivator")
    results = registry.search("neural")
"""

from __future__ import annotations

from typing import Any

import structlog

from ti4_rules_engine.models.card import ActionCard, StrategyCard
from ti4_rules_engine.models.faction import Faction
from ti4_rules_engine.models.objective import Objective
from ti4_rules_engine.models.planet import Planet
from ti4_rules_engine.models.technology import Technology
from ti4_rules_engine.models.unit import Unit

logger = structlog.get_logger(__name__)

# Type alias for any registered component
Component = Technology | ActionCard | StrategyCard | Faction | Planet | Unit | Objective


class ComponentRegistry:
    """
    A centralised lookup table for all registered game components.

    Components are stored by their ``id`` field and can be retrieved or
    searched by partial name match.
    """

    def __init__(self) -> None:
        self._store: dict[str, Component] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, component: Component) -> None:
        """
        Register a single component.

        If a component with the same ``id`` already exists it will be
        overwritten and a warning will be emitted.
        """
        if component.id in self._store:
            logger.warning(
                "component_overwritten",
                component_id=component.id,
                component_type=type(component).__name__,
            )
        self._store[component.id] = component
        logger.debug(
            "component_registered",
            component_id=component.id,
            component_type=type(component).__name__,
        )

    def register_many(self, components: list[Component]) -> None:
        """Register a collection of components in one call."""
        for component in components:
            self.register(component)

    # Typed convenience helpers ----------------------------------------

    def register_technology(self, tech: Technology) -> None:
        self.register(tech)

    def register_action_card(self, card: ActionCard) -> None:
        self.register(card)

    def register_strategy_card(self, card: StrategyCard) -> None:
        self.register(card)

    def register_faction(self, faction: Faction) -> None:
        self.register(faction)

    def register_planet(self, planet: Planet) -> None:
        self.register(planet)

    def register_unit(self, unit: Unit) -> None:
        self.register(unit)

    def register_objective(self, objective: Objective) -> None:
        self.register(objective)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, component_id: str) -> Component:
        """
        Return the component with the given ``id``.

        Raises
        ------
        KeyError
            If no component with the given ``id`` is registered.
        """
        try:
            return self._store[component_id]
        except KeyError:
            raise KeyError(f"No component with id '{component_id}' is registered.") from None

    def get_or_none(self, component_id: str) -> Component | None:
        """Return the component or ``None`` if not found."""
        return self._store.get(component_id)

    def search(self, query: str, *, case_sensitive: bool = False) -> list[Component]:
        """
        Return all components whose ``name`` contains *query* as a substring.

        Parameters
        ----------
        query:
            Substring to search for in component names.
        case_sensitive:
            When ``False`` (default) the search is case-insensitive.
        """
        needle = query if case_sensitive else query.lower()
        return [
            component
            for component in self._store.values()
            if needle in (component.name if case_sensitive else component.name.lower())
        ]

    def get_by_type(self, component_type: type) -> list[Any]:
        """Return all registered components of the given *component_type*."""
        return [c for c in self._store.values() if isinstance(c, component_type)]

    def all_ids(self) -> list[str]:
        """Return a sorted list of all registered component IDs."""
        return sorted(self._store.keys())

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, component_id: str) -> bool:
        return component_id in self._store
