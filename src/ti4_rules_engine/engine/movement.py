"""Movement range evaluation for TI4 tactical actions.

A fleet's effective movement value is the *minimum* ``move`` stat among all
ships that are not transported (i.e. not Fighters, Ground Forces, or Mechs).
:func:`get_fleet_move` computes this value, and
:func:`get_reachable_systems` performs a breadth-first search over the galaxy
map to enumerate every system reachable in a single tactical movement step.

Example usage::

    from ti4_rules_engine.engine.movement import get_fleet_move, get_reachable_systems
    from ti4_rules_engine.models.map import GalaxyMap, System

    galaxy = GalaxyMap(systems={
        "start": System(id="start", adjacent_system_ids=["a", "b"]),
        "a": System(id="a", adjacent_system_ids=["start", "b"]),
        "b": System(id="b", adjacent_system_ids=["start", "a"]),
    })

    fleet = {"carrier": 2, "fighter": 3}  # carriers have move=2
    unit_registry = {"carrier": carrier_unit, "fighter": fighter_unit}

    move = get_fleet_move(fleet, unit_registry)           # → 2
    reach = get_reachable_systems(galaxy, "start", move)  # → {"a", "b"}
"""

from __future__ import annotations

from collections import deque

from ti4_rules_engine.models.map import AnomalyType, GalaxyMap
from ti4_rules_engine.models.unit import UnitType

# Unit types that are transported inside ships and do not contribute to the
# fleet's movement speed.
_TRANSPORTED_UNIT_TYPES: frozenset[UnitType] = frozenset(
    {UnitType.FIGHTER, UnitType.GROUND_FORCE, UnitType.MECH}
)

# Unit types that are structures and cannot participate in fleet movement.
_STRUCTURE_UNIT_TYPES: frozenset[UnitType] = frozenset(
    {UnitType.PDS, UnitType.SPACE_DOCK}
)


def get_fleet_move(
    fleet: dict[str, int],
    unit_registry: dict,
    *,
    gravity_drive: bool = False,
) -> int:
    """Return the effective movement value for a fleet.

    The fleet's movement equals the *minimum* ``move`` value among all ships
    that are capable of independent movement (i.e. not Fighters, Ground
    Forces, Mechs, or Structures).

    Parameters
    ----------
    fleet:
        A mapping of ``unit_id → count`` describing all units in the fleet.
        Units with a count of 0 are ignored.
    unit_registry:
        A mapping of ``unit_id → Unit`` providing stats for each unit type.
    gravity_drive:
        When ``True`` the fleet has the *Gravity Drive* technology, which
        grants Carriers +1 movement.

    Returns
    -------
    int
        The effective movement value.  Returns ``0`` if the fleet contains no
        ships capable of independent movement.

    Raises
    ------
    KeyError
        If a unit ID in *fleet* is not present in *unit_registry*.
    """
    ship_moves: list[int] = []

    for unit_id, count in fleet.items():
        if count <= 0:
            continue
        unit = unit_registry[unit_id]
        if unit.unit_type in _TRANSPORTED_UNIT_TYPES:
            continue
        if unit.unit_type in _STRUCTURE_UNIT_TYPES:
            continue
        if unit.move is None:
            continue
        move = unit.move
        if gravity_drive and unit.unit_type == UnitType.CARRIER:
            move += 1
        ship_moves.append(move)

    return min(ship_moves) if ship_moves else 0


def get_reachable_systems(
    galaxy: GalaxyMap,
    from_system_id: str,
    move_value: int,
    *,
    enemy_ship_system_ids: set[str] | None = None,
    fleet_has_fighters_only: bool = False,
) -> set[str]:
    """Return all system IDs reachable from *from_system_id* in one move step.

    Performs a breadth-first search over *galaxy*, consuming 1 movement point
    per hop and respecting anomaly and enemy-ship movement restrictions:

    * **Supernova** – impassable; ships cannot enter or pass through.
    * **Nebula** – ships must stop upon entry; they cannot move through.
    * **Asteroid Field** – ships must stop upon entry unless the fleet consists
      *only* of Fighters (``fleet_has_fighters_only=True``).
    * **Gravity Rift** – when a ship enters a gravity rift system it gains
      +1 movement, allowing it to move one additional system beyond the rift.
    * **Enemy ships** – ships must stop upon entering a system that contains
      enemy ships; they cannot continue their movement beyond that system.

    Parameters
    ----------
    galaxy:
        The galaxy map.
    from_system_id:
        The system the fleet is currently in.
    move_value:
        The fleet's effective movement value (see :func:`get_fleet_move`).
    enemy_ship_system_ids:
        Set of system IDs that contain enemy ships.  The fleet must stop on
        entering any of these systems.
    fleet_has_fighters_only:
        When ``True`` the fleet contains only Fighters (or Mechs), which may
        pass through Asteroid Fields without stopping.

    Returns
    -------
    set[str]
        All system IDs that the fleet can reach (the starting system is not
        included).
    """
    if move_value <= 0:
        return set()

    enemy_ships: set[str] = enemy_ship_system_ids or set()

    # BFS state: track the maximum remaining movement budget recorded for each
    # system so that we only re-visit a system if we arrive with a *higher*
    # remaining budget (possible due to gravity rift bonus).
    best_remaining: dict[str, int] = {from_system_id: move_value}
    queue: deque[tuple[str, int]] = deque([(from_system_id, move_value)])
    reachable: set[str] = set()

    while queue:
        current_id, remaining = queue.popleft()

        # Prune: a later enqueue may have found a better path to current_id
        if remaining < best_remaining.get(current_id, -1):
            continue

        for neighbor_id in galaxy.get_adjacent_ids(current_id):
            if neighbor_id == from_system_id:
                continue
            if neighbor_id not in galaxy.systems:
                continue

            neighbor = galaxy.get_system(neighbor_id)

            # Supernova: no ship may enter
            if neighbor.anomaly == AnomalyType.SUPERNOVA:
                continue

            # Moving into a neighbor costs 1 movement point
            new_remaining = remaining - 1

            # Gravity Rift bonus: entering a gravity rift grants +1 movement,
            # allowing ships to effectively pass through the rift at no extra cost.
            if neighbor.anomaly == AnomalyType.GRAVITY_RIFT:
                new_remaining += 1

            if new_remaining < 0:
                continue

            # The fleet can reach this system
            reachable.add(neighbor_id)

            # Determine whether the fleet must stop here
            must_stop = (
                neighbor_id in enemy_ships
                or neighbor.anomaly == AnomalyType.NEBULA
                or (
                    neighbor.anomaly == AnomalyType.ASTEROID_FIELD
                    and not fleet_has_fighters_only
                )
            )

            if not must_stop and new_remaining > 0:
                prev_best = best_remaining.get(neighbor_id, -1)
                if new_remaining > prev_best:
                    best_remaining[neighbor_id] = new_remaining
                    queue.append((neighbor_id, new_remaining))

    return reachable
