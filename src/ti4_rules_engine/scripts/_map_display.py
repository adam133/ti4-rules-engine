"""Map display helpers for the TI4 game analysis output.

Formats per-tile and per-planet information drawn from the AsyncTI4 data files
and the in-game state into human-readable output lines.

Public entry point: :func:`_build_full_map_lines`.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from ti4_rules_engine.scripts._data_loaders import (
    fetch_attachment_data,
    fetch_planet_data,
    fetch_system_data,
)
from ti4_rules_engine.scripts._fleet_movement import _UNIT_NAMES

if TYPE_CHECKING:
    from ti4_rules_engine.models.state import GameState


def _get_planet_ri(
    tile_unit_data: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract per-planet static data from *tileUnitData*.

    Returns a dict ``{planet_id: {"resources": int, "influence": int}}``
    built from the planet entries embedded in each tile's data.  Only planets
    with non-null ``resources`` and ``influence`` fields are included.
    """
    planet_ri: dict[str, dict[str, Any]] = {}
    for tile_data in tile_unit_data.values():
        for pid, pdata in (tile_data.get("planets") or {}).items():
            if not isinstance(pdata, dict):
                continue
            res = pdata.get("resources")
            inf = pdata.get("influence")
            if res is not None and inf is not None:
                planet_ri[pid] = {"resources": int(res), "influence": int(inf)}
    return planet_ri


def _tile_position_sort_key(pos: str) -> tuple[int, int, str]:
    """Sort numeric map positions first by integer value.

    Non-numeric position strings are sorted alphabetically after numeric ones.
    """
    try:
        pos_int = int(pos)
        return (0, pos_int, "")
    except ValueError:
        return (1, 0, pos)


def _format_entity_display_name(entity_id: str, entity_type: str) -> str:
    """Return a human-readable display name for a tile entity."""
    if entity_type == "unit":
        return _UNIT_NAMES.get(entity_id, entity_id)
    attachment_data = fetch_attachment_data()
    if entity_id in attachment_data:
        return str(attachment_data[entity_id].get("name", entity_id))
    return entity_id.replace("_", " ")


def _format_modifier(modifier: int, label: str) -> str:
    """Return a signed modifier label, e.g. ``'+2 resources'``."""
    return f"{modifier:+d} {label}"


def _describe_attachment_effect(entity_id: str) -> str | None:
    """Return a concise effect description for an attachment/token if known."""
    special_tokens = {
        "frontier": "explore token when this system is activated",
        "custodian": "must spend 6 influence to remove this token and score 1 VP",
    }
    if entity_id in special_tokens:
        return special_tokens[entity_id]

    rec = fetch_attachment_data().get(entity_id)
    if not isinstance(rec, dict):
        return None

    effects: list[str] = []
    res_mod = rec.get("resourcesModifier")
    inf_mod = rec.get("influenceModifier")
    if isinstance(res_mod, int) and res_mod != 0:
        effects.append(_format_modifier(res_mod, "resources"))
    if isinstance(inf_mod, int) and inf_mod != 0:
        effects.append(_format_modifier(inf_mod, "influence"))

    tech_specs = rec.get("techSpeciality")
    if isinstance(tech_specs, list) and tech_specs:
        effects.append("adds tech specialty: " + ", ".join(str(s) for s in tech_specs))

    planet_types = rec.get("planetTypes")
    if isinstance(planet_types, list) and planet_types:
        effects.append("planet trait becomes: " + ", ".join(str(p) for p in planet_types))

    if rec.get("isLegendary"):
        effects.append("planet becomes legendary")

    die_count = rec.get("spaceCannonDieCount")
    hits_on = rec.get("spaceCannonHitsOn")
    if isinstance(die_count, int) and isinstance(hits_on, int):
        effects.append(f"grants SPACE CANNON {hits_on} (x{die_count})")

    if not effects:
        return "special attachment effect"
    return "; ".join(effects)


def _summarise_entity_list(entities: list[dict[str, Any]]) -> list[str]:
    """Return sorted ``"<name> x<count>"`` labels for units/tokens in *entities*."""
    counts: Counter[str] = Counter()
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        entity_type = str(entry.get("entityType", ""))
        entity_id = str(entry.get("entityId", ""))
        if not entity_id:
            continue
        raw_count = entry.get("count", 1)
        count = raw_count if isinstance(raw_count, int) else 1
        name = _format_entity_display_name(entity_id, entity_type)
        if entity_type != "unit":
            effect = _describe_attachment_effect(entity_id)
            if effect:
                name = f"{name} ({effect})"
        counts[name] += count
    return [
        name if count == 1 else f"{name} x{count}"
        for name, count in sorted(counts.items())
    ]


