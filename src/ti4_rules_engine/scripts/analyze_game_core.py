"""Core hub for TI4 game analysis.

For CLI usage, run ``ti4_rules_engine.scripts.analyze_game`` (or the installed
``ti4-analyze`` entrypoint), which wraps this module.

Usage::

    python scripts/analyze_game.py <game_number>

Example::

    python scripts/analyze_game.py pbd22295

Game data is fetched from::

    https://bot.asyncti4.com/api/public/game/{game}/web-data

Implementation is split across focused sub-modules:

* :mod:`._hex_grid`        — hex position arithmetic
* :mod:`._tile_catalog`    — static tile type data and hyperlane tile detection
* :mod:`._hyperlanes`      — hyperlane adjacency building
* :mod:`._data_loaders`    — all bundled data file loaders
* :mod:`._fleet_movement`  — fleet helpers, BFS, combat, tactical reach
* :mod:`._map_display`     — map formatting helpers

This module provides the output layer (game/player summary printing and main).
All symbols from the sub-modules are re-exported here to preserve the existing
import surface used by external consumers and tests.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from typing import TYPE_CHECKING, Any
from urllib.error import URLError

from ti4_rules_engine.adapters.asyncti4 import from_asyncti4
from ti4_rules_engine.engine.options import get_player_options
from ti4_rules_engine.scripts._data_loaders import (  # noqa: F401
    _ASYNCTI4_ATTACHMENTS_DATA_DIR,
    _ASYNCTI4_DATA_DIR,
    _ASYNCTI4_PLANETS_DATA_DIR,
    _ASYNCTI4_SYSTEMS_DATA_DIR,
    _BASE_TYPE_TO_UNIT_TYPE,
    _DATA_DIR,
    _FIGHTER_II_TECH_ID,
    _LEADERS_DATA_FILE,
    _PUBLIC_OBJECTIVES_DATA_FILE,
    _TECH_DATA_FILE,
    _UNITS_DATA_DIR,
    _asyncti4_unit_to_model,
    _build_ship_capacity_map,
    _build_ship_move_map,
    _format_objective,
    _get_objective_condition_text,
    _get_objective_stage_label,
    _has_fighter_ii,
    _load_action_tech_names_cached,
    _load_attachment_data_cached,
    _load_fighter_ii_aliases_cached,
    _load_leader_data_cached,
    _load_objective_data_cached,
    _load_planet_data_cached,
    _load_system_data_cached,
    _load_tech_names_cached,
    _load_unit_data_cached,
    fetch_action_tech_names,
    fetch_attachment_data,
    fetch_leader_data,
    fetch_objective_data,
    fetch_planet_data,
    fetch_system_data,
    fetch_tech_names,
    fetch_unit_data,
)
from ti4_rules_engine.scripts._fleet_movement import (  # noqa: F401
    _COMBAT_UNITS,
    _DEFAULT_SPACE_DOCK_FIGHTER_CAPACITY,
    _FIGHTER_ENTITY_ID,
    _FIGHTER_II_MOVE_SPEED,
    _GROUND_FORCE_IDS,
    _SHIP_CAPACITY,
    _SHIP_MOVE,
    _SPACE_DOCK_ENTITY_ID,
    _TRANSPORTED_UNITS,
    _UNIT_NAMES,
    _bfs,
    _build_combat_group,
    _compute_starting_transport_payload,
    _count_units_by_entity_id,
    _fighter_excess_count_for_movement,
    _fleet_capacity,
    _fleet_move_value,
    _format_combat_result,
    _get_reach_info,
    _get_tactical_reach,
    _ground_forces_in_space,
    _ground_forces_on_planets,
    _iter_fleet_movement_variants,
    _space_dock_fighter_capacity_in_tile,
    _summarise_ground_forces,
    _summarise_transportable_units,
    _summarise_units,
    get_reachable_systems,
)

# ---------------------------------------------------------------------------
# Sub-module re-exports (preserve the legacy import surface)
# ---------------------------------------------------------------------------
from ti4_rules_engine.scripts._hex_grid import (  # noqa: F401
    _make_tile_str,
    get_adjacent_positions,
)
from ti4_rules_engine.scripts._hyperlanes import (  # noqa: F401
    _MIN_HYPERLANE_NEIGHBORS_FOR_FALLBACK,
    _build_hyperlane_adjacency,
    _build_movement_context,
    _load_hyperlane_connections,
)
from ti4_rules_engine.scripts._map_display import (  # noqa: F401
    _build_full_map_lines,
    _describe_attachment_effect,
    _format_entity_display_name,
    _format_modifier,
    _format_planet_metadata,
    _format_system_label,
    _format_system_static_details,
    _get_planet_ri,
    _summarise_entity_list,
    _tile_position_sort_key,
)
from ti4_rules_engine.scripts._tile_catalog import (  # noqa: F401
    _HYPERLANE_ID_RE,
    _TILE_CATALOG,
    _is_hyperlane_tile_id,
)

if TYPE_CHECKING:
    from ti4_rules_engine.models.state import GameState

WEB_DATA_URL_TEMPLATE = "https://bot.asyncti4.com/api/public/game/{game}/web-data"

_STRATEGY_CARD_DATA_BY_INITIATIVE: dict[int, dict[str, str]] = {
    1: {
        "name": "Leadership",
        "primary": "Gain 3 command tokens. Then spend influence to gain additional command tokens.",
        "secondary": "Spend 1 strategy token to gain 1 command token.",
    },
    2: {
        "name": "Diplomacy",
        "primary": "Choose 1 system and ready all planets you control in that system.",
        "secondary": "Spend 1 strategy token to ready up to 2 exhausted planets you control.",
    },
    3: {
        "name": "Politics",
        "primary": "Choose another player to gain the speaker token. Draw 2 action cards.",
        "secondary": "Spend 1 strategy token to draw 2 action cards.",
    },
    4: {
        "name": "Construction",
        "primary": "Place 1 space dock and 1 PDS on planets you control.",
        "secondary": (
            "Spend 1 strategy token to place either 1 space dock or 1 PDS on a planet you control."
        ),
    },
    5: {
        "name": "Trade",
        "primary": "Gain 3 trade goods and replenish commodities for all players.",
        "secondary": "Spend 1 strategy token to replenish your commodities.",
    },
    6: {
        "name": "Warfare",
        "primary": "Remove 1 command token from the game board; then redistribute command tokens.",
        "secondary": "Spend 1 strategy token to use production in your home system.",
    },
    7: {
        "name": "Technology",
        "primary": "Research 1 technology.",
        "secondary": "Spend 1 strategy token and 6 resources to research 1 technology.",
    },
    8: {
        "name": "Imperial",
        "primary": (
            "Score 1 public objective if possible; if you control Mecatol Rex, "
            "gain 1 victory point."
        ),
        "secondary": "Spend 1 strategy token to draw 1 secret objective.",
    },
}
_UNKNOWN_INITIATIVE_SORT_KEY = 99

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def fetch_game_json(game_number: str) -> dict:
    """Download the game snapshot JSON from the asyncti4 bot web-data API."""
    url = WEB_DATA_URL_TEMPLATE.format(game=game_number)
    print(f"Fetching game data from: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except URLError as exc:
        print(f"ERROR: Failed to fetch game data – {exc}", file=sys.stderr)
        sys.exit(1)
    return json.loads(raw)


def _parse_strategy_card_initiative(card_id: str) -> int | None:
    """Extract initiative from strategy-card IDs such as '3' or 'pok3politics'."""
    if card_id.isdigit():
        initiative = int(card_id)
        return initiative if 1 <= initiative <= 8 else None
    match = re.search(r"(\d+)", card_id)
    if not match:
        return None
    initiative = int(match.group(1))
    return initiative if 1 <= initiative <= 8 else None


def _strategy_card_details(card_id: str) -> dict[str, Any]:
    """Return display metadata for a strategy card ID."""
    initiative = _parse_strategy_card_initiative(card_id)
    card = _STRATEGY_CARD_DATA_BY_INITIATIVE.get(initiative, {})
    return {
        "initiative": initiative,
        "name": card.get("name", card_id),
        "primary": card.get("primary", "(ability text unavailable)"),
        "secondary": card.get("secondary", "(ability text unavailable)"),
    }


def _build_turn_order_tracker(state: GameState) -> list[dict[str, Any]]:
    """Build a turn tracker sorted by lowest held strategy-card initiative."""
    speaker_id = state.turn_order.speaker_id
    entries: list[dict[str, Any]] = []
    for player_id in state.turn_order.order:
        player = state.players.get(player_id)
        if not player:
            continue
        initiatives = [
            i
            for i in (_parse_strategy_card_initiative(cid) for cid in player.strategy_card_ids)
            if i is not None
        ]
        if not initiatives:
            continue
        lowest = min(initiatives)
        details = _strategy_card_details(str(lowest))
        entries.append(
            {
                "player_id": player_id,
                "initiative": lowest,
                "card_name": details["name"],
                "is_speaker": player_id == speaker_id,
            }
        )
    entries.sort(key=lambda e: e["initiative"])
    return entries


def print_game_summary(state: GameState) -> None:
    """Print a human-readable summary of the game state."""
    # Merge bundled objective data with API-provided data while preserving
    # bundled condition text when API data omits descriptions.
    obj_data = fetch_objective_data().copy()
    for obj_id, api_rec in state.extra.get("objective_data", {}).items():
        if not isinstance(api_rec, dict):
            continue
        merged = dict(obj_data.get(obj_id, {}))
        merged.update(api_rec)
        if not _get_objective_condition_text(merged):
            bundled_desc = _get_objective_condition_text(obj_data.get(obj_id, {}))
            if bundled_desc:
                merged["description"] = bundled_desc
        obj_data[obj_id] = merged

    print()
    print("=" * 60)
    print(f"  Game:   {state.game_id}")
    print(f"  Round:  {state.round_number}")
    print(f"  Phase:  {state.phase.upper()}")
    if state.active_player_id:
        print(f"  Active: {state.active_player_id}")
    print(f"  Speaker: {state.turn_order.speaker_id}")
    if state.law_ids:
        print(f"  Laws in play: {', '.join(state.law_ids)}")
    tracker = _build_turn_order_tracker(state)
    if tracker:
        print("  Turn order tracker (lowest→highest initiative):")
        for entry in tracker:
            speaker_marker = " [SPEAKER]" if entry["is_speaker"] else ""
            print(
                f"    {entry['initiative']}: {entry['player_id']}"
                f" — {entry['card_name']}{speaker_marker}"
            )

    # --- Revealed public objectives ---
    if state.public_objectives:
        print()
        print("  PUBLIC OBJECTIVES (revealed):")
        for obj_id in state.public_objectives:
            rec = obj_data.get(obj_id)
            if rec:
                stage = _get_objective_stage_label(rec)
                pts = rec.get("points", "?")
                name = rec.get("name", obj_id)
                desc = _get_objective_condition_text(rec)
                print(f"    [{stage}, {pts}VP] {name}")
                if desc:
                    print(f"      {desc}")
            else:
                print(f"    {obj_id}")

    full_map_lines = _build_full_map_lines(state)
    if full_map_lines:
        print()
        print("  FULL MAP (tiles, units, tokens):")
        for line in full_map_lines:
            print(line)

    print("=" * 60)


def _get_leader_type(leader: dict[str, Any]) -> str:
    """Infer leader type (agent/commander/hero) from the leader dict."""
    if "type" in leader:
        return str(leader["type"]).lower()
    # Fall back to inferring from the ID suffix
    lid = str(leader.get("id", "")).lower()
    for suffix in ("agent", "commander", "hero"):
        if lid.endswith(suffix):
            return suffix
    return "leader"


def _format_leader(leader: dict[str, Any]) -> str:
    """Return a display string for a leader card with status indicators."""
    lid = str(leader.get("id", "unknown"))
    ltype = _get_leader_type(leader).capitalize()
    exhausted = leader.get("exhausted", False)
    locked = leader.get("locked", False)
    if locked:
        status = "LOCKED"
    elif exhausted:
        status = "exhausted"
    else:
        status = "READY"
    return f"{lid} ({ltype}) [{status}]"


def print_player_summary(state: GameState, player_options_map: dict) -> None:
    """Print per-player details and available actions."""
    from ti4_rules_engine.engine.options import PlayerAction

    tech_names = fetch_tech_names()
    action_techs = fetch_action_tech_names()
    leader_registry = fetch_leader_data()
    # Merge bundled objective data with API-provided data while preserving
    # bundled condition text when API data omits descriptions.
    obj_data = fetch_objective_data().copy()
    for obj_id, api_rec in state.extra.get("objective_data", {}).items():
        if not isinstance(api_rec, dict):
            continue
        merged = dict(obj_data.get(obj_id, {}))
        merged.update(api_rec)
        if not _get_objective_condition_text(merged):
            bundled_desc = _get_objective_condition_text(obj_data.get(obj_id, {}))
            if bundled_desc:
                merged["description"] = bundled_desc
        obj_data[obj_id] = merged
    tile_unit_data: dict[str, Any] = state.extra.get("tile_unit_data", {})
    planet_ri = _get_planet_ri(tile_unit_data)
    player_leaders: dict[str, list[dict[str, Any]]] = state.extra.get("player_leaders", {})

    print()
    print("  PLAYERS")
    print("  " + "-" * 56)

    for player_id in state.turn_order.order:
        if player_id not in state.players:
            continue
        player = state.players[player_id]
        opts = player_options_map.get(player_id)

        speaker_marker = " [SPEAKER]" if player_id == state.turn_order.speaker_id else ""
        active_marker = " [ACTIVE]" if player_id == state.active_player_id else ""
        passed_marker = " [PASSED]" if player.passed else ""

        print(f"\n  {player_id}{speaker_marker}{active_marker}{passed_marker}")
        print(f"    Faction:  {player.faction_id}")
        print(f"    VP:       {player.victory_points}")
        print(f"    TG:       {player.trade_goods}  |  Commodities: {player.commodities}")
        print(
            f"    Tokens:   {player.tactical_tokens} tactical"
            f" / {player.fleet_tokens} fleet"
            f" / {player.strategy_tokens} strategy"
        )
        print(
            f"    Planets:  {len(player.controlled_planets)} controlled"
            f", {len(player.exhausted_planets)} exhausted"
        )

        # --- Readied planets with resources / influence ---
        exhausted = set(player.exhausted_planets)
        ready_planets = [p for p in player.controlled_planets if p not in exhausted]
        total_ready_res = sum(planet_ri.get(p, {}).get("resources", 0) for p in ready_planets)
        total_ready_inf = sum(planet_ri.get(p, {}).get("influence", 0) for p in ready_planets)
        if ready_planets:
            planet_parts = []
            for p in sorted(ready_planets):
                ri = planet_ri.get(p)
                if ri:
                    planet_parts.append(f"{p} ({ri['resources']}R/{ri['influence']}I)")
                else:
                    planet_parts.append(p)
            print(
                f"    Readied:  {total_ready_res} resources, {total_ready_inf} influence"
                f"  — {', '.join(planet_parts)}"
            )
        else:
            print("    Readied:  0 resources, 0 influence  — (all planets exhausted)")

        # --- Technologies (full names where available) ---
        tech_ids = player.researched_technologies
        if tech_ids:
            tech_display = [tech_names.get(t, t) for t in tech_ids]
            print(f"    Techs:    {', '.join(tech_display)}")
        else:
            print("    Techs:    (none)")

        if player.strategy_card_ids:
            sorted_cards = sorted(
                player.strategy_card_ids,
                key=lambda cid: (
                    _parse_strategy_card_initiative(cid) or _UNKNOWN_INITIATIVE_SORT_KEY,
                    cid,
                ),
            )
            print("    Strategy cards:")
            for card_id in sorted_cards:
                details = _strategy_card_details(card_id)
                initiative = details["initiative"]
                init_suffix = f" ({initiative})" if initiative is not None else ""
                print(f"      • {details['name']}{init_suffix}")
                print(f"        Primary: {details['primary']}")
                print(f"        Secondary: {details['secondary']}")

        # --- Scored objectives (full names + descriptions) ---
        if player.scored_objectives:
            print("    Scored objectives:")
            for obj_id in player.scored_objectives:
                print(f"      • {_format_objective(obj_id, obj_data)}")

        # --- Unscored public objectives + eligibility ---
        if state.public_objectives:
            scored_set = set(player.scored_objectives)
            unscored_public = [oid for oid in state.public_objectives if oid not in scored_set]
            if unscored_public:
                print("    Unscored public objectives:")
                for obj_id in unscored_public:
                    obj_str = _format_objective(obj_id, obj_data)
                    print(f"      ○ {obj_str}")

        # --- Leaders (agents, commanders, heroes) ---
        leaders = player_leaders.get(player_id, [])
        if leaders:
            print("    Leaders:")
            for leader in leaders:
                ltype = _get_leader_type(leader)
                exhausted_flag = leader.get("exhausted", False)
                locked_flag = leader.get("locked", False)
                lid = str(leader.get("id", "unknown"))
                ltype_cap = ltype.capitalize()
                if locked_flag:
                    status = "LOCKED"
                elif exhausted_flag:
                    status = "exhausted"
                else:
                    status = "READY"
                # Show the actual leader name and ability text
                rec = leader_registry.get(lid)
                if rec:
                    name = rec.get("name", lid)
                    ability_text = rec.get("abilityText", "")
                    window = rec.get("abilityWindow", "")
                    if ability_text:
                        display_name = name
                        timing = f"  [{window}] {ability_text}" if window else f"  {ability_text}"
                    elif window:
                        display_name = name
                        timing = f"  [{window}]"
                    else:
                        display_name = name
                        timing = ""
                else:
                    display_name = lid
                    timing = ""
                print(f"      {display_name} ({ltype_cap}): {status}{timing}")

        if opts:
            actions = [a.value for a in opts.available_actions]
            if actions:
                print(f"    Available actions: {', '.join(actions)}")
            else:
                print("    Available actions: (none)")

            # --- Public component actions detail ---
            if PlayerAction.COMPONENT_ACTION in opts.available_actions:
                component_sources: list[str] = []

                # Technologies with ACTION timing
                action_tech_ids = [
                    t for t in (player.researched_technologies or []) if t in action_techs
                ]
                for t in action_tech_ids:
                    component_sources.append(f"tech: {action_techs[t]}")

                # Readied agents with ACTION: timing only.
                # Agents use their own timing windows (e.g. "At the end of a player's
                # turn:"); only those whose ability window is "ACTION:" are component
                # actions.  Agents without known data are conservatively excluded.
                for leader in leaders:
                    if _get_leader_type(leader) == "agent":
                        if leader.get("exhausted", False) or leader.get("locked", False):
                            continue
                        lid = str(leader.get("id", "unknown"))
                        rec = leader_registry.get(lid)
                        if rec and rec.get("abilityWindow", "").startswith("ACTION:"):
                            name = rec.get("name", lid)
                            component_sources.append(f"agent: {name} (READY)")

                if component_sources:
                    print("    Public component actions:")
                    for src in component_sources:
                        print(f"      • {src}")
                else:
                    print("    Public component actions: (action cards not shown)")

            if PlayerAction.TACTICAL_ACTION in opts.available_actions:
                reach = _get_tactical_reach(player_id, state)
                by_dest = reach.get("by_destination", {})
                no_adj = reach.get("no_adjacency", [])
                is_active = player_id == state.active_player_id

                if by_dest:
                    print("    Tactical reach (by destination):")
                    for dest_pos in sorted(by_dest):
                        dest_data = by_dest[dest_pos]
                        planets = dest_data["planets"]
                        planet_str = ", ".join(planets) if planets else "(empty space)"
                        defenders = dest_data.get("defenders", {})
                        defender_strs = [
                            f"{fac}: {', '.join(units)}" for fac, units in sorted(defenders.items())
                        ]
                        def_str = (
                            "  [defenders: " + "; ".join(defender_strs) + "]"
                            if defender_strs
                            else ""
                        )
                        print(f"      {dest_pos} — {planet_str}{def_str}")

                        for arrival in sorted(dest_data["arrivals"], key=lambda a: a["from_pos"]):
                            ships_str = ", ".join(arrival["ships"]) or "(unknown)"
                            flags: list[str] = []
                            if arrival["via_rift"]:
                                flags.append("gravity rift — all ships at risk")
                            if arrival["needs_gravity_drive"]:
                                gd_ships = ", ".join(arrival["needs_gravity_drive"])
                                flags.append(f"needs Gravity Drive: {gd_ships}")
                            flag_str = f"  [{'; '.join(flags)}]" if flags else ""
                            cap = arrival["capacity"]
                            cap_str = f", capacity {cap}" if cap > 0 else ""
                            print(
                                f"        ← from {arrival['from_pos']}"
                                f" [{ships_str}, move {arrival['fleet_move']}{cap_str}]{flag_str}"
                            )
                            cargo = arrival.get("transported_units") or []
                            if cargo:
                                print(
                                    f"          cargo options: {', '.join(cargo)}"
                                    f" (from {arrival['from_pos']})"
                                )
                            else:
                                gf = arrival["ground_forces"]
                                if gf:
                                    print(
                                        f"          ground forces: {', '.join(gf)}"
                                        f" (from {arrival['from_pos']})"
                                    )
                            pickup = arrival.get("pickup_systems", {})
                            for pick_pos in sorted(pickup):
                                pick_labels = pickup[pick_pos]
                                print(
                                    f"          + can pick up:"
                                    f" {', '.join(pick_labels)} from {pick_pos}"
                                )

                        if is_active and dest_data.get("combat_result"):
                            print(f"        ⚔ combat: {dest_data['combat_result']}")

                if no_adj:
                    print(
                        "    Tactical reach: fleets at special position(s) "
                        f"{', '.join(sorted(no_adj))} — no wormhole adjacency known"
                    )

    print()
    print("=" * 60)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: ti4-analyze <game_number>", file=sys.stderr)
        print("Example: ti4-analyze pbd22295", file=sys.stderr)
        sys.exit(1)

    game_number = sys.argv[1].strip()

    raw = fetch_game_json(game_number)
    state = from_asyncti4(raw)

    player_options = {pid: get_player_options(state, pid) for pid in state.players}

    print_game_summary(state)
    print_player_summary(state, player_options)


if __name__ == "__main__":
    main()
