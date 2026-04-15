"""Expected combat outcome via Monte Carlo simulation.

This module provides data structures and a simulation engine for estimating the
likely outcome of a TI4 space combat encounter.  Rather than exact
combinatorial analysis, a configurable number of independent combat simulations
are run and their results are averaged to produce win probabilities and expected
survivor counts.

TI4 space combat summary (per the Living Rules Reference):
----------------------------------------------------------
1. **Combat round**: each unit rolls a number of dice equal to its
   ``combat_rolls`` stat.  A die that shows a result **≥** the unit's
   ``combat`` value scores a hit.
2. **Sustain Damage**: before destroying a unit, the owning player may instead
   apply a *Sustain Damage* token to that unit (once per unit).  Sustained
   units continue fighting but are destroyed if they receive another hit.
3. **Hit assignment**: the defending player decides which of their own units
   to assign incoming hits to.  The heuristic used here prefers to sustain
   damage on high-cost units and to destroy the cheapest units first.
4. **Combat continues** until one or both sides have no surviving units.

Example usage::

    from ti4_rules_engine.engine.combat import CombatGroup, CombatUnit, simulate_combat
    from ti4_rules_engine.models.unit import Unit, UnitType

    carrier = Unit(id="carrier", name="Carrier", unit_type=UnitType.CARRIER,
                   cost=3, combat=9, move=2, capacity=4)
    destroyer = Unit(id="destroyer", name="Destroyer",
                     unit_type=UnitType.DESTROYER, cost=1, combat=9, move=2)

    attacker = CombatGroup([CombatUnit(carrier, 2)])
    defender = CombatGroup([CombatUnit(destroyer, 3)])

    result = simulate_combat(attacker, defender, simulations=5000)
    print(f"Attacker wins {result.attacker_win_probability:.1%}")
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import NamedTuple

from ti4_rules_engine.models.unit import Unit


@dataclass
class CombatUnit:
    """Mutable per-unit combat state used within a single simulation run.

    Attributes
    ----------
    unit:
        The underlying unit definition (stats are read-only).
    count:
        Number of undamaged instances of this unit currently alive.
    damaged:
        Number of instances that have already used their *Sustain Damage*
        ability.  These units are still alive and fight normally, but will be
        destroyed if they receive another hit.
    """

    unit: Unit
    count: int
    damaged: int = 0

    @property
    def total_count(self) -> int:
        """Total units alive (undamaged + sustained-damaged)."""
        return self.count + self.damaged

    @property
    def is_alive(self) -> bool:
        """True when at least one instance of this unit type is still alive."""
        return self.total_count > 0

    def roll_hits(self, rng: random.Random, modifier: int = 0) -> int:
        """Roll combat dice for all instances of this unit and return hit count.

        Parameters
        ----------
        rng:
            Random number generator to use.
        modifier:
            Added to the combat value before comparison (positive = easier to
            hit, negative = harder).  The effective combat value is clamped to
            the range [1, 10].
        """
        if self.unit.combat is None:
            return 0
        effective_combat = max(1, min(10, self.unit.combat - modifier))
        hits = 0
        for _ in range(self.total_count * self.unit.combat_rolls):
            if rng.randint(1, 10) >= effective_combat:
                hits += 1
        return hits


@dataclass
class CombatGroup:
    """One side in a space combat encounter.

    A :class:`CombatGroup` aggregates one or more :class:`CombatUnit` instances
    representing the full fleet fighting on this side.
    """

    units: list[CombatUnit] = field(default_factory=list)

    def is_alive(self) -> bool:
        """Return ``True`` if any unit in the group is still alive."""
        return any(u.is_alive for u in self.units)

    def roll_combat(self, rng: random.Random, modifier: int = 0) -> int:
        """Roll all combat dice across the fleet and return total hits."""
        return sum(u.roll_hits(rng, modifier) for u in self.units)

    def assign_hits(self, hits: int) -> None:
        """Distribute *hits* across units using the survival-optimal heuristic.

        The strategy prioritises the fleet's long-term strength:

        1. **Sustain Damage** – apply sustain damage tokens to undamaged
           sustainable units, starting with the *most expensive* (highest
           ``cost``) to protect the fleet's most valuable assets.
        2. **Destroy cheapest first** – once all sustain options are exhausted,
           remove the least-valuable units first.  Among already-sustained
           units, those are destroyed before fresh undamaged units.
        """
        remaining = hits

        # --- Phase 1: use Sustain Damage on undamaged sustainable units -----
        sustainable = sorted(
            [u for u in self.units if u.unit.sustain_damage and u.count > 0],
            key=lambda u: (u.unit.cost or 0),
            reverse=True,
        )
        for u in sustainable:
            if remaining <= 0:
                break
            used = min(u.count, remaining)
            u.count -= used
            u.damaged += used
            remaining -= used

        if remaining <= 0:
            return

        # --- Phase 2: destroy units (cheapest first) ------------------------
        destroyable = sorted(
            [u for u in self.units if u.is_alive],
            key=lambda u: (u.unit.cost or 0),
        )
        for u in destroyable:
            if remaining <= 0:
                break
            # Destroy already-sustained instances before fresh ones
            damaged_lost = min(u.damaged, remaining)
            u.damaged -= damaged_lost
            remaining -= damaged_lost

            if remaining <= 0:
                break

            undamaged_lost = min(u.count, remaining)
            u.count -= undamaged_lost
            remaining -= undamaged_lost

    def clone(self) -> CombatGroup:
        """Return a deep copy suitable for an independent simulation run."""
        return CombatGroup(
            units=[CombatUnit(u.unit, u.count, u.damaged) for u in self.units]
        )


class CombatResult(NamedTuple):
    """Aggregated statistics from a :func:`simulate_combat` run.

    All probabilities are in the range [0.0, 1.0].  Win and draw probabilities
    satisfy ``attacker_win_probability + defender_win_probability ≤ 1.0``
    (the remainder represents mutual-destruction draws).
    """

    attacker_win_probability: float
    """Fraction of simulations in which the attacker eliminated all defenders."""

    defender_win_probability: float
    """Fraction of simulations in which the defender eliminated all attackers."""

    attacker_expected_survivors: dict[str, float]
    """Average surviving unit count per unit type for the attacker.
    Keys are ``unit.id`` strings (e.g. ``"carrier"``).
    """

    defender_expected_survivors: dict[str, float]
    """Average surviving unit count per unit type for the defender."""

    average_rounds: float
    """Average number of combat rounds per simulation."""


def simulate_combat(
    attacker: CombatGroup,
    defender: CombatGroup,
    *,
    attacker_modifier: int = 0,
    defender_modifier: int = 0,
    simulations: int = 1000,
    max_rounds: int = 50,
    seed: int | None = None,
) -> CombatResult:
    """Run a Monte Carlo space-combat simulation and return expected outcomes.

    Each of the *simulations* independent runs proceeds as follows:

    1. Clone attacker and defender combat groups.
    2. Repeat each combat round until one or both sides are eliminated:

       a. Both sides roll combat dice simultaneously.
       b. The defender assigns the attacker's hits to their own units.
       c. The attacker assigns the defender's hits to their own units.

    3. Record winner and surviving unit counts.

    Parameters
    ----------
    attacker:
        The attacking fleet.
    defender:
        The defending fleet.
    attacker_modifier:
        Flat bonus added to the attacker's combat value comparisons (positive
        = more hits, e.g. +1 from *Morale Boost*).
    defender_modifier:
        Flat bonus for the defender's combat rolls.
    simulations:
        Number of independent simulations to run.  Higher values give more
        accurate estimates at the cost of CPU time.  Defaults to 1 000.
    max_rounds:
        Safety ceiling on rounds per simulation to prevent infinite loops
        in pathological cases.  Defaults to 50.
    seed:
        Optional integer seed for the RNG to make results reproducible.

    Returns
    -------
    CombatResult
        Aggregated statistics across all *simulations* runs.
    """
    rng = random.Random(seed)

    attacker_wins = 0
    defender_wins = 0
    total_rounds = 0

    attacker_survivor_sums: dict[str, float] = {u.unit.id: 0.0 for u in attacker.units}
    defender_survivor_sums: dict[str, float] = {u.unit.id: 0.0 for u in defender.units}

    for _ in range(simulations):
        att = attacker.clone()
        deff = defender.clone()
        rounds = 0

        while att.is_alive() and deff.is_alive() and rounds < max_rounds:
            rounds += 1
            att_hits = att.roll_combat(rng, attacker_modifier)
            def_hits = deff.roll_combat(rng, defender_modifier)
            deff.assign_hits(att_hits)
            att.assign_hits(def_hits)

        total_rounds += rounds

        att_alive = att.is_alive()
        def_alive = deff.is_alive()

        if att_alive and not def_alive:
            attacker_wins += 1
        elif def_alive and not att_alive:
            defender_wins += 1

        for u in att.units:
            attacker_survivor_sums[u.unit.id] += u.total_count
        for u in deff.units:
            defender_survivor_sums[u.unit.id] += u.total_count

    return CombatResult(
        attacker_win_probability=attacker_wins / simulations,
        defender_win_probability=defender_wins / simulations,
        attacker_expected_survivors={
            uid: total / simulations for uid, total in attacker_survivor_sums.items()
        },
        defender_expected_survivors={
            uid: total / simulations for uid, total in defender_survivor_sums.items()
        },
        average_rounds=total_rounds / simulations,
    )
