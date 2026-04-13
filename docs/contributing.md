# Contributing

## Tech Stack

| Concern | Library |
|---|---|
| Data Modelling | [Pydantic V2](https://docs.pydantic.dev/latest/) |
| Package Management | [uv](https://docs.astral.sh/uv/) |
| State Machine | [transitions](https://github.com/pytransitions/transitions) |
| Structured Logging | [structlog](https://www.structlog.org/) |
| API Layer (optional) | [FastAPI](https://fastapi.tiangolo.com/) |
| Runtime | Python 3.12+ |

## Getting Started

### 1. Install the package

The package must be installed before running any scripts or tests.

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

> **Note:** Moving the `adapters`/`engine` imports to the top of
> `scripts/analyze_game.py` means the script now requires the package to be
> installed.  Running `scripts/analyze_game.py` directly with a bare
> `PYTHONPATH` override is no longer supported; use the installed `ti4-analyze`
> command or `python -m scripts.analyze_game` from an activated virtualenv
> instead.

### 2. Run the tests

```bash
python -m pytest
```

### 3. Lint

```bash
ruff check .
ruff format --check .
```

## Roadmap

### Phase 1 – Foundation & Schema ✅
- [x] Pydantic V2 models: `Faction`, `Unit`, `Technology`, `StrategyCard`, `ActionCard`, `Planet`
- [x] `GameState` root object with full JSON round-trip support
- [x] Asset mapping utilities

### Phase 2 – Action & Effect Framework ✅
- [x] `ComponentRegistry` – searchable database of all game components
- [x] `EffectRegistry` – query active modifiers by trigger and owner
- [x] `Effect` schema matching the problem-statement design

### Phase 3 – State Machine & Transitions ✅
- [x] `RoundEngine` – phase state machine (Strategy → Action → Status → Agenda)
- [x] `GameHistory` – undo/redo with configurable depth
- [x] Structured logging via `structlog` on every phase transition

### Phase 4 – External State Ingestion & Player Options ✅
- [x] `AsyncTI4` adapter – parse the AsyncTI4 Discord bot JSON export into native `GameState`
- [x] `get_player_options` – return rules-allowable actions for a player given the current state

### Phase 5 – Phase Step Tracking ✅
- [x] `StatusPhaseStep` enum – the 8 ordered steps of the TI4 Status Phase (per the Living Rules Reference)
- [x] `AgendaPhaseStep` enum – the ordered steps of the TI4 Agenda Phase (replenish → reveal → vote → resolve, ×2 then ready planets)
- [x] `status_phase_step` / `agenda_phase_step` / `agendas_resolved` fields on `GameState`
- [x] `command_tokens` and `commodities_cap` fields on `PlayerState`
- [x] `RoundEngine.advance_status_step()` – advances through the 8 Status Phase steps
- [x] `RoundEngine.advance_agenda_step()` – advances through the Agenda Phase (handles two-agenda cycle)
- [x] Step-aware `get_player_options` – returns only the actions legal for the *current* phase step; speaker-only actions (reveal objective, reveal agenda, resolve outcome) restricted to the speaker

### Phase 6 – Tactical Action Support ✅
- [x] `models.map` – `System` and `GalaxyMap` models with hex adjacency, wormholes, and anomalies
- [x] `engine.movement.get_fleet_move` – effective movement value for a fleet (minimum move of all non-transported ships, +Gravity Drive bonus)
- [x] `engine.movement.get_reachable_systems` – BFS over the galaxy map returning all systems reachable in one tactical action, respecting anomaly rules (supernova impassable, nebula/asteroid must-stop, gravity rift +1 bonus) and enemy-ship blocking
- [x] `engine.combat.simulate_combat` – Monte Carlo space-combat simulation returning win probabilities and expected survivor counts for any two opposing fleets

### Phase 7 – Scoring Methods ✅
- [x] `models.objective` – `Objective`, `ObjectiveType`, `ScoringCondition`, `ScoringConditionType` models covering all TI4 scoring categories (Stage I/II public, secret, other)
- [x] `engine.scoring.can_score_objective` – evaluates whether a player meets an objective's condition; returns `True`/`False`/`None` (permissive design)
- [x] `engine.scoring.score_points_available` – sums VP across a list of objectives a player can provably score right now
- [x] Technology conditions fully evaluated from `PlayerState.researched_technologies` (unit upgrades, tech color counts)
- [x] Planet conditions fully evaluated from `PlayerState.controlled_planets` + planet registry (trait, tech skip, legendary, Mecatol Rex, outside home system)
- [x] Fleet/board conditions and spend conditions return `None` with a clear contract for manual player confirmation
- [x] `ComponentRegistry.register_objective` – objectives are first-class registered components

### Phase 8 – Opponent Public Info ✅
- [x] `PublicPlayerInfo` model – publicly observable actions and scoring potential for any player
- [x] `get_public_player_info` – returns `PublicPlayerInfo` for a player using only public state: excludes `component_action` (requires private action cards), scores only against revealed public objectives (`state.public_objectives`)
- [x] `get_all_opponents_public_info` – convenience wrapper returning a `{player_id → PublicPlayerInfo}` mapping for every opponent of the viewing player
