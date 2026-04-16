"""Hyperlane edge-specific adjacency building.

Hyperlane tiles are transparent connectors on the TI4 board.  Ships cannot stop
on them but can traverse them to reach otherwise-non-adjacent tiles.  This module
provides:

* :func:`_load_hyperlane_connections` — loads edge-connectivity matrices from the
  upstream ``data/hyperlanes.properties`` data file.
* :func:`_build_hyperlane_adjacency` — walks the hyperlane chains on a given map
  and returns a ``{pos: frozenset[pos]}`` adjacency mapping.
* :func:`_build_movement_context` — the top-level helper called by the tactical
  reach calculator; combines tile-type, wormhole, and hyperlane adjacency into the
  three dicts the BFS needs.
"""

from __future__ import annotations

import functools
import pathlib
import sys
from typing import Any

from ti4_rules_engine.scripts._hex_grid import get_adjacent_positions
from ti4_rules_engine.scripts._tile_catalog import (
    _TILE_CATALOG,
    _is_hyperlane_tile_id,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ASYNCTI4_SUBMODULE_ROOT = _REPO_ROOT / "data" / "TI4_map_generator_bot"
_DATA_DIR = _ASYNCTI4_SUBMODULE_ROOT / "src" / "main" / "resources" / "data"
_HYPERLANES_DATA_FILE = _DATA_DIR / "hyperlanes.properties"

# Entry-agnostic fallback is only enabled when a source has 2+ adjacent
# hyperlane connectors (branch points), where rotation mismatches are most likely.
_MIN_HYPERLANE_NEIGHBORS_FOR_FALLBACK = 2


@functools.cache
def _load_hyperlane_connections() -> dict[str, list[list[int]]]:
    """Load hyperlane edge-connectivity matrices from the upstream properties file.

    Returns a dict mapping tile ID (e.g. ``"83a"``, ``"86a240"``) to a 6×6
    integer adjacency matrix where ``matrix[i][j] == 1`` means edge *i* of the
    tile is connected to edge *j* through the hyperlane path.  The matrix is
    always symmetric.  Falls back to an empty dict on any error.
    """
    try:
        connections: dict[str, list[list[int]]] = {}
        with _HYPERLANES_DATA_FILE.open(encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                tile_id, matrix_text = line.split("=", maxsplit=1)
                matrix = [
                    [int(value) for value in row.split(",")]
                    for row in matrix_text.split(";")
                ]
                if len(matrix) != 6 or any(len(row) != 6 for row in matrix):
                    raise ValueError(
                        f"Invalid hyperlane matrix dimensions for {tile_id!r}: {matrix_text!r}"
                    )
                connections[tile_id] = matrix
        return connections
    except (OSError, ValueError) as exc:
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
