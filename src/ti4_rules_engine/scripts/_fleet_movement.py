"""Fleet movement helpers, combat utilities, and BFS tactical-reach calculator.

This module covers the full pipeline from raw AsyncTI4 unit lists to a complete
tactical-reach report:

Unit / fleet helpers
    :func:`_fleet_move_value`, :func:`_iter_fleet_movement_variants`,
    :func:`_fleet_capacity`, :func:`_count_units_by_entity_id`,
    :func:`_summarise_units`, :func:`_summarise_ground_forces`,
    :func:`_summarise_transportable_units`

Transport / pickup helpers
    :func:`_space_dock_fighter_capacity_in_tile`,
    :func:`_fighter_excess_count_for_movement`,
    :func:`_ground_forces_in_space`, :func:`_ground_forces_on_planets`,
    :func:`_compute_starting_transport_payload`

Combat helpers
    :func:`_build_combat_group`, :func:`_format_combat_result`

BFS movement
    :func:`_bfs`, :func:`get_reachable_systems`, :func:`_get_reach_info`

Tactical reach
    :func:`_get_tactical_reach`
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from ti4_rules_engine.engine.combat import CombatGroup, CombatResult, CombatUnit, simulate_combat
from ti4_rules_engine.models.unit import Unit

from ti4_rules_engine.scripts._data_loaders import (
    _build_ship_capacity_map,
    _build_ship_move_map,
    _has_fighter_ii,
    fetch_unit_data,
)
from ti4_rules_engine.scripts._hex_grid import get_adjacent_positions
from ti4_rules_engine.scripts._hyperlanes import _build_movement_context

if TYPE_CHECKING:
    from ti4_rules_engine.models.state import GameState

# ---------------------------------------------------------------------------
# Unit entity ID constants
# ---------------------------------------------------------------------------

# Human-readable names for the unit entity IDs used in AsyncTI4 exports.
# Note: cruisers appear as both 'ca' and 'cr' depending on the faction/upgrade;
# both map to the same display name.
_UNIT_NAMES: dict[str, str] = {
    "cv": "carrier",
    "dd": "destroyer",
    "ca": "cruiser",
    "cr": "cruiser",
    "dn": "dreadnought",
    "fs": "flagship",
    "ws": "war sun",
    "ff": "fighter",
    "gf": "infantry",
    "mf": "mech",
    "pd": "PDS",
    "sd": "space dock",
}

_TRANSPORTED_UNITS = frozenset({"ff", "gf", "mf"})  # fighter, ground force, mech
# NOTE: _TRANSPORTED_UNITS is used as documentation of which unit types are
# transported by ships and therefore excluded from fleet move calculations.

# Ground-force unit entity IDs (infantry and mechs live on planets).
_GROUND_FORCE_IDS = frozenset({"gf", "mf"})
_FIGHTER_ENTITY_ID = "ff"
_SPACE_DOCK_ENTITY_ID = "sd"
_DEFAULT_SPACE_DOCK_FIGHTER_CAPACITY = 3
_FIGHTER_II_MOVE_SPEED = 2
_ARRIVAL_LABEL_ENTITY_IDS: dict[str, str] = {
    "carrier": "cv",
    "destroyer": "dd",
    "cruiser": "ca",
    "dreadnought": "dn",
    "flagship": "fs",
    "war sun": "ws",
    "fighter": "ff",
    "mech": "mf",
    "infantry": "gf",
}

# ---------------------------------------------------------------------------
# Module-level unit registries (built from base unit data at import time)
# ---------------------------------------------------------------------------

# Unit registries built from data/units/baseUnits.json.
# These are populated at first use via fetch_unit_data().
# Faction-specific lookups can be built with fetch_unit_data(faction).
_COMBAT_UNITS: dict[str, Unit] = fetch_unit_data()

# Move values for standard TI4 unit types (entity IDs from AsyncTI4 exports).
# Built from the base unit data.  Fighters are excluded (they are transported).
_SHIP_MOVE: dict[str, int] = _build_ship_move_map(_COMBAT_UNITS)

# Transport capacity per ship type (entity ID → slots for ground forces / fighters).
# Built from the base unit data.
_SHIP_CAPACITY: dict[str, int] = _build_ship_capacity_map(_COMBAT_UNITS)

# ---------------------------------------------------------------------------
# Fleet value helpers
# ---------------------------------------------------------------------------


def _fleet_move_value(
    units: list[dict[str, Any]],
    ship_move: dict[str, int] | None = None,
    *,
    fighter_excess_count: int = 0,
    fighter_independent_move: int = 0,
) -> int:
    """Return the minimum move value for a collection of space units.

    Only non-transported ships contribute to the fleet's movement range.
    Returns 0 when the list contains no mobile ships.

    *ship_move* defaults to the base-game :data:`_SHIP_MOVE` lookup; pass a
    faction-specific dict (built via :func:`_build_ship_move_map`) to honour
    faction unit variants.
    """
    move_map = ship_move if ship_move is not None else _SHIP_MOVE
    move_vals = [
        move_map[u["entityId"]]
        for u in units
        if isinstance(u, dict)
        and u.get("entityType") == "unit"
        and u.get("entityId") in move_map
    ]
    if fighter_excess_count > 0 and fighter_independent_move > 0:
        move_vals.append(fighter_independent_move)
    return min(move_vals) if move_vals else 0


def _iter_fleet_movement_variants(
    fleet_units: list[dict[str, Any]],
    ship_move: dict[str, int],
    *,
    baseline_move: int,
) -> list[tuple[list[dict[str, Any]], int]]:
    """Return movement variants: full fleet baseline plus faster-ship detachments."""
    variants: list[tuple[list[dict[str, Any]], int]] = []
    if baseline_move <= 0:
        return variants

    variants.append((fleet_units, baseline_move))

    faster_moves = {
        ship_move[eid]
        for u in fleet_units
        if isinstance(u, dict)
        and u.get("entityType") == "unit"
        and (eid := str(u.get("entityId", ""))) in ship_move
        and ship_move[eid] > baseline_move
    }
    if not faster_moves:
        return variants

    seen_variant_signatures: set[tuple[tuple[str, int], ...]] = set()
    for min_speed in sorted(faster_moves):
        detachment: list[dict[str, Any]] = []
        for u in fleet_units:
            if not isinstance(u, dict) or u.get("entityType") != "unit":
                continue
            eid = str(u.get("entityId", ""))
            if eid not in ship_move or ship_move[eid] < min_speed:
                continue
            detachment.append(u)

        if not detachment:
            continue

        detachment_move = _fleet_move_value(detachment, ship_move)
        if detachment_move <= baseline_move:
            continue

        key = tuple(
            sorted(
                (str(u.get("entityId", "")), int(u.get("count", 1)))
                for u in detachment
                if isinstance(u, dict) and u.get("entityType") == "unit"
            )
        )
        if key in seen_variant_signatures:
            continue
        seen_variant_signatures.add(key)
        variants.append((detachment, detachment_move))

    return variants


def _summarise_units(units: list[dict[str, Any]]) -> list[str]:
    """Return a sorted list of ``"<name> x<count>"`` strings for space ships.

    Transported units (fighters, infantry, mechs) and non-unit entities are
    excluded.  A count of 1 is omitted (shows just ``"carrier"`` not
    ``"carrier x1"``).
    """
    counts: dict[str, int] = {}
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        if eid in _TRANSPORTED_UNITS:
            continue
        name = _UNIT_NAMES.get(eid, eid)
        counts[name] = counts.get(name, 0) + u.get("count", 1)

    parts = []
    for name, cnt in sorted(counts.items()):
        parts.append(name if cnt == 1 else f"{name} x{cnt}")
    return parts


def _fleet_capacity(
    units: list[dict[str, Any]],
    ship_capacity: dict[str, int] | None = None,
) -> int:
    """Return the total transport capacity of a fleet (sum across all ships).

    *ship_capacity* defaults to the base-game :data:`_SHIP_CAPACITY` lookup;
    pass a faction-specific dict (built via :func:`_build_ship_capacity_map`)
    to honour faction unit variants (e.g. Titans' cruiser with capacity 1).
    """
    cap_map = ship_capacity if ship_capacity is not None else _SHIP_CAPACITY
    total = 0
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        cap = cap_map.get(eid, 0)
        total += cap * u.get("count", 1)
    return total


def _count_units_by_entity_id(units: list[dict[str, Any]]) -> dict[str, int]:
    """Return ``{entity_id: count}`` for unit entities in *units*."""
    counts: dict[str, int] = {}
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        counts[eid] = counts.get(eid, 0) + u.get("count", 1)
    return counts


# ---------------------------------------------------------------------------
# Transport / pickup helpers
# ---------------------------------------------------------------------------


def _space_dock_fighter_capacity_in_tile(
    tile_data: dict[str, Any],
    faction: str,
    ship_capacity: dict[str, int] | None = None,
) -> int:
    """Return fighter capacity in *tile_data* provided by the player's space docks."""
    cap_map = ship_capacity if ship_capacity is not None else _SHIP_CAPACITY
    sd_capacity_raw = cap_map.get(_SPACE_DOCK_ENTITY_ID, _DEFAULT_SPACE_DOCK_FIGHTER_CAPACITY)
    sd_capacity = (
        sd_capacity_raw
        if isinstance(sd_capacity_raw, int) and sd_capacity_raw > 0
        else _DEFAULT_SPACE_DOCK_FIGHTER_CAPACITY
    )
    total_sd_count = 0

    # Space-area docks (rare but supported by the payload shape)
    space = tile_data.get("space") or {}
    if isinstance(space, dict):
        total_sd_count += _count_units_by_entity_id(
            space.get(faction) or []
        ).get(_SPACE_DOCK_ENTITY_ID, 0)

    # Planet-area docks
    for pdata in (tile_data.get("planets") or {}).values():
        if not isinstance(pdata, dict):
            continue
        entities = pdata.get("entities") or {}
        if not isinstance(entities, dict):
            continue
        total_sd_count += _count_units_by_entity_id(entities.get(faction) or []).get(
            _SPACE_DOCK_ENTITY_ID, 0
        )

    return total_sd_count * sd_capacity


def _fighter_excess_count_for_movement(
    fleet_units: list[dict[str, Any]],
    tile_data: dict[str, Any],
    faction: str,
    ship_capacity: dict[str, int] | None = None,
) -> int:
    """Return number of fighters that must move independently (Fighter II excess)."""
    cap_map = ship_capacity if ship_capacity is not None else _SHIP_CAPACITY
    counts = _count_units_by_entity_id(fleet_units)
    fighters = counts.get(_FIGHTER_ENTITY_ID, 0)
    if fighters <= 0:
        return 0

    ship_capacity_total = _fleet_capacity(fleet_units, cap_map)
    ground_forces_in_space = sum(counts.get(eid, 0) for eid in _GROUND_FORCE_IDS)
    remaining_ship_capacity = max(0, ship_capacity_total - ground_forces_in_space)

    # Space docks provide fighter-only capacity in the system.
    dock_fighter_capacity = _space_dock_fighter_capacity_in_tile(tile_data, faction, cap_map)
    fighters_requiring_ship_capacity = max(0, fighters - dock_fighter_capacity)

    return max(0, fighters_requiring_ship_capacity - remaining_ship_capacity)


def _ground_forces_in_space(units: list[dict[str, Any]]) -> dict[str, int]:
    """Return ``{entity_id: count}`` for infantry/mechs already in a fleet's space area."""
    counts: dict[str, int] = {}
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        if eid in _GROUND_FORCE_IDS:
            counts[eid] = counts.get(eid, 0) + u.get("count", 1)
    return counts


def _ground_forces_on_planets(tile_data: dict[str, Any], faction: str) -> dict[str, int]:
    """Return ``{entity_id: count}`` for infantry/mechs on planets in *tile_data*.

    Only units belonging to *faction* are counted.  Units are stored under
    each planet's ``entities`` dict (keyed by faction slug).
    """
    counts: dict[str, int] = {}
    for pdata in (tile_data.get("planets") or {}).values():
        if not isinstance(pdata, dict):
            continue
        entities = pdata.get("entities") or {}
        if not isinstance(entities, dict):
            continue
        faction_units = entities.get(faction) or []
        if not isinstance(faction_units, list):
            continue
        for u in faction_units:
            if not isinstance(u, dict):
                continue
            eid = u.get("entityId", "")
            if eid in _GROUND_FORCE_IDS:
                counts[eid] = counts.get(eid, 0) + u.get("count", 1)
    return counts


def _summarise_ground_forces(gf_counts: dict[str, int]) -> list[str]:
    """Return a human-readable list of ground force labels.

    e.g. ``{"gf": 3, "mf": 1}`` → ``["infantry x3", "mech"]``
    """
    parts = []
    for eid in ("mf", "gf"):  # mechs first (higher value)
        cnt = gf_counts.get(eid, 0)
        if cnt == 0:
            continue
        name = _UNIT_NAMES.get(eid, eid)
        parts.append(name if cnt == 1 else f"{name} x{cnt}")
    return parts


def _summarise_transportable_units(unit_counts: dict[str, int]) -> list[str]:
    """Return transportable-unit labels in fighter → mech → infantry order."""
    parts: list[str] = []
    for eid in ("ff", "mf", "gf"):
        cnt = unit_counts.get(eid, 0)
        if cnt <= 0:
            continue
        name = _UNIT_NAMES.get(eid, eid)
        parts.append(name if cnt == 1 else f"{name} x{cnt}")
    return parts


def _compute_starting_transport_payload(
    variant_units: list[dict[str, Any]],
    *,
    tile_data: dict[str, Any],
    faction: str,
    capacity: int,
) -> dict[str, int]:
    """Return transported-unit counts that this moving fleet can actually carry from its origin."""
    onboard = _count_units_by_entity_id(variant_units)
    payload: dict[str, int] = {}
    for eid in ("ff", "mf", "gf"):
        cnt = onboard.get(eid, 0)
        if cnt > 0:
            payload[eid] = cnt

    used_capacity = sum(payload.values())
    remaining_capacity = max(0, capacity - used_capacity)
    # All capacity is already consumed by onboard transportable units.
    if remaining_capacity == 0:
        return payload

    planet_gf = _ground_forces_on_planets(tile_data, faction)
    for eid in ("mf", "gf"):
        if remaining_capacity <= 0:
            break
        available = planet_gf.get(eid, 0)
        if available <= 0:
            continue
        loadable = min(available, remaining_capacity)
        payload[eid] = payload.get(eid, 0) + loadable
        remaining_capacity -= loadable

    return payload


# ---------------------------------------------------------------------------
# Combat helpers
# ---------------------------------------------------------------------------


def _arrival_label_to_unit_dict(label: str) -> dict[str, Any] | None:
    """Convert a tactical-arrival label (e.g. ``"fighter x2"``) to a raw unit dict."""
    normalized = label.strip().lower()
    if not normalized:
        return None

    unit_name = normalized
    count = 1
    if " x" in normalized:
        unit_name, suffix = normalized.rsplit(" x", 1)
        try:
            count = int(suffix)
        except ValueError:
            return None
        if count <= 0:
            return None

    entity_id = _ARRIVAL_LABEL_ENTITY_IDS.get(unit_name.strip())
    if entity_id is None:
        return None
    return {"entityId": entity_id, "entityType": "unit", "count": count}


def _arrival_to_unit_dicts(arrival: dict[str, Any]) -> list[dict[str, Any]]:
    """Build aggregated raw unit dicts from a tactical-arrival payload."""
    counts: dict[str, int] = {}
    for key in ("ships", "transported_units"):
        labels = arrival.get(key) or []
        if not isinstance(labels, list):
            continue
        for label in labels:
            if not isinstance(label, str):
                continue
            unit = _arrival_label_to_unit_dict(label)
            if unit is None:
                continue
            eid = str(unit["entityId"])
            counts[eid] = counts.get(eid, 0) + int(unit["count"])

    return [
        {"entityId": eid, "entityType": "unit", "count": count}
        for eid, count in sorted(counts.items())
        if count > 0
    ]


def _arrival_combat_size(arrival: dict[str, Any]) -> int:
    """Return total combat-capable unit count represented by an arrival payload."""
    combat_size = 0
    for unit in _arrival_to_unit_dicts(arrival):
        unit_def = _COMBAT_UNITS.get(str(unit["entityId"]))
        if unit_def is None or unit_def.combat is None:
            continue
        combat_size += int(unit["count"])
    return combat_size


def _build_combat_group(
    units: list[dict[str, Any]],
    combat_units: dict[str, Unit] | None = None,
) -> CombatGroup:
    """Build a :class:`CombatGroup` from a list of raw unit dicts.

    Only units with a defined ``combat`` stat are included.

    *combat_units* defaults to the base-game :data:`_COMBAT_UNITS` registry;
    pass a faction-specific dict (built via :func:`fetch_unit_data`) to use
    faction-specific unit stats (e.g. Titans' Saturn Engine, Sol Advanced
    Carrier, etc.).
    """
    unit_registry = combat_units if combat_units is not None else _COMBAT_UNITS
    cu_list: list[CombatUnit] = []
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        unit_def = unit_registry.get(eid)
        if unit_def is None or unit_def.combat is None:
            continue
        count = u.get("count", 1)
        cu_list.append(CombatUnit(unit_def, count))
    return CombatGroup(cu_list)


def _format_combat_result(result: CombatResult) -> str:
    """Return a one-line summary of a :class:`CombatResult`.

    Format: ``Win 63%, Lose 31%, Draw 6% | Avg 2.3 rounds``
    followed by expected survivors if non-trivial.
    """
    win = result.attacker_win_probability
    lose = result.defender_win_probability
    draw = 1.0 - win - lose
    summary = (
        f"Win {win:.0%}, Lose {lose:.0%}, Draw {draw:.0%}"
        f" | Avg {result.average_rounds:.1f} rounds"
    )

    surv_parts = [
        f"{k} avg {v:.1f}"
        for k, v in sorted(result.attacker_expected_survivors.items(), key=lambda x: -x[1])
        if v > 0.05
    ]
    if surv_parts:
        summary += f"  [survivors: {', '.join(surv_parts)}]"
    return summary


# ---------------------------------------------------------------------------
# BFS movement core
# ---------------------------------------------------------------------------


def _bfs(
    starting_pos: str,
    fleet_move: int,
    tile_unit_data: dict[str, Any],
    faction: str,
    tile_type_map: dict[str, dict[str, Any]] | None = None,
    wormhole_adjacency: dict[str, frozenset[str]] | None = None,
    hyperlane_adjacency: dict[str, frozenset[str]] | None = None,
    has_antimass_deflectors: bool = False,
    *,
    ignore_gravity_rift_bonus: bool = False,
) -> dict[str, int]:
    """BFS from *starting_pos*, returning ``{position: best_remaining_moves}``.

    This is the shared core for :func:`get_reachable_systems` and
    :func:`_get_reach_info`.  When *ignore_gravity_rift_bonus* is ``True``
    gravity-rift tiles are treated as normal tiles (cost 1 to enter) so that a
    second BFS run can identify destinations only reachable via the rift bonus.

    Hyperlane tiles (identified via ``tile_type_map`` entries with
    ``"hyperlane": True``) are never valid movement destinations; ships skip
    them entirely and instead use ``hyperlane_adjacency`` — a pre-computed map
    of positions reachable through adjacent hyperlane chains (following each
    tile's edge-specific connection rules).  Hyperlane-connected positions are
    treated as ordinary 1-move neighbours of the source tile.
    """
    if fleet_move <= 0:
        return {}

    best_remaining: dict[str, int] = {starting_pos: fleet_move}
    queue: deque[tuple[str, int]] = deque([(starting_pos, fleet_move)])

    while queue:
        pos, remaining = queue.popleft()
        if remaining <= 0:
            continue

        neighbours = list(get_adjacent_positions(pos))
        if wormhole_adjacency:
            for wh_pos in wormhole_adjacency.get(pos, frozenset()):
                if wh_pos not in neighbours:
                    neighbours.append(wh_pos)
        if hyperlane_adjacency:
            for hl_pos in hyperlane_adjacency.get(pos, frozenset()):
                if hl_pos not in neighbours:
                    neighbours.append(hl_pos)

        for adj_pos in neighbours:
            if adj_pos not in tile_unit_data:
                continue
            tile_data = tile_unit_data[adj_pos]

            if tile_type_map is not None:
                info = tile_type_map.get(adj_pos, {})
                if info.get("supernova"):
                    continue
                if info.get("hyperlane"):
                    # Hyperlane tiles are never valid destinations; adjacency
                    # through them is handled via hyperlane_adjacency above.
                    continue
                elif info.get("asteroid") and not has_antimass_deflectors:
                    continue
                else:
                    # Only real game tiles respect the CC-lock rule.
                    if faction in tile_data.get("ccs", []):
                        continue
                    if info.get("gravity_rift") and not ignore_gravity_rift_bonus:
                        new_remaining = remaining  # net cost 0 (−1 + rift bonus +1)
                    elif info.get("nebula"):
                        new_remaining = 0
                    else:
                        new_remaining = remaining - 1
            else:
                if faction in tile_data.get("ccs", []):
                    continue
                if tile_data.get("anomaly", False):
                    continue
                new_remaining = remaining - 1

            if best_remaining.get(adj_pos, -1) < new_remaining:
                best_remaining[adj_pos] = new_remaining
                if new_remaining > 0:
                    queue.append((adj_pos, new_remaining))

    return best_remaining


def get_reachable_systems(
    starting_pos: str,
    fleet_move: int,
    tile_unit_data: dict[str, Any],
    faction: str,
    tile_type_map: dict[str, dict[str, Any]] | None = None,
    wormhole_adjacency: dict[str, frozenset[str]] | None = None,
    hyperlane_adjacency: dict[str, frozenset[str]] | None = None,
    has_antimass_deflectors: bool = False,
) -> set[str]:
    """BFS from *starting_pos* returning all tile positions reachable by the fleet.

    Movement rules applied:

    * Each step costs 1 move.
    * Tiles already activated by *faction* (player's CC present) cannot be entered.
    * When *tile_type_map* is provided, per-anomaly rules are enforced:

      * **Supernova / Scar**: impassable — cannot be entered or transited.
      * **Asteroid field**: impassable unless *has_antimass_deflectors* is ``True``.
      * **Nebula**: the fleet can enter as a destination but cannot move further
        from there (remaining moves set to 0 on arrival).
      * **Gravity Rift**: grants +1 movement when moving through or out of the
        rift (arriving at a gravity rift does not consume a move).

    * When *wormhole_adjacency* is provided, tiles sharing a wormhole type are
      treated as mutually adjacent in addition to hex-grid neighbours.
    * When *hyperlane_adjacency* is provided, positions connected through
      hyperlane chains are treated as 1-move neighbours (following each
      hyperlane tile's edge-specific connection rules).  Hyperlane tiles
      themselves are never included as valid destinations.
    * Without *tile_type_map*, the legacy ``anomaly: bool`` field from
      *tile_unit_data* is used and all anomalies are treated as impassable.
    * The starting position itself is not included in the result.
    * Only positions present in *tile_unit_data* are considered (tiles off the
      map are ignored).
    * Tiles at special positions (e.g. ``"br"``, ``"tl"``) have no hex-grid
      neighbours; they are reachable/can reach other tiles only via wormholes.
    """
    best = _bfs(
        starting_pos,
        fleet_move,
        tile_unit_data,
        faction,
        tile_type_map=tile_type_map,
        wormhole_adjacency=wormhole_adjacency,
        hyperlane_adjacency=hyperlane_adjacency,
        has_antimass_deflectors=has_antimass_deflectors,
    )
    return {pos for pos in best if pos != starting_pos}


def _get_reach_info(
    starting_pos: str,
    fleet_move: int,
    tile_unit_data: dict[str, Any],
    faction: str,
    tile_type_map: dict[str, dict[str, Any]] | None = None,
    wormhole_adjacency: dict[str, frozenset[str]] | None = None,
    hyperlane_adjacency: dict[str, frozenset[str]] | None = None,
    has_antimass_deflectors: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return movement details for each reachable tile.

    Returns a dict mapping each reachable position (excluding *starting_pos*)
    to a sub-dict with:

    ``path_cost`` : int
        Minimum number of movement points spent to reach this position
        (``fleet_move - best_remaining``).
    ``via_rift`` : bool
        ``True`` when the destination is only reachable by passing through at
        least one gravity-rift tile (i.e. the rift's +1 bonus is essential).
    """
    bfs_kwargs: dict[str, Any] = dict(
        tile_unit_data=tile_unit_data,
        faction=faction,
        tile_type_map=tile_type_map,
        wormhole_adjacency=wormhole_adjacency,
        hyperlane_adjacency=hyperlane_adjacency,
        has_antimass_deflectors=has_antimass_deflectors,
    )
    best_with = _bfs(starting_pos, fleet_move, ignore_gravity_rift_bonus=False, **bfs_kwargs)
    best_without = _bfs(starting_pos, fleet_move, ignore_gravity_rift_bonus=True, **bfs_kwargs)
    reachable_without_rift = {pos for pos in best_without if pos != starting_pos}

    result: dict[str, dict[str, Any]] = {}
    for pos, remaining in best_with.items():
        if pos == starting_pos:
            continue
        result[pos] = {
            "path_cost": fleet_move - remaining,
            "via_rift": pos not in reachable_without_rift,
        }
    return result


# ---------------------------------------------------------------------------
# Tactical reach (top-level entry point for the output layer)
# ---------------------------------------------------------------------------


def _get_tactical_reach(
    player_id: str,
    state: GameState,
) -> dict[str, Any]:
    """Return tactical-reach information for all of a player's unlocked fleets.

    Returns a dict with:

    ``by_destination`` : dict[str, dict]
        Mapping from destination position to arrival information.  Each value
        has keys:

        ``"planets"`` : list[str]
            Planet names (or IDs) in the destination tile.
        ``"arrivals"`` : list[dict]
            One entry per starting position whose fleet can reach this
            destination.  Each entry has:

            * ``"from_pos"`` – starting tile position.
            * ``"ships"`` – human-readable ship list (no fighters/infantry/mechs).
            * ``"fleet_move"`` – fleet movement value.
            * ``"capacity"`` – total transport capacity of the fleet.
            * ``"ground_forces"`` – infantry/mechs this fleet can carry from
              its starting tile (respecting capacity).
            * ``"transported_units"`` – fighters/mechs/infantry this fleet can
              carry from its starting tile (respecting capacity).
            * ``"pickup_systems"`` – ``{pos: [gf_labels]}`` of player-controlled
              ground forces on planets in intermediate systems (i.e. systems
              between the starting pos and the destination that are not CC-locked).
            * ``"via_rift"`` – ``True`` if only reachable via a gravity rift.
            * ``"needs_gravity_drive"`` – ships that individually can't reach
              this destination without *Gravity Drive*.

        ``"defenders"`` : dict[str, list[str]]
            Enemy factions (not the moving player) present in the destination's
            space area, mapped to their ship/unit labels.
        ``"combat_result"`` : str | None
            Combat summary string for the **active player** (``None`` for
            non-active players or when there are no defenders).

    ``no_adjacency`` : list[str]
        Positions where the player has an unlocked fleet but no adjacency can be
        computed (special positions with no wormhole connections).

    The AsyncTI4 export uses the player's faction name as the identifier
    inside ``tileUnitData`` (not the player's token-colour slug).
    Returns empty results when tile data is unavailable.
    """
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    if not tile_unit_data:
        return {"by_destination": {}, "no_adjacency": []}
    player = state.players.get(player_id)
    if player is None:
        return {"by_destination": {}, "no_adjacency": []}
    faction = player.faction_id
    is_active = player_id == state.active_player_id

    tile_positions: dict[str, str] = state.extra.get("tile_positions", {})
    tile_type_map: dict[str, dict[str, Any]] | None = None
    wormhole_adjacency: dict[str, frozenset[str]] | None = None
    hyperlane_adjacency: dict[str, frozenset[str]] | None = None
    if tile_positions:
        # Detect if the Ghosts of Creuss are playing — their faction ability
        # (Quantum Entanglement) makes all alpha and beta wormholes adjacent.
        creuss_in_game = any(
            p.faction_id == "ghost" for p in state.players.values()
        )
        tile_type_map, wormhole_adjacency, hyperlane_adjacency = _build_movement_context(
            tile_positions, creuss_in_game=creuss_in_game
        )

    has_amd = "amd" in (player.researched_technologies or [])
    has_fighter_ii = _has_fighter_ii(player.researched_technologies or [])

    # Load faction-specific unit data for movement / capacity / combat calcs.
    faction_units = fetch_unit_data(faction)
    faction_ship_move = _build_ship_move_map(faction_units)
    faction_ship_capacity = _build_ship_capacity_map(faction_units)

    # by_destination[pos] = {planets, arrivals, defenders, combat_result}
    by_destination: dict[str, dict[str, Any]] = {}
    no_adjacency: list[str] = []

    for tile_pos, tile_data in tile_unit_data.items():
        space = tile_data.get("space") or {}
        if not isinstance(space, dict) or faction not in space:
            continue
        # Skip locked tiles (player already placed a CC here)
        if faction in tile_data.get("ccs", []):
            continue
        fleet_units: list[dict[str, Any]] = space[faction]
        fighter_excess = (
            _fighter_excess_count_for_movement(
                fleet_units, tile_data, faction, faction_ship_capacity
            )
            if has_fighter_ii
            else 0
        )
        fleet_move = _fleet_move_value(
            fleet_units,
            faction_ship_move,
            fighter_excess_count=fighter_excess,
            fighter_independent_move=_FIGHTER_II_MOVE_SPEED if has_fighter_ii else 0,
        )
        if fleet_move <= 0:
            continue

        movement_variants = _iter_fleet_movement_variants(
            fleet_units, faction_ship_move, baseline_move=fleet_move
        )
        any_reach = False

        for variant_units, variant_move in movement_variants:
            reach_info = _get_reach_info(
                tile_pos,
                variant_move,
                tile_unit_data,
                faction,
                tile_type_map=tile_type_map,
                wormhole_adjacency=wormhole_adjacency,
                hyperlane_adjacency=hyperlane_adjacency,
                has_antimass_deflectors=has_amd,
            )
            if not reach_info:
                continue
            any_reach = True

            unit_labels = _summarise_units(variant_units)
            capacity = _fleet_capacity(variant_units, faction_ship_capacity)
            starting_payload = _compute_starting_transport_payload(
                variant_units,
                tile_data=tile_data,
                faction=faction,
                capacity=capacity,
            )
            payload_ground_forces = {
                eid: starting_payload.get(eid, 0) for eid in _GROUND_FORCE_IDS
            }
            pickup_capacity_remaining = max(0, capacity - sum(starting_payload.values()))

            # Identify intermediate systems (closer to start than any given destination)
            # that have player ground forces on planets and no CC present.
            # These represent possible pickups on the way.
            intermediate_gf: dict[str, dict[str, int]] = {}
            for mid_pos in reach_info:
                mid_tile_data = tile_unit_data.get(mid_pos) or {}
                if faction in mid_tile_data.get("ccs", []):
                    continue  # locked system — can't pick up
                mid_gf = _ground_forces_on_planets(mid_tile_data, faction)
                if mid_gf:
                    intermediate_gf[mid_pos] = mid_gf

            for dest, info in reach_info.items():
                path_cost = info["path_cost"]
                via_rift = info["via_rift"]

                # Initialise destination entry if not yet present
                if dest not in by_destination:
                    planets = list((tile_unit_data.get(dest) or {}).get("planets", {}).keys())
                    # Collect enemy units in this destination's space area
                    dest_space = (tile_unit_data.get(dest) or {}).get("space") or {}
                    defenders: dict[str, list[str]] = {}
                    dest_space_items = dest_space.items() if isinstance(dest_space, dict) else []
                    for other_faction, other_units in dest_space_items:
                        if other_faction == faction:
                            continue
                        labels = (
                            _summarise_units(other_units)
                            if isinstance(other_units, list)
                            else []
                        )
                        if labels:
                            defenders[other_faction] = labels
                    by_destination[dest] = {
                        "planets": planets,
                        "arrivals": [],
                        "defenders": defenders,
                        "combat_result": None,
                    }

                # Needs Gravity Drive: ships whose individual move < path_cost
                needs_gd_seen: set[str] = set()
                needs_gd: list[str] = []
                for u in variant_units:
                    if not isinstance(u, dict) or u.get("entityType") != "unit":
                        continue
                    eid = u.get("entityId", "")
                    if eid not in faction_ship_move:
                        continue
                    ind_move = faction_ship_move[eid]
                    if ind_move < path_cost:
                        label = _UNIT_NAMES.get(eid, eid)
                        cnt = u.get("count", 1)
                        entry = label if cnt == 1 else f"{label} x{cnt}"
                        if entry not in needs_gd_seen:
                            needs_gd_seen.add(entry)
                            needs_gd.append(entry)

                # Intermediate pickup systems: those with path_cost < dest path_cost
                pickup_systems: dict[str, list[str]] = {}
                for mid_pos, mid_gf in intermediate_gf.items():
                    if pickup_capacity_remaining <= 0:
                        continue
                    mid_path_cost = reach_info.get(mid_pos, {}).get("path_cost", path_cost)
                    if mid_path_cost < path_cost:
                        remaining_for_mid = pickup_capacity_remaining
                        pickup_counts: dict[str, int] = {}
                        for eid in ("mf", "gf"):
                            if remaining_for_mid <= 0:
                                break
                            available = mid_gf.get(eid, 0)
                            if available <= 0:
                                continue
                            take = min(available, remaining_for_mid)
                            pickup_counts[eid] = take
                            remaining_for_mid -= take
                        labels = _summarise_ground_forces(pickup_counts)
                        if labels:
                            pickup_systems[mid_pos] = labels

                by_destination[dest]["arrivals"].append({
                    "from_pos": tile_pos,
                    "ships": unit_labels,
                    "fleet_move": variant_move,
                    "capacity": capacity,
                    "ground_forces": _summarise_ground_forces(payload_ground_forces),
                    "transported_units": _summarise_transportable_units(starting_payload),
                    "pickup_systems": pickup_systems,
                    "via_rift": via_rift,
                    "needs_gravity_drive": needs_gd,
                })

        if not any_reach:
            # No adjacency reachable (e.g. special position with no wormholes)
            no_adjacency.append(tile_pos)
            continue

    # For the active player, run combat simulations against defenders.
    if is_active:
        # Collect all attacker units across all fleets reaching each destination.
        for dest, dest_data in by_destination.items():
            defenders_raw = (tile_unit_data.get(dest) or {}).get("space") or {}
            if not isinstance(defenders_raw, dict):
                continue
            # Build combined defender unit list (all non-player factions)
            all_defender_units: list[dict[str, Any]] = []
            for other_faction, other_units in defenders_raw.items():
                if other_faction == faction:
                    continue
                if isinstance(other_units, list):
                    all_defender_units.extend(other_units)

            if not all_defender_units:
                dest_data["combat_result"] = "(no defenders — unopposed)"
                continue

            defender_group = _build_combat_group(all_defender_units)
            if not defender_group.units:
                dest_data["combat_result"] = "(no defenders with combat stats)"
                continue

            # Use the fleet with the most ships for combat simulation
            best_arrival = max(
                dest_data["arrivals"],
                key=_arrival_combat_size,
            )
            attacker_raw = _arrival_to_unit_dicts(best_arrival)

            attacker_group = _build_combat_group(attacker_raw, faction_units)
            if not attacker_group.units:
                dest_data["combat_result"] = "(attacker has no combat-capable ships)"
                continue

            result = simulate_combat(attacker_group, defender_group, simulations=2000, seed=42)
            dest_data["combat_result"] = _format_combat_result(result)

    return {"by_destination": by_destination, "no_adjacency": no_adjacency}
