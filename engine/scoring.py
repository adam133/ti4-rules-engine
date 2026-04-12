"""
Scoring engine – evaluates whether a player meets an objective's condition.

Given an :class:`~models.objective.Objective`, the current
:class:`~models.state.GameState`, and a ``player_id``, the
:func:`can_score_objective` function returns:

* ``True``  – the player demonstrably satisfies the condition.
* ``False`` – the player demonstrably does not satisfy the condition.
* ``None``  – evaluation requires information not captured in the base state
  (fleet positions, resource-spend tracking, etc.); the caller should prompt
  the player to confirm manually.

The engine is **permissive**: it surfaces what it can determine, leaving
enforcement to the external controller.

Example::

    from engine.scoring import can_score_objective, score_points_available
    from models.objective import Objective, ObjectiveType, ScoringCondition, ScoringConditionType
    from models.planet import Planet
    from models.technology import TechCategory, Technology

    expand_borders = Objective(
        id="expand_borders",
        name="Expand Borders",
        objective_type=ObjectiveType.STAGE_1,
        points=1,
        description="Control 6 planets outside of your home system.",
        condition=ScoringCondition(
            condition_type=ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        ),
    )

    result = can_score_objective(
        expand_borders, state, "alice",
        planet_registry={"mecatol_rex": mecatol_rex, ...},
    )
    # True / False / None
"""

from __future__ import annotations

from collections import Counter

from models.objective import Objective, ScoringConditionType
from models.planet import Planet
from models.state import GameState
from models.technology import TechCategory, Technology


def can_score_objective(
    objective: Objective,
    state: GameState,
    player_id: str,
    *,
    planet_registry: dict[str, Planet] | None = None,
    tech_registry: dict[str, Technology] | None = None,
) -> bool | None:
    """Evaluate whether *player_id* meets the condition to score *objective*.

    Parameters
    ----------
    objective:
        The objective to evaluate.
    state:
        The current game state.
    player_id:
        The player to evaluate.
    planet_registry:
        Optional mapping of ``planet_id → Planet``.  Required for planet-based
        conditions; without it those conditions return ``None``.
    tech_registry:
        Optional mapping of ``tech_id → Technology``.  Required for
        technology-based conditions; without it those conditions return ``None``.

    Returns
    -------
    bool | None
        ``True`` if the condition is met; ``False`` if it is not; ``None`` if
        it cannot be determined from the available data.

    Raises
    ------
    KeyError
        If *player_id* is not present in *state*.
    """
    player = state.get_player(player_id)
    cond = objective.condition
    ct = cond.condition_type

    # ------------------------------------------------------------------
    # Technology conditions
    # ------------------------------------------------------------------

    if ct == ScoringConditionType.OWN_N_UNIT_UPGRADES:
        if tech_registry is None:
            return None
        count = sum(
            1
            for tid in player.researched_technologies
            if tid in tech_registry and tech_registry[tid].is_unit_upgrade
        )
        return count >= cond.threshold

    if ct == ScoringConditionType.OWN_N_TECHS_OF_COLOR:
        if tech_registry is None:
            return None
        color_counts: Counter[str] = Counter(
            tech_registry[tid].category
            for tid in player.researched_technologies
            if tid in tech_registry and tech_registry[tid].category != TechCategory.FACTION
        )
        return any(count >= cond.threshold for count in color_counts.values())

    if ct == ScoringConditionType.OWN_N_TECHS_IN_N_COLORS:
        if tech_registry is None:
            return None
        color_counts = Counter(
            tech_registry[tid].category
            for tid in player.researched_technologies
            if tid in tech_registry and tech_registry[tid].category != TechCategory.FACTION
        )
        qualifying_colors = sum(
            1 for count in color_counts.values() if count >= cond.threshold
        )
        return qualifying_colors >= cond.secondary_threshold

    # ------------------------------------------------------------------
    # Planet conditions
    # ------------------------------------------------------------------

    if ct == ScoringConditionType.CONTROL_N_PLANETS_WITH_TECH_SKIP:
        if planet_registry is None:
            return None
        count = sum(
            1
            for pid in player.controlled_planets
            if pid in planet_registry and planet_registry[pid].tech_skip is not None
        )
        return count >= cond.threshold

    if ct == ScoringConditionType.CONTROL_N_PLANETS_OF_SAME_TRAIT:
        if planet_registry is None:
            return None
        trait_counts: Counter[str] = Counter(
            planet_registry[pid].trait
            for pid in player.controlled_planets
            if pid in planet_registry and planet_registry[pid].trait is not None
        )
        return any(count >= cond.threshold for count in trait_counts.values())

    if ct == ScoringConditionType.CONTROL_N_LEGENDARY_PLANETS:
        if planet_registry is None:
            return None
        count = sum(
            1
            for pid in player.controlled_planets
            if pid in planet_registry and planet_registry[pid].legendary
        )
        return count >= cond.threshold

    if ct == ScoringConditionType.CONTROL_MECATOL_REX:
        return "mecatol_rex" in player.controlled_planets

    if ct == ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME:
        if planet_registry is None:
            return None
        home_planets = _home_system_planet_ids(state, player_id, planet_registry)
        outside = sum(
            1
            for pid in player.controlled_planets
            if pid not in home_planets
        )
        return outside >= cond.threshold

    if ct == ScoringConditionType.CONTROL_N_PLANETS_IN_OPPONENT_HOME_SYSTEMS:
        if planet_registry is None:
            return None
        opponent_home_planets = _opponent_home_system_planet_ids(state, player_id, planet_registry)
        count = sum(
            1
            for pid in player.controlled_planets
            if pid in opponent_home_planets
        )
        return count >= cond.threshold

    if ct == ScoringConditionType.CONTROL_N_PLANETS_OF_SPECIFIC_TRAIT:
        if planet_registry is None or cond.trait is None:
            return None
        count = sum(
            1
            for pid in player.controlled_planets
            if pid in planet_registry and planet_registry[pid].trait == cond.trait
        )
        return count >= cond.threshold

    if ct == ScoringConditionType.CONTROL_N_PLANETS_OF_TRAIT_OUTSIDE_HOME:
        if planet_registry is None or cond.trait is None:
            return None
        home_planets = _home_system_planet_ids(state, player_id, planet_registry)
        count = sum(
            1
            for pid in player.controlled_planets
            if pid not in home_planets
            and pid in planet_registry
            and planet_registry[pid].trait == cond.trait
        )
        return count >= cond.threshold

    # ------------------------------------------------------------------
    # Fleet / board-state conditions  (cannot evaluate without fleet data)
    # ------------------------------------------------------------------

    if ct in {
        ScoringConditionType.SHIPS_IN_N_SYSTEMS_ADJACENT_MECATOL,
        ScoringConditionType.SHIPS_IN_N_OPPONENT_HOME_SYSTEMS,
        ScoringConditionType.HAVE_N_NON_FIGHTER_SHIPS_IN_1_SYSTEM,
        ScoringConditionType.HAVE_N_NON_FIGHTER_SHIPS_IN_N_SYSTEMS,
        ScoringConditionType.HAVE_SHIPS_IN_N_SYSTEMS_WITHOUT_PLANETS,
        ScoringConditionType.HAVE_N_STRUCTURES,
        ScoringConditionType.HAVE_N_MECHS,
        ScoringConditionType.HAVE_N_DREADNOUGHTS,
    }:
        return None

    # ------------------------------------------------------------------
    # Spend conditions  (cannot evaluate without round-action tracking)
    # ------------------------------------------------------------------

    if ct in {
        ScoringConditionType.SPEND_N_RESOURCES,
        ScoringConditionType.SPEND_N_INFLUENCE,
        ScoringConditionType.SPEND_N_TRADE_GOODS,
        ScoringConditionType.SPEND_N_COMMAND_TOKENS,
    }:
        return None

    # ------------------------------------------------------------------
    # Special / direct-state conditions
    # ------------------------------------------------------------------

    if ct == ScoringConditionType.HAVE_N_VICTORY_POINTS:
        return player.victory_points >= cond.threshold

    if ct == ScoringConditionType.HAVE_N_LAWS_IN_PLAY:
        return len(state.law_ids) >= cond.threshold

    if ct == ScoringConditionType.HAVE_N_INFLUENCE_ON_UNEXHAUSTED_PLANETS:
        if planet_registry is None:
            return None
        exhausted = set(player.exhausted_planets)
        total_influence = sum(
            planet_registry[pid].influence
            for pid in player.controlled_planets
            if pid in planet_registry and pid not in exhausted
        )
        return total_influence >= cond.threshold

    if ct == ScoringConditionType.PLAYER_DECLARED:
        return None

    # Unknown condition type – cannot evaluate.
    return None  # pragma: no cover


