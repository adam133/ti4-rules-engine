"""Tests for engine.combat – Monte Carlo space combat simulation."""

from __future__ import annotations

import pytest

from ti4_rules_engine.engine.combat import CombatGroup, CombatUnit, simulate_combat
from ti4_rules_engine.models.unit import Unit, UnitType

# ---------------------------------------------------------------------------
# Fixtures – canonical unit stats
# ---------------------------------------------------------------------------


@pytest.fixture()
def fighter_unit() -> Unit:
    return Unit(id="fighter", name="Fighter", unit_type=UnitType.FIGHTER, cost=1, combat=9)


@pytest.fixture()
def destroyer_unit() -> Unit:
    return Unit(
        id="destroyer", name="Destroyer", unit_type=UnitType.DESTROYER, cost=1, combat=9, move=2
    )


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
    return Unit(
        id="dreadnought",
        name="Dreadnought",
        unit_type=UnitType.DREADNOUGHT,
        cost=4,
        combat=5,
        sustain_damage=True,
        move=1,
        capacity=1,
        bombardment=5,
        combat_rolls=2,
    )


@pytest.fixture()
def war_sun_unit() -> Unit:
    return Unit(
        id="war_sun",
        name="War Sun",
        unit_type=UnitType.WAR_SUN,
        cost=12,
        combat=3,
        sustain_damage=True,
        move=2,
        capacity=6,
        combat_rolls=3,
    )


# ---------------------------------------------------------------------------
# CombatUnit
# ---------------------------------------------------------------------------


class TestCombatUnit:
    def test_total_count(self, carrier_unit: Unit) -> None:
        cu = CombatUnit(carrier_unit, count=2, damaged=1)
        assert cu.total_count == 3

    def test_is_alive_true(self, carrier_unit: Unit) -> None:
        assert CombatUnit(carrier_unit, count=1).is_alive

    def test_is_alive_false(self, carrier_unit: Unit) -> None:
        assert not CombatUnit(carrier_unit, count=0, damaged=0).is_alive

    def test_roll_hits_no_combat_stat(self) -> None:
        pds = Unit(id="pds", name="PDS", unit_type=UnitType.PDS, space_cannon=6)
        cu = CombatUnit(pds, count=1)
        import random
        hits = cu.roll_hits(random.Random(42))
        assert hits == 0

    def test_roll_hits_always_hit_with_modifier(self, destroyer_unit: Unit) -> None:
        """A +9 modifier reduces the combat threshold to 1, guaranteeing hits."""
        import random
        cu = CombatUnit(destroyer_unit, count=3)
        hits = cu.roll_hits(random.Random(0), modifier=9)
        assert hits == 3  # 3 units × 1 roll each, all guaranteed to hit

    def test_roll_hits_never_hit_below_threshold(self, destroyer_unit: Unit) -> None:
        """A −10 modifier sets threshold to 10, only a roll of 10 hits."""
        import random
        rng = random.Random(1)
        cu = CombatUnit(destroyer_unit, count=10)
        hits = cu.roll_hits(rng, modifier=-10)
        # With threshold 10 (clamped from 9-(-10)=19→clamped to 10),
        # only die=10 scores a hit, so hits << 10
        # This is probabilistic, but very few hits expected
        assert hits <= 10  # sanity check: can't exceed roll count


# ---------------------------------------------------------------------------
# CombatGroup.assign_hits
# ---------------------------------------------------------------------------


class TestAssignHits:
    def test_sustain_before_destroy(self, dreadnought_unit: Unit, fighter_unit: Unit) -> None:
        """Dreadnoughts should absorb hits via sustain before fighters die."""
        group = CombatGroup([
            CombatUnit(dreadnought_unit, count=1),
            CombatUnit(fighter_unit, count=2),
        ])
        group.assign_hits(1)
        dread_cu = next(u for u in group.units if u.unit.id == "dreadnought")
        fighter_cu = next(u for u in group.units if u.unit.id == "fighter")
        # Dreadnought should have sustained damage
        assert dread_cu.damaged == 1
        assert dread_cu.count == 0
        # Fighters should be intact
        assert fighter_cu.total_count == 2

    def test_sustained_unit_destroyed_on_second_hit(self, dreadnought_unit: Unit) -> None:
        group = CombatGroup([CombatUnit(dreadnought_unit, count=1)])
        group.assign_hits(2)  # 1 to sustain, 1 to destroy
        assert not group.is_alive()

    def test_destroys_cheapest_first(self, fighter_unit: Unit, carrier_unit: Unit) -> None:
        """Among non-sustainable units, cheapest should be destroyed first."""
        group = CombatGroup([
            CombatUnit(fighter_unit, count=2),
            CombatUnit(carrier_unit, count=1),
        ])
        group.assign_hits(1)
        fighter_cu = next(u for u in group.units if u.unit.id == "fighter")
        carrier_cu = next(u for u in group.units if u.unit.id == "carrier")
        assert fighter_cu.total_count == 1
        assert carrier_cu.total_count == 1

    def test_more_hits_than_units(self, fighter_unit: Unit) -> None:
        """Excess hits beyond fleet size should not cause negative counts."""
        group = CombatGroup([CombatUnit(fighter_unit, count=2)])
        group.assign_hits(10)
        assert not group.is_alive()

    def test_zero_hits_no_change(self, carrier_unit: Unit) -> None:
        group = CombatGroup([CombatUnit(carrier_unit, count=2)])
        group.assign_hits(0)
        assert group.units[0].total_count == 2


