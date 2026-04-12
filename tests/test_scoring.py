"""Tests for the scoring engine."""

from __future__ import annotations

import pytest

from engine.scoring import can_score_objective, score_points_available
from models.objective import Objective, ObjectiveType, ScoringCondition, ScoringConditionType
from models.planet import Planet, PlanetTrait, TechSkip
from models.state import GamePhase, GameState, PlayerState, TurnOrder
from models.technology import TechCategory, Technology

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_state(
    player_id: str = "player_1",
    *,
    controlled_planets: list[str] | None = None,
    researched_technologies: list[str] | None = None,
    scored_objectives: list[str] | None = None,
    victory_points: int = 0,
    extra: dict | None = None,
) -> GameState:
    """Return a minimal GameState for scoring tests."""
    player = PlayerState(
        player_id=player_id,
        faction_id="test_faction",
        victory_points=victory_points,
        controlled_planets=controlled_planets or [],
        researched_technologies=researched_technologies or [],
        scored_objectives=scored_objectives or [],
    )
    turn_order = TurnOrder(speaker_id=player_id, order=[player_id])
    return GameState(
        game_id="test-scoring",
        round_number=1,
        phase=GamePhase.STATUS,
        turn_order=turn_order,
        players={player_id: player},
        extra=extra or {},
    )


def _make_obj(
    obj_id: str,
    condition_type: ScoringConditionType,
    *,
    threshold: int = 1,
    secondary_threshold: int = 1,
    objective_type: ObjectiveType = ObjectiveType.STAGE_1,
    points: int = 1,
) -> Objective:
    return Objective(
        id=obj_id,
        name=obj_id.replace("_", " ").title(),
        objective_type=objective_type,
        points=points,
        description="Test objective.",
        condition=ScoringCondition(
            condition_type=condition_type,
            threshold=threshold,
            secondary_threshold=secondary_threshold,
        ),
    )


# Sample technology registry
@pytest.fixture()
def tech_registry() -> dict[str, Technology]:
    return {
        "neural_motivator": Technology(
            id="neural_motivator",
            name="Neural Motivator",
            category=TechCategory.BIOTIC,
            description="Draw 2 action cards.",
        ),
        "bio_stims": Technology(
            id="bio_stims",
            name="Bio-Stims",
            category=TechCategory.BIOTIC,
            description="Exhaust to ready a planet or unit.",
        ),
        "psychoarchaeology": Technology(
            id="psychoarchaeology",
            name="Psychoarchaeology",
            category=TechCategory.BIOTIC,
            description="Use cultural planets.",
        ),
        "ai_development_algorithm": Technology(
            id="ai_development_algorithm",
            name="AI Development Algorithm",
            category=TechCategory.CYBERNETIC,
            description="Cybernetic tech.",
        ),
        "sarween_tools": Technology(
            id="sarween_tools",
            name="Sarween Tools",
            category=TechCategory.CYBERNETIC,
            description="Produce 1 extra unit.",
        ),
        "carrier_ii": Technology(
            id="carrier_ii",
            name="Carrier II",
            category=TechCategory.PROPULSION,
            is_unit_upgrade=True,
            description="Upgraded carrier.",
        ),
        "dreadnought_ii": Technology(
            id="dreadnought_ii",
            name="Dreadnought II",
            category=TechCategory.WARFARE,
            is_unit_upgrade=True,
            description="Upgraded dreadnought.",
        ),
        "faction_tech": Technology(
            id="faction_tech",
            name="Faction Tech",
            category=TechCategory.FACTION,
            faction_id="test_faction",
            description="Faction-specific tech.",
        ),
    }


