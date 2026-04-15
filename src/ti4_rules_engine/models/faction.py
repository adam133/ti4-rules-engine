"""Faction model – represents a TI4 playable faction."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ti4_rules_engine.models.technology import Technology
from ti4_rules_engine.models.unit import Unit


class FactionAbility(BaseModel):
    """A named faction ability with its rules text."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'quantum_entanglement'.")
    name: str = Field(description="Display name.")
    description: str = Field(description="Rules text for this ability.")

    model_config = {"frozen": True}


class Faction(BaseModel):
    """Schema for a TI4 playable faction."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'the_universities_of_jol_nar'.")
    name: str = Field(description="Display name, e.g. 'The Universities of Jol-Nar'.")
    short_name: str = Field(description="Abbreviated name used in UI contexts, e.g. 'Jol-Nar'.")
    home_system_id: str = Field(description="ID of this faction's home system tile.")
    starting_planets: list[str] = Field(
        default_factory=list, description="IDs of the faction's starting planets."
    )
    starting_units: dict[str, int] = Field(
        default_factory=dict,
        description="Map of unit_id → quantity for the faction's starting fleet.",
    )
    starting_technologies: list[str] = Field(
        default_factory=list,
        description="IDs of technologies the faction starts with.",
    )
    faction_technologies: list[Technology] = Field(
        default_factory=list,
        description="Faction-specific technology cards available only to this faction.",
    )
    faction_units: list[Unit] = Field(
        default_factory=list,
        description="Faction-specific unit types (typically the Flagship and Mech).",
    )
    abilities: list[FactionAbility] = Field(
        default_factory=list, description="List of named faction abilities."
    )
    commodities: int = Field(ge=0, description="Maximum commodity count for this faction.")
    starting_resources: int = Field(
        default=0, ge=0, description="Trade goods the faction begins the game with."
    )
    flavor_text: str | None = Field(default=None, description="Lore text for the faction.")
    asset_id: str | None = Field(
        default=None,
        description=(
            "Asset identifier used to locate faction artwork and tokens, "
            "following TI4 Map Generator Bot conventions."
        ),
    )

    model_config = {"frozen": True}
