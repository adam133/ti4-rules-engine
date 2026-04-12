"""
Fetch an AsyncTI4 game snapshot from S3 and print a readable analysis.

Usage::

    python scripts/analyze_game.py <game_number>

Example::

    python scripts/analyze_game.py pbd22295
"""

from __future__ import annotations

import functools
import json
import sys
import urllib.request
from collections import deque
from typing import TYPE_CHECKING, Any
from urllib.error import URLError

if TYPE_CHECKING:
    from models.state import GameState

S3_URL_TEMPLATE = (
    "https://s3.us-east-1.amazonaws.com/asyncti4.com/webdata/{game}/{game}.json"
)

# URL for the AsyncTI4 bot's technology data (all tech aliases and full names).
_ASYNCTI4_TECH_URL = (
    "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot"
    "/master/src/main/resources/data/technologies/pok.json"
)

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
) -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]]]:
    """Build a per-position tile type map and wormhole adjacency sets.

    Parameters
    ----------
    tile_positions:
        Mapping of board position (e.g. ``"212"``) to tile ID (e.g. ``"42"``).

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
# Static data: fetch tech names from AsyncTI4 GitHub
# ---------------------------------------------------------------------------


def fetch_tech_names() -> dict[str, str]:
    """Fetch alias→full-name mapping for all technologies from the AsyncTI4 bot.

    Returns a dict mapping the short alias used in game exports (e.g. ``"amd"``)
    to the full display name (e.g. ``"Antimass Deflectors"``).  Falls back to an
    empty dict if the network request fails so the caller can display raw aliases.
    Results are cached after the first successful call.
    """
    return _fetch_tech_names_cached()


@functools.cache
def _fetch_tech_names_cached() -> dict[str, str]:
    """Cached implementation of :func:`fetch_tech_names`."""
    try:
        with urllib.request.urlopen(_ASYNCTI4_TECH_URL, timeout=10) as resp:  # noqa: S310
            techs: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
        return {
            t["alias"]: t["name"]
            for t in techs
            if isinstance(t, dict) and "alias" in t and "name" in t
        }
    except (URLError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"Warning: could not fetch tech names from AsyncTI4 GitHub ({exc!r}); "
            "showing raw tech aliases.",
            file=sys.stderr,
        )
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

    ``fleets`` : list[dict]
        One entry per starting position that has an unlocked mobile fleet.
        Each entry has keys ``"from_pos"``, ``"units"`` (human-readable ship
        list), and ``"destinations"`` (list of destination dicts).

        Each destination dict has:

        ``"pos"`` : str
            Tile position string.
        ``"planets"`` : list[str]
            Planet names (or IDs) in the destination tile.
        ``"via_rift"`` : bool
            ``True`` if the destination is only reachable through a gravity rift.
        ``"needs_gravity_drive"`` : list[str]
            Ships in the fleet whose individual movement value is less than the
            path cost — they would need the *Gravity Drive* technology to make
            this move without holding back the fleet.

    ``no_adjacency`` : list[str]
        Positions where the player has an unlocked fleet but no adjacency can be
        computed (special positions with no wormhole connections).

    The AsyncTI4 export uses the player's faction name as the identifier
    inside ``tileUnitData`` (not the player's token-colour slug).
    Returns empty results when tile data is unavailable.
    """
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    if not tile_unit_data:
        return {"fleets": [], "no_adjacency": []}
    player = state.players.get(player_id)
    if player is None:
        return {"fleets": [], "no_adjacency": []}
    faction = player.faction_id

    tile_positions: dict[str, str] = state.extra.get("tile_positions", {})
    tile_type_map: dict[str, dict[str, Any]] | None = None
    wormhole_adjacency: dict[str, frozenset[str]] | None = None
    if tile_positions:
        tile_type_map, wormhole_adjacency = _build_movement_context(tile_positions)

    has_amd = "amd" in (player.researched_technologies or [])

    fleets: list[dict[str, Any]] = []
    no_adjacency: list[str] = []
    # Accumulate all reachable positions across all fleets to avoid duplicates
    # in the destination list (same tile reachable from multiple starting points).
    all_reachable: dict[str, list[str]] = {}

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

        destinations: list[dict[str, Any]] = []
        for dest, info in sorted(reach_info.items()):
            path_cost = info["path_cost"]
            via_rift = info["via_rift"]
            planets = list((tile_unit_data.get(dest) or {}).get("planets", {}).keys())

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

            destinations.append({
                "pos": dest,
                "planets": planets,
                "via_rift": via_rift,
                "needs_gravity_drive": needs_gd,
            })
            all_reachable[dest] = planets

        fleets.append({
            "from_pos": tile_pos,
            "units": unit_labels,
            "fleet_move": fleet_move,
            "destinations": destinations,
        })

    return {"fleets": fleets, "no_adjacency": no_adjacency}


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
    """Download the game snapshot JSON from S3 and return it as a dict."""
    url = S3_URL_TEMPLATE.format(game=game_number)
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
    print("=" * 60)


def print_player_summary(state: GameState, player_options_map: dict) -> None:
    """Print per-player details and available actions."""
    from engine.options import PlayerAction

    tech_names = fetch_tech_names()
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    planet_ri = _get_planet_ri(tile_unit_data)

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
        if player.scored_objectives:
            print(f"    Scored:   {', '.join(player.scored_objectives)}")

        if opts:
            actions = [a.value for a in opts.available_actions]
            if actions:
                print(f"    Available actions: {', '.join(actions)}")
            else:
                print("    Available actions: (none)")

            if PlayerAction.TACTICAL_ACTION in opts.available_actions:
                reach = _get_tactical_reach(player_id, state)
                fleets = reach.get("fleets", [])
                no_adj = reach.get("no_adjacency", [])

                if fleets:
                    print("    Tactical reach (unlocked fleets):")
                    for fleet in sorted(fleets, key=lambda f: f["from_pos"]):
                        unit_str = ", ".join(fleet["units"]) or "(unknown)"
                        print(
                            f"      From {fleet['from_pos']}"
                            f" [fleet: {unit_str}, move {fleet['fleet_move']}]:"
                        )
                        for dest in fleet["destinations"]:
                            pos = dest["pos"]
                            planets = dest["planets"]
                            planet_str = ", ".join(planets) if planets else "(empty space)"
                            flags: list[str] = []
                            if dest["via_rift"]:
                                flags.append("gravity rift path — all ships at risk")
                            if dest["needs_gravity_drive"]:
                                gd_ships = ", ".join(dest["needs_gravity_drive"])
                                flags.append(f"needs Gravity Drive: {gd_ships}")
                            flag_str = f"  [{'; '.join(flags)}]" if flags else ""
                            print(f"        → {pos}: {planet_str}{flag_str}")

                if no_adj:
                    print(
                        "    Tactical reach: fleets at special position(s) "
                        f"{', '.join(sorted(no_adj))} — no wormhole adjacency known"
                    )

    print()
    print("=" * 60)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/analyze_game.py <game_number>", file=sys.stderr)
        print("Example: python scripts/analyze_game.py pbd22295", file=sys.stderr)
        sys.exit(1)

    game_number = sys.argv[1].strip()

    # Import here so the script can be run from repo root with PYTHONPATH set
    from adapters.asyncti4 import from_asyncti4
    from engine.options import get_player_options

    raw = fetch_game_json(game_number)
    state = from_asyncti4(raw)

    player_options = {
        pid: get_player_options(state, pid) for pid in state.players
    }

    print_game_summary(state)
    print_player_summary(state, player_options)


if __name__ == "__main__":
    main()
