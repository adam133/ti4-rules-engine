"""
Asset mapping utilities.

Establishes a link between game entity IDs and their visual asset file
paths, following the naming conventions used by the TI4 Map Generator Bot
to ensure compatibility with existing map-rendering tooling.

The mapper works with a configurable base path and a set of naming
conventions so that it can be pointed at any local asset bundle.

Example usage::

    mapper = AssetMapper(base_path="/assets/ti4")
    path = mapper.resolve("the_universities_of_jol_nar", AssetType.FACTION_ICON)
    # → "/assets/ti4/factions/the_universities_of_jol_nar_icon.png"
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class AssetType(StrEnum):
    """Categories of visual assets that can be resolved."""

    FACTION_ICON = "faction_icon"
    FACTION_TOKEN = "faction_token"
    FACTION_SHEET = "faction_sheet"
    UNIT_IMAGE = "unit_image"
    PLANET_IMAGE = "planet_image"
    SYSTEM_TILE = "system_tile"
    TECHNOLOGY_CARD = "technology_card"
    ACTION_CARD = "action_card"
    STRATEGY_CARD = "strategy_card"


# Mapping from AssetType → (subdirectory, filename suffix, extension)
# Mirrors the layout used by the TI4 Map Generator Bot asset bundle.
_ASSET_TEMPLATE: dict[AssetType, tuple[str, str, str]] = {
    AssetType.FACTION_ICON: ("factions", "_icon", ".png"),
    AssetType.FACTION_TOKEN: ("factions", "_token", ".png"),
    AssetType.FACTION_SHEET: ("factions", "_sheet", ".png"),
    AssetType.UNIT_IMAGE: ("units", "", ".png"),
    AssetType.PLANET_IMAGE: ("planets", "", ".png"),
    AssetType.SYSTEM_TILE: ("tiles", "_tile", ".png"),
    AssetType.TECHNOLOGY_CARD: ("technologies", "_tech", ".png"),
    AssetType.ACTION_CARD: ("action_cards", "_action", ".png"),
    AssetType.STRATEGY_CARD: ("strategy_cards", "_strategy", ".png"),
}


class AssetMapper:
    """
    Resolves game entity IDs to filesystem asset paths.

    Parameters
    ----------
    base_path:
        Root directory containing all TI4 asset subdirectories.
        Defaults to ``./assets``.
    verify_exists:
        When ``True``, ``resolve`` raises ``FileNotFoundError`` if the
        computed path does not exist on disk.  Set to ``False`` (default)
        for environments where the asset bundle may not be present at
        resolution time.
    """

    def __init__(
        self,
        base_path: str | os.PathLike = "assets",
        *,
        verify_exists: bool = False,
    ) -> None:
        self._base = Path(base_path)
        self._verify_exists = verify_exists
        self._overrides: dict[tuple[str, AssetType], Path] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, entity_id: str, asset_type: AssetType) -> Path:
        """
        Compute the path for the asset associated with *entity_id*.

        Parameters
        ----------
        entity_id:
            Snake-case ID of the game entity (faction, unit, planet, …).
        asset_type:
            The kind of asset being requested.

        Returns
        -------
        Path
            Absolute (or relative to CWD) path to the asset file.

        Raises
        ------
        FileNotFoundError
            If ``verify_exists=True`` and the path does not exist.
        """
        key = (entity_id, asset_type)
        if key in self._overrides:
            path = self._overrides[key]
        else:
            path = self._build_path(entity_id, asset_type)

        if self._verify_exists and not path.exists():
            raise FileNotFoundError(
                f"Asset not found: {path} (entity_id={entity_id!r}, type={asset_type!r})"
            )

        logger.debug("asset_resolved", entity_id=entity_id, asset_type=asset_type, path=str(path))
        return path

    def register_override(
        self, entity_id: str, asset_type: AssetType, path: str | os.PathLike
    ) -> None:
        """
        Register a custom path for a specific (entity_id, asset_type) pair.

        Useful when a faction's asset does not follow the standard naming
        convention (e.g. Creuss rift tiles).
        """
        self._overrides[(entity_id, asset_type)] = Path(path)
        logger.debug(
            "asset_override_registered",
            entity_id=entity_id,
            asset_type=asset_type,
            path=str(path),
        )

    def all_overrides(self) -> dict[tuple[str, AssetType], Path]:
        """Return a copy of the currently registered overrides."""
        return dict(self._overrides)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_path(self, entity_id: str, asset_type: AssetType) -> Path:
        subdir, suffix, ext = _ASSET_TEMPLATE[asset_type]
        filename = f"{entity_id}{suffix}{ext}"
        return self._base / subdir / filename
