"""
Fetch an AsyncTI4 game snapshot from S3 and print a readable analysis.

Usage::

    python scripts/analyze_game.py <game_number>

Example::

    python scripts/analyze_game.py pbd22295
"""

from __future__ import annotations

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
    """
    if fleet_move <= 0:
        return set()

    # BFS state: position → best remaining moves reaching that position
    best_remaining: dict[str, int] = {starting_pos: fleet_move}
    queue: deque[tuple[str, int]] = deque([(starting_pos, fleet_move)])
    reachable: set[str] = set()

    while queue:
        pos, remaining = queue.popleft()
        if remaining <= 0:
            continue

        # Neighbours via hex-grid adjacency + wormhole connections
        neighbours = list(get_adjacent_positions(pos))
        if wormhole_adjacency:
            for wh_pos in wormhole_adjacency.get(pos, frozenset()):
                if wh_pos not in neighbours:
                    neighbours.append(wh_pos)

        for adj_pos in neighbours:
            if adj_pos not in tile_unit_data:
                continue
            tile_data = tile_unit_data[adj_pos]

            # Cannot enter a tile the player has already activated
            if faction in tile_data.get("ccs", []):
                continue

            # Determine movement cost and reachability for this tile
            if tile_type_map is not None:
                info = tile_type_map.get(adj_pos, {})
                # Supernova and Scar: completely impassable
                if info.get("supernova"):
                    continue
                # Asteroid field: impassable without Antimass Deflectors
                if info.get("asteroid") and not has_antimass_deflectors:
                    continue
                # Gravity Rift: moving into/through costs 0 net move (+1 bonus)
                if info.get("gravity_rift"):
                    new_remaining = remaining  # remaining - 1 + 1 = remaining
                # Nebula: can enter, but cannot move further from there
                elif info.get("nebula"):
                    new_remaining = 0
                else:
                    new_remaining = remaining - 1
            else:
                # Legacy fallback: treat all anomaly tiles as impassable
                if tile_data.get("anomaly", False):
                    continue
                new_remaining = remaining - 1

            if best_remaining.get(adj_pos, -1) < new_remaining:
                best_remaining[adj_pos] = new_remaining
                reachable.add(adj_pos)
                if new_remaining > 0:
                    queue.append((adj_pos, new_remaining))

    return reachable


def _get_tactical_reach(
    player_id: str,
    state: "GameState",
) -> tuple[dict[str, list[str]], list[str]]:
    """Return reachable tiles and a list of special-position warnings.

    Returns:
        A 2-tuple of:
        * ``reachable``: ``{tile_position: [planet_names]}`` for tiles
          reachable by the player's unlocked fleets.
        * ``special_positions``: list of position strings where the player
          has an unlocked fleet but adjacency cannot be computed (e.g. "br",
          "tl").

    The AsyncTI4 export uses the player's faction name as the identifier
    inside ``tileUnitData`` (not the player's token-colour slug).
    Returns empty results when tile data is unavailable.
    """
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    if not tile_unit_data:
        return {}, []
    player = state.players.get(player_id)
    if player is None:
        return {}, []
    # tileUnitData uses the faction name (e.g. "jolnar") as the per-player key
    faction = player.faction_id

    # Build per-position tile type info and wormhole adjacency when available
    tile_positions: dict[str, str] = state.extra.get("tile_positions", {})
    tile_type_map: dict[str, dict[str, Any]] | None = None
    wormhole_adjacency: dict[str, frozenset[str]] | None = None
    if tile_positions:
        tile_type_map, wormhole_adjacency = _build_movement_context(tile_positions)

    has_amd = "amd" in (player.researched_technologies or [])

    reachable: dict[str, list[str]] = {}
    special_positions: list[str] = []

    for tile_pos, tile_data in tile_unit_data.items():
        space = tile_data.get("space") or {}
        if not isinstance(space, dict) or faction not in space:
            continue
        # Skip locked tiles (player already placed a CC here)
        if faction in tile_data.get("ccs", []):
            continue
        fleet_move = _fleet_move_value(space[faction])
        if fleet_move <= 0:
            continue
        # Special positions (non-numeric like "br", "tl") cannot be pathfound
        # using the hex-grid formula.  Note: "000" (centre) is numeric and
        # handled normally by get_adjacent_positions / get_reachable_systems.
        try:
            int(tile_pos)
        except ValueError:
            special_positions.append(tile_pos)
            continue
        for dest in get_reachable_systems(
            tile_pos,
            fleet_move,
            tile_unit_data,
            faction,
            tile_type_map=tile_type_map,
            wormhole_adjacency=wormhole_adjacency,
            has_antimass_deflectors=has_amd,
        ):
            if dest not in reachable:
                planets = list((tile_unit_data.get(dest) or {}).get("planets", {}).keys())
                reachable[dest] = planets

    return reachable, special_positions


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


def print_game_summary(state: "GameState") -> None:
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


def print_player_summary(state: "GameState", player_options_map: dict) -> None:
    """Print per-player details and available actions."""
    from engine.options import PlayerAction

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
        print(f"    Techs:    {', '.join(player.researched_technologies) or '(none)'}")
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
                reach, special_positions = _get_tactical_reach(player_id, state)
                if reach:
                    lines = []
                    for pos in sorted(reach):
                        planets = reach[pos]
                        planet_str = ", ".join(planets) if planets else "(empty space)"
                        lines.append(f"{pos}: {planet_str}")
                    print("    Tactical reach (unlocked fleets):")
                    for line in lines:
                        print(f"      {line}")
                if special_positions:
                    print(
                        "    Tactical reach: fleets at special position(s) "
                        f"{', '.join(sorted(special_positions))} — adjacency unknown"
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