@pytest.fixture()
def planet_registry() -> dict[str, Planet]:
    return {
        "mecatol_rex": Planet(
            id="mecatol_rex",
            name="Mecatol Rex",
            resources=1,
            influence=6,
            system_id="18",
        ),
        "jord": Planet(
            id="jord",
            name="Jord",
            resources=4,
            influence=2,
            system_id="sol_home",
        ),
        "nar": Planet(
            id="nar",
            name="Nar",
            resources=2,
            influence=3,
            system_id="jol_nar_home",
        ),
        "vefut_ii": Planet(
            id="vefut_ii",
            name="Vefut II",
            resources=2,
            influence=2,
            trait=PlanetTrait.HAZARDOUS,
            system_id="A",
        ),
        "abaddon": Planet(
            id="abaddon",
            name="Abaddon",
            resources=1,
            influence=0,
            trait=PlanetTrait.CULTURAL,
            system_id="B",
        ),
        "lazar": Planet(
            id="lazar",
            name="Lazar",
            resources=1,
            influence=0,
            trait=PlanetTrait.INDUSTRIAL,
            system_id="C",
        ),
        "sakulag": Planet(
            id="sakulag",
            name="Sakulag",
            resources=2,
            influence=1,
            trait=PlanetTrait.HAZARDOUS,
            system_id="D",
        ),
        "maakar_martyrs": Planet(
            id="maakar_martyrs",
            name="Maakar Martyrs",
            resources=1,
            influence=2,
            trait=PlanetTrait.HAZARDOUS,
            tech_skip=TechSkip.BIOTIC,
            system_id="E",
        ),
        "starpoint": Planet(
            id="starpoint",
            name="Starpoint",
            resources=3,
            influence=1,
            trait=PlanetTrait.HAZARDOUS,
            tech_skip=TechSkip.PROPULSION,
            system_id="F",
        ),
        "hope_s_end": Planet(
            id="hope_s_end",
            name="Hope's End",
            resources=3,
            influence=0,
            trait=PlanetTrait.HAZARDOUS,
            legendary=True,
            system_id="G",
        ),
        "mallice": Planet(
            id="mallice",
            name="Mallice",
            resources=0,
            influence=3,
            legendary=True,
            system_id="H",
        ),
    }


# ---------------------------------------------------------------------------
# Technology conditions
# ---------------------------------------------------------------------------


class TestOwnNUnitUpgrades:
    def test_meets_threshold(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["carrier_ii", "dreadnought_ii"])
        obj = _make_obj("develop_weaponry", ScoringConditionType.OWN_N_UNIT_UPGRADES, threshold=2)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is True

    def test_below_threshold(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["carrier_ii"])
        obj = _make_obj("develop_weaponry", ScoringConditionType.OWN_N_UNIT_UPGRADES, threshold=2)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(researched_technologies=["carrier_ii", "dreadnought_ii"])
        obj = _make_obj("develop_weaponry", ScoringConditionType.OWN_N_UNIT_UPGRADES, threshold=2)
        assert can_score_objective(obj, state, "player_1") is None

    def test_non_upgrade_techs_not_counted(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["neural_motivator", "sarween_tools"])
        obj = _make_obj("develop_weaponry", ScoringConditionType.OWN_N_UNIT_UPGRADES, threshold=1)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False


