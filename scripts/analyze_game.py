"""
Fetch an AsyncTI4 game snapshot from the bot API and print a readable analysis.

Usage::

    python scripts/analyze_game.py <game_number>

Example::

    python scripts/analyze_game.py pbd22295

Game data is fetched from::

    https://bot.asyncti4.com/api/public/game/{game}/web-data
"""

from __future__ import annotations

import functools
import json
import pathlib
import sys
import urllib.request
from collections import deque
from typing import TYPE_CHECKING, Any
from urllib.error import URLError

from adapters.asyncti4 import from_asyncti4
from engine.combat import CombatGroup, CombatResult, CombatUnit, simulate_combat
from engine.options import get_player_options
from models.unit import Unit, UnitType

if TYPE_CHECKING:
    from models.state import GameState

WEB_DATA_URL_TEMPLATE = (
    "https://bot.asyncti4.com/api/public/game/{game}/web-data"
)

# Path to the bundled data files (data/ at repo root).
_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
_TECH_DATA_FILE = _DATA_DIR / "technologies.json"
_OBJECTIVES_DATA_FILE = _DATA_DIR / "objectives.json"

# ---------------------------------------------------------------------------
# Hex-grid adjacency
# ---------------------------------------------------------------------------
# Translated from the AsyncTI4 bot's PositionMapper.getAdjacentTilePositionsNew()
# Tile positions are strings of the form "RNN" where R is the ring (0–N) and
# NN is the 1-indexed position within that ring (e.g. "211" = ring 2, tile 11).
# Special positions such as "br", "tl", "special" are not supported and return
# an empty list.


def _make_tile_str(ring: int, tile_num: int) -> str:
    """Return the position string for a given ring and tile number.

    ``tile_num`` is automatically wrapped within the ring's bounds.
    Returns ``"000"`` for ring 0 (the centre tile).
    """
    if ring <= 0:
        return "000"
    ring_size = ring * 6
    tile_num = ((tile_num - 1) % ring_size) + 1
    return f"{ring}{tile_num:02d}"


def get_adjacent_positions(pos: str) -> list[str]:
    """Return the (up to six) tile positions adjacent to *pos*.

    The algorithm is a Python port of
    ``PositionMapper.getAdjacentTilePositionsNew`` from the AsyncTI4 bot.
    Non-integer positions (``"br"``, ``"tl"``, ``"special"``, …) are not
    supported and return an empty list.
    """
    if pos == "000":
        return ["101", "102", "103", "104", "105", "106"]
    try:
        pos_int = int(pos)
    except ValueError:
        return []

    ring = pos_int // 100
    tile = pos_int % 100
    side = (tile - 1) // ring
    is_corner = ((tile - 1) % ring) == 0

    next_ring1 = _make_tile_str(ring + 1, tile + side)
    next_ring2 = _make_tile_str(ring + 1, tile + side + 1)
    same_ring_next = _make_tile_str(ring, tile + 1)
    prev_ring1 = _make_tile_str(ring - 1, tile - side)
    same_ring_prev = _make_tile_str(ring, tile - 1)

    if not is_corner:
        prev_ring2 = _make_tile_str(ring - 1, tile - side - 1)
        ordering = [next_ring1, next_ring2, same_ring_next, prev_ring1, prev_ring2, same_ring_prev]
    else:
        next_ring3 = _make_tile_str(ring + 1, tile + side - 1)
        ordering = [next_ring1, next_ring2, same_ring_next, prev_ring1, same_ring_prev, next_ring3]

    # Rotate left by `side` positions (mirrors Collections.rotate(list, -side) in Java)
    s = side % len(ordering)
    return ordering[s:] + ordering[:s]


# ---------------------------------------------------------------------------
# Static tile catalog (sourced from AsyncTI4 bot systems/*.json)
# ---------------------------------------------------------------------------
# Each entry: tile_id → {"supernova", "asteroid", "nebula", "gravity_rift",
#                         "wormholes": list[str]}
# Movement rules:
#   supernova         : impassable (cannot be entered or moved through)
#   asteroid          : impassable unless player has Antimass Deflectors ("amd")
#   nebula            : can be entered as a *destination* but cannot be moved through
#                       (remaining moves drop to 0 on arrival)
#   gravity_rift      : grants +1 movement when moving through or out of the rift
#   wormholes         : tile is adjacent to all other tiles sharing the same wormhole type

