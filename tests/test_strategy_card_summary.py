from __future__ import annotations

from ti4_rules_engine.models.state import GameState, PlayerState, TurnOrder
from ti4_rules_engine.scripts.analyze_game import (
    _build_turn_order_tracker,
    _strategy_card_details,
)


def test_strategy_card_details_resolves_known_card() -> None:
    details = _strategy_card_details("7")
    assert details["initiative"] == 7
    assert details["name"] == "Technology"
    assert "Research 1 technology" in details["primary"]
    assert "6 resources" in details["secondary"]


def test_strategy_card_details_supports_asyncti4_id_format() -> None:
    details = _strategy_card_details("pok3politics")
    assert details["initiative"] == 3
    assert details["name"] == "Politics"


def test_strategy_card_details_unknown_card_falls_back_to_raw_id() -> None:
    details = _strategy_card_details("custom_card")
    assert details["initiative"] is None
    assert details["name"] == "custom_card"
    assert details["primary"] == "(ability text unavailable)"
    assert details["secondary"] == "(ability text unavailable)"


def test_build_turn_order_tracker_uses_lowest_initiative() -> None:
    state = GameState(
        game_id="g",
        round_number=3,
        turn_order=TurnOrder(speaker_id="alice", order=["alice", "bob", "cara"]),
        players={
            "alice": PlayerState(
                player_id="alice",
                faction_id="a",
                strategy_card_ids=["7", "2"],
            ),
            "bob": PlayerState(player_id="bob", faction_id="b", strategy_card_ids=["3"]),
            "cara": PlayerState(player_id="cara", faction_id="c", strategy_card_ids=[]),
        },
    )
    tracker = _build_turn_order_tracker(state)
    assert [entry["player_id"] for entry in tracker] == ["alice", "bob"]
    assert [entry["initiative"] for entry in tracker] == [2, 3]
    assert tracker[0]["card_name"] == "Diplomacy"
    assert tracker[0]["is_speaker"] is True
    assert tracker[1]["is_speaker"] is False
