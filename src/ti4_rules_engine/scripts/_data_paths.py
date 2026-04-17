"""Shared path resolution for AsyncTI4 submodule data."""

from __future__ import annotations

import pathlib

_SUBMODULE_RESOURCES_RELATIVE_PATH_CANDIDATES = (
    pathlib.Path("data/TI4_map_generator_bot/src/main/resources"),
    pathlib.Path("ti4_rules_engine/data/TI4_map_generator_bot/src/main/resources"),
)


def _iter_search_roots() -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []
    cwd = pathlib.Path.cwd().resolve()
    roots.append(cwd)
    roots.extend(cwd.parents)

    module_path = pathlib.Path(__file__).resolve()
    roots.extend(module_path.parents)
    return roots


def _locate_asyncti4_resources_dir() -> pathlib.Path:
    checked: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for root in _iter_search_roots():
        for relative_path in _SUBMODULE_RESOURCES_RELATIVE_PATH_CANDIDATES:
            candidate = (root / relative_path).resolve()
            if candidate in seen:
                continue
            seen.add(candidate)
            checked.append(candidate)
            if candidate.is_dir():
                return candidate
    checked_paths = ", ".join(str(path) for path in checked)
    raise FileNotFoundError(
        "Required AsyncTI4 submodule resources directory was not found. "
        "Expected one of: data/TI4_map_generator_bot/src/main/resources, "
        "ti4_rules_engine/data/TI4_map_generator_bot/src/main/resources. "
        f"Checked: {checked_paths}"
    )


ASYNCTI4_RESOURCES_DIR = _locate_asyncti4_resources_dir()
DATA_DIR = ASYNCTI4_RESOURCES_DIR / "data"
