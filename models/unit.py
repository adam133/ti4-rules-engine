"""Unit model – represents a single type of TI4 military or non-military unit."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class UnitType(StrEnum):
    """High-level unit categories used throughout the rules engine."""

    FLAGSHIP = "flagship"
    WAR_SUN = "war_sun"
    DREADNOUGHT = "dreadnought"
    CARRIER = "carrier"
    CRUISER = "cruiser"
    DESTROYER = "destroyer"
    FIGHTER = "fighter"
    PDS = "pds"
    SPACE_DOCK = "space_dock"
    GROUND_FORCE = "ground_force"
    MECH = "mech"


class Unit(BaseModel):
    """Schema for a TI4 unit type, including combat and production statistics."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'carrier'.")
    name: str = Field(description="Display name, e.g. 'Carrier'.")
    unit_type: UnitType
    cost: int | None = Field(
        default=None,
        ge=0,
        description="Production cost in resources. None for units that cannot be built (e.g. Flagship).",
    )
    combat: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Base combat roll value (hits on this or higher).",
    )
    combat_rolls: int = Field(default=1, ge=1, description="Number of combat dice rolled per round.")
    move: int | None = Field(default=None, ge=0, description="Movement value. None for structures.")
    capacity: int = Field(default=0, ge=0, description="Number of units this unit can transport.")
    sustain_damage: bool = Field(
        default=False, description="Whether the unit can absorb one hit via Sustain Damage."
    )
    planetary_shield: bool = Field(
        default=False, description="Whether the unit provides Planetary Shield."
    )
    space_cannon: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Space Cannon combat value. None if unit lacks Space Cannon.",
    )
    space_cannon_rolls: int = Field(
        default=1, ge=1, description="Number of Space Cannon dice rolled."
    )
    bombardment: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Bombardment combat value. None if unit cannot bombard.",
    )
    bombardment_rolls: int = Field(default=1, ge=1, description="Number of Bombardment dice rolled.")
    production: int = Field(
        default=0, ge=0, description="Number of units this structure can produce per round."
    )

    model_config = {"frozen": True}
