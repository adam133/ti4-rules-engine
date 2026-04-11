"""Technology model – represents a TI4 technology card."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TechCategory(StrEnum):
    """The four standard technology colours plus faction-specific."""

    BIOTIC = "biotic"
    CYBERNETIC = "cybernetic"
    PROPULSION = "propulsion"
    WARFARE = "warfare"
    FACTION = "faction"


class Technology(BaseModel):
    """Schema for a TI4 technology card."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'neural_motivator'.")
    name: str = Field(description="Display name, e.g. 'Neural Motivator'.")
    category: TechCategory
    prerequisites: dict[TechCategory, int] = Field(
        default_factory=dict,
        description="Required prerequisites by colour, e.g. {'biotic': 2}.",
    )
    description: str = Field(default="", description="Rules text describing the technology effect.")
    is_unit_upgrade: bool = Field(
        default=False, description="True if this card upgrades a specific unit type."
    )
    faction_id: str | None = Field(
        default=None,
        description="Faction that owns this tech. None for generic technologies.",
    )

    model_config = {"frozen": True}
