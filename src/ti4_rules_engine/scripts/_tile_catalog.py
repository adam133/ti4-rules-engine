"""Static tile catalog and hyperlane tile identification.

The catalog maps tile IDs to their anomaly/wormhole properties (sourced from the
AsyncTI4 bot's ``systems/*.json`` data).  Movement rules encoded here:

* ``supernova``    — impassable (cannot be entered or moved through)
* ``asteroid``     — impassable unless the player has Antimass Deflectors (``"amd"``)
* ``nebula``       — can be entered as a *destination* but cannot be transited
  (remaining moves drop to 0 on arrival)
* ``gravity_rift`` — grants +1 movement when moving through or out of the rift
* ``wormholes``    — tile is adjacent to all other tiles sharing the same wormhole type
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Static tile catalog (sourced from AsyncTI4 bot systems/*.json)
# ---------------------------------------------------------------------------

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
