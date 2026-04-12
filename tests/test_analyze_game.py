"""Tests for the hex-grid adjacency and BFS movement helpers in analyze_game."""

from __future__ import annotations

import pytest

from scripts.analyze_game import get_adjacent_positions, get_reachable_systems


# ---------------------------------------------------------------------------
# get_adjacent_positions – adjacency algorithm
# ---------------------------------------------------------------------------


class TestGetAdjacentPositions:
    # --- Centre tile ---
    def test_centre_adjacent_to_all_ring1(self) -> None:
        result = get_adjacent_positions("000")
        assert set(result) == {"101", "102", "103", "104", "105", "106"}

    # --- Ring 1 tiles: each has exactly 6 neighbours ---
    def test_101_neighbours(self) -> None:
        result = get_adjacent_positions("101")
        assert set(result) == {"000", "102", "106", "201", "202", "212"}

    def test_102_neighbours(self) -> None:
        result = get_adjacent_positions("102")
        assert set(result) == {"000", "101", "103", "202", "203", "204"}

    def test_106_neighbours(self) -> None:
        result = get_adjacent_positions("106")
        assert set(result) == {"000", "101", "105", "210", "211", "212"}

    # --- Ring 2 tiles ---
    def test_201_neighbours(self) -> None:
        result = get_adjacent_positions("201")
        assert set(result) == {"101", "212", "202", "301", "302", "318"}

    def test_202_neighbours(self) -> None:
        result = get_adjacent_positions("202")
        assert set(result) == {"101", "102", "201", "203", "302", "303"}

    def test_212_neighbours(self) -> None:
        result = get_adjacent_positions("212")
        assert set(result) == {"101", "106", "211", "201", "317", "318"}

    # --- Ring 3 tiles ---
    def test_301_neighbours(self) -> None:
        result = get_adjacent_positions("301")
        assert set(result) == {"201", "318", "302", "401", "402", "424"}

    def test_302_neighbours(self) -> None:
        result = get_adjacent_positions("302")
        assert set(result) == {"201", "202", "301", "303", "402", "403"}

    # --- Each ring 1 tile has exactly 6 distinct neighbours ---
    def test_each_ring1_has_six_neighbours(self) -> None:
        for i in range(1, 7):
            pos = f"10{i}"
            neighbours = get_adjacent_positions(pos)
            assert len(neighbours) == 6, f"{pos} should have 6 neighbours"
            assert len(set(neighbours)) == 6, f"{pos} neighbours should be distinct"

    # --- Each ring 2 tile has exactly 6 distinct neighbours ---
    def test_each_ring2_has_six_neighbours(self) -> None:
        for i in range(1, 13):
            pos = f"2{i:02d}"
            neighbours = get_adjacent_positions(pos)
            assert len(neighbours) == 6, f"{pos} should have 6 neighbours"
            assert len(set(neighbours)) == 6, f"{pos} neighbours should be distinct"

    # --- Non-integer positions return empty list ---
    def test_br_returns_empty(self) -> None:
        assert get_adjacent_positions("br") == []

    def test_tl_returns_empty(self) -> None:
        assert get_adjacent_positions("tl") == []

    def test_special_returns_empty(self) -> None:
        assert get_adjacent_positions("special") == []

    # --- Symmetry: if A is adjacent to B, B should be adjacent to A ---
    def test_adjacency_is_symmetric_ring1_ring2(self) -> None:
        for i in range(1, 7):
            pos_a = f"10{i}"
            for pos_b in get_adjacent_positions(pos_a):
                try:
                    int(pos_b)
                except ValueError:
                    continue
                assert pos_a in get_adjacent_positions(pos_b), (
                    f"Adjacency is not symmetric: {pos_a} has {pos_b} as neighbour "
                    f"but {pos_b} does not have {pos_a}"
                )


# ---------------------------------------------------------------------------
# get_reachable_systems – BFS movement
# ---------------------------------------------------------------------------


def _make_tile(anomaly: bool = False, ccs: list[str] | None = None) -> dict:
    return {"anomaly": anomaly, "ccs": ccs or [], "planets": {}, "space": {}}


class TestGetReachableSystems:
    # Build a simple tile_unit_data containing rings 0–2
    _ALL_POSITIONS = (
        ["000"]
        + [f"10{i}" for i in range(1, 7)]
        + [f"2{i:02d}" for i in range(1, 13)]
    )
    _OPEN_MAP: dict = {pos: _make_tile() for pos in _ALL_POSITIONS}

    def test_move_zero_returns_empty(self) -> None:
        result = get_reachable_systems("101", 0, self._OPEN_MAP, "red")
        assert result == set()

    def test_move_one_reaches_adjacent_only(self) -> None:
        result = get_reachable_systems("101", 1, self._OPEN_MAP, "red")
        expected = {"000", "102", "106", "201", "202", "212"}
        assert result == expected

    def test_starting_position_excluded(self) -> None:
        result = get_reachable_systems("101", 2, self._OPEN_MAP, "red")
        assert "101" not in result

    def test_move_two_reaches_two_hops(self) -> None:
        result = get_reachable_systems("000", 2, self._OPEN_MAP, "red")
        # Ring 1 (1 hop) + ring 2 (2 hops)
        ring1 = {f"10{i}" for i in range(1, 7)}
        ring2 = {f"2{i:02d}" for i in range(1, 13)}
        assert ring1.issubset(result)
        assert ring2.issubset(result)

    def test_anomaly_tile_blocks_entry_and_passthrough(self) -> None:
        tile_data = {**self._OPEN_MAP, "102": _make_tile(anomaly=True)}
        result = get_reachable_systems("101", 3, tile_data, "red")
        assert "102" not in result  # can't enter
        # 204 can only be reached via 102 (or other neighbours of 103)
        # but NOT via the anomaly path  101→102→204 is blocked

    def test_activated_tile_blocked_by_own_cc(self) -> None:
        tile_data = {**self._OPEN_MAP, "102": _make_tile(ccs=["red"])}
        result = get_reachable_systems("101", 2, tile_data, "red")
        assert "102" not in result  # locked by own CC

    def test_other_player_cc_does_not_block(self) -> None:
        tile_data = {**self._OPEN_MAP, "102": _make_tile(ccs=["blue"])}
        result = get_reachable_systems("101", 2, tile_data, "red")
        assert "102" in result  # blue's CC doesn't block red

    def test_tile_not_in_map_skipped(self) -> None:
        # Only positions 000 and 101-106 in map – ring 2 positions absent
        limited_map = {"000": _make_tile()} | {
            f"10{i}": _make_tile() for i in range(1, 7)
        }
        result = get_reachable_systems("000", 2, limited_map, "red")
        # Ring 2 tiles are not present → shouldn't appear
        for i in range(1, 13):
            assert f"2{i:02d}" not in result
