"""Bundled data file loaders for TI4 game components.

All functions return cached results after the first call.  Each ``fetch_*``
function is a thin public wrapper around a ``@functools.cache``-decorated
implementation so that the cache can be bypassed in tests if needed.

Included loaders
----------------
* :func:`fetch_tech_names` / :func:`fetch_action_tech_names` — technology alias→name maps
* :func:`fetch_objective_data` — full objective records
* :func:`fetch_leader_data` — faction leader records
* :func:`fetch_system_data` / :func:`fetch_planet_data` / :func:`fetch_attachment_data`
* :func:`fetch_unit_data` — :class:`~ti4_rules_engine.models.unit.Unit` objects,
  optionally overridden with faction-specific stats
* :func:`_build_ship_move_map` / :func:`_build_ship_capacity_map` — derived lookups
  built from a unit registry
"""

from __future__ import annotations

import functools
import json
import pathlib
import sys
from typing import Any

from ti4_rules_engine.models.unit import Unit, UnitType

# ---------------------------------------------------------------------------
# Data file paths
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ASYNCTI4_SUBMODULE_ROOT = _REPO_ROOT / "data" / "TI4_map_generator_bot"
_ASYNCTI4_RESOURCES_DIR = _ASYNCTI4_SUBMODULE_ROOT / "src" / "main" / "resources"
_DATA_DIR = _ASYNCTI4_RESOURCES_DIR / "data"
_ASYNCTI4_DATA_DIR = _ASYNCTI4_RESOURCES_DIR
_TECH_DATA_DIR = _DATA_DIR / "technologies"
_PUBLIC_OBJECTIVES_DATA_DIR = _DATA_DIR / "public_objectives"
_LEADERS_DATA_DIR = _DATA_DIR / "leaders"
_UNITS_DATA_DIR = _DATA_DIR / "units"
_ASYNCTI4_ATTACHMENTS_DATA_DIR = _DATA_DIR / "attachments"
_ASYNCTI4_PLANETS_DATA_DIR = _ASYNCTI4_RESOURCES_DIR / "planets"
_ASYNCTI4_SYSTEMS_DATA_DIR = _ASYNCTI4_RESOURCES_DIR / "systems"
_TECH_DATA_FILE = _TECH_DATA_DIR
_PUBLIC_OBJECTIVES_DATA_FILE = _PUBLIC_OBJECTIVES_DATA_DIR
_LEADERS_DATA_FILE = _LEADERS_DATA_DIR

# Tech alias used by Fighter II upgrade detection
_FIGHTER_II_TECH_ID = "ff2"


def _load_json_records_from_dir(data_dir: pathlib.Path) -> list[dict[str, Any]]:
    """Return dict records from all ``*.json`` files in *data_dir*."""
    records: list[dict[str, Any]] = []
    try:
        files = sorted(data_dir.glob("*.json"))
    except OSError:
        return records
    for path in files:
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            records.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            records.append(data)
    return records

# ---------------------------------------------------------------------------
# Technology loaders
# ---------------------------------------------------------------------------


def fetch_tech_names() -> dict[str, str]:
    """Load alias→full-name mapping for all technologies from the bundled data file.

    Returns a dict mapping the short alias used in game exports (e.g. ``"amd"``)
    to the full display name (e.g. ``"Antimass Deflectors"``).  The data is
    ported from the AsyncTI4 bot and stored in ``data/technologies/*.json``.
    Falls back to an empty dict if the file cannot be read.
    Results are cached after the first call.
    """
    return _load_tech_names_cached()


def _has_fighter_ii(researched_techs: list[str]) -> bool:
    """Return ``True`` if the player's researched techs include any Fighter II upgrade."""
    fighter_ii_aliases = _load_fighter_ii_aliases_cached()
    return any(t in fighter_ii_aliases for t in (researched_techs or []))