class TestOwnNTechsOfColor:
    def test_meets_threshold(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(
            researched_technologies=["neural_motivator", "bio_stims", "psychoarchaeology"]
        )
        obj = _make_obj("tech_color", ScoringConditionType.OWN_N_TECHS_OF_COLOR, threshold=3)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is True

    def test_below_threshold(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["neural_motivator"])
        obj = _make_obj("tech_color", ScoringConditionType.OWN_N_TECHS_OF_COLOR, threshold=2)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False

    def test_faction_techs_excluded(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["faction_tech"])
        obj = _make_obj("tech_color", ScoringConditionType.OWN_N_TECHS_OF_COLOR, threshold=1)
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(researched_technologies=["neural_motivator", "bio_stims"])
        obj = _make_obj("tech_color", ScoringConditionType.OWN_N_TECHS_OF_COLOR, threshold=2)
        assert can_score_objective(obj, state, "player_1") is None


class TestOwnNTechsInNColors:
    def test_meets_both_thresholds(self, tech_registry: dict[str, Technology]) -> None:
        # 3 biotic + 2 cybernetic → should have 2 techs in each of 2 colors
        state = _make_state(
            researched_technologies=[
                "neural_motivator",
                "bio_stims",
                "ai_development_algorithm",
                "sarween_tools",
            ]
        )
        obj = _make_obj(
            "diversify_research",
            ScoringConditionType.OWN_N_TECHS_IN_N_COLORS,
            threshold=2,
            secondary_threshold=2,
        )
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is True

    def test_only_one_color(self, tech_registry: dict[str, Technology]) -> None:
        state = _make_state(researched_technologies=["neural_motivator", "bio_stims"])
        obj = _make_obj(
            "diversify_research",
            ScoringConditionType.OWN_N_TECHS_IN_N_COLORS,
            threshold=2,
            secondary_threshold=2,
        )
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False

    def test_not_enough_per_color(self, tech_registry: dict[str, Technology]) -> None:
        # 1 biotic + 1 cybernetic – not enough per color
        state = _make_state(
            researched_technologies=["neural_motivator", "ai_development_algorithm"]
        )
        obj = _make_obj(
            "diversify_research",
            ScoringConditionType.OWN_N_TECHS_IN_N_COLORS,
            threshold=2,
            secondary_threshold=2,
        )
        assert can_score_objective(obj, state, "player_1", tech_registry=tech_registry) is False

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(
            researched_technologies=["neural_motivator", "bio_stims"]
        )
        obj = _make_obj(
            "diversify_research",
            ScoringConditionType.OWN_N_TECHS_IN_N_COLORS,
            threshold=2,
            secondary_threshold=2,
        )
        assert can_score_objective(obj, state, "player_1") is None


# ---------------------------------------------------------------------------
# Planet conditions
# ---------------------------------------------------------------------------


class TestControlNPlanetsWithTechSkip:
    def test_meets_threshold(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["maakar_martyrs", "starpoint", "mecatol_rex"])
        obj = _make_obj(
            "found_research_outposts",
            ScoringConditionType.CONTROL_N_PLANETS_WITH_TECH_SKIP,
            threshold=2,
        )
        assert can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is True

    def test_below_threshold(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["maakar_martyrs", "mecatol_rex"])
        obj = _make_obj(
            "found_research_outposts",
            ScoringConditionType.CONTROL_N_PLANETS_WITH_TECH_SKIP,
            threshold=3,
        )
        assert (
            can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is False
        )

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(controlled_planets=["maakar_martyrs"])
        obj = _make_obj(
            "found_research_outposts",
            ScoringConditionType.CONTROL_N_PLANETS_WITH_TECH_SKIP,
            threshold=1,
        )
        assert can_score_objective(obj, state, "player_1") is None


class TestControlNPlanetsOfSameTrait:
    def test_meets_threshold(self, planet_registry: dict[str, Planet]) -> None:
        # vefut_ii, sakulag, maakar_martyrs, starpoint, hope_s_end = 5 hazardous
        state = _make_state(
            controlled_planets=["vefut_ii", "sakulag", "maakar_martyrs", "starpoint"]
        )
        obj = _make_obj(
            "corner_the_market",
            ScoringConditionType.CONTROL_N_PLANETS_OF_SAME_TRAIT,
            threshold=4,
        )
        assert can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is True

    def test_mixed_traits_insufficient(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["vefut_ii", "abaddon", "lazar"])
        obj = _make_obj(
            "corner_the_market",
            ScoringConditionType.CONTROL_N_PLANETS_OF_SAME_TRAIT,
            threshold=2,
        )
        assert (
            can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is False
        )

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(controlled_planets=["vefut_ii", "sakulag"])
        obj = _make_obj(
            "corner_the_market",
            ScoringConditionType.CONTROL_N_PLANETS_OF_SAME_TRAIT,
            threshold=2,
        )
        assert can_score_objective(obj, state, "player_1") is None


class TestControlNLegendaryPlanets:
    def test_meets_threshold(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["hope_s_end", "mallice"])
        obj = _make_obj(
            "legendary_planets",
            ScoringConditionType.CONTROL_N_LEGENDARY_PLANETS,
            threshold=2,
        )
        assert can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is True

    def test_below_threshold(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["hope_s_end"])
        obj = _make_obj(
            "legendary_planets",
            ScoringConditionType.CONTROL_N_LEGENDARY_PLANETS,
            threshold=2,
        )
        assert (
            can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is False
        )

    def test_no_registry_returns_none(self) -> None:
        state = _make_state(controlled_planets=["hope_s_end"])
        obj = _make_obj(
            "legendary_planets",
            ScoringConditionType.CONTROL_N_LEGENDARY_PLANETS,
            threshold=1,
        )
        assert can_score_objective(obj, state, "player_1") is None


class TestControlMecatolRex:
    def test_controls_mecatol(self) -> None:
        state = _make_state(controlled_planets=["mecatol_rex", "jord"])
        obj = _make_obj("mecatol_holder", ScoringConditionType.CONTROL_MECATOL_REX)
        assert can_score_objective(obj, state, "player_1") is True

    def test_does_not_control_mecatol(self) -> None:
        state = _make_state(controlled_planets=["jord"])
        obj = _make_obj("mecatol_holder", ScoringConditionType.CONTROL_MECATOL_REX)
        assert can_score_objective(obj, state, "player_1") is False


class TestControlNPlanetsOutsideHome:
    def test_meets_threshold_with_home_system(
        self, planet_registry: dict[str, Planet]
    ) -> None:
        # player_1's home system is "sol_home" (jord)
        planets = ["jord", "vefut_ii", "abaddon", "lazar", "sakulag", "maakar_martyrs", "starpoint"]
        state = _make_state(
            controlled_planets=planets,
            extra={"home_systems": {"player_1": "sol_home"}},
        )
        obj = _make_obj(
            "expand_borders",
            ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        )
        # 7 planets, 1 in home system → 6 outside
        assert can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is True

    def test_below_threshold_with_home_system(
        self, planet_registry: dict[str, Planet]
    ) -> None:
        state = _make_state(
            controlled_planets=["jord", "vefut_ii", "abaddon"],
            extra={"home_systems": {"player_1": "sol_home"}},
        )
        obj = _make_obj(
            "expand_borders",
            ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        )
        assert (
            can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is False
        )

    def test_no_home_system_in_extra_counts_all_planets(
        self, planet_registry: dict[str, Planet]
    ) -> None:
        # Without home system info, all planets count as "outside"
        planets = ["jord", "vefut_ii", "abaddon", "lazar", "sakulag", "maakar_martyrs"]
        state = _make_state(
            controlled_planets=planets,
        )
        obj = _make_obj(
            "expand_borders",
            ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        )
        assert can_score_objective(obj, state, "player_1", planet_registry=planet_registry) is True

    def test_no_planet_registry_returns_none(self) -> None:
        state = _make_state(controlled_planets=["jord", "vefut_ii"])
        obj = _make_obj(
            "expand_borders",
            ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        )
        assert can_score_objective(obj, state, "player_1") is None


# ---------------------------------------------------------------------------
# Fleet / board-state conditions (all return None)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition_type",
    [
        ScoringConditionType.SHIPS_IN_N_SYSTEMS_ADJACENT_MECATOL,
        ScoringConditionType.SHIPS_IN_N_OPPONENT_HOME_SYSTEMS,
        ScoringConditionType.HAVE_N_NON_FIGHTER_SHIPS_IN_1_SYSTEM,
        ScoringConditionType.HAVE_N_NON_FIGHTER_SHIPS_IN_N_SYSTEMS,
        ScoringConditionType.HAVE_SHIPS_IN_N_SYSTEMS_WITHOUT_PLANETS,
        ScoringConditionType.HAVE_N_STRUCTURES,
        ScoringConditionType.HAVE_N_MECHS,
        ScoringConditionType.HAVE_N_DREADNOUGHTS,
    ],
)
def test_fleet_conditions_return_none(condition_type: ScoringConditionType) -> None:
    state = _make_state()
    obj = _make_obj("fleet_obj", condition_type, threshold=1)
    assert can_score_objective(obj, state, "player_1") is None


