# agent/ — game-playing AI for VCK Online

A headless simulator and a ladder of increasingly strong agents for Valeria
Card Kingdoms, built entirely alongside the existing engine — **no engine,
server, or bots/ files are modified**. Scope so far: base-set, 2-player.

## What's here

| Module | Purpose |
|---|---|
| `seed_data.py` | Parses `sql/seed/*.sql` into in-memory card tables — no MariaDB needed |
| `fake_db.py` | In-memory stand-in for `db_config.connect` so the real `load_game_data` bootstrap runs unmodified |
| `headless.py` | Build/advance/apply-move/clone `Game` objects in-process (mirrors server.py's action dispatch) |
| `moves.py` | Legal-move enumeration with engine-exact costs and prompt verbs (fixes several gaps in `bots/legal_moves.py`) |
| `fast_state.py` | Zero-copy dict-view over a live `Game` (~10x faster than JSON serialization per step) |
| `policies.py` | `RandomPolicy` baseline and `GreedyPolicy` — VP-equivalent move valuation incl. duke scoring deltas and expected future harvest income |
| `mcts.py` | Determinized open-loop MCTS with PUCT selection (greedy-softmax priors) and ε-greedy rollouts |
| `reconstruct.py` | Rebuild a playable `Game` from a server wire-state snapshot (samples hidden info) |
| `server_bot.py` | Host/join a lobby on a live server and play any policy over the REST API |
| `validate.py` | Invariant/parity/round-trip validation across hundreds of seeded games |
| `evaluate.py` / `play_random.py` | Head-to-head evaluation harness and random-playout smoke driver |

## Quickstart (no database required)

```bash
# smoke test: full random games, ~0.2s each
python -m agent.play_random --games 10 --seed 1

# validation suite
python -m agent.validate --games 300 --seed 1

# head-to-head: greedy vs random
python -m agent.evaluate --p1 greedy --p2 random --games 50 --seed 1

# host a bot lobby on the hosted server and play against it
python -m agent.server_bot --policy mcts --iterations 200 --host --preset base
```

## Results (2-player, seat-alternating, seeded)

| Matchup | Result |
|---|---|
| Greedy vs Random | 86–88% (n=50) |
| MCTS (100 iter) vs Random | 100% (n=10) |
| MCTS (100 iter) vs Greedy | 70% (n=50) |
| MCTS (200 iter) vs Greedy | 80% (n=20) |
| MCTS (400 iter) vs Greedy | 80% (n=10) |

MCTS is determinized (ISMCTS-style): each search iteration re-randomizes
buried domain cards, the undealt event deck order, and the opponent's duke —
it does not peek at hidden information.

## Engine findings made along the way

- The engine is fully synchronous (docs/game.md's background-thread note is
  stale) and silently ignores malformed prompt responses.
- `bots/legal_moves.py` emits generic verbs/printed costs for several prompts
  the engine keys on specific verbs/effective costs; `agent/moves.py`
  documents and implements the full verb + payment table.
- Latent engine bug: returning an owned Undead Samurai minion via a
  `domain_return_owned` prompt raises IndexError when the Lord event
  registered its area as a 6th `monster_stack_areas` entry
  (`engines/domain_effects.py` `_return_monster_to_stack`).

## Self-play training pipeline

| Module | Purpose |
|---|---|
| `features.py` | Viewer-relative state features (projected VP via the engine's scorer, income model, tableau/board depletion) |
| `selfplay.py` | Generate labeled positions from ε-greedy self-play (~160k positions from 3k games in ~80s) |
| `value_net.py` / `train_value.py` | Numpy MLP predicting P(win); v1 reaches ~72% held-out accuracy |
| `models/value_v1.npz` | Committed trained weights; used by the `mcts-nn` policy |

```bash
python -m agent.selfplay --games 3000 --seed 1 --out agent/data/selfplay_v1.npz
python -m agent.train_value --data agent/data/selfplay_v1.npz --out agent/models/value_v1.npz
python -m agent.evaluate --p1 mcts-nn --p2 greedy --games 20 --iterations 100
```

`mcts-nn` replaces MCTS leaf rollouts with the value net (~5x cheaper per
iteration). The pipeline loops: regenerate data with the stronger agent,
retrain, re-evaluate.

## Known simplifications / next steps

- Reconstruction models the face-down event deck as blank Exhausted tokens.
- Greedy's effect-string valuation is approximate for unusual payouts.
- Roadmap: move-recommendation mode, event-composition sampling, learned
  policy priors (currently greedy-derived), pipeline iteration with
  search-generated data.