_TILE_CATALOG: dict[str, dict[str, Any]] = {
    # --- Wormhole-only tiles (standard game) ---
    "17":  {"wormholes": ["DELTA"]},
    "25":  {"wormholes": ["BETA"]},
    "26":  {"wormholes": ["ALPHA"]},
    "39":  {"wormholes": ["ALPHA"]},
    "40":  {"wormholes": ["BETA"]},
    # --- Standard-game anomalies ---
    "41":  {"gravity_rift": True},
    "42":  {"nebula": True},
    "43":  {"supernova": True},
    "44":  {"asteroid": True},
    "45":  {"asteroid": True},
    "56":  {"nebula": True},
    # --- PoK anomalies / wormholes ---
    "51":  {"wormholes": ["DELTA"]},
    "64":  {"wormholes": ["BETA"]},
    "67":  {"gravity_rift": True},
    "68":  {"nebula": True},
    "79":  {"asteroid": True, "wormholes": ["ALPHA"]},
    "80":  {"supernova": True},
    "81":  {"supernova": True},
    "92":  {"nebula": True},
    "94":  {"wormholes": ["EPSILON"]},
    "102": {"wormholes": ["ALPHA"]},
    "113": {"gravity_rift": True, "wormholes": ["BETA"]},
    "115": {"asteroid": True},
    "117": {"asteroid": True, "gravity_rift": True},
    "118": {"wormholes": ["EPSILON"]},
    # --- Mallice / Nexus (Prophecy of Kings) ---
    "82a": {"wormholes": ["GAMMA"]},
    "82b": {"wormholes": ["BETA", "ALPHA", "GAMMA"]},
    # --- Entropic Scar / Scar tiles (Thunders Edge expansion) ---
    # Note: Scars affect unit *abilities* in the system but do NOT block ship movement.
    "114": {},
    "116": {},
}


def _build_movement_context(
    tile_positions: dict[str, str],
    *,
    creuss_in_game: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]]]:
    """Build a per-position tile type map and wormhole adjacency sets.

    Parameters
    ----------
    tile_positions:
        Mapping of board position (e.g. ``"212"``) to tile ID (e.g. ``"42"``).
    creuss_in_game:
        When ``True``, applies the Ghosts of Creuss faction ability
        *Quantum Entanglement*: all α (ALPHA) and β (BETA) wormhole systems
        are adjacent to each other, merging them into a single adjacency group.
        This affects movement for **all** players, not just the Creuss player.

    Returns
    -------
    tile_type_map:
        ``{pos: tile_info}`` where *tile_info* is the corresponding entry from
        :data:`_TILE_CATALOG` (or an empty dict for uncatalogued tiles).
    wormhole_adjacency:
        ``{pos: frozenset[pos]}`` — positions mutually adjacent via matching
        wormhole types.
    """
    tile_type_map: dict[str, dict[str, Any]] = {}
    wormhole_groups: dict[str, list[str]] = {}  # wormhole_type → [positions]

    for pos, tile_id in tile_positions.items():
        info = _TILE_CATALOG.get(tile_id, {})
        tile_type_map[pos] = info
        for wh in info.get("wormholes", []):
            wormhole_groups.setdefault(wh, []).append(pos)

    # Ghosts of Creuss ability: merge ALPHA and BETA wormhole groups so that
    # every alpha system is adjacent to every beta system and vice versa.
    if creuss_in_game:
        alpha_positions = wormhole_groups.pop("ALPHA", [])
        beta_positions = wormhole_groups.pop("BETA", [])
        merged = alpha_positions + beta_positions
        if merged:
            wormhole_groups["ALPHA_BETA_MERGED"] = merged

    # Build adjacency from matching wormhole groups
    wormhole_adjacency: dict[str, set[str]] = {}
    for positions in wormhole_groups.values():
        if len(positions) >= 2:
            for pos in positions:
                for other in positions:
                    if other != pos:
                        wormhole_adjacency.setdefault(pos, set()).add(other)

    return tile_type_map, {k: frozenset(v) for k, v in wormhole_adjacency.items()}


