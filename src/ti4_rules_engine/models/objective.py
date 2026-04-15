"""Objective models – represents TI4 scoring objectives.

TI4 has three categories of scoring objective:

* **Stage I Public** (1 VP) – revealed during the Status Phase, scorable by any player.
* **Stage II Public** (2 VP) – revealed during the Status Phase, scorable by any player.
* **Secret** (1 VP) – held and scored privately by a single player.

In addition a small number of "other" scoring methods exist: the Custodians Token,
Support for the Throne promissory notes, the Shard of the Throne relic, and the
Imperial Strategy Card's speaker ability.

Example usage::

    from ti4_rules_engine.models.objective import Objective, ObjectiveType, ScoringCondition, ScoringConditionType

    obj = Objective(
        id="expand_borders",
        name="Expand Borders",
        objective_type=ObjectiveType.STAGE_1,
        points=1,
        description="Control 6 planets outside of your home system.",
        condition=ScoringCondition(
            condition_type=ScoringConditionType.CONTROL_N_PLANETS_OUTSIDE_HOME,
            threshold=6,
        ),
    )
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ti4_rules_engine.models.planet import PlanetTrait


class ObjectiveType(StrEnum):
    """The type/stage of a TI4 scoring objective."""

    STAGE_1 = "stage_1"
    """Public objective worth 1 VP; scored during the Status Phase."""

    STAGE_2 = "stage_2"
    """Public objective worth 2 VP; scored during the Status Phase."""

    SECRET = "secret"
    """Private objective worth 1 VP; scored at any time once conditions are met."""

    OTHER = "other"
    """Miscellaneous scoring method (e.g. Custodians Token, Support for the Throne)."""


class ScoringConditionType(StrEnum):
    """
    The category of condition that must be satisfied to score an objective.

    Determines which evaluator in :mod:`engine.scoring` handles this condition.
    Conditions are grouped by what game-state information they require:

    * **Technology** – evaluable from :attr:`~models.state.PlayerState.researched_technologies`.
    * **Planet** – evaluable from :attr:`~models.state.PlayerState.controlled_planets`
      plus a planet registry.
    * **Fleet/board** – require fleet position data not captured in the base
      :class:`~models.state.PlayerState`; evaluation returns ``None``.
    * **Spend** – require tracking of resources/influence/tokens spent during the round;
      evaluation returns ``None``.
    * **Special** – directly evaluable from core state fields (e.g. VP, laws in play).
    * **Player-declared** – cannot be auto-evaluated; the player must confirm.
    """

    # ------------------------------------------------------------------
    # Technology conditions
    # ------------------------------------------------------------------

    OWN_N_TECHS_OF_COLOR = "own_n_techs_of_color"
    """Own at least *threshold* technologies of a single standard color."""

    OWN_N_TECHS_IN_N_COLORS = "own_n_techs_in_n_colors"
    """Own at least *threshold* technologies in each of *secondary_threshold* different colors."""

    OWN_N_UNIT_UPGRADES = "own_n_unit_upgrades"
    """Own at least *threshold* unit upgrade technologies."""

    # ------------------------------------------------------------------
    # Planet conditions
    # ------------------------------------------------------------------

    CONTROL_N_PLANETS_OF_SAME_TRAIT = "control_n_planets_of_same_trait"
    """Control *threshold* planets that each share the same planet trait."""

    CONTROL_N_PLANETS_WITH_TECH_SKIP = "control_n_planets_with_tech_skip"
    """Control *threshold* planets that have a technology specialty."""

    CONTROL_N_PLANETS_OUTSIDE_HOME = "control_n_planets_outside_home"
    """Control *threshold* planets outside your home system."""

    CONTROL_N_LEGENDARY_PLANETS = "control_n_legendary_planets"
    """Control *threshold* legendary planets."""

    CONTROL_MECATOL_REX = "control_mecatol_rex"
    """Control Mecatol Rex (the Galactic Council's home planet)."""

    CONTROL_N_PLANETS_IN_OPPONENT_HOME_SYSTEMS = "control_n_planets_in_opponent_home_systems"
    """Control *threshold* planets that are in other players' home systems.

    Uses ``state.extra["home_systems"]`` (a mapping of ``player_id → system_id``) and
    a planet registry to identify which controlled planets lie in opponent home systems.
    """

    CONTROL_N_PLANETS_OF_SPECIFIC_TRAIT = "control_n_planets_of_specific_trait"
    """Control *threshold* planets that have the specific trait given by :attr:`ScoringCondition.trait`."""

    CONTROL_N_PLANETS_OF_TRAIT_OUTSIDE_HOME = "control_n_planets_of_trait_outside_home"
    """Control *threshold* planets with the specific trait given by :attr:`ScoringCondition.trait`,
    all outside the player's home system.

    Uses ``state.extra["home_systems"]`` and a planet registry.
    """

    # ------------------------------------------------------------------
    # Fleet / board-state conditions  (evaluation returns ``None``)
    # ------------------------------------------------------------------

    SHIPS_IN_N_SYSTEMS_ADJACENT_MECATOL = "ships_in_n_systems_adjacent_mecatol"
    """Have 1 or more ships in each of *threshold* systems adjacent to Mecatol Rex."""

    SHIPS_IN_N_OPPONENT_HOME_SYSTEMS = "ships_in_n_opponent_home_systems"
    """Have 1 or more ships in each of *threshold* different opponent home systems."""

    HAVE_N_NON_FIGHTER_SHIPS_IN_1_SYSTEM = "have_n_non_fighter_ships_in_1_system"
    """Have *threshold* or more non-fighter ships in a single system."""

    HAVE_N_NON_FIGHTER_SHIPS_IN_N_SYSTEMS = "have_n_non_fighter_ships_in_n_systems"
    """Have at least *threshold* non-fighter ships in each of *secondary_threshold* systems."""

    HAVE_SHIPS_IN_N_SYSTEMS_WITHOUT_PLANETS = "have_ships_in_n_systems_without_planets"
    """Have 1 or more ships in each of *threshold* systems that contain no planets."""

    HAVE_N_STRUCTURES = "have_n_structures"
    """Have *threshold* or more structures (PDS / Space Docks) on the board."""

    HAVE_N_MECHS = "have_n_mechs"
    """Have *threshold* or more mechs on the board."""

    HAVE_N_DREADNOUGHTS = "have_n_dreadnoughts"
    """Have *threshold* or more dreadnoughts on the board."""

    # ------------------------------------------------------------------
    # Spend conditions  (evaluation returns ``None``)
    # ------------------------------------------------------------------

    SPEND_N_RESOURCES = "spend_n_resources"
    """Spend a combined total of *threshold* resources."""

    SPEND_N_INFLUENCE = "spend_n_influence"
    """Spend a combined total of *threshold* influence."""

    SPEND_N_TRADE_GOODS = "spend_n_trade_goods"
    """Spend a combined total of *threshold* trade goods."""

    SPEND_N_COMMAND_TOKENS = "spend_n_command_tokens"
    """Spend a combined total of *threshold* command tokens."""

    # ------------------------------------------------------------------
    # Special / direct-state conditions
    # ------------------------------------------------------------------

    HAVE_N_VICTORY_POINTS = "have_n_victory_points"
    """Hold *threshold* or more victory points."""

    HAVE_N_LAWS_IN_PLAY = "have_n_laws_in_play"
    """There are *threshold* or more laws currently in play.

    Evaluable directly from :attr:`~models.state.GameState.law_ids`.
    """

    HAVE_N_INFLUENCE_ON_UNEXHAUSTED_PLANETS = "have_n_influence_on_unexhausted_planets"
    """Have *threshold* or more total influence on unexhausted planets the player controls.

    Requires a planet registry; sums the :attr:`~models.planet.Planet.influence` of every
    controlled planet that is **not** in :attr:`~models.state.PlayerState.exhausted_planets`.
    """

    PLAYER_DECLARED = "player_declared"
    """Condition cannot be auto-evaluated; the player must confirm manually."""


class ScoringCondition(BaseModel):
    """
    The specific condition that must be met to score an objective.

    The meaning of each field depends on the :attr:`condition_type`:

    * ``threshold`` – the primary numeric requirement (e.g. control **6** planets).
    * ``secondary_threshold`` – a second numeric requirement used by compound conditions
      (e.g. own **2** techs in each of **2** colors → ``threshold=2``,
      ``secondary_threshold=2``).
    * ``trait`` – the specific :class:`~models.planet.PlanetTrait` required by
      :attr:`~ScoringConditionType.CONTROL_N_PLANETS_OF_SPECIFIC_TRAIT` and
      :attr:`~ScoringConditionType.CONTROL_N_PLANETS_OF_TRAIT_OUTSIDE_HOME`.
    """

    condition_type: ScoringConditionType = Field(
        description="The category of condition that must be satisfied."
    )
    threshold: int = Field(
        default=1,
        ge=1,
        description="Primary numeric threshold (e.g. control 6 planets → threshold=6).",
    )
    secondary_threshold: int = Field(
        default=1,
        ge=1,
        description=(
            "Secondary threshold for compound conditions "
            "(e.g. own 2 techs in each of 2 colors → threshold=2, secondary_threshold=2)."
        ),
    )
    trait: PlanetTrait | None = Field(
        default=None,
        description=(
            "Required planet trait for trait-specific conditions "
            "(CONTROL_N_PLANETS_OF_SPECIFIC_TRAIT and CONTROL_N_PLANETS_OF_TRAIT_OUTSIDE_HOME)."
        ),
    )

    model_config = {"frozen": True}


class Objective(BaseModel):
    """A TI4 scoring objective (public Stage I/II, secret, or other)."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'expand_borders'.")
    name: str = Field(description="Display name, e.g. 'Expand Borders'.")
    objective_type: ObjectiveType = Field(
        description="Stage I public, Stage II public, secret, or other."
    )
    points: int = Field(
        ge=1,
        description="Victory points awarded when this objective is scored.",
    )
    description: str = Field(description="Rules text describing what must be done to score.")
    condition: ScoringCondition = Field(
        description="Structured representation of the scoring condition."
    )

    model_config = {"frozen": True}
