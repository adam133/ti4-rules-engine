"""
Game history – undo/redo manager for ``GameState`` snapshots.

Each time the caller records a checkpoint the current ``GameState`` is
serialised to a plain dict and pushed onto an undo stack.  The redo stack
is maintained automatically.

Example usage::

    history = GameHistory(state)
    history.checkpoint("before_action")

    # … modify state …

    history.undo()  # rewinds to the snapshot taken above
    history.redo()  # replays the modification
"""

from __future__ import annotations

from collections import deque
from typing import Any

import structlog

from ti4_rules_engine.models.state import GameState

logger = structlog.get_logger(__name__)


class GameHistory:
    """
    Undo/redo manager for a ``GameState``.

    Parameters
    ----------
    state:
        The live game state this history tracks.
    max_depth:
        Maximum number of undo snapshots to retain.  Older entries are
        discarded when the limit is exceeded.
    """

    def __init__(self, state: GameState, max_depth: int = 50) -> None:
        self._state = state
        self._max_depth = max_depth
        self._undo_stack: deque[tuple[str, dict[str, Any]]] = deque(maxlen=max_depth)
        self._redo_stack: deque[tuple[str, dict[str, Any]]] = deque()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        """True if there is at least one snapshot available to revert to."""
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        """True if there is at least one snapshot available to replay."""
        return len(self._redo_stack) > 0

    def checkpoint(self, label: str = "") -> None:
        """
        Persist the current game state as an undo checkpoint.

        Parameters
        ----------
        label:
            Human-readable description of what is about to happen (stored
            alongside the snapshot for debugging purposes).
        """
        snapshot = self._state.snapshot()
        self._undo_stack.append((label, snapshot))
        # A new action invalidates the redo history
        self._redo_stack.clear()
        logger.debug(
            "checkpoint_saved",
            game_id=self._state.game_id,
            label=label,
            depth=len(self._undo_stack),
        )

    def undo(self) -> GameState:
        """
        Revert the game state to the most recent checkpoint.

        Returns the restored ``GameState`` (the same object mutated in-place).

        Raises
        ------
        IndexError
            If the undo stack is empty.
        """
        if not self.can_undo:
            raise IndexError("Nothing to undo.")

        # Push current state onto redo stack before reverting
        self._redo_stack.append(("redo", self._state.snapshot()))

        label, snapshot = self._undo_stack.pop()
        self._apply(snapshot)
        logger.info(
            "undo_applied",
            game_id=self._state.game_id,
            label=label,
        )
        return self._state

    def redo(self) -> GameState:
        """
        Replay the most recently undone action.

        Returns the restored ``GameState``.

        Raises
        ------
        IndexError
            If the redo stack is empty.
        """
        if not self.can_redo:
            raise IndexError("Nothing to redo.")

        # Push current state onto undo stack so we can undo the redo
        self._undo_stack.append(("undo", self._state.snapshot()))

        label, snapshot = self._redo_stack.pop()
        self._apply(snapshot)
        logger.info(
            "redo_applied",
            game_id=self._state.game_id,
        )
        return self._state

    def history_labels(self) -> list[str]:
        """Return labels of all recorded undo checkpoints (oldest first)."""
        return [label for label, _ in self._undo_stack]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply(self, snapshot: dict[str, Any]) -> None:
        """Overwrite every field of the live state from *snapshot* in-place."""
        restored = GameState.restore(snapshot)
        for field in GameState.model_fields:
            setattr(self._state, field, getattr(restored, field))
