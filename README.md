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
| `/engine` | Phase state machine (`RoundEngine`), undo/redo history (`GameHistory`), and player-options query (`get_player_options`) |
| `/adapters` | Converters from external game-state formats (e.g. AsyncTI4 JSON) into the engine's native `GameState` |
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

## AsyncTI4 Adapter

The `adapters.asyncti4` module converts the JSON snapshot produced by the
[AsyncTI4 Discord bot](https://github.com/AsyncTI4/TI4_map_generator_bot)
into the engine's native `GameState`.  The bot publishes each game's snapshot
to S3 at:

```
https://s3.us-east-1.amazonaws.com/asyncti4.com/webdata/{gameId}/{gameId}.json
```

```python
import json
from adapters.asyncti4 import from_asyncti4

with open("pbd22295.json") as fh:
    raw = json.load(fh)

state = from_asyncti4(raw)
print(state.game_id, state.phase, state.round_number)
# pbd22295 action 1
```

Key mapping from the AsyncTI4 JSON to `GameState`:

| AsyncTI4 JSON | `GameState` / `PlayerState` field | Notes |
|---|---|---|
| `gameName` | `game_id` | |
| `gameRound` | `round_number` | |
| `lawsInPlay` | `law_ids` | |
| `playerData[].userName` | player key + `player_id` | |
| `playerData[].faction` | `faction_id` | |
| `playerData[].totalVps` | `victory_points` | |
| `playerData[].scs` | `strategy_card_ids` | Ints converted to strings |
| `playerData[].techs` | `researched_technologies` | |
| `playerData[].tg` | `trade_goods` | |
| `playerData[].isSpeaker` | `turn_order.speaker_id` | Per-player flag |
| `playerData[].active` | `active_player_id` | Per-player flag |
| Phase | Inferred from `strategyCards[].played` | No explicit phase field |
| Action card IDs | *(not exposed)* | Only count (`acCount`) is exported |
| Promissory note IDs | *(not exposed)* | Only count (`pnCount`) is exported |

## Player Options

Given a `GameState` and a player ID, `get_player_options` returns every
action that player may legally take under TI4 rules at that moment:

```python
from engine import get_player_options
from engine.options import PlayerAction

options = get_player_options(state, player_id="alice")
print(options.phase, options.available_actions)
# action [tactical_action, component_action, strategic_action, pass]

if PlayerAction.STRATEGIC_ACTION in options.available_actions:
    print("Alice may use her strategy card's primary ability.")
```

The complete set of `PlayerAction` values:

| Action | Phase | Step | Condition |
|---|---|---|---|
| `pick_strategy_card` | Strategy | — | Player does not yet hold a strategy card |
| `tactical_action` | Action | — | Player has not passed |
| `strategic_action` | Action | — | Player has not passed **and** holds a strategy card |
| `component_action` | Action | — | Player has not passed |
| `pass` | Action | — | Player has not passed |
| `score_objective` | Status | 1 – Score Objectives | Always |
| `reveal_public_objective` | Status | 2 – Reveal Public Objective | Speaker only |
| `draw_action_cards` | Status | 3 – Draw Action Cards | Always |
| `remove_command_tokens` | Status | 4 – Remove Command Tokens | Always |
| `gain_and_redistribute_command_tokens` | Status | 5 – Gain & Redistribute Command Tokens | Always |
| `ready_cards` | Status | 6 – Ready Cards | Always |
| `repair_units` | Status | 7 – Repair Units | Always |
| `return_strategy_cards` | Status | 8 – Return Strategy Cards | Always |
| `replenish_commodities` | Agenda | 1 – Replenish Commodities | Always |
| `reveal_agenda` | Agenda | 2 – Reveal Agenda | Speaker only |
| `cast_votes` | Agenda | 3 – Vote | Always |
| `abstain` | Agenda | 3 – Vote | Always |
| `resolve_outcome` | Agenda | 4 – Resolve Outcome | Speaker only |
| `ready_planets` | Agenda | After both agendas | Always |

## Movement Range Evaluation

The `engine.movement` module evaluates which systems a fleet can reach in a
single tactical action.  `get_fleet_move` computes the fleet's effective
movement speed; `get_reachable_systems` performs a BFS over a `GalaxyMap`.

```python
from engine.movement import get_fleet_move, get_reachable_systems
from models.map import GalaxyMap, System, WormholeType, AnomalyType
from models.unit import Unit, UnitType

# Define unit stats
carrier = Unit(id="carrier", name="Carrier", unit_type=UnitType.CARRIER,
               cost=3, combat=9, move=2, capacity=4)
fighter = Unit(id="fighter", name="Fighter", unit_type=UnitType.FIGHTER,
               cost=1, combat=9, move=0)
unit_registry = {"carrier": carrier, "fighter": fighter}

# Build a simple 6-system map
galaxy = GalaxyMap(systems={
    "home":  System(id="home",  adjacent_system_ids=["A", "B"]),
    "A":     System(id="A",     adjacent_system_ids=["home", "C"]),
    "B":     System(id="B",     adjacent_system_ids=["home", "C"],
                                wormholes=[WormholeType.ALPHA]),
    "C":     System(id="C",     adjacent_system_ids=["A", "B", "D"]),
    "D":     System(id="D",     adjacent_system_ids=["C"]),
    "worm":  System(id="worm",  adjacent_system_ids=[],
                                wormholes=[WormholeType.ALPHA]),
})

fleet = {"carrier": 2, "fighter": 3}

move  = get_fleet_move(fleet, unit_registry)             # → 2 (fighters excluded)
reach = get_reachable_systems(galaxy, "home", move)
# → {"A", "B", "C", "worm"}  (worm reachable via alpha wormhole from B)

# With Gravity Drive technology: carriers move 3
move_gd = get_fleet_move(fleet, unit_registry, gravity_drive=True)  # → 3

# Enemy ships block further movement
reach_blocked = get_reachable_systems(
    galaxy, "home", move, enemy_ship_system_ids={"A"}
)
# → {"A", "B", "worm"}  (can enter A but not pass through)
```

### Anomaly rules

| Anomaly | Effect on movement |
|---|---|
| Supernova | Impassable – ships cannot enter |
| Nebula | Ships must stop upon entry; cannot move through |
| Asteroid Field | Ships must stop upon entry (Fighters/Mechs exempt) |
| Gravity Rift | +1 movement when entering; ships risk casualties on exit |

## Combat Simulation

`engine.combat.simulate_combat` runs a configurable number of independent
Monte Carlo space-combat simulations and returns win probabilities and expected
survivor counts.

```python
from engine.combat import CombatGroup, CombatUnit, simulate_combat
from models.unit import Unit, UnitType

dreadnought = Unit(id="dreadnought", name="Dreadnought",
                   unit_type=UnitType.DREADNOUGHT,
                   cost=4, combat=5, sustain_damage=True,
                   move=1, capacity=1, combat_rolls=2)
destroyer   = Unit(id="destroyer", name="Destroyer",
                   unit_type=UnitType.DESTROYER, cost=1, combat=9, move=2)
fighter     = Unit(id="fighter",   name="Fighter",
                   unit_type=UnitType.FIGHTER,   cost=1, combat=9)

attacker = CombatGroup([
    CombatUnit(dreadnought, count=2),
    CombatUnit(destroyer,   count=1),
])
defender = CombatGroup([
    CombatUnit(fighter, count=5),
])

result = simulate_combat(attacker, defender, simulations=5000, seed=42)
print(f"Attacker wins {result.attacker_win_probability:.1%}")
print(f"Defender wins {result.defender_win_probability:.1%}")
print(f"Avg rounds:   {result.average_rounds:.1f}")
print("Expected attacker survivors:", result.attacker_expected_survivors)
# Attacker wins ~98%
# Avg rounds: ~1.1

# Flat combat bonus from an Action Card (e.g. Morale Boost)
result_boosted = simulate_combat(
    attacker, defender, attacker_modifier=1, simulations=5000
)
```

### Combat mechanics

| Mechanic | Description |
|---|---|
| Combat rolls | Each unit rolls `combat_rolls` dice; roll ≥ `combat` value = hit |
| Sustain Damage | Unit absorbs 1 hit (takes damage token instead of being destroyed) |
| Hit assignment | Optimal heuristic: sustain high-cost units first, destroy cheapest first |
| Simultaneous | Both sides roll and assign hits at the same time each round |



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