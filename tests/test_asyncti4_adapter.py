"""Tests for the AsyncTI4 game-state adapter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adapters.asyncti4 import AsyncTI4GameData, from_asyncti4
from models.state import GamePhase, GameState

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_DATA: dict = {
    "gameId": "pbd22295",
    "round": 3,
    "phase": "action",
    "speaker": "player_1",
    "players": [
        {
            "userName": "player_1",
            "faction": "the_universities_of_jol_nar",
            "color": "blue",
            "victoryPoints": 5,
            "strategyCards": ["technology"],
            "passed": False,
            "tg": 3,
            "commodities": 2,
            "planets": ["mecatol_rex", "jord"],
            "exhaustedPlanets": ["mecatol_rex"],
            "technologies": ["neural_motivator"],
            "promissoryNotesInHand": [],
            "scoredSecrets": [],
        },
        {
            "userName": "player_2",
            "faction": "the_emirates_of_hacan",
            "color": "yellow",
            "victoryPoints": 4,
            "strategyCards": [],
            "passed": True,
            "tg": 5,
            "commodities": 3,
            "planets": ["arretze", "hercant", "kamdorn"],
            "exhaustedPlanets": [],
            "technologies": ["sarween_tools"],
            "promissoryNotesInHand": [],
            "scoredSecrets": [],
        },
    ],
    "laws": ["shard_of_the_throne"],
    "publicObjectives": ["expansion_i"],
    "scoredSecretObjectives": [],
    "activePlayerName": "player_1",
}


# ---------------------------------------------------------------------------
# Conversion tests
# ---------------------------------------------------------------------------


class TestFromAsyncTI4:
    def test_returns_game_state(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert isinstance(state, GameState)

    def test_game_id(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.game_id == "pbd22295"

    def test_round_number(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.round_number == 3

    def test_phase_mapped(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.phase == GamePhase.ACTION

    def test_players_imported(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "player_1" in state.players
        assert "player_2" in state.players

    def test_player_faction(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_1"].faction_id == "the_universities_of_jol_nar"

    def test_player_strategy_cards(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_1"].strategy_card_ids == ["technology"]

    def test_player_no_strategy_cards(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_2"].strategy_card_ids == []

    def test_player_passed(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_2"].passed is True
        assert state.players["player_1"].passed is False

    def test_player_victory_points(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_1"].victory_points == 5
        assert state.players["player_2"].victory_points == 4

    def test_player_trade_goods(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_1"].trade_goods == 3

    def test_player_commodities(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["player_2"].commodities == 3

    def test_player_planets(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "mecatol_rex" in state.players["player_1"].controlled_planets

    def test_player_exhausted_planets(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "mecatol_rex" in state.players["player_1"].exhausted_planets

    def test_player_technologies(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "neural_motivator" in state.players["player_1"].researched_technologies

    def test_speaker(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.turn_order.speaker_id == "player_1"

    def test_turn_order(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.turn_order.order == ["player_1", "player_2"]

    def test_active_player(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.active_player_id == "player_1"

    def test_laws(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "shard_of_the_throne" in state.law_ids

    def test_public_objectives(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "expansion_i" in state.public_objectives

    def test_scored_secret_objectives(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.secret_objectives_scored == []

    def test_accepts_asyncti4gamedata_instance(self) -> None:
        parsed = AsyncTI4GameData.model_validate(SAMPLE_DATA)
        state = from_asyncti4(parsed)
        assert state.game_id == "pbd22295"

    def test_phase_case_insensitive(self) -> None:
        data = {**SAMPLE_DATA, "phase": "ACTION"}
        state = from_asyncti4(data)
        assert state.phase == GamePhase.ACTION

    def test_unknown_phase_defaults_to_strategy(self) -> None:
        data = {**SAMPLE_DATA, "phase": "unknown_phase"}
        state = from_asyncti4(data)
        assert state.phase == GamePhase.STRATEGY

    def test_all_phases_mapped(self) -> None:
        for phase_str, expected in [
            ("strategy", GamePhase.STRATEGY),
            ("action", GamePhase.ACTION),
            ("status", GamePhase.STATUS),
            ("agenda", GamePhase.AGENDA),
        ]:
            data = {**SAMPLE_DATA, "phase": phase_str}
            state = from_asyncti4(data)
            assert state.phase == expected

    def test_speaker_not_in_players_raises(self) -> None:
        data = {**SAMPLE_DATA, "speaker": "ghost_player"}
        with pytest.raises(ValueError, match="ghost_player"):
            from_asyncti4(data)

    def test_no_active_player(self) -> None:
        data = {**SAMPLE_DATA, "activePlayerName": None}
        state = from_asyncti4(data)
        assert state.active_player_id is None

    def test_action_cards_imported(self) -> None:
        data = {
            **SAMPLE_DATA,
            "players": [
                {**SAMPLE_DATA["players"][0], "actionCards": ["direct_hit", "morale_boost"]},
                SAMPLE_DATA["players"][1],
            ],
        }
        state = from_asyncti4(data)
        assert state.players["player_1"].action_cards == ["direct_hit", "morale_boost"]

    def test_scored_secrets_per_player(self) -> None:
        data = {
            **SAMPLE_DATA,
            "players": [
                {**SAMPLE_DATA["players"][0], "scoredSecrets": ["secret_one"]},
                SAMPLE_DATA["players"][1],
            ],
        }
        state = from_asyncti4(data)
        assert "secret_one" in state.players["player_1"].scored_objectives


# ---------------------------------------------------------------------------
# AsyncTI4GameData schema validation
# ---------------------------------------------------------------------------


class TestAsyncTI4GameDataSchema:
    def test_round_must_be_positive(self) -> None:
        data = {**SAMPLE_DATA, "round": 0}
        with pytest.raises(ValidationError):
            AsyncTI4GameData.model_validate(data)

    def test_phase_normalized_to_lowercase(self) -> None:
        parsed = AsyncTI4GameData.model_validate({**SAMPLE_DATA, "phase": "ACTION"})
        assert parsed.phase == "action"

    def test_defaults_applied(self) -> None:
        minimal = {
            "gameId": "test",
            "speaker": "player_1",
            "players": [{"userName": "player_1", "faction": "sol"}],
        }
        parsed = AsyncTI4GameData.model_validate(minimal)
        assert parsed.round == 1
        assert parsed.phase == "strategy"
        assert parsed.laws == []
