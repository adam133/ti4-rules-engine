# TI4 Rules Engine

A Pythonic, structured data engine for Twilight Imperium 4th Edition. This
repository serves as a headless "Game Master" that tracks game state, provides
rule references, and calculates entity modifiers.

## Overview

Unlike a strict simulator, this engine is designed to be **permissive but
aware**. It provides the data structures and logic required to run a game of
TI4, but allows external controllers (like Discord bots or Web UIs) to decide
when and how to enforce specific constraints.

## Architecture

The project follows a modular architecture where data (Models) is separated
from game flow (Engine).

| Package | Purpose |
|---|---|
| `/models` | Pydantic V2 schemas for Factions, Planets, Units, Technologies, and Cards |
| `/engine` | Phase state machine (`RoundEngine`) and undo/redo history (`GameHistory`) |
| `/registry` | Searchable component database (`ComponentRegistry`) and modifier system (`EffectRegistry`) |
| `/utils` | Asset-mapping utilities for linking game IDs to visual assets |

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

### 1. Install dependencies

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### 2. Run the tests

```bash
python -m pytest
```

### 3. Define a game session

```python
from models import GameState, GamePhase, TurnOrder
from models.state import PlayerState
from engine import RoundEngine, GameHistory

# --- Build the initial state ---
state = GameState(
    game_id="my-game",
    round_number=1,
    turn_order=TurnOrder(
        speaker_id="alice",
        order=["alice", "bob", "carol"],
    ),
    players={
        "alice": PlayerState(player_id="alice", faction_id="the_universities_of_jol_nar"),
        "bob":   PlayerState(player_id="bob",   faction_id="the_emirates_of_hacan"),
        "carol": PlayerState(player_id="carol", faction_id="the_federation_of_sol"),
    },
)

# --- Attach the engine ---
history = GameHistory(state)
engine  = RoundEngine(state)

# --- Advance through the round ---
history.checkpoint("before_action_phase")
engine.begin_action_phase()

# undo if needed
history.undo()
assert state.phase == GamePhase.STRATEGY
```

## Modifier System

Instead of hard-coding logic for cards like *Morale Boost*, the engine exposes
an `EffectRegistry` that surfaces all active modifiers for a given trigger
without enforcing them. External controllers decide when (and whether) to apply
the effects.

```python
from registry import EffectRegistry, Effect, TriggerType

reg = EffectRegistry()

reg.add_effect(Effect(
    name="Morale Boost",
    trigger=TriggerType.COMBAT_ROLL,
    modifier=1,
    source="Morale Boost Action Card",
    owner_id="alice",
))

# Query all active combat-roll bonuses for Alice
bonuses = reg.query(TriggerType.COMBAT_ROLL, owner_id="alice")
total   = sum(e.modifier for e in bonuses)   # → 1
```

## Component Registry

All game components (technologies, cards, factions, planets, units) can be
registered and looked up by ID or fuzzy name search:

```python
from registry import ComponentRegistry
from models import Technology, TechCategory

reg = ComponentRegistry()
reg.register_technology(Technology(
    id="neural_motivator",
    name="Neural Motivator",
    category=TechCategory.BIOTIC,
    description="During the Status Phase, draw 2 Action Cards (instead of 1).",
))

tech = reg.get("neural_motivator")
hits = reg.search("neural")   # partial name search
```

## Asset Mapping

Asset paths follow the naming conventions established in the
[TI4 Map Generator Bot](https://github.com/PaxAndromedia/TI4_map_generator_bot)
to ensure compatibility with existing rendering tools:

```python
from utils import AssetMapper, AssetType

mapper = AssetMapper(base_path="/assets/ti4")

# /assets/ti4/factions/jol_nar_icon.png
path = mapper.resolve("jol_nar", AssetType.FACTION_ICON)

# Override paths for non-standard assets
mapper.register_override("ghosts_of_creuss", AssetType.FACTION_ICON, "/custom/creuss.png")
```

## Project Roadmap

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