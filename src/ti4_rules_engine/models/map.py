"""Galaxy map model – system nodes and adjacency for movement evaluation."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class WormholeType(StrEnum):
    """Types of wormhole that can appear in TI4 systems."""

    ALPHA = "alpha"
    BETA = "beta"
    DELTA = "delta"
    GAMMA = "gamma"


class AnomalyType(StrEnum):
    """Anomaly types that affect ship movement and combat."""

    GRAVITY_RIFT = "gravity_rift"
    """Ships exiting a gravity rift may suffer casualties; ships adjacent to or
    in a gravity rift gain +1 movement."""

    NEBULA = "nebula"
    """Ships moving into a nebula must end their movement there (cannot pass
    through). Ships in a nebula get +1 defence in space combat."""

    SUPERNOVA = "supernova"
    """Ships cannot enter or move through a supernova system."""

    ASTEROID_FIELD = "asteroid_field"
    """Ships must end their movement when entering an asteroid field (cannot
    pass through). Fighters and Mechs are exempt."""


class System(BaseModel):
    """A single system tile on the TI4 galaxy map."""

    id: str = Field(description="Unique system identifier, e.g. '18' for Mecatol Rex.")
    name: str | None = Field(default=None, description="Optional display name.")
    adjacent_system_ids: list[str] = Field(
        default_factory=list,
        description="IDs of systems that share a hex edge with this system.",
    )
    wormholes: list[WormholeType] = Field(
        default_factory=list,
        description="Wormhole types present in this system.",
    )
    anomaly: AnomalyType | None = Field(
        default=None,
        description="The anomaly type, or None if no anomaly is present.",
    )
    is_home_system: bool = Field(
        default=False,
        description="True if this is a player's home system.",
    )

    model_config = {"frozen": True}


class GalaxyMap(BaseModel):
    """The full galaxy map represented as a graph of :class:`System` nodes.

    Adjacency between systems is determined by two mechanisms:

    1. **Hex-grid adjacency** – systems that share a tile edge are listed in
       each other's ``adjacent_system_ids``.
    2. **Wormhole adjacency** – any two systems that share the same
       :class:`WormholeType` are treated as adjacent for movement purposes.
    """

    systems: dict[str, System] = Field(
        default_factory=dict,
        description="Mapping of system_id → System.",
    )

    model_config = {"frozen": True}

    def get_system(self, system_id: str) -> System:
        """Return the system with *system_id*, raising ``KeyError`` if absent."""
        try:
            return self.systems[system_id]
        except KeyError:
            raise KeyError(f"No system with id '{system_id}' in the galaxy map.") from None

    def get_adjacent_ids(self, system_id: str) -> list[str]:
        """Return all system IDs adjacent to *system_id*.

        Adjacency is **bidirectional**: a system B is considered adjacent to A
        if A lists B in its ``adjacent_system_ids`` *or* B lists A in its own
        ``adjacent_system_ids``.  Wormhole connections are also included: any
        two systems that share the same :class:`WormholeType` are adjacent.

        The origin system is never included in the result.
        """
        system = self.get_system(system_id)
        adjacent: set[str] = set(system.adjacent_system_ids)

        # Bidirectional adjacency: also include systems that list system_id
        for other_id, other_system in self.systems.items():
            if other_id != system_id and system_id in other_system.adjacent_system_ids:
                adjacent.add(other_id)

        # Add wormhole connections: any other system sharing a wormhole type
        for wormhole in system.wormholes:
            for other_id, other_system in self.systems.items():
                if other_id != system_id and wormhole in other_system.wormholes:
                    adjacent.add(other_id)

        return sorted(adjacent)
