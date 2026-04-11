"""Shared pytest fixtures for the TI4 Rules Engine test suite."""

from __future__ import annotations

import pytest

from models.card import ActionCard, ActionCardType, StrategyCard
from models.faction import Faction, FactionAbility
from models.planet import Planet, PlanetTrait, TechSkip
from models.state import GamePhase, GameState, PlayerState, TurnOrder
from models.technology import TechCategory, Technology
from models.unit import Unit, UnitType


@pytest.fixture()
def carrier() -> Unit:
    return Unit(
        id="carrier",
        name="Carrier",
        unit_type=UnitType.CARRIER,
        cost=3,
        combat=9,
        move=2,
        capacity=4,
    )


@pytest.fixture()
def dreadnought() -> Unit:
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
    )


@pytest.fixture()
def neural_motivator() -> Technology:
    return Technology(
        id="neural_motivator",
        name="Neural Motivator",
        category=TechCategory.BIOTIC,
        description="During the Status Phase, draw 2 Action Cards (instead of 1).",
    )


@pytest.fixture()
def mecatol_rex() -> Planet:
    return Planet(
        id="mecatol_rex",
        name="Mecatol Rex",
        resources=1,
        influence=6,
        system_id="18",
    )


@pytest.fixture()
def technology_card() -> StrategyCard:
    return StrategyCard(
        id="technology",
        name="Technology",
        initiative=7,
        primary_ability="Research 1 technology.",
        secondary_ability="Spend 6 resources to research 1 technology.",
    )


@pytest.fixture()
def direct_hit() -> ActionCard:
    return ActionCard(
        id="direct_hit",
        name="Direct Hit",
        card_type=ActionCardType.COMPONENT,
        description=(
            "After another player's unit uses Sustain Damage to cancel a hit, "
            "cancel the unit's Sustain Damage ability."
        ),
    )


@pytest.fixture()
def jol_nar_ability() -> FactionAbility:
    return FactionAbility(
        id="analytical",
        name="Analytical",
        description="When you research a technology that has prerequisites, gain 1 trade good.",
    )


@pytest.fixture()
def jol_nar(neural_motivator: Technology, jol_nar_ability: FactionAbility) -> Faction:
    return Faction(
        id="the_universities_of_jol_nar",
        name="The Universities of Jol-Nar",
        short_name="Jol-Nar",
        home_system_id="jol_nar_home",
        starting_planets=["jol", "nar"],
        starting_units={"carrier": 2, "destroyer": 1, "fighter": 3, "space_dock": 1},
        starting_technologies=["neural_motivator", "sarween_tools", "e_res_siphons"],
        abilities=[jol_nar_ability],
        commodities=4,
        asset_id="jol_nar",
    )


@pytest.fixture()
def turn_order() -> TurnOrder:
    return TurnOrder(speaker_id="player_1", order=["player_1", "player_2", "player_3"])


@pytest.fixture()
def player_1_state() -> PlayerState:
    return PlayerState(player_id="player_1", faction_id="the_universities_of_jol_nar")


@pytest.fixture()
def player_2_state() -> PlayerState:
    return PlayerState(player_id="player_2", faction_id="the_emirates_of_hacan")


@pytest.fixture()
def player_3_state() -> PlayerState:
    return PlayerState(player_id="player_3", faction_id="the_federation_of_sol")


@pytest.fixture()
def game_state(
    turn_order: TurnOrder,
    player_1_state: PlayerState,
    player_2_state: PlayerState,
    player_3_state: PlayerState,
) -> GameState:
    return GameState(
        game_id="test-game-1",
        round_number=1,
        phase=GamePhase.STRATEGY,
        turn_order=turn_order,
        players={
            "player_1": player_1_state,
            "player_2": player_2_state,
            "player_3": player_3_state,
        },
    )
