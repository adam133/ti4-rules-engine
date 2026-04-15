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
import re
import sys
import urllib.request
from collections import Counter, deque
from typing import TYPE_CHECKING, Any
from urllib.error import URLError

from ti4_rules_engine.adapters.asyncti4 import from_asyncti4
from ti4_rules_engine.engine.combat import CombatGroup, CombatResult, CombatUnit, simulate_combat
from ti4_rules_engine.engine.options import get_player_options
from ti4_rules_engine.models.unit import Unit, UnitType

if TYPE_CHECKING:
    from ti4_rules_engine.models.state import GameState

WEB_DATA_URL_TEMPLATE = (
    "https://bot.asyncti4.com/api/public/game/{game}/web-data"
)

# Path to the bundled data files (data/ at repo root).
_DATA_DIR = pathlib.Path(__file__).parent.parent / "data"
_TECH_DATA_FILE = _DATA_DIR / "technologies.json"
_OBJECTIVES_DATA_FILE = _DATA_DIR / "objectives.json"
_PUBLIC_OBJECTIVES_DATA_FILE = _DATA_DIR / "public_objectives.json"
_LEADERS_DATA_FILE = _DATA_DIR / "leaders.json"
_HYPERLANES_DATA_FILE = _DATA_DIR / "hyperlanes.json"
_UNITS_DATA_DIR = _DATA_DIR / "units"
_ASYNCTI4_DATA_DIR = _DATA_DIR / "asyncti4"
_ASYNCTI4_ATTACHMENTS_DATA_DIR = _ASYNCTI4_DATA_DIR / "attachments"
_ASYNCTI4_PLANETS_DATA_DIR = _ASYNCTI4_DATA_DIR / "planets"
_ASYNCTI4_SYSTEMS_DATA_DIR = _ASYNCTI4_DATA_DIR / "systems"

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

# ---------------------------------------------------------------------------
# Hyperlane tile identification
# ---------------------------------------------------------------------------
# Hyperlane tiles are positioned on the map but are NOT real game systems.
# Ships cannot stop on them; they only provide adjacency between adjacent tiles.
# Tile IDs 83–91 (with "a"/"b" variant and optional rotation suffix) and IDs
# starting with "hl_" are all hyperlane tiles, as defined in the AsyncTI4 bot's
# hyperlanes.properties data file.

_HYPERLANE_ID_RE = re.compile(r"^(83|84|85|86|87|88|89|90|91)[ab](\d+)?$|^hl_")


def _is_hyperlane_tile_id(tile_id: str) -> bool:
    """Return ``True`` if *tile_id* identifies a hyperlane tile.

    Hyperlane tiles (IDs 83a–91b with optional rotation suffix and IDs
    prefixed with ``hl_``) are transparent connectors on the board.  Ships
    cannot land on them; they only create adjacency between the real game
    tiles on either side.
    """
    return bool(_HYPERLANE_ID_RE.match(tile_id))


def _build_movement_context(
    tile_positions: dict[str, str],
    *,
    creuss_in_game: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """Build a per-position tile type map, wormhole adjacency sets, and hyperlane adjacency.

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
        Hyperlane tiles are marked with ``{"hyperlane": True}`` so that the BFS
        skips them as destinations.
    wormhole_adjacency:
        ``{pos: frozenset[pos]}`` — positions mutually adjacent via matching
        wormhole types.
    hyperlane_adjacency:
        ``{pos: frozenset[pos]}`` — non-hyperlane positions reachable from each
        non-hyperlane position through adjacent hyperlane tile chains (following
        edge-specific connection rules).  Ships treat these destinations as
        ordinary 1-move neighbours.
    """
    tile_type_map: dict[str, dict[str, Any]] = {}
    wormhole_groups: dict[str, list[str]] = {}  # wormhole_type → [positions]

    for pos, tile_id in tile_positions.items():
        info = _TILE_CATALOG.get(tile_id, {})
        if _is_hyperlane_tile_id(tile_id):
            # Merge the hyperlane flag without mutating _TILE_CATALOG entries
            info = {**info, "hyperlane": True}
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

    hyperlane_adjacency = _build_hyperlane_adjacency(tile_positions)

    return (
        tile_type_map,
        {k: frozenset(v) for k, v in wormhole_adjacency.items()},
        hyperlane_adjacency,
    )


# ---------------------------------------------------------------------------
# Hyperlane edge-specific adjacency
# ---------------------------------------------------------------------------


@functools.cache
def _load_hyperlane_connections() -> dict[str, list[list[int]]]:
    """Load the hyperlane edge-connectivity matrices from the bundled data file.

    Returns a dict mapping tile ID (e.g. ``"83a"``, ``"86a240"``) to a 6×6
    integer adjacency matrix where ``matrix[i][j] == 1`` means edge *i* of the
    tile is connected to edge *j* through the hyperlane path.  The matrix is
    always symmetric.  Falls back to an empty dict on any error.
    """
    try:
        with _HYPERLANES_DATA_FILE.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"Warning: could not load hyperlane data from {_HYPERLANES_DATA_FILE}"
            f" ({exc!r}); hyperlane adjacency will be empty.",
            file=sys.stderr,
        )
        return {}