def score_points_available(
    state: GameState,
    player_id: str,
    objectives: list[Objective],
    *,
    planet_registry: dict[str, Planet] | None = None,
    tech_registry: dict[str, Technology] | None = None,
) -> int:
    """Return the total VP a player can provably score from *objectives* right now.

    Only objectives whose conditions :func:`can_score_objective` evaluates as
    ``True`` are counted.  Objectives already present in the player's
    :attr:`~models.state.PlayerState.scored_objectives` list are skipped.

    Parameters
    ----------
    state:
        Current game state.
    player_id:
        The player to evaluate.
    objectives:
        The pool of objectives to consider.
    planet_registry:
        Optional mapping of ``planet_id → Planet`` for planet-based conditions.
    tech_registry:
        Optional mapping of ``tech_id → Technology`` for technology-based conditions.

    Returns
    -------
    int
        Total VP the player can demonstrably score from *objectives* right now.
    """
    player = state.get_player(player_id)
    already_scored = set(player.scored_objectives)

    total = 0
    for obj in objectives:
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
            total += obj.points
    return total


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _home_system_planet_ids(
    state: GameState,
    player_id: str,
    planet_registry: dict[str, Planet],
) -> set[str]:
    """Return the set of planet IDs in *player_id*'s home system.

    The home system ID is read from ``state.extra["home_systems"][player_id]``
    when present, and matched against ``planet.system_id`` in *planet_registry*.
    If the home system cannot be determined an empty set is returned (so that
    all controlled planets are treated as outside the home system).
    """
    home_system_id: str | None = (
        state.extra.get("home_systems", {}).get(player_id)
    )
    if home_system_id is None:
        return set()
    return {
        pid
        for pid, planet in planet_registry.items()
        if planet.system_id == home_system_id
    }


def _opponent_home_system_planet_ids(
    state: GameState,
    player_id: str,
    planet_registry: dict[str, Planet],
) -> set[str]:
    """Return the set of planet IDs in any opponent's home system.

    Reads ``state.extra["home_systems"]`` (a mapping of ``player_id → system_id``)
    and returns all planets whose ``system_id`` matches any opponent's home system.
    If no home-system data is available an empty set is returned.
    """
    home_systems: dict[str, str] = state.extra.get("home_systems", {})
    opponent_system_ids = {
        system_id
        for pid, system_id in home_systems.items()
        if pid != player_id
    }
    if not opponent_system_ids:
        return set()
    return {
        pid
        for pid, planet in planet_registry.items()
        if planet.system_id in opponent_system_ids
    }
