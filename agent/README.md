# agent/ — game-playing AI for VCK Online

A headless simulator and a ladder of increasingly strong agents for Valeria
Card Kingdoms. Deals from `sql/seed/*.sql` in memory (no MariaDB). Scope so
far: base-set, 2-player.

## What's here

| Module | Purpose |
|---|---|
| `seed_data.py` | Parses `sql/seed/*.sql` into in-memory card tables |
| `fake_db.py` | Seeds `card_pool` + patches `db_config.connect` so `load_game_data` runs without MariaDB |
| `headless.py` | Build/advance/apply-move/clone `Game` objects; stall-safe random driver |
| `client.py` | HTTP client for the hosted/local VCK Online API |
| `fast_state.py` | Zero-copy dict-view over a live `Game` (optional fast enum path) |
| `policies.py` | `RandomPolicy` baseline and `GreedyPolicy` — VP-equivalent move valuation |
| `mcts.py` | Determinized open-loop MCTS with PUCT selection and ε-greedy rollouts |
| `move_summary.py` | Decision logging + ranked summaries (bot `--compare-greedy`, advisor mode) |
| `recommend.py` | Read-only move advisor: poll a human game's URL, suggest top-N moves, never play |
| `reconstruct.py` | Rebuild a playable `Game` from a server wire-state snapshot |
| `server_bot.py` | Host/join a lobby on a live server and play any policy over the REST API |
| `validate.py` | Invariant/parity/round-trip validation across hundreds of seeded games |
| `evaluate.py` / `play_random.py` | Head-to-head evaluation harness and random-playout smoke driver |

Legal moves come from `engines.available_actions` (same enumerator the server
attaches to wire state), with engine-exact effective costs stamped by
`agent.headless.legal_moves`.

## Quickstart (no database required)

```bash
# smoke test: full random games
python -m agent.play_random --games 10 --seed 1

# batch / throughput (multiprocess)
python3 scripts/run_headless_sim.py --benchmark --games 100 --workers 4

# validation suite
python -m agent.validate --games 300 --seed 1

# head-to-head: greedy vs random
python -m agent.evaluate --p1 greedy --p2 random --games 50 --seed 1

# host a bot lobby on the hosted server and play against it
python -m agent.server_bot --policy mcts --iterations 200 --host --preset base

# same, with root-parallel MCTS across CPU cores
python -m agent.server_bot --policy mcts --iterations 200 --workers 4 --host --preset base

# MCTS with side-by-side greedy comparison (still plays MCTS)
python -m agent.server_bot --policy mcts --compare-greedy --host --preset base

# after Ctrl-C / crash mid-game (session auto-saved to agent_session.json)
python -m agent.server_bot --policy mcts --resume

# play your seat in an existing game (paste the browser URL)
python -m agent.server_bot --policy mcts --iterations 200 --workers 4 \\
  --url 'https://vcko.lukesau.com/?game_id=...&player_id=...'

# move recommendation mode — advise on a live human game (never submits moves)
python -m agent.recommend --url 'https://vcko.lukesau.com/?game_id=...&player_id=...'

# one-shot recommendation for the current decision, then exit
python -m agent.recommend --url 'https://vcko.lukesau.com/?game_id=...&player_id=...' --once
```

When the bot plays, each greedy or MCTS action also logs a ranked summary
(visit counts and Q for MCTS; VP-equivalent scores for greedy). Use
`--compare-greedy` with MCTS to print both rankings plus agree/diverge notes.

**Move recommendation mode** (`agent.recommend`) attaches to a game you are
playing in the browser: paste the page URL, and it polls your seat, runs
greedy + MCTS, and prints the top 5 options from each — without executing
anything. Use `agent.server_bot --url` with the same link when you want the
bot to take over and play that seat automatically.

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
- Roadmap: event-composition sampling, learned policy priors (currently
  greedy-derived), pipeline iteration with search-generated data.