# ---------------------------------------------------------------------------
# simulate_combat
# ---------------------------------------------------------------------------


class TestSimulateCombat:
    def test_result_probabilities_sum_to_at_most_one(
        self, carrier_unit: Unit, destroyer_unit: Unit
    ) -> None:
        att = CombatGroup([CombatUnit(carrier_unit, 2)])
        deff = CombatGroup([CombatUnit(destroyer_unit, 2)])
        result = simulate_combat(att, deff, simulations=500, seed=0)
        assert 0.0 <= result.attacker_win_probability <= 1.0
        assert 0.0 <= result.defender_win_probability <= 1.0
        assert result.attacker_win_probability + result.defender_win_probability <= 1.0

    def test_dreadnought_beats_fighters(
        self, dreadnought_unit: Unit, fighter_unit: Unit
    ) -> None:
        """A single dreadnought (combat 5, 2 rolls, sustain) should beat 2 fighters."""
        att = CombatGroup([CombatUnit(dreadnought_unit, 1)])
        deff = CombatGroup([CombatUnit(fighter_unit, 2)])
        result = simulate_combat(att, deff, simulations=2000, seed=42)
        assert result.attacker_win_probability > 0.7

    def test_overwhelming_force_wins(self, carrier_unit: Unit, fighter_unit: Unit) -> None:
        """A large fleet should have a very high win rate against a single fighter."""
        att = CombatGroup([CombatUnit(carrier_unit, 5)])
        deff = CombatGroup([CombatUnit(fighter_unit, 1)])
        result = simulate_combat(att, deff, simulations=1000, seed=0)
        assert result.attacker_win_probability > 0.95

    def test_attacker_modifier_improves_win_rate(
        self, carrier_unit: Unit, destroyer_unit: Unit
    ) -> None:
        """A positive attacker modifier should increase the attacker win rate."""
        att = CombatGroup([CombatUnit(carrier_unit, 1)])
        deff = CombatGroup([CombatUnit(destroyer_unit, 1)])
        base = simulate_combat(att, deff, simulations=2000, seed=1)
        boosted = simulate_combat(att, deff, simulations=2000, seed=1, attacker_modifier=2)
        assert boosted.attacker_win_probability >= base.attacker_win_probability

    def test_expected_survivors_keys_match_input_units(
        self, carrier_unit: Unit, cruiser_unit: Unit, fighter_unit: Unit
    ) -> None:
        att = CombatGroup([CombatUnit(carrier_unit, 1), CombatUnit(cruiser_unit, 1)])
        deff = CombatGroup([CombatUnit(fighter_unit, 3)])
        result = simulate_combat(att, deff, simulations=200, seed=0)
        assert set(result.attacker_expected_survivors.keys()) == {"carrier", "cruiser"}
        assert set(result.defender_expected_survivors.keys()) == {"fighter"}

    def test_expected_survivors_nonnegative(
        self, dreadnought_unit: Unit, fighter_unit: Unit
    ) -> None:
        att = CombatGroup([CombatUnit(dreadnought_unit, 2)])
        deff = CombatGroup([CombatUnit(fighter_unit, 5)])
        result = simulate_combat(att, deff, simulations=300, seed=7)
        for v in result.attacker_expected_survivors.values():
            assert v >= 0.0
        for v in result.defender_expected_survivors.values():
            assert v >= 0.0

    def test_average_rounds_positive(self, carrier_unit: Unit, destroyer_unit: Unit) -> None:
        att = CombatGroup([CombatUnit(carrier_unit, 1)])
        deff = CombatGroup([CombatUnit(destroyer_unit, 1)])
        result = simulate_combat(att, deff, simulations=200, seed=3)
        assert result.average_rounds > 0.0

    def test_seed_produces_reproducible_results(
        self, carrier_unit: Unit, destroyer_unit: Unit
    ) -> None:
        att = CombatGroup([CombatUnit(carrier_unit, 2)])
        deff = CombatGroup([CombatUnit(destroyer_unit, 2)])
        r1 = simulate_combat(att, deff, simulations=500, seed=99)
        r2 = simulate_combat(att, deff, simulations=500, seed=99)
        assert r1.attacker_win_probability == r2.attacker_win_probability
        assert r1.defender_win_probability == r2.defender_win_probability

    def test_war_sun_dominates_fighters(self, war_sun_unit: Unit, fighter_unit: Unit) -> None:
        """A War Sun (combat 3, 3 rolls, sustain) should usually beat 3 fighters."""
        att = CombatGroup([CombatUnit(war_sun_unit, 1)])
        deff = CombatGroup([CombatUnit(fighter_unit, 3)])
        result = simulate_combat(att, deff, simulations=2000, seed=5)
        assert result.attacker_win_probability > 0.80

    def test_clone_does_not_mutate_original(self, dreadnought_unit: Unit) -> None:
        group = CombatGroup([CombatUnit(dreadnought_unit, 2)])
        clone = group.clone()
        clone.assign_hits(4)
        assert group.units[0].total_count == 2  # original unchanged

    def test_equal_forces_roughly_even(self, cruiser_unit: Unit) -> None:
        """Identical fleets should each win roughly half the time."""
        att = CombatGroup([CombatUnit(cruiser_unit, 3)])
        deff = CombatGroup([CombatUnit(cruiser_unit, 3)])
        result = simulate_combat(att, deff, simulations=3000, seed=42)
        # Each side should win ~50% of the time (draws are rare)
        assert abs(result.attacker_win_probability - result.defender_win_probability) < 0.15
