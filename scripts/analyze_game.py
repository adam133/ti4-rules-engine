"""
Fetch an AsyncTI4 game snapshot from S3 and print a readable analysis.

Usage::

    python scripts/analyze_game.py <game_number>

Example::

    python scripts/analyze_game.py pbd22295
"""

from __future__ import annotations

import json
import sys
import urllib.request
from typing import TYPE_CHECKING
from urllib.error import URLError

if TYPE_CHECKING:
    from models.state import GameState

S3_URL_TEMPLATE = (
    "https://s3.us-east-1.amazonaws.com/asyncti4.com/webdata/{game}/{game}.json"
)


def fetch_game_json(game_number: str) -> dict:
    """Download the game snapshot JSON from S3 and return it as a dict."""
    url = S3_URL_TEMPLATE.format(game=game_number)
    print(f"Fetching game data from: {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except URLError as exc:
        print(f"ERROR: Failed to fetch game data – {exc}", file=sys.stderr)
        sys.exit(1)
    return json.loads(raw)


def print_game_summary(state: "GameState") -> None:
    """Print a human-readable summary of the game state."""
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
    print("=" * 60)


def print_player_summary(state: "GameState", player_options_map: dict) -> None:
    """Print per-player details and available actions."""
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
            f"    Planets:  {len(player.controlled_planets)} controlled"
            f", {len(player.exhausted_planets)} exhausted"
        )
        print(f"    Techs:    {', '.join(player.researched_technologies) or '(none)'}")
        if player.strategy_card_ids:
            print(f"    Strat cards: {', '.join(player.strategy_card_ids)}")
        if player.scored_objectives:
            print(f"    Scored:   {', '.join(player.scored_objectives)}")

        if opts:
            actions = [a.value for a in opts.available_actions]
            if actions:
                print(f"    Available actions: {', '.join(actions)}")
            else:
                print("    Available actions: (none)")

    print()
    print("=" * 60)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/analyze_game.py <game_number>", file=sys.stderr)
        print("Example: python scripts/analyze_game.py pbd22295", file=sys.stderr)
        sys.exit(1)

    game_number = sys.argv[1].strip()

    # Import here so the script can be run from repo root with PYTHONPATH set
    from adapters.asyncti4 import from_asyncti4
    from engine.options import get_player_options

    raw = fetch_game_json(game_number)
    state = from_asyncti4(raw)

    player_options = {
        pid: get_player_options(state, pid) for pid in state.players
    }

    print_game_summary(state)
    print_player_summary(state, player_options)


if __name__ == "__main__":
    main()
