from __future__ import annotations

from ti4_rules_engine.scripts import _data_paths


def test_locate_asyncti4_resources_dir_finds_repo_layout(tmp_path, monkeypatch) -> None:
    resources_dir = tmp_path / "data" / "TI4_map_generator_bot" / "src" / "main" / "resources"
    resources_dir.mkdir(parents=True)
    monkeypatch.setattr(_data_paths, "_iter_search_roots", lambda: [tmp_path])
    assert _data_paths._locate_asyncti4_resources_dir() == resources_dir.resolve()


def test_locate_asyncti4_resources_dir_finds_packaged_layout(tmp_path, monkeypatch) -> None:
    resources_dir = (
        tmp_path
        / "ti4_rules_engine"
        / "data"
        / "TI4_map_generator_bot"
        / "src"
        / "main"
        / "resources"
    )
    resources_dir.mkdir(parents=True)
    monkeypatch.setattr(_data_paths, "_iter_search_roots", lambda: [tmp_path])
    assert _data_paths._locate_asyncti4_resources_dir() == resources_dir.resolve()