def _format_system_label(tile_id: str | None) -> str | None:
    """Return the display label for a tile ID, preferring the system name."""
    if not tile_id:
        return None
    rec = fetch_system_data().get(tile_id)
    if isinstance(rec, dict) and rec.get("name"):
        return str(rec["name"])
    return f"tile {tile_id}"


def _format_system_static_details(tile_id: str | None) -> list[str]:
    """Return static descriptors for a system tile (anomalies/wormholes/stations)."""
    if not tile_id:
        return []
    rec = fetch_system_data().get(tile_id)
    if not isinstance(rec, dict):
        return []

    details: list[str] = []
    anomalies: list[str] = []
    for key, name in (
        ("isSupernova", "supernova"),
        ("isAsteroidField", "asteroid field"),
        ("isNebula", "nebula"),
        ("isGravityRift", "gravity rift"),
    ):
        if rec.get(key):
            anomalies.append(name)
    if anomalies:
        details.append("anomalies: " + ", ".join(anomalies))

    wormholes = rec.get("wormholes")
    if isinstance(wormholes, list) and wormholes:
        details.append("wormholes: " + ", ".join(str(w).lower() for w in wormholes))

    station_planets = [
        p for p in rec.get("planets", [])
        if isinstance(p, str) and "station" in p.lower()
    ]
    if station_planets:
        details.append("trade stations: " + ", ".join(sorted(station_planets)))
    return details


def _format_planet_metadata(planet_id: str) -> str | None:
    """Return static planet metadata string (name, base R/I, legendary text)."""
    rec = fetch_planet_data().get(planet_id)
    if not isinstance(rec, dict):
        return None
    name = str(rec.get("name", planet_id))
    resources = rec.get("resources")
    influence = rec.get("influence")
    parts = [name]
    if isinstance(resources, int) and isinstance(influence, int):
        parts.append(f"R{resources}/I{influence}")
    legendary_name = rec.get("legendaryAbilityName")
    legendary_text = rec.get("legendaryAbilityText")
    if legendary_name and legendary_text:
        parts.append(f"legendary: {legendary_name} — {legendary_text}")
    return " | ".join(parts)


def _build_full_map_lines(state: GameState) -> list[str]:
    """Return printable lines describing every tile and its current units/tokens."""
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    tile_positions: dict[str, str] = state.extra.get("tile_positions", {})
    if not tile_unit_data:
        return []

    lines: list[str] = []
    for pos in sorted(tile_unit_data, key=_tile_position_sort_key):
        tile_data = tile_unit_data.get(pos) or {}
        tile_id = tile_positions.get(pos)
        tile_label = _format_system_label(tile_id)
        label = f"{pos} ({tile_label})" if tile_label else pos
        lines.append(f"    {label}:")

        details: list[str] = []
        details.extend(_format_system_static_details(tile_id))
        ccs = tile_data.get("ccs") or []
        if ccs:
            details.append(f"CCs: {', '.join(sorted(str(cc) for cc in ccs))}")

        space = tile_data.get("space") or {}
        if isinstance(space, dict):
            for fac in sorted(space):
                ents = space.get(fac)
                if isinstance(ents, list):
                    labels = _summarise_entity_list(ents)
                    if labels:
                        details.append(f"space/{fac}: {', '.join(labels)}")

        planets = tile_data.get("planets") or {}
        if isinstance(planets, dict):
            for planet_id in sorted(planets):
                pdata = planets.get(planet_id)
                if not isinstance(pdata, dict):
                    continue
                entities = pdata.get("entities") or {}
                if not isinstance(entities, dict):
                    continue
                for fac in sorted(entities):
                    ents = entities.get(fac)
                    if isinstance(ents, list):
                        labels = _summarise_entity_list(ents)
                        if labels:
                            planet_meta = _format_planet_metadata(planet_id)
                            planet_label = (
                                f"{planet_id} ({planet_meta})" if planet_meta else planet_id
                            )
                            details.append(
                                f"planet/{planet_label}/{fac}: {', '.join(labels)}"
                            )

        if details:
            lines.extend([f"      - {d}" for d in details])
        else:
            lines.append("      - (no units/tokens)")

    return lines
