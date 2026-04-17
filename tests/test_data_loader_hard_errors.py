from __future__ import annotations

import pathlib

import pytest

from ti4_rules_engine.scripts import _data_loaders, _hyperlanes


def test_fetch_tech_names_raises_when_data_dir_missing(monkeypatch) -> None:
    _data_loaders._load_tech_names_cached.cache_clear()
    monkeypatch.setattr(
        _data_loaders,
        "_TECH_DATA_DIR",
        pathlib.Path("/tmp/does-not-exist/technologies"),
    )

    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_tech_names()

    _data_loaders._load_tech_names_cached.cache_clear()


def test_fetch_leader_data_raises_when_data_dir_missing(monkeypatch) -> None:
    _data_loaders._load_leader_data_cached.cache_clear()
    monkeypatch.setattr(
        _data_loaders,
        "_LEADERS_DATA_DIR",
        pathlib.Path("/tmp/does-not-exist/leaders"),
    )

    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_leader_data()

    _data_loaders._load_leader_data_cached.cache_clear()


def test_fetch_system_data_raises_when_data_dir_missing(monkeypatch) -> None:
    _data_loaders._load_system_data_cached.cache_clear()
    monkeypatch.setattr(
        _data_loaders, "_ASYNCTI4_SYSTEMS_DATA_DIR", pathlib.Path("/tmp/does-not-exist/systems")
    )

    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_system_data()

    _data_loaders._load_system_data_cached.cache_clear()


def test_fetch_planet_data_raises_when_data_dir_missing(monkeypatch) -> None:
    _data_loaders._load_planet_data_cached.cache_clear()
    monkeypatch.setattr(
        _data_loaders, "_ASYNCTI4_PLANETS_DATA_DIR", pathlib.Path("/tmp/does-not-exist/planets")
    )

    with pytest.raises(FileNotFoundError):
        _data_loaders.fetch_planet_data()

    _data_loaders._load_planet_data_cached.cache_clear()


def test_load_hyperlane_connections_raises_when_data_file_missing(monkeypatch) -> None:
    _hyperlanes._load_hyperlane_connections.cache_clear()
    monkeypatch.setattr(
        _hyperlanes,
        "_HYPERLANES_DATA_FILE",
        pathlib.Path("/tmp/does-not-exist/hyperlanes.properties"),
    )

    with pytest.raises(FileNotFoundError):
        _hyperlanes._load_hyperlane_connections()

    _hyperlanes._load_hyperlane_connections.cache_clear()