def _build_hyperlane_adjacency(
    tile_positions: dict[str, str],
) -> dict[str, frozenset[str]]:
    """Return a map of position → positions reachable via adjacent hyperlane chains.

    For each non-hyperlane position *A*, walks along any adjacent hyperlane
    tiles following their edge-specific connections (including chains of
    consecutive hyperlane tiles) and collects all non-hyperlane positions that
    can be reached.  Ships enter a hyperlane from the edge facing the source
    tile; only the connected exit edges (as defined by the hyperlane's
    connection matrix) lead to valid destinations.

    Parameters
    ----------
    tile_positions:
        Mapping of board position to tile ID for every tile currently on the map.

    Returns
    -------
    A dict where each key is a non-hyperlane position that has at least one
    hyperlane-connected destination, and the value is the ``frozenset`` of
    reachable non-hyperlane positions (excluding the source itself).
    """
    connections = _load_hyperlane_connections()
    existing = set(tile_positions)

    def _traverse(hl_pos: str, entered_from: str, visited: frozenset[str]) -> set[str]:
        """Recursively follow hyperlane connections from *hl_pos* entered via *entered_from*."""
        if hl_pos in visited:
            return set()
        visited = visited | {hl_pos}

        tile_id = tile_positions.get(hl_pos, "")
        matrix = connections.get(tile_id)
        if matrix is None:
            return set()

        neighbors = get_adjacent_positions(hl_pos)
        try:
            entry_edge = neighbors.index(entered_from)
        except ValueError:
            return set()

        destinations: set[str] = set()
        for exit_edge, connected in enumerate(matrix[entry_edge]):
            if not connected:
                continue
            if exit_edge >= len(neighbors):
                continue
            exit_pos = neighbors[exit_edge]
            if exit_pos not in existing:
                continue
            exit_tile_id = tile_positions.get(exit_pos, "")
            if _is_hyperlane_tile_id(exit_tile_id):
                destinations |= _traverse(exit_pos, hl_pos, visited)
            else:
                destinations.add(exit_pos)
        return destinations

    result: dict[str, set[str]] = {}
    for pos, tile_id in tile_positions.items():
        if _is_hyperlane_tile_id(tile_id):
            continue
        hl_neighbors = [
            hl_neighbor
            for hl_neighbor in get_adjacent_positions(pos)
            if hl_neighbor in existing
            and _is_hyperlane_tile_id(tile_positions.get(hl_neighbor, ""))
        ]
        for hl_neighbor in hl_neighbors:
            hl_tile_id = tile_positions.get(hl_neighbor, "")
            dests = _traverse(hl_neighbor, pos, frozenset())
            if (
                not dests
                and len(hl_neighbors) >= _MIN_HYPERLANE_NEIGHBORS_FOR_FALLBACK
            ):
                # Fallback for maps whose hyperlane tile rotation metadata does not
                # align with this position ordering: try all possible entry rows on
                # the first hyperlane tile, then continue strict traversal.
                matrix = connections.get(hl_tile_id)
                if matrix is not None:
                    neighbors = get_adjacent_positions(hl_neighbor)
                    fallback_dests: set[str] = set()
                    for row in matrix:
                        for exit_edge, connected in enumerate(row):
                            if not connected or exit_edge >= len(neighbors):
                                continue
                            exit_pos = neighbors[exit_edge]
                            if exit_pos not in existing:
                                continue
                            exit_tile_id = tile_positions.get(exit_pos, "")
                            if _is_hyperlane_tile_id(exit_tile_id):
                                fallback_dests |= _traverse(
                                    exit_pos,
                                    hl_neighbor,
                                    frozenset({hl_neighbor}),
                                )
                            else:
                                fallback_dests.add(exit_pos)
                    fallback_dests.discard(pos)
                    dests = fallback_dests
            if dests:
                result.setdefault(pos, set()).update(dests)

    return {pos: frozenset(dests) for pos, dests in result.items()}


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