@functools.cache
def _load_fighter_ii_aliases_cached() -> frozenset[str]:
    """Return all technology aliases that represent Fighter II upgrades."""
    try:
        techs = _load_json_records_from_dir(_TECH_DATA_DIR)
        aliases = {
            t["alias"]
            for t in techs
            if isinstance(t, dict)
            and "alias" in t
            and (
                t.get("alias") == _FIGHTER_II_TECH_ID
                or t.get("baseUpgrade") == _FIGHTER_II_TECH_ID
            )
        }
        aliases.add(_FIGHTER_II_TECH_ID)
        return frozenset(aliases)
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return frozenset({_FIGHTER_II_TECH_ID})


@functools.cache
def _load_tech_names_cached() -> dict[str, str]:
    """Cached implementation of :func:`fetch_tech_names`."""
    try:
        techs = _load_json_records_from_dir(_TECH_DATA_DIR)
        return {
            t["alias"]: t["name"]
            for t in techs
            if isinstance(t, dict) and "alias" in t and "name" in t
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            f"Warning: could not load tech names from {_TECH_DATA_DIR} ({exc!r}); "
            "showing raw tech aliases.",
            file=sys.stderr,
        )
        return {}


def fetch_action_tech_names() -> dict[str, str]:
    """Return alias→name for technologies that have an ACTION-timing ability.

    Parses ``data/technologies/*.json`` and returns entries whose ``text`` field
    contains ``"ACTION:"`` (case-sensitive), indicating the technology can be
    used as a component action.
    """
    return _load_action_tech_names_cached()


