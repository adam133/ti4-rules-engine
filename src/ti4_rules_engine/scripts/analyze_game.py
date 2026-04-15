"""Compatibility wrapper for the TI4 game analysis script.

The full implementation lives in :mod:`ti4_rules_engine.scripts.analyze_game_core`.
This file intentionally remains small while preserving existing import behavior.
"""

from __future__ import annotations

from typing import Any

from ti4_rules_engine.scripts import analyze_game_core as _core

main = _core.main


def __getattr__(name: str) -> Any:
    return getattr(_core, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))


if __name__ == "__main__":
    main()