def _has_fighter_ii(researched_techs: list[str]) -> bool:
    """Return ``True`` if the player's researched techs include any Fighter II upgrade."""
    fighter_ii_aliases = _load_fighter_ii_aliases_cached()
    return any(t in fighter_ii_aliases for t in (researched_techs or []))


@functools.cache
def _load_fighter_ii_aliases_cached() -> frozenset[str]:
    """Return all technology aliases that represent Fighter II upgrades."""
    try:
        with _TECH_DATA_FILE.open(encoding="utf-8") as fh:
            techs: list[dict[str, Any]] = json.load(fh)
        aliases = {
            t["alias"]
            for t in techs
            if isinstance(t, dict)
            and "alias" in t
            and (
                t.get("alias") == _FIGHTER_II_TECH_ID
                or t.get("baseUpgrade") == _FIGHTER_II_TECH_ID
            )
        }
        aliases.add(_FIGHTER_II_TECH_ID)
        return frozenset(aliases)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return frozenset({_FIGHTER_II_TECH_ID})


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
    objective record. Data is loaded from ``data/objectives.json`` and from
    ``data/public_objectives.json`` (ported from the AsyncTI4 bot).
    Falls back to an empty dict if the file cannot be read.
    Results are cached after the first call.
    """
    return _load_objective_data_cached()


@functools.cache
def _load_objective_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_objective_data`."""
    objective_data: dict[str, dict[str, Any]] = {}
    try:
        with _OBJECTIVES_DATA_FILE.open(encoding="utf-8") as fh:
            objectives: list[dict[str, Any]] = json.load(fh)
        objective_data.update(
            {
                obj["id"]: obj
                for obj in objectives
                if isinstance(obj, dict) and "id" in obj
            }
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"Warning: could not load objective data from {_OBJECTIVES_DATA_FILE} ({exc!r}); "
            "showing raw objective IDs.",
            file=sys.stderr,
        )

    try:
        with _PUBLIC_OBJECTIVES_DATA_FILE.open(encoding="utf-8") as fh:
            public_objectives: list[dict[str, Any]] = json.load(fh)
        for obj in public_objectives:
            if not isinstance(obj, dict):
                continue
            alias = obj.get("alias")
            if not alias:
                continue
            text = obj.get("text")
            notes = obj.get("notes")
            description = text
            if text and notes:
                description = f"{text} Note: {notes}"
            public_entry: dict[str, Any] = {
                "id": alias,
                "name": obj.get("name", alias),
                "points": obj.get("points"),
                "description": description,
                "source": obj.get("source"),
            }
            if obj.get("points") == 1:
                public_entry["type"] = "stage_1"
            elif obj.get("points") == 2:
                public_entry["type"] = "stage_2"
            else:
                public_entry["type"] = "public"
            if alias in objective_data:
                # Keep existing local data but backfill missing condition text.
                if not _get_objective_condition_text(objective_data[alias]):
                    objective_data[alias]["description"] = description
            else:
                objective_data[alias] = public_entry
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    if objective_data:
        return objective_data
    return {}


def _get_objective_condition_text(obj: dict[str, Any]) -> str:
    """Return the best available condition text for an objective record."""
    return str(
        obj.get("description")
        or obj.get("condition")
        or obj.get("text")
        or ""
    )


def _get_objective_stage_label(obj: dict[str, Any]) -> str:
    """Infer a human-readable stage label from objective metadata."""
    obj_type = obj.get("type")
    points = obj.get("points")
    if obj_type == "stage_1" or points == 1:
        return "Stage I"
    if obj_type == "stage_2" or points == 2:
        return "Stage II"
    return "Public"


def _format_objective(obj_id: str, obj_data: dict[str, dict[str, Any]]) -> str:
    """Return a display string for an objective with score and condition text."""
    if obj_id not in obj_data:
        return obj_id
    rec = obj_data[obj_id]
    name = rec.get("name", obj_id)
    desc = _get_objective_condition_text(rec)
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


