"""Planet model – represents a TI4 planet tile."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PlanetTrait(StrEnum):
    """Cultural, Hazardous, and Industrial planet traits."""

    CULTURAL = "cultural"
    HAZARDOUS = "hazardous"
    INDUSTRIAL = "industrial"


class TechSkip(StrEnum):
    """Technology specialty (skip) provided by a planet."""

    BIOTIC = "biotic"
    CYBERNETIC = "cybernetic"
    PROPULSION = "propulsion"
    WARFARE = "warfare"


class Planet(BaseModel):
    """Schema for a TI4 planet."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'mecatol_rex'.")
    name: str = Field(description="Display name, e.g. 'Mecatol Rex'.")
    resources: int = Field(ge=0, description="Resource value of the planet.")
    influence: int = Field(ge=0, description="Influence value of the planet.")
    trait: PlanetTrait | None = Field(
        default=None, description="Cultural, Hazardous, or Industrial. None for planets with no trait."
    )
    tech_skip: TechSkip | None = Field(
        default=None, description="Technology specialty provided by the planet, if any."
    )
    legendary: bool = Field(default=False, description="True if this is a Legendary planet.")
    system_id: str | None = Field(
        default=None, description="ID of the system tile that contains this planet."
    )

    model_config = {"frozen": True}
