"""Tests for the Pydantic model schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ti4_rules_engine.models.card import ActionCard, ActionCardType, StrategyCard
from ti4_rules_engine.models.faction import Faction
from ti4_rules_engine.models.planet import Planet, PlanetTrait, TechSkip
from ti4_rules_engine.models.state import GamePhase, GameState, PlayerState, TurnOrder
from ti4_rules_engine.models.technology import TechCategory, Technology
from ti4_rules_engine.models.unit import Unit, UnitType


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------


class TestUnit:
    def test_carrier_fields(self, carrier: Unit) -> None:
        assert carrier.id == "carrier"
        assert carrier.unit_type == UnitType.CARRIER
        assert carrier.cost == 3
        assert carrier.combat == 9
        assert carrier.capacity == 4
        assert not carrier.sustain_damage

    def test_dreadnought_sustain_damage(self, dreadnought: Unit) -> None:
        assert dreadnought.sustain_damage is True
        assert dreadnought.bombardment == 5

    def test_unit_is_frozen(self, carrier: Unit) -> None:
        with pytest.raises(ValidationError):
            carrier.cost = 99  # type: ignore[misc]

    def test_combat_roll_default(self, carrier: Unit) -> None:
        assert carrier.combat_rolls == 1

    def test_invalid_combat_range(self) -> None:
        with pytest.raises(ValidationError):
            Unit(id="bad", name="Bad", unit_type=UnitType.FIGHTER, cost=1, combat=11)


# ---------------------------------------------------------------------------
# Technology
# ---------------------------------------------------------------------------


class TestTechnology:
    def test_neural_motivator(self, neural_motivator: Technology) -> None:
        assert neural_motivator.id == "neural_motivator"
        assert neural_motivator.category == TechCategory.BIOTIC
        assert not neural_motivator.is_unit_upgrade
        assert neural_motivator.faction_id is None

    def test_tech_is_frozen(self, neural_motivator: Technology) -> None:
        with pytest.raises(ValidationError):
            neural_motivator.category = TechCategory.WARFARE  # type: ignore[misc]

    def test_faction_tech(self) -> None:
        tech = Technology(
            id="e_res_siphons",
            name="E-Res Siphons",
            category=TechCategory.FACTION,
            faction_id="the_universities_of_jol_nar",
            description="When another player activates a system that contains 1+ of your units, gain 2 trade goods.",
        )
        assert tech.faction_id == "the_universities_of_jol_nar"


# ---------------------------------------------------------------------------
# Planet
# ---------------------------------------------------------------------------


class TestPlanet:
    def test_mecatol_rex(self, mecatol_rex: Planet) -> None:
        assert mecatol_rex.resources == 1
        assert mecatol_rex.influence == 6
        assert mecatol_rex.trait is None
        assert not mecatol_rex.legendary

    def test_planet_with_trait(self) -> None:
        planet = Planet(
            id="vefut_ii",
            name="Vefut II",
            resources=2,
            influence=2,
            trait=PlanetTrait.HAZARDOUS,
        )
        assert planet.trait == PlanetTrait.HAZARDOUS

    def test_legendary_planet(self) -> None:
        planet = Planet(
            id="hope_s_end",
            name="Hope's End",
            resources=3,
            influence=0,
            trait=PlanetTrait.HAZARDOUS,
            legendary=True,
        )
        assert planet.legendary is True

    def test_tech_skip(self) -> None:
        planet = Planet(
            id="valk",
            name="Valk",
            resources=2,
            influence=0,
            tech_skip=TechSkip.WARFARE,
        )
        assert planet.tech_skip == TechSkip.WARFARE


# ---------------------------------------------------------------------------
# StrategyCard and ActionCard
# ---------------------------------------------------------------------------


class TestCards:
    def test_strategy_card(self, technology_card: StrategyCard) -> None:
        assert technology_card.initiative == 7
        assert "research" in technology_card.primary_ability.lower()

    def test_action_card(self, direct_hit: ActionCard) -> None:
        assert direct_hit.card_type == ActionCardType.COMPONENT

    def test_strategy_card_initiative_bounds(self) -> None:
        with pytest.raises(ValidationError):
            StrategyCard(
                id="bad",
                name="Bad",
                initiative=9,
                primary_ability="x",
                secondary_ability="y",
            )


# ---------------------------------------------------------------------------
# Faction
# ---------------------------------------------------------------------------


class TestFaction:
    def test_jol_nar(self, jol_nar: Faction) -> None:
        assert jol_nar.short_name == "Jol-Nar"
        assert jol_nar.commodities == 4
        assert len(jol_nar.abilities) == 1
        assert jol_nar.abilities[0].id == "analytical"

    def test_faction_is_frozen(self, jol_nar: Faction) -> None:
        with pytest.raises(ValidationError):
            jol_nar.commodities = 99  # type: ignore[misc]

    def test_faction_with_technologies_and_units_serializes(
        self, neural_motivator: Technology, carrier: Unit
    ) -> None:
        faction = Faction(
            id="test_faction",
            name="Test Faction",
            short_name="Test",
            home_system_id="test_home",
            commodities=3,
            faction_technologies=[neural_motivator],
            faction_units=[carrier],
        )
        data = faction.model_dump(mode="json")
        restored = Faction.model_validate(data)
        assert len(restored.faction_technologies) == 1
        assert restored.faction_technologies[0].id == "neural_motivator"
        assert len(restored.faction_units) == 1
        assert restored.faction_units[0].id == "carrier"


# ---------------------------------------------------------------------------
# TurnOrder
# ---------------------------------------------------------------------------


class TestTurnOrder:
    def test_valid_turn_order(self, turn_order: TurnOrder) -> None:
        assert turn_order.speaker_id == "player_1"
        assert len(turn_order.order) == 3

    def test_speaker_not_in_order(self) -> None:
        with pytest.raises(ValidationError, match="speaker_id"):
            TurnOrder(speaker_id="player_999", order=["player_1", "player_2"])


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------


class TestGameState:
    def test_initial_phase(self, game_state: GameState) -> None:
        assert game_state.phase == GamePhase.STRATEGY
        assert game_state.round_number == 1

    def test_get_player(self, game_state: GameState) -> None:
        player = game_state.get_player("player_1")
        assert player.faction_id == "the_universities_of_jol_nar"

    def test_get_player_missing(self, game_state: GameState) -> None:
        with pytest.raises(KeyError, match="player_999"):
            game_state.get_player("player_999")

    def test_all_players_passed_false(self, game_state: GameState) -> None:
        assert game_state.all_players_passed() is False

    def test_all_players_passed_true(self, game_state: GameState) -> None:
        for player in game_state.players.values():
            player.passed = True
        assert game_state.all_players_passed() is True

    def test_snapshot_round_trip(self, game_state: GameState) -> None:
        snap = game_state.snapshot()
        restored = GameState.restore(snap)
        assert restored.game_id == game_state.game_id
        assert restored.phase == game_state.phase
        assert restored.round_number == game_state.round_number
        assert set(restored.players.keys()) == set(game_state.players.keys())

    def test_snapshot_is_dict(self, game_state: GameState) -> None:
        snap = game_state.snapshot()
        assert isinstance(snap, dict)

    def test_apply_snapshot_returns_new_state(self, game_state: GameState) -> None:
        snap = game_state.snapshot()
        new_state = game_state.apply_snapshot(snap)
        assert new_state is not game_state
        assert new_state.game_id == game_state.game_id