@functools.cache
def _load_action_tech_names_cached() -> dict[str, str]:
    """Cached implementation of :func:`fetch_action_tech_names`."""
    try:
        techs = _load_json_records_from_dir(_TECH_DATA_DIR)
        return {
            t["alias"]: t["name"]
            for t in techs
            if isinstance(t, dict)
            and "alias" in t
            and "name" in t
            and "ACTION:" in t.get("text", "")
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Objective loaders
# ---------------------------------------------------------------------------


def fetch_objective_data() -> dict[str, dict[str, Any]]:
    """Load full objective data from the bundled data file.

    Returns a dict mapping objective ID (e.g. ``"expand_borders"``) to the full
    objective record. Data is loaded from ``data/public_objectives/*.json``
    (ported from the AsyncTI4 bot).
    Falls back to an empty dict if the file cannot be read.
    Results are cached after the first call.
    """
    return _load_objective_data_cached()


@functools.cache
def _load_objective_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_objective_data`."""
    objective_data: dict[str, dict[str, Any]] = {}
    try:
        public_objectives = _load_json_records_from_dir(_PUBLIC_OBJECTIVES_DATA_DIR)
        for obj in public_objectives:
            if not isinstance(obj, dict):
                continue
            alias = obj.get("alias")
            if not alias:
                continue
            text = obj.get("text")
            notes = obj.get("notes")
            description = text
            if text and notes:
                description = f"{text} Note: {notes}"
            public_entry: dict[str, Any] = {
                "id": alias,
                "name": obj.get("name", alias),
                "points": obj.get("points"),
                "description": description,
                "source": obj.get("source"),
            }
            if obj.get("points") == 1:
                public_entry["type"] = "stage_1"
            elif obj.get("points") == 2:
                public_entry["type"] = "stage_2"
            else:
                public_entry["type"] = "public"
            objective_data[alias] = public_entry
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            "Warning: could not load objective data from "
            f"{_PUBLIC_OBJECTIVES_DATA_DIR} ({exc!r}); "
            "showing raw objective IDs.",
            file=sys.stderr,
        )

    if objective_data:
        return objective_data
    return {}


def _get_objective_condition_text(obj: dict[str, Any]) -> str:
    """Return the best available condition text for an objective record."""
    return str(
        obj.get("description")
        or obj.get("condition")
        or obj.get("text")
        or ""
    )


def _get_objective_stage_label(obj: dict[str, Any]) -> str:
    """Infer a human-readable stage label from objective metadata."""
    obj_type = obj.get("type")
    points = obj.get("points")
    if obj_type == "stage_1" or points == 1:
        return "Stage I"
    if obj_type == "stage_2" or points == 2:
        return "Stage II"
    return "Public"


def _format_objective(obj_id: str, obj_data: dict[str, dict[str, Any]]) -> str:
    """Return a display string for an objective with score and condition text."""
    if obj_id not in obj_data:
        return obj_id
    rec = obj_data[obj_id]
    name = rec.get("name", obj_id)
    desc = _get_objective_condition_text(rec)
    pts = rec.get("points", "")
    pt_str = f" [{pts}VP]" if pts else ""
    if desc:
        return f"{name}{pt_str} — {desc}"
    return f"{name}{pt_str}"


# ---------------------------------------------------------------------------
# Leader loader
# ---------------------------------------------------------------------------


def fetch_leader_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of leader id → leader record from ``data/leaders/*.json``.

    Each record contains at minimum: ``id``, ``faction``, ``type``, ``name``,
    ``title``, ``abilityWindow``, and ``source``.
    """
    return _load_leader_data_cached()


@functools.cache
def _load_leader_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_leader_data`."""
    try:
        leaders = _load_json_records_from_dir(_LEADERS_DATA_DIR)
        return {
            entry["id"]: entry
            for entry in leaders
            if isinstance(entry, dict) and "id" in entry
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# System / planet / attachment loaders
# ---------------------------------------------------------------------------


def fetch_system_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of system-tile ID → system metadata record."""
    return _load_system_data_cached()


def fetch_planet_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of planet ID → planet metadata record."""
    return _load_planet_data_cached()


def fetch_attachment_data() -> dict[str, dict[str, Any]]:
    """Return a mapping of attachment/token ID → attachment metadata record."""
    return _load_attachment_data_cached()


@functools.cache
def _load_system_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_system_data`."""
    systems: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_SYSTEMS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "id" in data:
                systems[str(data["id"])] = data
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return systems


@functools.cache
def _load_planet_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_planet_data`."""
    planets: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_PLANETS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "id" in data:
                planets[str(data["id"])] = data
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return planets


@functools.cache
def _load_attachment_data_cached() -> dict[str, dict[str, Any]]:
    """Cached implementation of :func:`fetch_attachment_data`."""
    attachments: dict[str, dict[str, Any]] = {}
    try:
        for path in sorted(_ASYNCTI4_ATTACHMENTS_DATA_DIR.glob("*.json")):
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "id" in item:
                        attachments[str(item["id"])] = item
            elif isinstance(data, dict) and "id" in data:
                attachments[str(data["id"])] = data
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return {}
    return attachments


# ---------------------------------------------------------------------------
# Unit loaders
# ---------------------------------------------------------------------------

# Mapping from asyncti4 baseType → UnitType enum value.
_BASE_TYPE_TO_UNIT_TYPE: dict[str, UnitType] = {
    "carrier": UnitType.CARRIER,
    "cruiser": UnitType.CRUISER,
    "destroyer": UnitType.DESTROYER,
    "dreadnought": UnitType.DREADNOUGHT,
    "flagship": UnitType.FLAGSHIP,
    "warsun": UnitType.WAR_SUN,
    "fighter": UnitType.FIGHTER,
    "infantry": UnitType.GROUND_FORCE,
    "mech": UnitType.MECH,
    "pds": UnitType.PDS,
    "spacedock": UnitType.SPACE_DOCK,
}


def _asyncti4_unit_to_model(entry: dict[str, Any]) -> Unit | None:
    """Convert an asyncti4 unit JSON entry to a :class:`Unit` model.

    Returns ``None`` for entries whose ``baseType`` is not recognised or that
    lack an ``asyncId`` field.
    """
    base_type = entry.get("baseType", "")
    unit_type = _BASE_TYPE_TO_UNIT_TYPE.get(base_type)
    if unit_type is None:
        return None
    async_id = entry.get("asyncId")
    if not async_id:
        return None
    combat_hits_on = entry.get("combatHitsOn")
    return Unit(
        id=entry.get("id", async_id),
        name=entry.get("name", async_id),
        unit_type=unit_type,
        cost=entry.get("cost"),
        combat=combat_hits_on if isinstance(combat_hits_on, int) else None,
        combat_rolls=entry.get("combatDieCount", 1) or 1,
        move=entry.get("moveValue"),
        capacity=entry.get("capacityValue", 0),
        sustain_damage=bool(entry.get("sustainDamage", False)),
        planetary_shield=bool(entry.get("planetaryShield", False)),
        bombardment=entry.get("bombardHitsOn"),
        bombardment_rolls=entry.get("bombardDieCount", 1) or 1,
        space_cannon=entry.get("spaceCannonHitsOn"),
        space_cannon_rolls=entry.get("spaceCannonDieCount", 1) or 1,
    )


def fetch_unit_data(faction: str | None = None) -> dict[str, Unit]:
    """Return a mapping of asyncId → :class:`Unit` built from the bundled data files.

    Loads ``data/units/baseUnits.json`` for the standard units.  If *faction*
    is provided, also loads ``data/units/pok.json`` and applies any faction-
    specific unit overrides (e.g. Titans' cruiser with capacity).

    The returned dict is keyed by ``asyncId`` (e.g. ``"cv"``, ``"dd"``).
    Where a faction has a variant of a unit type that differs from the base
    stats, the faction variant takes precedence.
    """
    return _load_unit_data_cached(faction)


@functools.cache
def _load_unit_data_cached(faction: str | None = None) -> dict[str, Unit]:
    """Cached implementation of :func:`fetch_unit_data`."""
    units: dict[str, Unit] = {}

    # 1. Load base units (shared by all factions).
    try:
        base_file = _UNITS_DATA_DIR / "baseUnits.json"
        with base_file.open(encoding="utf-8") as fh:
            base_entries: list[dict[str, Any]] = json.load(fh)
        for entry in base_entries:
            model = _asyncti4_unit_to_model(entry)
            if model is None:
                continue
            async_id = entry["asyncId"]
            # Only keep the base (non-upgraded) variant as the default – it
            # has no "upgradesFromUnitId" field.
            if "upgradesFromUnitId" not in entry:
                units[async_id] = model
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass

    # 2. Apply faction-specific overrides when requested.
    if faction:
        try:
            pok_file = _UNITS_DATA_DIR / "pok.json"
            with pok_file.open(encoding="utf-8") as fh:
                pok_entries: list[dict[str, Any]] = json.load(fh)
            for entry in pok_entries:
                if entry.get("faction") != faction:
                    continue
                if "upgradesFromUnitId" in entry:
                    # Upgraded variants are not the unit's default stats.
                    continue
                model = _asyncti4_unit_to_model(entry)
                if model is None:
                    continue
                async_id = entry["asyncId"]
                units[async_id] = model
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            pass

    # Add "cr" as an alias for "ca" (cruiser) – some AsyncTI4 exports use
    # "cr" as the entity ID for cruisers.
    if "ca" in units and "cr" not in units:
        units["cr"] = units["ca"]

    return units


# ---------------------------------------------------------------------------
# Derived unit lookups
# ---------------------------------------------------------------------------


def _build_ship_move_map(unit_data: dict[str, Unit]) -> dict[str, int]:
    """Build a move-value lookup from a unit registry.

    Only ships (units with a move value) are included; fighters are excluded
    as they are transported rather than self-propelled.
    """
    fighter_type = UnitType.FIGHTER
    return {
        async_id: unit.move
        for async_id, unit in unit_data.items()
        if unit.move is not None and unit.unit_type is not fighter_type
    }


def _build_ship_capacity_map(unit_data: dict[str, Unit]) -> dict[str, int]:
    """Build a capacity-value lookup (transport slots) from a unit registry."""
    return {async_id: unit.capacity for async_id, unit in unit_data.items()}
