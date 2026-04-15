"""Tests for the ComponentRegistry and EffectRegistry."""

from __future__ import annotations

import pytest

from ti4_rules_engine.models.card import ActionCard, ActionCardType, StrategyCard
from ti4_rules_engine.models.planet import Planet
from ti4_rules_engine.models.technology import TechCategory, Technology
from ti4_rules_engine.models.unit import Unit, UnitType
from ti4_rules_engine.registry.component_registry import ComponentRegistry
from ti4_rules_engine.registry.effect_registry import Effect, EffectRegistry, TriggerType


# ---------------------------------------------------------------------------
# ComponentRegistry
# ---------------------------------------------------------------------------


class TestComponentRegistry:
    def test_register_and_get(self, neural_motivator: Technology) -> None:
        registry = ComponentRegistry()
        registry.register_technology(neural_motivator)
        result = registry.get("neural_motivator")
        assert result == neural_motivator

    def test_get_missing_raises(self) -> None:
        registry = ComponentRegistry()
        with pytest.raises(KeyError, match="not_a_real_id"):
            registry.get("not_a_real_id")

    def test_get_or_none_returns_none(self) -> None:
        registry = ComponentRegistry()
        assert registry.get_or_none("missing") is None

    def test_search_case_insensitive(
        self, neural_motivator: Technology, mecatol_rex: Planet
    ) -> None:
        registry = ComponentRegistry()
        registry.register_technology(neural_motivator)
        registry.register_planet(mecatol_rex)

        results = registry.search("neural")
        assert len(results) == 1
        assert results[0].id == "neural_motivator"

    def test_search_case_sensitive(self, neural_motivator: Technology) -> None:
        registry = ComponentRegistry()
        registry.register_technology(neural_motivator)
        # Wrong case should find nothing
        assert registry.search("NEURAL", case_sensitive=True) == []
        # Correct case should match
        assert len(registry.search("Neural", case_sensitive=True)) == 1

    def test_get_by_type(
        self, neural_motivator: Technology, carrier: Unit, mecatol_rex: Planet
    ) -> None:
        registry = ComponentRegistry()
        registry.register_technology(neural_motivator)
        registry.register_unit(carrier)
        registry.register_planet(mecatol_rex)

        techs = registry.get_by_type(Technology)
        assert len(techs) == 1
        assert techs[0].id == "neural_motivator"

    def test_register_many(
        self, neural_motivator: Technology, mecatol_rex: Planet
    ) -> None:
        registry = ComponentRegistry()
        registry.register_many([neural_motivator, mecatol_rex])
        assert len(registry) == 2

    def test_contains(self, neural_motivator: Technology) -> None:
        registry = ComponentRegistry()
        registry.register(neural_motivator)
        assert "neural_motivator" in registry
        assert "missing" not in registry

    def test_all_ids_sorted(
        self, carrier: Unit, neural_motivator: Technology
    ) -> None:
        registry = ComponentRegistry()
        registry.register(carrier)
        registry.register(neural_motivator)
        ids = registry.all_ids()
        assert ids == sorted(ids)

    def test_overwrite_emits_warning(self, neural_motivator: Technology) -> None:
        """Overwriting an existing component should not raise."""
        registry = ComponentRegistry()
        registry.register(neural_motivator)
        # Should not raise – structlog warning is emitted instead
        registry.register(neural_motivator)
        assert len(registry) == 1


# ---------------------------------------------------------------------------
# EffectRegistry
# ---------------------------------------------------------------------------


class TestEffectRegistry:
    def _morale_boost(self, owner_id: str = "player_1") -> Effect:
        return Effect(
            name="Morale Boost",
            trigger=TriggerType.COMBAT_ROLL,
            modifier=1,
            source="Morale Boost Action Card",
            owner_id=owner_id,
        )

    def test_add_and_query(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        results = reg.query(TriggerType.COMBAT_ROLL, owner_id="player_1")
        assert len(results) == 1
        assert results[0].name == "Morale Boost"

    def test_query_consumes_effect(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        reg.query(TriggerType.COMBAT_ROLL, owner_id="player_1")
        # Second query should return nothing (effect was consumed)
        assert reg.query(TriggerType.COMBAT_ROLL, owner_id="player_1") == []

    def test_persistent_effect_not_consumed(self) -> None:
        reg = EffectRegistry()
        effect = Effect(
            name="Scan Link",
            trigger=TriggerType.MOVEMENT,
            modifier=1,
            source="Scan Link Technology",
            owner_id="player_1",
            expires_after_use=False,
        )
        reg.add_effect(effect)
        reg.query(TriggerType.MOVEMENT, owner_id="player_1")
        # Should still be present
        assert len(reg) == 1

    def test_total_modifier(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        reg.add_effect(
            Effect(
                name="Morale Boost 2",
                trigger=TriggerType.COMBAT_ROLL,
                modifier=2,
                source="Another Card",
                owner_id="player_1",
            )
        )
        total = reg.total_modifier(TriggerType.COMBAT_ROLL, owner_id="player_1")
        assert total == 3

    def test_global_effect_included(self) -> None:
        reg = EffectRegistry()
        global_effect = Effect(
            name="Gravity Drive",
            trigger=TriggerType.MOVEMENT,
            modifier=1,
            source="Gravity Drive Technology",
            owner_id=None,
        )
        reg.add_effect(global_effect)
        results = reg.query(TriggerType.MOVEMENT, owner_id="player_2", include_global=True)
        assert len(results) == 1

    def test_global_effect_excluded(self) -> None:
        reg = EffectRegistry()
        global_effect = Effect(
            name="Gravity Drive",
            trigger=TriggerType.MOVEMENT,
            modifier=1,
            source="Gravity Drive Technology",
            owner_id=None,
        )
        reg.add_effect(global_effect)
        results = reg.query(TriggerType.MOVEMENT, owner_id="player_2", include_global=False)
        assert results == []

    def test_wrong_trigger_not_returned(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        results = reg.query(TriggerType.BOMBARDMENT, owner_id="player_1")
        assert results == []

    def test_remove_effect(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        removed = reg.remove_effect("Morale Boost", owner_id="player_1")
        assert removed == 1
        assert len(reg) == 0

    def test_remove_effect_by_name_only(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost("player_1"))
        reg.add_effect(self._morale_boost("player_2"))
        removed = reg.remove_effect("Morale Boost")
        assert removed == 2

    def test_clear(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        reg.clear()
        assert len(reg) == 0

    def test_all_effects_snapshot(self) -> None:
        reg = EffectRegistry()
        reg.add_effect(self._morale_boost())
        snapshot = reg.all_effects()
        # Mutating the snapshot should not affect the registry
        snapshot.clear()
        assert len(reg) == 1