# ---------------------------------------------------------------------------
# Static data: technology names (ported from AsyncTI4 bot)
# ---------------------------------------------------------------------------


def fetch_tech_names() -> dict[str, str]:
    """Load alias→full-name mapping for all technologies from the bundled data file.

    Returns a dict mapping the short alias used in game exports (e.g. ``"amd"``)
    to the full display name (e.g. ``"Antimass Deflectors"``).  The data is
    ported from the AsyncTI4 bot and stored in ``data/technologies.json``.
    Falls back to an empty dict if the file cannot be read.
    Results are cached after the first call.
    """
    return _load_tech_names_cached()


@functools.cache
def _load_tech_names_cached() -> dict[str, str]:
    """Cached implementation of :func:`fetch_tech_names`."""
    try:
        with _TECH_DATA_FILE.open(encoding="utf-8") as fh:
            techs: list[dict[str, Any]] = json.load(fh)
        return {
            t["alias"]: t["name"]
            for t in techs
            if isinstance(t, dict) and "alias" in t and "name" in t
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"Warning: could not load tech names from {_TECH_DATA_FILE} ({exc!r}); "
            "showing raw tech aliases.",
            file=sys.stderr,
        )
        return {}


def fetch_objective_data() -> dict[str, dict[str, Any]]:
    """Load full objective data from the bundled data file.

    Returns a dict mapping objective ID (e.g. ``"expand_borders"``) to the full
    objective record ``{"id", "name", "type", "points", "description"}``.
    Ported from the AsyncTI4 bot and stored in ``data/objectives.json``.
    Falls back to an empty dict if the file cannot be read.
    Results are cached after the first call.
    """
    return _load_objective_data_cached()


