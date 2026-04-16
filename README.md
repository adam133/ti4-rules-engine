# TI4 Rules Engine

A Pythonic, structured data engine for Twilight Imperium 4th Edition. Tracks
game state, provides rule references, and calculates player options from a live
[AsyncTI4](https://github.com/AsyncTI4/TI4_map_generator_bot) Discord bot game.

## Analyse a game in one command

No installation required — just `uvx`:

```bash
uvx --from ti4-rules-engine ti4-analyze <game_name>
```

Replace `<game_name>` with the name of your AsyncTI4 game (the identifier shown
by the bot, e.g. `pbd22295`):

```
uvx --from ti4-rules-engine ti4-analyze pbd22295
```

The command fetches the live game snapshot from the AsyncTI4 API and prints:

- Current round, phase, and active player
- Per-player summary: faction, VP, resources, planets, technologies, and leaders
- Every legal action available to each player under TI4 rules right now
- Reachable systems for each fleet (movement + anomaly rules applied)

> **Note:** `uvx --from ti4-rules-engine` requires the package to be published
> on PyPI.  Until then, clone the repo and use the local install instead:
>
> ```bash
> git clone --recurse-submodules https://github.com/adam133/ti4-rules-engine
> cd ti4-rules-engine
> uv tool install .
> ti4-analyze pbd22295
> ```
>
> **Development note:** this repository reads game data from a git submodule
> (`data/TI4_map_generator_bot`), so local development requires cloning with
> submodules (or running `git submodule update --init --recursive` in an
> existing clone).

### What it shows

```
============================================================
Game:   pbd22295   Round: 3   Phase: action
Active: sargun
============================================================

  sargun [ACTIVE]
    Faction:  Nekro Virus
    VP:       5
    TG:       3  |  Commodities: 0
    Tokens:   3 tactical / 5 fleet / 2 strategy
    Planets:  8 controlled, 2 exhausted
    ...
    Actions available:
      • tactical_action
      • component_action
      • strategic_action
```

## Further reading

- **[docs/implementation.md](docs/implementation.md)** — module reference and
  API examples (game session setup, modifier system, combat simulation, scoring,
  movement, opponent public info)
- **[docs/contributing.md](docs/contributing.md)** — local dev setup, running
  tests, and project roadmap
