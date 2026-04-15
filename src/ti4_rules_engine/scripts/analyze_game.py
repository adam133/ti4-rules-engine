"""Compatibility wrapper for the TI4 game analysis script.

The full implementation lives in :mod:`ti4_rules_engine.scripts.analyze_game_core`.
This file intentionally remains small and re-exports all script helpers so existing
imports continue to work.
"""

from __future__ import annotations

from ti4_rules_engine.scripts.analyze_game_core import *  # noqa: F403
from ti4_rules_engine.scripts.analyze_game_core import main


if __name__ == "__main__":
    main()