def fetch_leader_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of leader id → leader record from ``data/leaders.json``.

    Each record contains at minimum: ``id``, ``faction``, ``type``, ``name``,
    ``title``, ``abilityWindow``, and ``source``.
    """
    return _load_leader_data_cached()


@functools.cache
def _load_leader_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_leader_data`."""
    try:
        with _LEADERS_DATA_FILE.open(encoding="utf-8") as fh:
            leaders: list[dict[str, Any]] = json.load(fh)
        return {
            entry["id"]: entry
            for entry in leaders
            if isinstance(entry, dict) and "id" in entry
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def fetch_system_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of system-tile ID → system metadata record."""
    return _load_system_data_cached()


def fetch_planet_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of planet ID → planet metadata record."""
    return _load_planet_data_cached()


def fetch_attachment_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of attachment/token ID → attachment metadata record."""
    return _load_attachment_data_cached()


@functools.cache
def _load_system_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_system_data`."""
    systems: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_SYSTEMS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "id" in data:
                systems[str(data["id"])] = data
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return systems


@functools.cache
def _load_planet_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_planet_data`."""
    planets: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_PLANETS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "id" in data:
                planets[str(data["id"])] = data
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return planets


@functools.cache
def _load_attachment_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_attachment_data`."""
    attachments: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_ATTACHMENTS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "id" in item:
                        attachments[str(item["id"])] = item
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return attachments


# Mapping from asyncti4 baseType → UnitType enum value.
_BASE_TYPE_TO_UNIT_TYPE: dict[str, UnitType] = {
    "carrier": UnitType.CARRIER,
    "cruiser": UnitType.CRUISER,
    "destroyer": UnitType.DESTROYER,
    "dreadnought": UnitType.DREADNOUGHT,
    "flagship": UnitType.FLAGSHIP,
    "warsun": UnitType.WAR_SUN,
    "fighter": UnitType.FIGHTER,
    "infantry": UnitType.GROUND_FORCE,
    "mech": UnitType.MECH,
    "pds": UnitType.PDS,
    "spacedock": UnitType.SPACE_DOCK,
}


def _asyncti4_unit_to_model(entry: dict[str, Any]) -> Unit | None:
    """Convert an asyncti4 unit JSON entry to a :class:`Unit` model.

    Returns ``None`` for entries whose ``baseType`` is not recognised or that
    lack an ``asyncId`` field.
    """
    base_type = entry.get("baseType", "")
    unit_type = _BASE_TYPE_TO_UNIT_TYPE.get(base_type)
    if unit_type is None:
        return None
    async_id = entry.get("asyncId")
    if not async_id:
        return None
    combat_hits_on = entry.get("combatHitsOn")
    return Unit(
        id=entry.get("id", async_id),
        name=entry.get("name", async_id),
        unit_type=unit_type,
        cost=entry.get("cost"),
        combat=combat_hits_on if isinstance(combat_hits_on, int) else None,
        combat_rolls=entry.get("combatDieCount", 1) or 1,
        move=entry.get("moveValue"),
        capacity=entry.get("capacityValue", 0),
        sustain_damage=bool(entry.get("sustainDamage", False)),
        planetary_shield=bool(entry.get("planetaryShield", False)),
        bombardment=entry.get("bombardHitsOn"),
        bombardment_rolls=entry.get("bombardDieCount", 1) or 1,
        space_cannon=entry.get("spaceCannonHitsOn"),
        space_cannon_rolls=entry.get("spaceCannonDieCount", 1) or 1,
    )


def fetch_unit_data(faction: str | None = None) -> dict[str, Unit]:
    """Return a mapping of asyncId → :class:`Unit` built from the bundled data files.

    Loads ``data/units/baseUnits.json`` for the standard units.  If *faction*
    is provided, also loads ``data/units/pok.json`` and applies any faction-
    specific unit overrides (e.g. Titans' cruiser with capacity).

    The returned dict is keyed by ``asyncId`` (e.g. ``"cv"``, ``"dd"``).
    Where a faction has a variant of a unit type that differs from the base
    stats, the faction variant takes precedence.
    """
    return _load_unit_data_cached(faction)


@functools.cache
def _load_unit_data_cached(faction: str | None = None) -> dict[str, Unit]:
    """Cached implementation of :func:`fetch_unit_data`."""
    units: dict[str, Unit] = {}

    # 1. Load base units (shared by all factions).
    try:
        base_file = _UNITS_DATA_DIR / "baseUnits.json"
        with base_file.open(encoding="utf-8") as fh:
            base_entries: list[dict[str, Any]] = json.load(fh)
        for entry in base_entries:
            model = _asyncti4_unit_to_model(entry)
            if model is None:
                continue
            async_id = entry["asyncId"]
            # Only keep the base (non-upgraded) variant as the default – it
            # has no "upgradesFromUnitId" field.
            if "upgradesFromUnitId" not in entry:
                units[async_id] = model
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    # 2. Apply faction-specific overrides when requested.
    if faction:
        try:
            pok_file = _UNITS_DATA_DIR / "pok.json"
            with pok_file.open(encoding="utf-8") as fh:
                pok_entries: list[dict[str, Any]] = json.load(fh)
            for entry in pok_entries:
                if entry.get("faction") != faction:
                    continue
                if "upgradesFromUnitId" in entry:
                    # Upgraded variants are not the unit's default stats.
                    continue
                model = _asyncti4_unit_to_model(entry)
                if model is None:
                    continue
                async_id = entry["asyncId"]
                units[async_id] = model
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass

    # Add "cr" as an alias for "ca" (cruiser) – some AsyncTI4 exports use
    # "cr" as the entity ID for cruisers.
    if "ca" in units and "cr" not in units:
        units["cr"] = units["ca"]

    return units


def _build_ship_move_map(unit_data: dict[str, Unit]) -> dict[str, int]:
    """Build a move-value lookup from a unit registry.

    Only ships (units with a move value) are included; fighters are excluded
    as they are transported rather than self-propelled.
    """
    fighter_type = UnitType.FIGHTER
    return {
        async_id: unit.move
        for async_id, unit in unit_data.items()
        if unit.move is not None and unit.unit_type is not fighter_type
    }


def _build_ship_capacity_map(unit_data: dict[str, Unit]) -> dict[str, int]:
    """Build a capacity-value lookup (transport slots) from a unit registry."""
    return {async_id: unit.capacity for async_id, unit in unit_data.items()}


# ---------------------------------------------------------------------------
# Fleet movement BFS
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
_FIGHTER_II_TECH_ID = "ff2"
_DEFAULT_SPACE_DOCK_FIGHTER_CAPACITY = 3
_FIGHTER_II_MOVE_SPEED = 2
# Entry-agnostic fallback is only enabled when a source has 2+ adjacent
# hyperlane connectors (branch points), where rotation mismatches are most likely.
_MIN_HYPERLANE_NEIGHBORS_FOR_FALLBACK = 2

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
                key=lambda a: len(a["ships"]),
            )
            # Gather the raw fleet units for the best arrival
            best_from = best_arrival["from_pos"]
            from_tile_data = tile_unit_data.get(best_from) or {}
            from_space = from_tile_data.get("space") or {}
            attacker_raw: list[dict[str, Any]] = (
                from_space.get(faction) or []
            ) if isinstance(from_space, dict) else []

            attacker_group = _build_combat_group(attacker_raw, faction_units)
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


def _tile_position_sort_key(pos: str) -> tuple[int, int, str]:
    """Sort numeric map positions first by integer value.

    Non-numeric position strings are sorted alphabetically after numeric ones.
    """
    try:
        pos_int = int(pos)
        return (0, pos_int, "")
    except ValueError:
        return (1, 0, pos)


def _format_entity_display_name(entity_id: str, entity_type: str) -> str:
    """Return a human-readable display name for a tile entity."""
    if entity_type == "unit":
        return _UNIT_NAMES.get(entity_id, entity_id)
    attachment_data = fetch_attachment_data()
    if entity_id in attachment_data:
        return str(attachment_data[entity_id].get("name", entity_id))
    return entity_id.replace("_", " ")


def _format_modifier(modifier: int, label: str) -> str:
    """Return a signed modifier label, e.g. ``'+2 resources'``."""
    return f"{modifier:+d} {label}"


def _describe_attachment_effect(entity_id: str) -> str | None:
    """Return a concise effect description for an attachment/token if known."""
    special_tokens = {
        "frontier": "explore token when this system is activated",
        "custodian": "must spend 6 influence to remove this token and score 1 VP",
    }
    if entity_id in special_tokens:
        return special_tokens[entity_id]

    rec = fetch_attachment_data().get(entity_id)
    if not isinstance(rec, dict):
        return None

    effects: list[str] = []
    res_mod = rec.get("resourcesModifier")
    inf_mod = rec.get("influenceModifier")
    if isinstance(res_mod, int) and res_mod != 0:
        effects.append(_format_modifier(res_mod, "resources"))
    if isinstance(inf_mod, int) and inf_mod != 0:
        effects.append(_format_modifier(inf_mod, "influence"))

    tech_specs = rec.get("techSpeciality")
    if isinstance(tech_specs, list) and tech_specs:
        effects.append("adds tech specialty: " + ", ".join(str(s) for s in tech_specs))

    planet_types = rec.get("planetTypes")
    if isinstance(planet_types, list) and planet_types:
        effects.append("planet trait becomes: " + ", ".join(str(p) for p in planet_types))

    if rec.get("isLegendary"):
        effects.append("planet becomes legendary")

    die_count = rec.get("spaceCannonDieCount")
    hits_on = rec.get("spaceCannonHitsOn")
    if isinstance(die_count, int) and isinstance(hits_on, int):
        effects.append(f"grants SPACE CANNON {hits_on} (x{die_count})")

    if not effects:
        return "special attachment effect"
    return "; ".join(effects)


def _summarise_entity_list(entities: list[dict[str, Any]]) -> list[str]:
    """Return sorted ``"<name> x<count>"`` labels for units/tokens in *entities*."""
    counts: Counter[str] = Counter()
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        entity_type = str(entry.get("entityType", ""))
        entity_id = str(entry.get("entityId", ""))
        if not entity_id:
            continue
        raw_count = entry.get("count", 1)
        count = raw_count if isinstance(raw_count, int) else 1
        name = _format_entity_display_name(entity_id, entity_type)
        if entity_type != "unit":
            effect = _describe_attachment_effect(entity_id)
            if effect:
                name = f"{name} ({effect})"
        counts[name] += count
    return [
        name if count == 1 else f"{name} x{count}"
        for name, count in sorted(counts.items())
    ]


def _format_system_label(tile_id: str | None) -> str | None:
    """Return the display label for a tile ID, preferring the system name."""
    if not tile_id:
        return None
    rec = fetch_system_data().get(tile_id)
    if isinstance(rec, dict) and rec.get("name"):
        return str(rec["name"])
    return f"tile {tile_id}"


def _format_system_static_details(tile_id: str | None) -> list[str]:
    """Return static descriptors for a system tile (anomalies/wormholes/stations)."""
    if not tile_id:
        return []
    rec = fetch_system_data().get(tile_id)
    if not isinstance(rec, dict):
        return []

    details: list[str] = []
    anomalies: list[str] = []
    for key, name in (
        ("isSupernova", "supernova"),
        ("isAsteroidField", "asteroid field"),
        ("isNebula", "nebula"),
        ("isGravityRift", "gravity rift"),
    ):
        if rec.get(key):
            anomalies.append(name)
    if anomalies:
        details.append("anomalies: " + ", ".join(anomalies))

    wormholes = rec.get("wormholes")
    if isinstance(wormholes, list) and wormholes:
        details.append("wormholes: " + ", ".join(str(w).lower() for w in wormholes))

    station_planets = [
        p for p in rec.get("planets", [])
        if isinstance(p, str) and "station" in p.lower()
    ]
    if station_planets:
        details.append("trade stations: " + ", ".join(sorted(station_planets)))
    return details


def _format_planet_metadata(planet_id: str) -> str | None:
    """Return static planet metadata string (name, base R/I, legendary text)."""
    rec = fetch_planet_data().get(planet_id)
    if not isinstance(rec, dict):
        return None
    name = str(rec.get("name", planet_id))
    resources = rec.get("resources")
    influence = rec.get("influence")
    parts = [name]
    if isinstance(resources, int) and isinstance(influence, int):
        parts.append(f"R{resources}/I{influence}")
    legendary_name = rec.get("legendaryAbilityName")
    legendary_text = rec.get("legendaryAbilityText")
    if legendary_name and legendary_text:
        parts.append(f"legendary: {legendary_name} — {legendary_text}")
    return " | ".join(parts)


def _build_full_map_lines(state: GameState) -> list[str]:
    """Return printable lines describing every tile and its current units/tokens."""
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    tile_positions: dict[str, str] = state.extra.get("tile_positions", {})
    if not tile_unit_data:
        return []

    lines: list[str] = []
    for pos in sorted(tile_unit_data, key=_tile_position_sort_key):
        tile_data = tile_unit_data.get(pos) or {}
        tile_id = tile_positions.get(pos)
        tile_label = _format_system_label(tile_id)
        label = f"{pos} ({tile_label})" if tile_label else pos
        lines.append(f"    {label}:")

        details: list[str] = []
        details.extend(_format_system_static_details(tile_id))
        ccs = tile_data.get("ccs") or []
        if ccs:
            details.append(f"CCs: {', '.join(sorted(str(cc) for cc in ccs))}")

        space = tile_data.get("space") or {}
        if isinstance(space, dict):
            for fac in sorted(space):
                ents = space.get(fac)
                if isinstance(ents, list):
                    labels = _summarise_entity_list(ents)
                    if labels:
                        details.append(f"space/{fac}: {', '.join(labels)}")

        planets = tile_data.get("planets") or {}
        if isinstance(planets, dict):
            for planet_id in sorted(planets):
                pdata = planets.get(planet_id)
                if not isinstance(pdata, dict):
                    continue
                entities = pdata.get("entities") or {}
                if not isinstance(entities, dict):
                    continue
                for fac in sorted(entities):
                    ents = entities.get(fac)
                    if isinstance(ents, list):
                        labels = _summarise_entity_list(ents)
                        if labels:
                            planet_meta = _format_planet_metadata(planet_id)
                            planet_label = (
                                f"{planet_id} ({planet_meta})" if planet_meta else planet_id
                            )
                            details.append(
                                f"planet/{planet_label}/{fac}: {', '.join(labels)}"
                            )

        if details:
            lines.extend([f"      - {d}" for d in details])
        else:
            lines.append("      - (no units/tokens)")

    return lines


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
    # Merge bundled objective data with API-provided data (API takes precedence,
    # so expansion/custom objectives not in objectives.json are still named).
    obj_data = {**fetch_objective_data(), **state.extra.get("objective_data", {})}

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
                stage = _get_objective_stage_label(rec)
                pts = rec.get("points", "?")
                name = rec.get("name", obj_id)
                desc = _get_objective_condition_text(rec)
                print(f"    [{stage}, {pts}VP] {name}")
                if desc:
                    print(f"      {desc}")
            else:
                print(f"    {obj_id}")

    full_map_lines = _build_full_map_lines(state)
    if full_map_lines:
        print()
        print("  FULL MAP (tiles, units, tokens):")
        for line in full_map_lines:
            print(line)

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
    from ti4_rules_engine.engine.options import PlayerAction

    tech_names = fetch_tech_names()
    action_techs = fetch_action_tech_names()
    leader_registry = fetch_leader_data()
    # Merge bundled objective data with API-provided data (API takes precedence).
    obj_data = {**fetch_objective_data(), **state.extra.get("objective_data", {})}
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
                # Show the actual leader name and ability text
                rec = leader_registry.get(lid)
                if rec:
                    name = rec.get("name", lid)
                    ability_text = rec.get("abilityText", "")
                    window = rec.get("abilityWindow", "")
                    if ability_text:
                        display_name = name
                        timing = f"  [{window}] {ability_text}" if window else f"  {ability_text}"
                    elif window:
                        display_name = name
                        timing = f"  [{window}]"
                    else:
                        display_name = name
                        timing = ""
                else:
                    display_name = lid
                    timing = ""
                print(f"      {display_name} ({ltype_cap}): {status}{timing}")

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

                # Readied agents with ACTION: timing only.
                # Agents use their own timing windows (e.g. "At the end of a player's
                # turn:"); only those whose ability window is "ACTION:" are component
                # actions.  Agents without known data are conservatively excluded.
                for leader in leaders:
                    if _get_leader_type(leader) == "agent":
                        if leader.get("exhausted", False) or leader.get("locked", False):
                            continue
                        lid = str(leader.get("id", "unknown"))
                        rec = leader_registry.get(lid)
                        if rec and rec.get("abilityWindow", "").startswith("ACTION:"):
                            name = rec.get("name", lid)
                            component_sources.append(f"agent: {name} (READY)")

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
                            cargo = arrival.get("transported_units") or []
                            if cargo:
                                print(
                                    f"          cargo options: {', '.join(cargo)}"
                                    f" (from {arrival['from_pos']})"
                                )
                            else:
                                gf = arrival["ground_forces"]
                                if gf:
                                    print(
                                        f"          ground forces: {', '.join(gf)}"
                                        f" (from {arrival['from_pos']})"
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
