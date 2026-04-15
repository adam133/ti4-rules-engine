"""Tests for the AsyncTI4 game-state adapter – matching real pbd22295 JSON structure."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ti4_rules_engine.adapters.asyncti4 import AsyncTI4GameData, AsyncTI4Player, from_asyncti4
from ti4_rules_engine.models.state import GamePhase, GameState

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
    def test_action_phase_when_expected_pick_count_reached_with_skipped_cards(self) -> None:
        # 3-player game: 6 of 8 cards picked (2 skipped), none played yet.
        # This should still be action phase because strategy picking is complete.
        p1 = {**SAMPLE_PLAYER_1, "userName": "p1", "faction": "jolnar", "scs": [1, 5]}
        p2 = {**SAMPLE_PLAYER_2, "userName": "p2", "faction": "sol", "scs": [2, 6]}
        p3 = {**SAMPLE_PLAYER_1, "userName": "p3", "faction": "hacan", "scs": [3, 7]}
        data = {
            **SAMPLE_DATA,
            "playerData": [p1, p2, p3],
            "strategyCards": [
                {"id": "pok1leadership", "initiative": 1, "picked": True, "played": False},
                {"id": "pok2diplomacy", "initiative": 2, "picked": True, "played": False},
                {"id": "pok3politics", "initiative": 3, "picked": True, "played": False},
                {"id": "te4construction", "initiative": 4, "picked": False, "played": False},
                {"id": "pok5trade", "initiative": 5, "picked": True, "played": False},
                {"id": "te6warfare", "initiative": 6, "picked": True, "played": False},
                {"id": "pok7technology", "initiative": 7, "picked": True, "played": False},
                {"id": "pok8imperial", "initiative": 8, "picked": False, "played": False},
            ],
        }
        state = from_asyncti4(data)
        assert state.phase == GamePhase.ACTION
        assert state.players["p1"].strategy_card_ids == ["1", "5"]
        assert state.players["p2"].strategy_card_ids == ["2", "6"]
        assert state.players["p3"].strategy_card_ids == ["3", "7"]

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

    def test_laws_in_play_as_string_ids(self) -> None:
        # Original format: plain string IDs
        data = {**SAMPLE_DATA, "lawsInPlay": ["shard_of_the_throne", "minister_policy"]}
        parsed = AsyncTI4GameData.model_validate(data)
        assert parsed.lawsInPlay == ["shard_of_the_throne", "minister_policy"]

    def test_laws_in_play_as_dicts(self) -> None:
        # Newer AsyncTI4 export format: full law objects
        law_objects = [
            {
                "controlTokens": [],
                "displaysElectedFaction": True,
                "electedFaction": "naaz",
                "id": "minister_policy",
                "name": "Minister of Policy",
                "type": "Law",
                "uniqueId": 481,
            },
            {
                "controlTokens": [],
                "id": "minister_sciences",
                "name": "Minister of Sciences",
                "type": "Law",
                "uniqueId": 659,
            },
        ]
        data = {**SAMPLE_DATA, "lawsInPlay": law_objects}
        parsed = AsyncTI4GameData.model_validate(data)
        assert parsed.lawsInPlay == ["minister_policy", "minister_sciences"]

    def test_laws_in_play_as_dicts_round_trips_through_from_asyncti4(self) -> None:
        # Ensure from_asyncti4 correctly populates law_ids from dict-format lawsInPlay
        law_objects = [
            {"id": "minister_policy", "type": "Law", "uniqueId": 481, "controlTokens": []},
        ]
        data = {**SAMPLE_DATA, "lawsInPlay": law_objects}
        state = from_asyncti4(data)
        assert state.law_ids == ["minister_policy"]


# ---------------------------------------------------------------------------
# Dicecord / neutral-faction filtering
# ---------------------------------------------------------------------------

DICECORD_PLAYER: dict = {
    "userName": "Dicecord",
    "faction": "neutral",
    "color": "aberration",
    "totalVps": 0,
    "scs": [],
    "passed": False,
    "tg": 0,
    "commodities": 0,
    "planets": [],
    "exhaustedPlanets": [],
    "techs": [],
    "secretsScored": {},
    "isSpeaker": False,
    "active": False,
    "acCount": 0,
    "eliminated": False,
}


class TestDicecordFiltering:
    def test_neutral_faction_player_excluded(self) -> None:
        """Players with faction='neutral' (Dicecord) must be excluded from the analysis."""
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_1, SAMPLE_PLAYER_2, DICECORD_PLAYER],
        }
        state = from_asyncti4(data)
        assert "Dicecord" not in state.players

    def test_neutral_faction_not_in_turn_order(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_1, SAMPLE_PLAYER_2, DICECORD_PLAYER],
        }
        state = from_asyncti4(data)
        assert "Dicecord" not in state.turn_order.order

    def test_non_neutral_players_still_present(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_1, SAMPLE_PLAYER_2, DICECORD_PLAYER],
        }
        state = from_asyncti4(data)
        assert "gokurohit" in state.players
        assert "Rowdy" in state.players

    def test_neutral_as_speaker_raises(self) -> None:
        """If the only isSpeaker is neutral, we should still raise for missing speaker."""
        data = {
            **SAMPLE_DATA,
            "playerData": [
                {**SAMPLE_PLAYER_1, "isSpeaker": False},
                {**SAMPLE_PLAYER_2, "isSpeaker": False},
                {**DICECORD_PLAYER, "isSpeaker": True},
            ],
        }
        with pytest.raises(ValueError, match="isSpeaker"):
            from_asyncti4(data)


# ---------------------------------------------------------------------------
# Command token mapping
# ---------------------------------------------------------------------------


SAMPLE_PLAYER_WITH_TOKENS: dict = {
    **SAMPLE_PLAYER_1,
    "tacticalCC": 3,
    "fleetCC": 2,
    "strategicCC": 1,
}


class TestCommandTokenMapping:
    def test_tactical_tokens_mapped(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_WITH_TOKENS, SAMPLE_PLAYER_2],
        }
        state = from_asyncti4(data)
        assert state.players["gokurohit"].tactical_tokens == 3

    def test_fleet_tokens_mapped(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_WITH_TOKENS, SAMPLE_PLAYER_2],
        }
        state = from_asyncti4(data)
        assert state.players["gokurohit"].fleet_tokens == 2

    def test_strategy_tokens_mapped(self) -> None:
        data = {
            **SAMPLE_DATA,
            "playerData": [SAMPLE_PLAYER_WITH_TOKENS, SAMPLE_PLAYER_2],
        }
        state = from_asyncti4(data)
        assert state.players["gokurohit"].strategy_tokens == 1

    def test_default_tokens_are_zero(self) -> None:
        # SAMPLE_PLAYER_1 has no token fields → should default to 0
        state = from_asyncti4(SAMPLE_DATA)
        assert state.players["gokurohit"].tactical_tokens == 0
        assert state.players["gokurohit"].fleet_tokens == 0
        assert state.players["gokurohit"].strategy_tokens == 0


# ---------------------------------------------------------------------------
# Tile unit data stored in GameState.extra
# ---------------------------------------------------------------------------

SAMPLE_TILE_UNIT_DATA: dict = {
    "000": {"anomaly": False, "ccs": [], "planets": {"mecatol": {}}, "space": {}},
    "101": {
        "anomaly": False,
        "ccs": ["royal"],
        "planets": {},
        "space": {
            "royal": [{"entityId": "cv", "entityType": "unit", "count": 2}]
        },
    },
    "102": {"anomaly": False, "ccs": [], "planets": {"jol": {}, "nar": {}}, "space": {}},
    "201": {"anomaly": True, "ccs": [], "planets": {}, "space": {}},
}


class TestTileUnitDataInExtra:
    def test_tile_unit_data_stored_in_extra(self) -> None:
        data = {**SAMPLE_DATA, "tileUnitData": SAMPLE_TILE_UNIT_DATA}
        state = from_asyncti4(data)
        assert "tile_unit_data" in state.extra
        assert state.extra["tile_unit_data"] == SAMPLE_TILE_UNIT_DATA

    def test_player_colors_stored_in_extra(self) -> None:
        data = {**SAMPLE_DATA, "tileUnitData": SAMPLE_TILE_UNIT_DATA}
        state = from_asyncti4(data)
        assert "player_colors" in state.extra
        assert state.extra["player_colors"]["gokurohit"] == "royal"
        assert state.extra["player_colors"]["Rowdy"] == "lime"

    def test_neutral_color_not_in_player_colors(self) -> None:
        data = {
            **SAMPLE_DATA,
            "tileUnitData": SAMPLE_TILE_UNIT_DATA,
            "playerData": [SAMPLE_PLAYER_1, SAMPLE_PLAYER_2, DICECORD_PLAYER],
        }
        state = from_asyncti4(data)
        # Dicecord's color ("aberration") must not appear in player_colors
        assert "aberration" not in state.extra["player_colors"].values()
        assert "Dicecord" not in state.extra["player_colors"]

    def test_empty_tile_unit_data_when_absent(self) -> None:
        # If the JSON has no tileUnitData key, the extra dict should still work
        state = from_asyncti4(SAMPLE_DATA)
        assert state.extra["tile_unit_data"] == {}


# ---------------------------------------------------------------------------
# Web-data API: nested objectives format
# ---------------------------------------------------------------------------

# Minimal sample of the nested objectives structure returned by the web-data API.
SAMPLE_OBJECTIVES_BLOCK: dict = {
    "stage1Objectives": [
        {
            "key": "research_outposts",
            "name": "Found Research Outposts",
            "revealed": True,
            "scoredFactions": ["jolnar", "ralnel"],
            "pointValue": 1,
        },
        {
            "key": "expand_borders",
            "name": "Expand Borders",
            "revealed": True,
            "scoredFactions": ["jolnar"],
            "pointValue": 1,
        },
        {
            "key": "UNREVEALED_9999",
            "name": "UNREVEALED",
            "revealed": False,
            "scoredFactions": [],
            "pointValue": 1,
        },
    ],
    "stage2Objectives": [
        {
            "key": "subdue",
            "name": "Subdue the Galaxy",
            "revealed": True,
            "scoredFactions": [],
            "pointValue": 2,
        },
    ],
    "customObjectives": [
        {
            "key": "Custodian/Imperial",
            "name": "Custodian/Imperial",
            "revealed": True,
            "scoredFactions": ["ralnel"],
            "pointValue": 1,
        },
    ],
    "allObjectives": [],
}

# Build a minimal web-data style payload using the players from SAMPLE_DATA.
# Note: SAMPLE_PLAYER_1 and SAMPLE_PLAYER_2 do not have a scoredPublicObjectives
# field (the web-data API omits it; scoring is derived from the objectives block).
SAMPLE_PLAYER_1_WEB: dict = {
    **SAMPLE_PLAYER_1,
}
SAMPLE_PLAYER_2_WEB: dict = {
    **SAMPLE_PLAYER_2,
}

SAMPLE_WEB_DATA: dict = {
    "gameName": "pbd22295",
    "gameRound": 3,
    "lawsInPlay": [],
    "playerData": [SAMPLE_PLAYER_1_WEB, SAMPLE_PLAYER_2_WEB],
    "strategyCards": SAMPLE_DATA["strategyCards"],
    "objectives": SAMPLE_OBJECTIVES_BLOCK,
}


class TestWebDataObjectivesFormat:
    def test_public_objectives_extracted_from_nested_objectives(self) -> None:
        """Revealed stage-I and stage-II objective IDs must populate publicObjectives."""
        state = from_asyncti4(SAMPLE_WEB_DATA)
        assert "research_outposts" in state.public_objectives
        assert "expand_borders" in state.public_objectives
        assert "subdue" in state.public_objectives

    def test_unrevealed_objectives_excluded(self) -> None:
        """Unrevealed objectives must not appear in publicObjectives."""
        state = from_asyncti4(SAMPLE_WEB_DATA)
        assert not any(k.startswith("UNREVEALED") for k in state.public_objectives)

    def test_custom_objectives_excluded_from_public_objectives(self) -> None:
        """Custom objectives (Custodians, etc.) are in customObjectives, not stage lists."""
        state = from_asyncti4(SAMPLE_WEB_DATA)
        assert "Custodian/Imperial" not in state.public_objectives

    def test_scored_public_objectives_derived_from_scored_factions(self) -> None:
        """Player scored public objectives must be derived from scoredFactions in objectives."""
        state = from_asyncti4(SAMPLE_WEB_DATA)
        # jolnar player scored both research_outposts and expand_borders
        assert "research_outposts" in state.players["gokurohit"].scored_objectives
        assert "expand_borders" in state.players["gokurohit"].scored_objectives
        # ralnel player scored only research_outposts (not expand_borders)
        assert "research_outposts" in state.players["Rowdy"].scored_objectives
        assert "expand_borders" not in state.players["Rowdy"].scored_objectives

    def test_per_player_scored_public_takes_precedence_over_objectives_block(self) -> None:
        """When scoredPublicObjectives is set per-player, it overrides the objectives block."""
        player_with_scored = {**SAMPLE_PLAYER_1, "scoredPublicObjectives": ["expand_borders"]}
        data = {
            **SAMPLE_WEB_DATA,
            "playerData": [player_with_scored, SAMPLE_PLAYER_2_WEB],
            # objectives block would also give jolnar "research_outposts"
        }
        state = from_asyncti4(data)
        # Only the per-player list should be used for gokurohit
        scored = state.players["gokurohit"].scored_objectives
        assert "expand_borders" in scored
        # research_outposts should NOT be there because per-player list takes over
        assert "research_outposts" not in scored

    def test_model_validator_populates_public_objectives(self) -> None:
        """AsyncTI4GameData model should expose publicObjectives from nested objectives."""
        parsed = AsyncTI4GameData.model_validate(SAMPLE_WEB_DATA)
        assert "research_outposts" in parsed.publicObjectives
        assert "expand_borders" in parsed.publicObjectives
        assert "subdue" in parsed.publicObjectives

    def test_legacy_public_objectives_list_not_overwritten(self) -> None:
        """If publicObjectives is already populated, the nested objectives block is ignored."""
        data = {
            **SAMPLE_WEB_DATA,
            "publicObjectives": ["existing_obj"],
        }
        parsed = AsyncTI4GameData.model_validate(data)
        assert parsed.publicObjectives == ["existing_obj"]

    def test_empty_objectives_block_leaves_public_objectives_empty(self) -> None:
        """When objectives block is absent, publicObjectives stays empty."""
        data = {**SAMPLE_DATA}  # no "objectives" key, no "publicObjectives" key
        parsed = AsyncTI4GameData.model_validate(data)
        assert parsed.publicObjectives == []



# ---------------------------------------------------------------------------
# objective_data in state.extra
# ---------------------------------------------------------------------------


class TestObjectiveDataInExtra:
    """Full objective display data (name, points) should be stored in extra."""

    def test_objective_data_stored_in_extra(self) -> None:
        state = from_asyncti4(SAMPLE_WEB_DATA)
        assert "objective_data" in state.extra

    def test_objective_data_contains_names(self) -> None:
        state = from_asyncti4(SAMPLE_WEB_DATA)
        obj_data = state.extra["objective_data"]
        # research_outposts is a stage1 objective with name "Found Research Outposts"
        assert "research_outposts" in obj_data
        assert obj_data["research_outposts"]["name"] == "Found Research Outposts"

    def test_objective_data_normalises_point_value(self) -> None:
        """API field 'pointValue' should be normalised to 'points' in extra data."""
        state = from_asyncti4(SAMPLE_WEB_DATA)
        obj_data = state.extra["objective_data"]
        assert obj_data["research_outposts"]["points"] == 1
        assert obj_data["subdue"]["points"] == 2

    def test_objective_data_includes_type(self) -> None:
        state = from_asyncti4(SAMPLE_WEB_DATA)
        obj_data = state.extra["objective_data"]
        assert obj_data["research_outposts"]["type"] == "stage_1"
        assert obj_data["subdue"]["type"] == "stage_2"

    def test_objective_data_empty_when_no_objectives_block(self) -> None:
        state = from_asyncti4(SAMPLE_DATA)  # no objectives block
        assert state.extra.get("objective_data") == {}
