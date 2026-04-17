from __future__ import annotations

import pathlib

import pytest

from ti4_rules_engine.scripts import _data_loaders


def test_fetch_strategy_card_data_loads_local_dataset() -> None:
    _data_loaders._load_strategy_card_data_cached.cache_clear()

    cards = _data_loaders.fetch_strategy_card_data()
    assert cards
    assert any(card.get("name") == "Leadership" for card in cards.values())
    _data_loaders._load_strategy_card_data_cached.cache_clear()


def test_fetch_strategy_card_data_raises_when_local_dataset_missing(monkeypatch) -> None:
    _data_loaders._load_strategy_card_data_cached.cache_clear()

    monkeypatch.setattr(
        _data_loaders,
        "_STRATEGY_CARD_DATA_DIR",
        pathlib.Path("/tmp/does-not-exist/strategy_cards"),
    )

    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_strategy_card_data()

    _data_loaders._load_strategy_card_data_cached.cache_clear()


def test_fetch_strategy_card_set_data_raises_when_local_file_missing(monkeypatch) -> None:
    _data_loaders._load_strategy_card_set_data_cached.cache_clear()

    monkeypatch.setattr(
        _data_loaders,
        "_STRATEGY_CARD_SETS_FILE",
        pathlib.Path("/tmp/does-not-exist/strategyCardSets.json"),
    )
    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_strategy_card_set_data()

    _data_loaders._load_strategy_card_set_data_cached.cache_clear()