# ---------------------------------------------------------------------------
# Spend conditions (all return None)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "condition_type",
    [
        ScoringConditionType.SPEND_N_RESOURCES,
        ScoringConditionType.SPEND_N_INFLUENCE,
        ScoringConditionType.SPEND_N_TRADE_GOODS,
        ScoringConditionType.SPEND_N_COMMAND_TOKENS,
    ],
)
def test_spend_conditions_return_none(condition_type: ScoringConditionType) -> None:
    state = _make_state()
    obj = _make_obj("spend_obj", condition_type, threshold=5)
    assert can_score_objective(obj, state, "player_1") is None


# ---------------------------------------------------------------------------
# Special / direct-state conditions
# ---------------------------------------------------------------------------


class TestHaveNVictoryPoints:
    def test_meets_threshold(self) -> None:
        state = _make_state(victory_points=5)
        obj = _make_obj("vp_obj", ScoringConditionType.HAVE_N_VICTORY_POINTS, threshold=5)
        assert can_score_objective(obj, state, "player_1") is True

    def test_below_threshold(self) -> None:
        state = _make_state(victory_points=3)
        obj = _make_obj("vp_obj", ScoringConditionType.HAVE_N_VICTORY_POINTS, threshold=5)
        assert can_score_objective(obj, state, "player_1") is False

    def test_exceeds_threshold(self) -> None:
        state = _make_state(victory_points=7)
        obj = _make_obj("vp_obj", ScoringConditionType.HAVE_N_VICTORY_POINTS, threshold=5)
        assert can_score_objective(obj, state, "player_1") is True


