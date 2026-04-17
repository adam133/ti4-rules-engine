from __future__ import annotations

import pathlib

from ti4_rules_engine.scripts import _data_loaders


def test_fetch_strategy_card_data_falls_back_to_remote_set_file(
    monkeypatch,
) -> None:
    _data_loaders._load_strategy_card_data_cached.cache_clear()
    _data_loaders._load_strategy_card_set_data_cached.cache_clear()

    monkeypatch.setattr(_data_loaders, "_load_json_records_from_dir", lambda _: [])
    monkeypatch.setattr(
        _data_loaders,
        "fetch_strategy_card_set_data",
        lambda: {"pok": {"alias": "pok", "name": "Prophecy of Kings"}},
    )

    requested_urls: list[str] = []

    def _fake_load_json_records_from_url(url: str) -> list[dict[str, object]]:
        requested_urls.append(url)
        if not url.endswith("/strategy_cards/pok.json"):
            return []
        return [
            {
                "id": "pok1leadership",
                "initiative": 1,
                "name": "Leadership",
                "primaryTexts": ["Gain 3 command tokens"],
                "secondaryTexts": [
                    "Spend any amount of influence to gain 1 command token "
                    "for every 3 influence spent"
                ],
            }
        ]

    monkeypatch.setattr(
        _data_loaders,
        "_load_json_records_from_url",
        _fake_load_json_records_from_url,
    )

    cards = _data_loaders.fetch_strategy_card_data()
    assert cards["pok1leadership"]["name"] == "Leadership"
    assert cards["pok1leadership"]["primary"] == "Gain 3 command tokens"
    assert "every 3 influence spent" in cards["pok1leadership"]["secondary"]
    assert any(url.endswith("/strategy_cards/pok.json") for url in requested_urls)

    _data_loaders._load_strategy_card_data_cached.cache_clear()
    _data_loaders._load_strategy_card_set_data_cached.cache_clear()


def test_fetch_strategy_card_set_data_falls_back_to_remote_file(monkeypatch) -> None:
    _data_loaders._load_strategy_card_set_data_cached.cache_clear()

    monkeypatch.setattr(
        _data_loaders,
        "_STRATEGY_CARD_SETS_FILE",
        pathlib.Path("/tmp/does-not-exist/strategyCardSets.json"),
    )
    monkeypatch.setattr(
        _data_loaders,
        "_load_json_records_from_url",
        lambda _: [
            {
                "alias": "pok",
                "name": "Prophecy of Kings",
                "description": "Default PoK strategy card set",
                "source": "pok",
                "scIDs": ["pok1leadership", "pok2diplomacy"],
            }
        ],
    )

    sets = _data_loaders.fetch_strategy_card_set_data()
    assert sets["pok"]["name"] == "Prophecy of Kings"
    assert sets["pok"]["scIDs"] == ["pok1leadership", "pok2diplomacy"]

    _data_loaders._load_strategy_card_set_data_cached.cache_clear()


def test_load_json_records_from_url_rejects_untrusted_urls(monkeypatch) -> None:
    def _raise_if_called(*_args, **_kwargs):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(
        _data_loaders,
        "urlopen",
        _raise_if_called,
    )

    rejected_urls = [
        "https://example.com/data.json",
        "http://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/src/main/resources/data/strategy_cards/pok.json",
        "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/README.md",
        "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/src/other/file.json",
        "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/src/main/resources/data/strategy_cards/../pok.json",
        "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/src/main/resources/data/strategy_cards/%2e%2e/pok.json",
        "https://raw.githubusercontent.com/AsyncTI4/TI4_map_generator_bot/master/src/main/resources/data/strategy_cards/%2fpok.json",
    ]
    for url in rejected_urls:
        assert _data_loaders._load_json_records_from_url(url) == []
