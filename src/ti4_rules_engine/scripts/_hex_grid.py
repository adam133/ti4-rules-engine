"""Hex-grid tile-position arithmetic for the AsyncTI4 board.

Translated from the AsyncTI4 bot's ``PositionMapper.getAdjacentTilePositionsNew()``.
Tile positions are strings of the form ``"RNN"`` where *R* is the ring (0–N) and
*NN* is the 1-indexed position within that ring (e.g. ``"211"`` = ring 2, tile 11).
Special positions such as ``"br"``, ``"tl"``, ``"special"`` are not supported and
:func:`get_adjacent_positions` returns an empty list for them.
"""

from __future__ import annotations


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
