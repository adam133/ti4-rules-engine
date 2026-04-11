"""
TI4 Rules Engine – adapters package.

Provides converters from external game-state formats into the engine's
native :class:`~models.state.GameState`.

Currently supported formats
---------------------------
* **AsyncTI4** – the JSON snapshot produced by the `AsyncTI4 Discord bot
  <https://github.com/AsyncTI4/TI4_map_generator_bot>`_.
  See :mod:`adapters.asyncti4` for details.
"""

from adapters.asyncti4 import AsyncTI4GameData, from_asyncti4

__all__ = ["AsyncTI4GameData", "from_asyncti4"]