@functools.cache
def _load_objective_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_objective_data`."""
    try:
        with _OBJECTIVES_DATA_FILE.open(encoding="utf-8") as fh:
            objectives: list[dict[str, Any]] = json.load(fh)
        return {
            obj["id"]: obj
            for obj in objectives
            if isinstance(obj, dict) and "id" in obj
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"Warning: could not load objective data from {_OBJECTIVES_DATA_FILE} ({exc!r}); "
            "showing raw objective IDs.",
            file=sys.stderr,
        )
        return {}


def _format_objective(obj_id: str, obj_data: dict[str, dict[str, Any]]) -> str:
    """Return a display string for an objective, using full name and description if available."""
    if obj_id not in obj_data:
        return obj_id
    rec = obj_data[obj_id]
    name = rec.get("name", obj_id)
    desc = rec.get("description", "")
    pts = rec.get("points", "")
    pt_str = f" [{pts}VP]" if pts else ""
    if desc:
        return f"{name}{pt_str} — {desc}"
    return f"{name}{pt_str}"


def fetch_action_tech_names() -> dict[str, str]:
    """Return alias→name for technologies that have an ACTION-timing ability.

    Parses ``data/technologies.json`` and returns entries whose ``text`` field
    contains ``"ACTION:"`` (case-sensitive), indicating the technology can be
    used as a component action.
    """
    return _load_action_tech_names_cached()


@functools.cache
def _load_action_tech_names_cached() -> dict[str, str]:
    """Cached implementation of :func:`fetch_action_tech_names`."""
    try:
        with _TECH_DATA_FILE.open(encoding="utf-8") as fh:
            techs: list[dict[str, Any]] = json.load(fh)
        return {
            t["alias"]: t["name"]
            for t in techs
            if isinstance(t, dict)
            and "alias" in t
            and "name" in t
            and "ACTION:" in t.get("text", "")
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Fleet movement BFS
# ---------------------------------------------------------------------------

# Move values for standard TI4 unit types (entity IDs from AsyncTI4 exports).
# Fighters are transported and excluded from fleet move calculation.
_SHIP_MOVE: dict[str, int] = {
    "cv": 1,   # carrier
    "dd": 2,   # destroyer
    "ca": 2,   # cruiser (alternate ID)
    "cr": 2,   # cruiser
    "dn": 1,   # dreadnought
    "fs": 1,   # flagship (conservative default)
    "ws": 3,   # war sun
}

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

# Transport capacity per ship type (entity ID → slots for ground forces / fighters).
_SHIP_CAPACITY: dict[str, int] = {
    "cv": 4,   # carrier
    "dn": 1,   # dreadnought (base; Advance Carrier upgrade gives 2)
    "fs": 3,   # flagship (generic conservative default)
    "ws": 6,   # war sun
    "dd": 0,   # destroyer
    "ca": 0,   # cruiser
    "cr": 0,   # cruiser
}

# Standard TI4 unit definitions used for Monte Carlo combat simulations.
_COMBAT_UNITS: dict[str, Unit] = {
    "cv": Unit(
        id="carrier", name="Carrier", unit_type=UnitType.CARRIER,
        cost=3, combat=9, move=2, capacity=4,
    ),
    "dd": Unit(
        id="destroyer", name="Destroyer", unit_type=UnitType.DESTROYER,
        cost=1, combat=9, move=2,
    ),
    "ca": Unit(
        id="cruiser", name="Cruiser", unit_type=UnitType.CRUISER,
        cost=2, combat=7, move=2,
    ),
    "cr": Unit(
        id="cruiser", name="Cruiser", unit_type=UnitType.CRUISER,
        cost=2, combat=7, move=2,
    ),
    "dn": Unit(
        id="dreadnought", name="Dreadnought", unit_type=UnitType.DREADNOUGHT,
        cost=4, combat=5, combat_rolls=2, move=1, capacity=1, sustain_damage=True,
    ),
    "fs": Unit(
        id="flagship", name="Flagship", unit_type=UnitType.FLAGSHIP,
        cost=8, combat=5, combat_rolls=2, move=1, sustain_damage=True,
    ),
    "ws": Unit(
        id="war_sun", name="War Sun", unit_type=UnitType.WAR_SUN,
        cost=12, combat=3, combat_rolls=3, move=2, capacity=6, sustain_damage=True,
    ),
    "ff": Unit(
        id="fighter", name="Fighter", unit_type=UnitType.FIGHTER,
        cost=1, combat=9, move=0,
    ),
}


def _fleet_move_value(units: list[dict[str, Any]]) -> int:
    """Return the minimum move value for a collection of space units.

    Only non-transported ships contribute to the fleet's movement range.
    Returns 0 when the list contains no mobile ships.
    """
    move_vals = [
        _SHIP_MOVE[u["entityId"]]
        for u in units
        if isinstance(u, dict)
        and u.get("entityType") == "unit"
        and u.get("entityId") in _SHIP_MOVE
    ]
    return min(move_vals) if move_vals else 0


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


def _fleet_capacity(units: list[dict[str, Any]]) -> int:
    """Return the total transport capacity of a fleet (sum across all ships)."""
    total = 0
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        cap = _SHIP_CAPACITY.get(eid, 0)
        total += cap * u.get("count", 1)
    return total


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


def _build_combat_group(units: list[dict[str, Any]]) -> CombatGroup:
    """Build a :class:`CombatGroup` from a list of raw unit dicts.

    Only units present in :data:`_COMBAT_UNITS` (ships and fighters) with a
    defined ``combat`` stat are included.
    """
    combat_units: list[CombatUnit] = []
    for u in units:
        if not isinstance(u, dict) or u.get("entityType") != "unit":
            continue
        eid = u.get("entityId", "")
        unit_def = _COMBAT_UNITS.get(eid)
        if unit_def is None or unit_def.combat is None:
            continue
        count = u.get("count", 1)
        combat_units.append(CombatUnit(unit_def, count))
    return CombatGroup(combat_units)


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


def _bfs(
    starting_pos: str,
    fleet_move: int,
    tile_unit_data: dict[str, Any],
    faction: str,
    tile_type_map: dict[str, dict[str, Any]] | None = None,
    wormhole_adjacency: dict[str, frozenset[str]] | None = None,
    has_antimass_deflectors: bool = False,
    *,
    ignore_gravity_rift_bonus: bool = False,
) -> dict[str, int]:
    """BFS from *starting_pos*, returning ``{position: best_remaining_moves}``.

    This is the shared core for :func:`get_reachable_systems` and
    :func:`_get_reach_info`.  When *ignore_gravity_rift_bonus* is ``True``
    gravity-rift tiles are treated as normal tiles (cost 1 to enter) so that a
    second BFS run can identify destinations only reachable via the rift bonus.
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

        for adj_pos in neighbours:
            if adj_pos not in tile_unit_data:
                continue
            tile_data = tile_unit_data[adj_pos]

            if faction in tile_data.get("ccs", []):
                continue

            if tile_type_map is not None:
                info = tile_type_map.get(adj_pos, {})
                if info.get("supernova"):
                    continue
                if info.get("asteroid") and not has_antimass_deflectors:
                    continue
                if info.get("gravity_rift") and not ignore_gravity_rift_bonus:
                    new_remaining = remaining  # net cost 0 (−1 + rift bonus +1)
                elif info.get("nebula"):
                    new_remaining = 0
                else:
                    new_remaining = remaining - 1
            else:
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
            * ``"ground_forces"`` – infantry/mechs already carried (from
              starting tile space area + planets in the starting tile).
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
    if tile_positions:
        # Detect if the Ghosts of Creuss are playing — their faction ability
        # (Quantum Entanglement) makes all alpha and beta wormholes adjacent.
        creuss_in_game = any(
            p.faction_id == "ghost" for p in state.players.values()
        )
        tile_type_map, wormhole_adjacency = _build_movement_context(
            tile_positions, creuss_in_game=creuss_in_game
        )

    has_amd = "amd" in (player.researched_technologies or [])

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
        fleet_move = _fleet_move_value(fleet_units)
        if fleet_move <= 0:
            continue

        reach_info = _get_reach_info(
            tile_pos,
            fleet_move,
            tile_unit_data,
            faction,
            tile_type_map=tile_type_map,
            wormhole_adjacency=wormhole_adjacency,
            has_antimass_deflectors=has_amd,
        )

        if not reach_info:
            # No adjacency reachable (e.g. special position with no wormholes)
            no_adjacency.append(tile_pos)
            continue

        unit_labels = _summarise_units(fleet_units)
        capacity = _fleet_capacity(fleet_units)

        # Ground forces already in the fleet (in space area + on planets in starting tile)
        gf_space = _ground_forces_in_space(fleet_units)
        gf_planets = _ground_forces_on_planets(tile_data, faction)
        combined_gf: dict[str, int] = {}
        for eid in ("gf", "mf"):
            total = gf_space.get(eid, 0) + gf_planets.get(eid, 0)
            if total > 0:
                combined_gf[eid] = total

        # Identify intermediate systems (closer to start than any given destination)
        # that have player ground forces on planets and no CC present.
        # These represent possible pickups on the way.
        intermediate_gf: dict[str, dict[str, int]] = {}
        for mid_pos, mid_info in reach_info.items():
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
                    labels = _summarise_units(other_units) if isinstance(other_units, list) else []
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
            for u in fleet_units:
                if not isinstance(u, dict) or u.get("entityType") != "unit":
                    continue
                eid = u.get("entityId", "")
                if eid not in _SHIP_MOVE:
                    continue
                ind_move = _SHIP_MOVE[eid]
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
                mid_path_cost = reach_info.get(mid_pos, {}).get("path_cost", path_cost)
                if mid_path_cost < path_cost:
                    labels = _summarise_ground_forces(mid_gf)
                    if labels:
                        pickup_systems[mid_pos] = labels

            by_destination[dest]["arrivals"].append({
                "from_pos": tile_pos,
                "ships": unit_labels,
                "fleet_move": fleet_move,
                "capacity": capacity,
                "ground_forces": _summarise_ground_forces(combined_gf),
                "pickup_systems": pickup_systems,
                "via_rift": via_rift,
                "needs_gravity_drive": needs_gd,
            })

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

            # Use the strongest arriving fleet for combat simulation
            best_arrival = max(
                dest_data["arrivals"],
                key=lambda a: sum(
                    _SHIP_MOVE.get(u.get("entityId", ""), 0)
                    for u in []  # placeholder — pick first fleet for now
                ) if False else len(a["ships"]),
            )
            # Gather the raw fleet units for the best arrival
            best_from = best_arrival["from_pos"]
            from_tile_data = tile_unit_data.get(best_from) or {}
            from_space = from_tile_data.get("space") or {}
            attacker_raw: list[dict[str, Any]] = (
                from_space.get(faction) or []
            ) if isinstance(from_space, dict) else []

            attacker_group = _build_combat_group(attacker_raw)
            if not attacker_group.units:
                dest_data["combat_result"] = "(attacker has no combat-capable ships)"
                continue

            result = simulate_combat(attacker_group, defender_group, simulations=2000, seed=42)
            dest_data["combat_result"] = _format_combat_result(result)

    return {"by_destination": by_destination, "no_adjacency": no_adjacency}


def _get_planet_ri(
    tile_unit_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract per-planet static data from *tileUnitData*.

    Returns a dict ``{planet_id: {"resources": int, "influence": int}}``
    built from the planet entries embedded in each tile's data.  Only planets
    with non-null ``resources`` and ``influence`` fields are included.
    """
    planet_ri: dict[str, dict[str, Any]] = {}
    for tile_data in tile_unit_data.values():
        for pid, pdata in (tile_data.get("planets") or {}).items():
            if not isinstance(pdata, dict):
                continue
            res = pdata.get("resources")
            inf = pdata.get("influence")
            if res is not None and inf is not None:
                planet_ri[pid] = {"resources": int(res), "influence": int(inf)}
    return planet_ri


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def fetch_game_json(game_number: str) -> dict:
    """Download the game snapshot JSON from the asyncti4 bot web-data API."""
    url = WEB_DATA_URL_TEMPLATE.format(game=game_number)
    print(f"Fetching game data from: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except URLError as exc:
        print(f"ERROR: Failed to fetch game data – {exc}", file=sys.stderr)
        sys.exit(1)
    return json.loads(raw)


def print_game_summary(state: GameState) -> None:
    """Print a human-readable summary of the game state."""
    obj_data = fetch_objective_data()

    print()
    print("=" * 60)
    print(f"  Game:   {state.game_id}")
    print(f"  Round:  {state.round_number}")
    print(f"  Phase:  {state.phase.upper()}")
    if state.active_player_id:
        print(f"  Active: {state.active_player_id}")
    print(f"  Speaker: {state.turn_order.speaker_id}")
    if state.law_ids:
        print(f"  Laws in play: {', '.join(state.law_ids)}")

    # --- Revealed public objectives ---
    if state.public_objectives:
        print()
        print("  PUBLIC OBJECTIVES (revealed):")
        for obj_id in state.public_objectives:
            rec = obj_data.get(obj_id)
            if rec:
                stage = "Stage I" if rec.get("type") == "stage_1" else "Stage II"
                pts = rec.get("points", "?")
                name = rec.get("name", obj_id)
                desc = rec.get("description", "")
                print(f"    [{stage}, {pts}VP] {name}")
                if desc:
                    print(f"      {desc}")
            else:
                print(f"    {obj_id}")

    print("=" * 60)


def _get_leader_type(leader: dict[str, Any]) -> str:
    """Infer leader type (agent/commander/hero) from the leader dict."""
    if "type" in leader:
        return str(leader["type"]).lower()
    # Fall back to inferring from the ID suffix
    lid = str(leader.get("id", "")).lower()
    for suffix in ("agent", "commander", "hero"):
        if lid.endswith(suffix):
            return suffix
    return "leader"


def _format_leader(leader: dict[str, Any]) -> str:
    """Return a display string for a leader card with status indicators."""
    lid = str(leader.get("id", "unknown"))
    ltype = _get_leader_type(leader).capitalize()
    exhausted = leader.get("exhausted", False)
    locked = leader.get("locked", False)
    if locked:
        status = "LOCKED"
    elif exhausted:
        status = "exhausted"
    else:
        status = "READY"
    return f"{lid} ({ltype}) [{status}]"


def print_player_summary(state: GameState, player_options_map: dict) -> None:
    """Print per-player details and available actions."""
    from engine.options import PlayerAction

    tech_names = fetch_tech_names()
    action_techs = fetch_action_tech_names()
    obj_data = fetch_objective_data()
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    planet_ri = _get_planet_ri(tile_unit_data)
    player_leaders: dict[str, list[dict[str, Any]]] = state.extra.get("player_leaders", {})

    print()
    print("  PLAYERS")
    print("  " + "-" * 56)

    for player_id in state.turn_order.order:
        if player_id not in state.players:
            continue
        player = state.players[player_id]
        opts = player_options_map.get(player_id)

        speaker_marker = " [SPEAKER]" if player_id == state.turn_order.speaker_id else ""
        active_marker = " [ACTIVE]" if player_id == state.active_player_id else ""
        passed_marker = " [PASSED]" if player.passed else ""

        print(f"\n  {player_id}{speaker_marker}{active_marker}{passed_marker}")
        print(f"    Faction:  {player.faction_id}")
        print(f"    VP:       {player.victory_points}")
        print(f"    TG:       {player.trade_goods}  |  Commodities: {player.commodities}")
        print(
            f"    Tokens:   {player.tactical_tokens} tactical"
            f" / {player.fleet_tokens} fleet"
            f" / {player.strategy_tokens} strategy"
        )
        print(
            f"    Planets:  {len(player.controlled_planets)} controlled"
            f", {len(player.exhausted_planets)} exhausted"
        )

        # --- Readied planets with resources / influence ---
        exhausted = set(player.exhausted_planets)
        ready_planets = [p for p in player.controlled_planets if p not in exhausted]
        total_ready_res = sum(planet_ri.get(p, {}).get("resources", 0) for p in ready_planets)
        total_ready_inf = sum(planet_ri.get(p, {}).get("influence", 0) for p in ready_planets)
        if ready_planets:
            planet_parts = []
            for p in sorted(ready_planets):
                ri = planet_ri.get(p)
                if ri:
                    planet_parts.append(f"{p} ({ri['resources']}R/{ri['influence']}I)")
                else:
                    planet_parts.append(p)
            print(
                f"    Readied:  {total_ready_res} resources, {total_ready_inf} influence"
                f"  — {', '.join(planet_parts)}"
            )
        else:
            print("    Readied:  0 resources, 0 influence  — (all planets exhausted)")

        # --- Technologies (full names where available) ---
        tech_ids = player.researched_technologies
        if tech_ids:
            tech_display = [tech_names.get(t, t) for t in tech_ids]
            print(f"    Techs:    {', '.join(tech_display)}")
        else:
            print("    Techs:    (none)")

        if player.strategy_card_ids:
            print(f"    Strat cards: {', '.join(player.strategy_card_ids)}")

        # --- Scored objectives (full names + descriptions) ---
        if player.scored_objectives:
            print("    Scored objectives:")
            for obj_id in player.scored_objectives:
                print(f"      • {_format_objective(obj_id, obj_data)}")

        # --- Unscored public objectives + eligibility ---
        if state.public_objectives:
            scored_set = set(player.scored_objectives)
            unscored_public = [
                oid for oid in state.public_objectives if oid not in scored_set
            ]
            if unscored_public:
                print("    Unscored public objectives:")
                for obj_id in unscored_public:
                    obj_str = _format_objective(obj_id, obj_data)
                    print(f"      ○ {obj_str}")

        # --- Leaders (agents, commanders, heroes) ---
        leaders = player_leaders.get(player_id, [])
        if leaders:
            print("    Leaders:")
            for leader in leaders:
                ltype = _get_leader_type(leader)
                exhausted_flag = leader.get("exhausted", False)
                locked_flag = leader.get("locked", False)
                lid = str(leader.get("id", "unknown"))
                ltype_cap = ltype.capitalize()
                if locked_flag:
                    status = "LOCKED"
                elif exhausted_flag:
                    status = "exhausted"
                else:
                    status = "READY"
                print(f"      {lid} ({ltype_cap}): {status}")

        if opts:
            actions = [a.value for a in opts.available_actions]
            if actions:
                print(f"    Available actions: {', '.join(actions)}")
            else:
                print("    Available actions: (none)")

            # --- Public component actions detail ---
            if PlayerAction.COMPONENT_ACTION in opts.available_actions:
                component_sources: list[str] = []

                # Technologies with ACTION timing
                action_tech_ids = [
                    t for t in (player.researched_technologies or [])
                    if t in action_techs
                ]
                for t in action_tech_ids:
                    component_sources.append(f"tech: {action_techs[t]}")

                # Readied (not exhausted, not locked) agents
                for leader in leaders:
                    if _get_leader_type(leader) == "agent":
                        if not leader.get("exhausted", False) and not leader.get("locked", False):
                            component_sources.append(
                                f"agent: {leader.get('id', 'unknown')} (readied)"
                            )

                if component_sources:
                    print("    Public component actions:")
                    for src in component_sources:
                        print(f"      • {src}")
                else:
                    print("    Public component actions: (action cards not shown)")

            if PlayerAction.TACTICAL_ACTION in opts.available_actions:
                reach = _get_tactical_reach(player_id, state)
                by_dest = reach.get("by_destination", {})
                no_adj = reach.get("no_adjacency", [])
                is_active = player_id == state.active_player_id

                if by_dest:
                    print("    Tactical reach (by destination):")
                    for dest_pos in sorted(by_dest):
                        dest_data = by_dest[dest_pos]
                        planets = dest_data["planets"]
                        planet_str = ", ".join(planets) if planets else "(empty space)"
                        defenders = dest_data.get("defenders", {})
                        defender_strs = [
                            f"{fac}: {', '.join(units)}"
                            for fac, units in sorted(defenders.items())
                        ]
                        def_str = (
                            "  [defenders: " + "; ".join(defender_strs) + "]"
                            if defender_strs else ""
                        )
                        print(f"      {dest_pos} — {planet_str}{def_str}")

                        for arrival in sorted(dest_data["arrivals"], key=lambda a: a["from_pos"]):
                            ships_str = ", ".join(arrival["ships"]) or "(unknown)"
                            flags: list[str] = []
                            if arrival["via_rift"]:
                                flags.append("gravity rift — all ships at risk")
                            if arrival["needs_gravity_drive"]:
                                gd_ships = ", ".join(arrival["needs_gravity_drive"])
                                flags.append(f"needs Gravity Drive: {gd_ships}")
                            flag_str = f"  [{'; '.join(flags)}]" if flags else ""
                            cap = arrival["capacity"]
                            cap_str = f", capacity {cap}" if cap > 0 else ""
                            print(
                                f"        ← from {arrival['from_pos']}"
                                f" [{ships_str}, move {arrival['fleet_move']}{cap_str}]{flag_str}"
                            )
                            gf = arrival["ground_forces"]
                            if gf:
                                from_pos = arrival['from_pos']
                                print(
                                    f"          ground forces: {', '.join(gf)}"
                                    f" (from {from_pos})"
                                )
                            pickup = arrival.get("pickup_systems", {})
                            for pick_pos in sorted(pickup):
                                pick_labels = pickup[pick_pos]
                                print(
                                    f"          + can pick up:"
                                    f" {', '.join(pick_labels)} from {pick_pos}"
                                )

                        if is_active and dest_data.get("combat_result"):
                            print(f"        ⚔ combat: {dest_data['combat_result']}")

                if no_adj:
                    print(
                        "    Tactical reach: fleets at special position(s) "
                        f"{', '.join(sorted(no_adj))} — no wormhole adjacency known"
                    )

    print()
    print("=" * 60)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ti4-analyze <game_number>", file=sys.stderr)
        print("Example: ti4-analyze pbd22295", file=sys.stderr)
        sys.exit(1)

    game_number = sys.argv[1].strip()

    raw = fetch_game_json(game_number)
    state = from_asyncti4(raw)

    player_options = {
        pid: get_player_options(state, pid) for pid in state.players
    }

    print_game_summary(state)
    print_player_summary(state, player_options)


if __name__ == "__main__":
    main()
