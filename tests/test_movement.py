"""Tests for engine.movement – fleet movement range evaluation."""

from __future__ import annotations

import pytest

from ti4_rules_engine.engine.movement import get_fleet_move, get_reachable_systems
from ti4_rules_engine.models.map import AnomalyType, GalaxyMap, System, WormholeType
from ti4_rules_engine.models.unit import Unit, UnitType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def carrier_unit() -> Unit:
    return Unit(
        id="carrier", name="Carrier", unit_type=UnitType.CARRIER,
        cost=3, combat=9, move=2, capacity=4,
    )


@pytest.fixture()
def cruiser_unit() -> Unit:
    return Unit(id="cruiser", name="Cruiser", unit_type=UnitType.CRUISER, cost=2, combat=7, move=3)


@pytest.fixture()
def dreadnought_unit() -> Unit:
    return Unit(id="dreadnought", name="Dreadnought", unit_type=UnitType.DREADNOUGHT,
                cost=4, combat=5, sustain_damage=True, move=1, capacity=1)


@pytest.fixture()
def fighter_unit() -> Unit:
    return Unit(id="fighter", name="Fighter", unit_type=UnitType.FIGHTER, cost=1, combat=9, move=0)


@pytest.fixture()
def infantry_unit() -> Unit:
    return Unit(id="infantry", name="Infantry", unit_type=UnitType.GROUND_FORCE, cost=1, combat=8)


@pytest.fixture()
def pds_unit() -> Unit:
    return Unit(id="pds", name="PDS", unit_type=UnitType.PDS, space_cannon=6)


@pytest.fixture()
def unit_registry(
    carrier_unit: Unit,
    cruiser_unit: Unit,
    dreadnought_unit: Unit,
    fighter_unit: Unit,
    infantry_unit: Unit,
    pds_unit: Unit,
) -> dict[str, Unit]:
    return {
        u.id: u
        for u in [
            carrier_unit, cruiser_unit, dreadnought_unit, fighter_unit, infantry_unit, pds_unit
        ]
    }


@pytest.fixture()
def linear_galaxy() -> GalaxyMap:
    """A straight chain: home → A → B → C → D."""
    return GalaxyMap(
        systems={
            "home": System(id="home", adjacent_system_ids=["A"]),
            "A": System(id="A", adjacent_system_ids=["home", "B"]),
            "B": System(id="B", adjacent_system_ids=["A", "C"]),
            "C": System(id="C", adjacent_system_ids=["B", "D"]),
            "D": System(id="D", adjacent_system_ids=["C"]),
        }
    )


# ---------------------------------------------------------------------------
# get_fleet_move
# ---------------------------------------------------------------------------


class TestGetFleetMove:
    def test_single_carrier(self, unit_registry: dict) -> None:
        fleet = {"carrier": 2}
        assert get_fleet_move(fleet, unit_registry) == 2

    def test_single_cruiser(self, unit_registry: dict) -> None:
        fleet = {"cruiser": 1}
        assert get_fleet_move(fleet, unit_registry) == 3

    def test_carrier_and_cruiser_returns_minimum(self, unit_registry: dict) -> None:
        """Mixed fleet is limited by the slowest ship."""
        fleet = {"carrier": 1, "cruiser": 1}
        assert get_fleet_move(fleet, unit_registry) == 2

    def test_dreadnought_limits_fleet(self, unit_registry: dict) -> None:
        fleet = {"carrier": 1, "cruiser": 2, "dreadnought": 1}
        assert get_fleet_move(fleet, unit_registry) == 1

    def test_fighters_excluded(self, unit_registry: dict) -> None:
        """Fighters are transported; they don't slow the fleet."""
        fleet = {"carrier": 1, "fighter": 3}
        assert get_fleet_move(fleet, unit_registry) == 2

    def test_infantry_excluded(self, unit_registry: dict) -> None:
        """Ground Forces are transported; they don't slow the fleet."""
        fleet = {"carrier": 1, "infantry": 2}
        assert get_fleet_move(fleet, unit_registry) == 2

    def test_only_fighters_returns_zero(self, unit_registry: dict) -> None:
        """A fleet of only fighters has no independent movement."""
        fleet = {"fighter": 6}
        assert get_fleet_move(fleet, unit_registry) == 0

    def test_only_pds_returns_zero(self, unit_registry: dict) -> None:
        """Structures have no movement."""
        fleet = {"pds": 2}
        assert get_fleet_move(fleet, unit_registry) == 0

    def test_empty_fleet_returns_zero(self, unit_registry: dict) -> None:
        assert get_fleet_move({}, unit_registry) == 0

    def test_zero_count_units_ignored(self, unit_registry: dict) -> None:
        """Units with count=0 should not affect movement."""
        fleet = {"carrier": 1, "cruiser": 0}
        assert get_fleet_move(fleet, unit_registry) == 2

    def test_gravity_drive_boosts_carrier(self, unit_registry: dict) -> None:
        fleet = {"carrier": 2}
        assert get_fleet_move(fleet, unit_registry, gravity_drive=True) == 3

    def test_gravity_drive_does_not_boost_non_carrier(self, unit_registry: dict) -> None:
        """Gravity Drive only affects Carriers."""
        fleet = {"dreadnought": 1}
        assert get_fleet_move(fleet, unit_registry, gravity_drive=True) == 1

    def test_gravity_drive_mixed_fleet(self, unit_registry: dict) -> None:
        """With Gravity Drive, carrier gets +1 but fleet move is still min."""
        # carrier=3, dreadnought=1 → min=1
        fleet = {"carrier": 1, "dreadnought": 1}
        assert get_fleet_move(fleet, unit_registry, gravity_drive=True) == 1


