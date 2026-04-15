"""Tests for the GameHistory undo/redo manager."""

from __future__ import annotations

import pytest

from ti4_rules_engine.engine.history import GameHistory
from ti4_rules_engine.models.state import GamePhase, GameState


class TestGameHistoryCheckpoint:
    def test_initial_cannot_undo(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        assert not history.can_undo

    def test_initial_cannot_redo(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        assert not history.can_redo

    def test_checkpoint_enables_undo(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("before_action")
        assert history.can_undo

    def test_checkpoint_label_recorded(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("before_action")
        assert "before_action" in history.history_labels()


class TestGameHistoryUndo:
    def test_undo_reverts_phase(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("initial")
        game_state.phase = GamePhase.ACTION
        assert game_state.phase == GamePhase.ACTION

        history.undo()
        assert game_state.phase == GamePhase.STRATEGY

    def test_undo_reverts_round_number(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("round_1")
        game_state.round_number = 3

        history.undo()
        assert game_state.round_number == 1

    def test_undo_empty_raises(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        with pytest.raises(IndexError, match="Nothing to undo"):
            history.undo()

    def test_undo_clears_redo_after_checkpoint(self, game_state: GameState) -> None:
        """After undo→checkpoint, the redo stack must be cleared."""
        history = GameHistory(game_state)
        history.checkpoint("snap1")
        game_state.round_number = 2
        history.undo()
        # redo stack should have "snap1" before taking another checkpoint
        assert history.can_redo
        history.checkpoint("snap2")
        # new checkpoint clears redo
        assert not history.can_redo


class TestGameHistoryRedo:
    def test_redo_replays_change(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("before")
        game_state.phase = GamePhase.ACTION

        history.undo()
        assert game_state.phase == GamePhase.STRATEGY

        history.redo()
        assert game_state.phase == GamePhase.ACTION

    def test_redo_empty_raises(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        with pytest.raises(IndexError, match="Nothing to redo"):
            history.redo()

    def test_multiple_undos_and_redos(self, game_state: GameState) -> None:
        history = GameHistory(game_state)
        history.checkpoint("round_1")
        game_state.round_number = 2
        history.checkpoint("round_2")
        game_state.round_number = 3

        history.undo()
        assert game_state.round_number == 2
        history.undo()
        assert game_state.round_number == 1

        history.redo()
        assert game_state.round_number == 2
        history.redo()
        assert game_state.round_number == 3


class TestGameHistoryDepthLimit:
    def test_max_depth_evicts_oldest(self, game_state: GameState) -> None:
        history = GameHistory(game_state, max_depth=3)
        for i in range(5):
            history.checkpoint(f"snap_{i}")
        # Only the last 3 fit
        labels = history.history_labels()
        assert len(labels) == 3
        assert labels[-1] == "snap_4"