class TestPlayerDeclared:
    def test_always_returns_none(self) -> None:
        state = _make_state()
        obj = _make_obj("custom_obj", ScoringConditionType.PLAYER_DECLARED)
        assert can_score_objective(obj, state, "player_1") is None


# ---------------------------------------------------------------------------
# Objective model attributes
# ---------------------------------------------------------------------------


class TestObjectiveModel:
    def test_stage_1_points(self) -> None:
        obj = _make_obj("x", ScoringConditionType.CONTROL_MECATOL_REX)
        assert obj.points == 1
        assert obj.objective_type == ObjectiveType.STAGE_1

    def test_stage_2_points(self) -> None:
        obj = _make_obj(
            "x",
            ScoringConditionType.CONTROL_MECATOL_REX,
            objective_type=ObjectiveType.STAGE_2,
            points=2,
        )
        assert obj.points == 2

    def test_objective_is_frozen(self) -> None:
        from pydantic import ValidationError

        obj = _make_obj("x", ScoringConditionType.CONTROL_MECATOL_REX)
        with pytest.raises(ValidationError):
            obj.points = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# score_points_available
# ---------------------------------------------------------------------------


class TestScorePointsAvailable:
    def test_counts_scorable_objectives(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(controlled_planets=["mecatol_rex"])

        mecatol_obj = _make_obj("mecatol", ScoringConditionType.CONTROL_MECATOL_REX)
        fleet_obj = _make_obj(
            "fleet",
            ScoringConditionType.HAVE_N_NON_FIGHTER_SHIPS_IN_1_SYSTEM,
            threshold=5,
        )

        total = score_points_available(
            state,
            "player_1",
            [mecatol_obj, fleet_obj],
            planet_registry=planet_registry,
        )
        assert total == 1  # only mecatol_obj evaluates as True

    def test_skips_already_scored(self, planet_registry: dict[str, Planet]) -> None:
        state = _make_state(
            controlled_planets=["mecatol_rex"],
            scored_objectives=["mecatol"],
        )
        mecatol_obj = _make_obj("mecatol", ScoringConditionType.CONTROL_MECATOL_REX)
        total = score_points_available(
            state, "player_1", [mecatol_obj], planet_registry=planet_registry
        )
        assert total == 0

    def test_stage_2_worth_2_points(self) -> None:
        state = _make_state(victory_points=10)
        obj = _make_obj(
            "high_vp",
            ScoringConditionType.HAVE_N_VICTORY_POINTS,
            threshold=5,
            objective_type=ObjectiveType.STAGE_2,
            points=2,
        )
        total = score_points_available(state, "player_1", [obj])
        assert total == 2

    def test_empty_objectives_list(self) -> None:
        state = _make_state()
        assert score_points_available(state, "player_1", []) == 0

    def test_missing_player_raises(self) -> None:
        state = _make_state()
        obj = _make_obj("mecatol", ScoringConditionType.CONTROL_MECATOL_REX)
        with pytest.raises(KeyError):
            score_points_available(state, "unknown_player", [obj])


# ---------------------------------------------------------------------------
# Missing player
# ---------------------------------------------------------------------------


def test_can_score_objective_missing_player_raises() -> None:
    state = _make_state()
    obj = _make_obj("mecatol", ScoringConditionType.CONTROL_MECATOL_REX)
    with pytest.raises(KeyError):
        can_score_objective(obj, state, "unknown_player")
