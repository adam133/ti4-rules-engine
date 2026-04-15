"""Card models – Strategy Cards and Action Cards."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class StrategyCard(BaseModel):
    """One of the eight Strategy Cards chosen during the Strategy Phase."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'technology'.")
    name: str = Field(description="Display name, e.g. 'Technology'.")
    initiative: int = Field(
        ge=1,
        le=8,
        description="Initiative order (1 = Leadership, 8 = Imperial).",
    )
    primary_ability: str = Field(
        description="Rules text for the primary ability used by the card holder."
    )
    secondary_ability: str = Field(
        description="Rules text for the secondary ability available to other players."
    )
    trade_goods_bonus: int = Field(
        default=0,
        ge=0,
        description="Trade goods placed on this card when it is not chosen.",
    )

    model_config = {"frozen": True}


class ActionCardType(StrEnum):
    """When an Action Card may be played."""

    ACTION = "action"
    AGENDA = "agenda"
    COMPONENT = "component"
    POLITICAL = "political"
    SPECIAL = "special"


class ActionCard(BaseModel):
    """An Action Card that players draw and play during the game."""

    id: str = Field(description="Unique snake_case identifier, e.g. 'direct_hit'.")
    name: str = Field(description="Display name, e.g. 'Direct Hit'.")
    card_type: ActionCardType
    description: str = Field(description="Full rules text of the card.")
    flavor_text: str | None = Field(default=None, description="Optional flavour/lore text.")

    model_config = {"frozen": True}