# ---------------------------------------------------------------------------
# get_reachable_systems
# ---------------------------------------------------------------------------


class TestGetReachableSystems:
    def test_move_zero_returns_empty(self, linear_galaxy: GalaxyMap) -> None:
        assert get_reachable_systems(linear_galaxy, "home", 0) == set()

    def test_move_one_reaches_adjacent(self, linear_galaxy: GalaxyMap) -> None:
        result = get_reachable_systems(linear_galaxy, "home", 1)
        assert result == {"A"}

    def test_move_two_reaches_two_hops(self, linear_galaxy: GalaxyMap) -> None:
        result = get_reachable_systems(linear_galaxy, "home", 2)
        assert result == {"A", "B"}

    def test_move_three_reaches_three_hops(self, linear_galaxy: GalaxyMap) -> None:
        result = get_reachable_systems(linear_galaxy, "home", 3)
        assert result == {"A", "B", "C"}

    def test_starting_system_excluded(self, linear_galaxy: GalaxyMap) -> None:
        result = get_reachable_systems(linear_galaxy, "A", 2)
        assert "A" not in result

    def test_supernova_is_impassable(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["nova", "safe"]),
                "nova": System(id="nova", adjacent_system_ids=["home", "far"],
                               anomaly=AnomalyType.SUPERNOVA),
                "safe": System(id="safe", adjacent_system_ids=["home"]),
                "far": System(id="far", adjacent_system_ids=["nova"]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 3)
        assert "nova" not in result
        assert "far" not in result
        assert "safe" in result

    def test_nebula_stops_movement(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["nebula"]),
                "nebula": System(id="nebula", adjacent_system_ids=["home", "far"],
                                 anomaly=AnomalyType.NEBULA),
                "far": System(id="far", adjacent_system_ids=["nebula"]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 3)
        assert "nebula" in result   # can enter the nebula
        assert "far" not in result  # cannot move through

    def test_asteroid_field_stops_ships(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["field"]),
                "field": System(id="field", adjacent_system_ids=["home", "far"],
                                anomaly=AnomalyType.ASTEROID_FIELD),
                "far": System(id="far", adjacent_system_ids=["field"]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 3)
        assert "field" in result   # can enter
        assert "far" not in result  # cannot move through

    def test_asteroid_field_passable_for_fighters_only(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["field"]),
                "field": System(id="field", adjacent_system_ids=["home", "far"],
                                anomaly=AnomalyType.ASTEROID_FIELD),
                "far": System(id="far", adjacent_system_ids=["field"]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 3, fleet_has_fighters_only=True)
        assert "field" in result
        assert "far" in result

    def test_enemy_ships_stop_fleet(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["enemy_sys"]),
                "enemy_sys": System(id="enemy_sys", adjacent_system_ids=["home", "far"]),
                "far": System(id="far", adjacent_system_ids=["enemy_sys"]),
            }
        )
        result = get_reachable_systems(
            galaxy, "home", 3, enemy_ship_system_ids={"enemy_sys"}
        )
        assert "enemy_sys" in result    # fleet can enter to initiate combat
        assert "far" not in result      # but cannot continue past enemy ships

    def test_gravity_rift_adds_bonus_movement(self) -> None:
        """A fleet exiting a gravity rift gains +1 movement for that exit."""
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=["rift"]),
                "rift": System(id="rift", adjacent_system_ids=["home", "A"],
                               anomaly=AnomalyType.GRAVITY_RIFT),
                "A": System(id="A", adjacent_system_ids=["rift", "B"]),
                "B": System(id="B", adjacent_system_ids=["A"]),
            }
        )
        # Without rift bonus: move 1 → only "rift" reachable from "home"
        # With rift bonus: exiting rift to A costs 1, but +1 bonus = net 0
        # So from home with move=1: home→rift (costs 1, 0 remaining) + rift
        # bonus +1 when moving home→rift→A = net cost 0 from rift, so A is
        # reachable with move=1!
        result = get_reachable_systems(galaxy, "home", 1)
        assert "rift" in result
        # Move 1: home→rift costs 1, remaining=0. Exiting rift: +1, remaining=1.
        # So A is reachable from rift with remaining=1.
        assert "A" in result

    def test_wormhole_adjacency(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=[], wormholes=[WormholeType.ALPHA]),
                "alpha_dest": System(id="alpha_dest", adjacent_system_ids=[],
                                     wormholes=[WormholeType.ALPHA]),
                "far": System(id="far", adjacent_system_ids=["alpha_dest"]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 2)
        assert "alpha_dest" in result
        assert "far" in result

    def test_wormhole_does_not_connect_different_types(self) -> None:
        galaxy = GalaxyMap(
            systems={
                "home": System(id="home", adjacent_system_ids=[], wormholes=[WormholeType.ALPHA]),
                "beta_sys": System(id="beta_sys", adjacent_system_ids=[],
                                   wormholes=[WormholeType.BETA]),
            }
        )
        result = get_reachable_systems(galaxy, "home", 2)
        assert "beta_sys" not in result
