"""Tests for the AssetMapper utility."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.asset_mapping import AssetMapper, AssetType


class TestAssetMapper:
    def test_resolve_faction_icon(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("jol_nar", AssetType.FACTION_ICON)
        assert path == Path("/assets/ti4/factions/jol_nar_icon.png")

    def test_resolve_faction_token(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("jol_nar", AssetType.FACTION_TOKEN)
        assert path == Path("/assets/ti4/factions/jol_nar_token.png")

    def test_resolve_faction_sheet(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("jol_nar", AssetType.FACTION_SHEET)
        assert path == Path("/assets/ti4/factions/jol_nar_sheet.png")

    def test_resolve_unit_image(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("carrier", AssetType.UNIT_IMAGE)
        assert path == Path("/assets/ti4/units/carrier.png")

    def test_resolve_system_tile(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("18", AssetType.SYSTEM_TILE)
        assert path == Path("/assets/ti4/tiles/18_tile.png")

    def test_resolve_technology_card(self) -> None:
        mapper = AssetMapper(base_path="/assets/ti4")
        path = mapper.resolve("neural_motivator", AssetType.TECHNOLOGY_CARD)
        assert path == Path("/assets/ti4/technologies/neural_motivator_tech.png")

    def test_resolve_planet_image(self) -> None:
        mapper = AssetMapper(base_path="/assets")
        path = mapper.resolve("mecatol_rex", AssetType.PLANET_IMAGE)
        assert path == Path("/assets/planets/mecatol_rex.png")

    def test_override_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom_creuss.png"
        custom.touch()

        mapper = AssetMapper(base_path="/assets/ti4")
        mapper.register_override("ghosts_of_creuss", AssetType.FACTION_ICON, custom)
        path = mapper.resolve("ghosts_of_creuss", AssetType.FACTION_ICON)
        assert path == custom

    def test_verify_exists_raises(self) -> None:
        mapper = AssetMapper(base_path="/nonexistent", verify_exists=True)
        with pytest.raises(FileNotFoundError):
            mapper.resolve("jol_nar", AssetType.FACTION_ICON)

    def test_verify_exists_passes(self, tmp_path: Path) -> None:
        (tmp_path / "factions").mkdir()
        icon = tmp_path / "factions" / "jol_nar_icon.png"
        icon.touch()

        mapper = AssetMapper(base_path=tmp_path, verify_exists=True)
        path = mapper.resolve("jol_nar", AssetType.FACTION_ICON)
        assert path == icon

    def test_all_overrides_empty(self) -> None:
        mapper = AssetMapper()
        assert mapper.all_overrides() == {}

    def test_all_overrides_populated(self) -> None:
        mapper = AssetMapper()
        mapper.register_override("x", AssetType.UNIT_IMAGE, "/tmp/x.png")
        overrides = mapper.all_overrides()
        assert ("x", AssetType.UNIT_IMAGE) in overrides
