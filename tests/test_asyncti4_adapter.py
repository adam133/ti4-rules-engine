"""Tests for the AsyncTI4 game-state adapter – matching real pbd22295 JSON structure."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adapters.asyncti4 import AsyncTI4GameData, AsyncTI4Player, from_asyncti4
from models.state import GamePhase, GameState

# ---------------------------------------------------------------------------
# Minimal sample data matching the actual AsyncTI4 JSON structure
# ---------------------------------------------------------------------------

SAMPLE_PLAYER_1: dict = {
    "userName": "gokurohit",
    "faction": "jolnar",
    "color": "royal",
    "totalVps": 3,
    "scs": [4],
    "passed": False,
    "tg": 2,
    "commodities": 0,
    "planets": ["jol", "nar", "semlore"],
    "exhaustedPlanets": ["semlore"],
    "techs": ["amd", "st", "nm"],
    "secretsScored": {},
    "isSpeaker": False,
    "active": True,
    "acCount": 1,
    "eliminated": False,
}

SAMPLE_PLAYER_2: dict = {
    "userName": "Rowdy",
    "faction": "ralnel",
    "color": "lime",
    "totalVps": 2,
    "scs": [7],
    "passed": True,
    "tg": 2,
    "commodities": 0,
    "planets": ["mez", "rep", "archonvail"],
    "exhaustedPlanets": [],
    "techs": ["aida", "bs"],
    "secretsScored": {"secret_x": {"round": 1}},
    "isSpeaker": True,
    "active": False,
    "acCount": 3,
    "eliminated": False,
}

SAMPLE_DATA: dict = {
    "gameName": "pbd22295",
    "gameRound": 1,
    "lawsInPlay": ["shard_of_the_throne"],
    "playerData": [SAMPLE_PLAYER_1, SAMPLE_PLAYER_2],
    "strategyCards": [
        {"id": "pok1leadership", "initiative": 1, "picked": True, "played": True},
        {"id": "pok2diplomacy", "initiative": 2, "picked": False, "played": False},
        {"id": "pok3politics", "initiative": 3, "picked": True, "played": True},
        {"id": "te4construction", "initiative": 4, "picked": True, "played": True},
        {"id": "pok5trade", "initiative": 5, "picked": True, "played": True},
        {"id": "te6warfare", "initiative": 6, "picked": True, "played": True},
        {"id": "pok7technology", "initiative": 7, "picked": True, "played": True},
        {"id": "pok8imperial", "initiative": 8, "picked": False, "played": False},
    ],
}


# ---------------------------------------------------------------------------
# Conversion tests
# ---------------------------------------------------------------------------


class TestFromAsyncTI4:
    def test_returns_game_state(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert isinstance(state, GameState)

    def test_game_id_from_game_name(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.game_id == "pbd22295"

    def test_round_number_from_game_round(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.round_number == 1

    def test_players_imported(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "gokurohit" in state.players
        assert "Rowdy" in state.players

    def test_player_faction(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].faction_id == "jolnar"
        assert state.players["Rowdy"].faction_id == "ralnel"

    def test_player_vps_from_total_vps(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].victory_points == 3
        assert state.players["Rowdy"].victory_points == 2

    def test_player_strategy_cards_from_scs(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        # scs=[4] in the source → ["4"] as strings
        assert state.players["gokurohit"].strategy_card_ids == ["4"]
        assert state.players["Rowdy"].strategy_card_ids == ["7"]

    def test_player_passed(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].passed is False
        assert state.players["Rowdy"].passed is True

    def test_player_trade_goods(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].trade_goods == 2

    def test_player_commodities(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].commodities == 0

    def test_player_planets(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "jol" in state.players["gokurohit"].controlled_planets

    def test_player_exhausted_planets(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "semlore" in state.players["gokurohit"].exhausted_planets

    def test_player_technologies_from_techs(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "nm" in state.players["gokurohit"].researched_technologies

    def test_player_scored_secrets_from_dict_keys(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        # Player 1 has empty secretsScored
        assert state.players["gokurohit"].scored_objectives == []
        # Player 2 has one scored secret
        assert "secret_x" in state.players["Rowdy"].scored_objectives

    def test_speaker_from_is_speaker_flag(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.turn_order.speaker_id == "Rowdy"

    def test_active_player_from_active_flag(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert state.active_player_id == "gokurohit"

    def test_laws_from_laws_in_play(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert "shard_of_the_throne" in state.law_ids

    def test_action_cards_empty(self) -> None:
        # Action card IDs are not exposed in AsyncTI4 exports
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].action_cards == []

    def test_promissory_notes_empty(self) -> None:
        # Promissory note IDs in hand are not exposed
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].promissory_notes == []

    def test_accepts_asyncti4gamedata_instance(self) -> None:
        parsed = AsyncTI4GameData.model_validate(SAMPLE_DATA)
        state = from_asyncti4(parsed)
        assert state.game_id == "pbd22295"

    def test_no_active_player_when_none_active(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [
                {**SAMPLE_PLAYER_1, "active": False},
                SAMPLE_PLAYER_2,
            ],
        }
        state = from_asyncti4(data)
        assert state.active_player_id is None

    def test_no_speaker_raises(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [
                {**SAMPLE_PLAYER_1, "isSpeaker": False},
                {**SAMPLE_PLAYER_2, "isSpeaker": False},
            ],
        }
        with pytest.raises(ValueError, match="isSpeaker"):
            from_asyncti4(data)

    def test_eliminated_players_excluded(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [
                {**SAMPLE_PLAYER_1, "eliminated": True},
                SAMPLE_PLAYER_2,
            ],
        }
        state = from_asyncti4(data)
        assert "gokurohit" not in state.players
        assert "Rowdy" in state.players

    def test_turn_order_contains_all_non_eliminated(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)
        assert set(state.turn_order.order) == {"gokurohit", "Rowdy"}


# ---------------------------------------------------------------------------
# Phase inference tests
# ---------------------------------------------------------------------------


class TestPhaseInference:
    def test_action_phase_when_all_cards_picked(self) -> None:
        # All strategy cards picked but none played → action phase (picking complete)
        data = {
            **SAMPLE_DATA,
            "strategyCards": [
                {"id": f"card{i}", "initiative": i, "picked": True, "played": False}
                for i in range(1, 9)
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.ACTION

    def test_action_phase_when_any_card_played(self) -> None:
        # Some cards played (primary ability used) → action phase
        data = {
            **SAMPLE_DATA,
            "strategyCards": [
                {"id": "pok1leadership", "initiative": 1, "picked": True, "played": True},
                {"id": "pok2diplomacy", "initiative": 2, "picked": False, "played": False},
                {"id": "pok3politics", "initiative": 3, "picked": True, "played": False},
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.ACTION

    def test_strategy_phase_when_no_cards_picked(self) -> None:
        data = {
            **SAMPLE_DATA,
            "strategyCards": [
                {"id": f"card{i}", "initiative": i, "picked": False, "played": False}
                for i in range(1, 9)
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.STRATEGY

    def test_strategy_phase_when_some_cards_not_picked(self) -> None:
        # Mix of picked and unpicked, none played → strategy phase (picking in progress)
        data = {
            **SAMPLE_DATA,
            "strategyCards": [
                {"id": "pok1leadership", "initiative": 1, "picked": True, "played": False},
                {"id": "pok2diplomacy", "initiative": 2, "picked": False, "played": False},
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.STRATEGY

    def test_strategy_phase_when_no_strategy_card_data(self) -> None:
        data = {**SAMPLE_DATA, "strategyCards": []}
        state = from_asyncti4(data)
        assert state.phase == GamePhase.STRATEGY

    def test_real_pbd22295_pattern_infers_action(self) -> None:
        # Real game: 6 of 8 cards picked, all picked cards played (6-player game skips 2)
        data = {
            **SAMPLE_DATA,
            "strategyCards": [
                {"id": "pok1leadership", "initiative": 1, "picked": True, "played": True},
                {"id": "pok2diplomacy", "initiative": 2, "picked": False, "played": False},
                {"id": "pok3politics", "initiative": 3, "picked": True, "played": True},
                {"id": "te4construction", "initiative": 4, "picked": True, "played": True},
                {"id": "pok5trade", "initiative": 5, "picked": True, "played": True},
                {"id": "te6warfare", "initiative": 6, "picked": True, "played": True},
                {"id": "pok7technology", "initiative": 7, "picked": True, "played": True},
                {"id": "pok8imperial", "initiative": 8, "picked": False, "played": False},
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.ACTION


# ---------------------------------------------------------------------------
# AsyncTI4GameData schema validation
# ---------------------------------------------------------------------------


class TestAsyncTI4GameDataSchema:
    def test_game_round_must_be_positive(self) -> None:
        data = {**SAMPLE_DATA, "gameRound": 0}
        with pytest.raises(ValidationError):
            AsyncTI4GameData.model_validate(data)

    def test_defaults_applied(self) -> None:
        minimal = {
            "gameName": "test",
            "playerData": [
                {
                    "userName": "player_1",
                    "faction": "sol",
                    "isSpeaker": True,
                    "scs": [],
                    "planets": [],
                    "exhaustedPlanets": [],
                    "techs": [],
                    "secretsScored": {},
                }
            ],
        }
        parsed = AsyncTI4GameData.model_validate(minimal)
        assert parsed.gameRound == 1
        assert parsed.lawsInPlay == []

    def test_player_defaults(self) -> None:
        p = AsyncTI4Player.model_validate(
            {"userName": "x", "faction": "sol", "scs": []}
        )
        assert p.totalVps == 0
        assert p.passed is False
        assert p.tg == 0
        assert p.eliminated is False
        assert p.isSpeaker is False
        assert p.active is False
