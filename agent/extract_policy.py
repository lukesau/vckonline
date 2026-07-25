"""Extract policy-head training data from recorded MCTS visit distributions.

Reads `agent.selfplay --record-visits` output (records with "visit_counts"),
featurizes each decision under the CURRENT feature/move encodings, and writes
grouped arrays: one state row per decision, contiguous candidate move rows,
offsets, and visit-share targets.

Usage:
  python -m agent.extract_policy --states "agent/data/sp3_chunk*.jsonl.gz" \
      --out agent/data/policy_v1.npz
"""

import argparse
import contextlib
import glob
import gzip
import io
import json
import time
from pathlib import Path

import numpy as np

_SINK = io.StringIO()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", required=True,
                        help="glob of .jsonl.gz files from selfplay --record-visits")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-moves", type=int, default=2)
    args = parser.parse_args()

    from game_serialization import deserialize_save_dict_to_game

    from agent import fake_db
    from agent.features import FEATURE_VERSION, N_FEATURES
    from agent.policy_net import N_MOVE_FEATURES, featurize_decision
    from agent.policies import GreedyPolicy

    fake_db.install()
    greedy = GreedyPolicy()

    paths = sorted(glob.glob(args.states))
    if not paths:
        raise SystemExit(f"no files match {args.states!r}")

    states, move_rows, targets = [], [], []
    starts = [0]
    skipped = 0
    t0 = time.perf_counter()
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                    counts = record.get("visit_counts")
                    if not counts or len(counts) < args.min_moves:
                        skipped += 1
                        continue
                    moves = [m for m, _ in counts]
                    visits = np.asarray([max(0, int(v)) for _, v in counts], dtype=np.float64)
                    total = visits.sum()
                    if total <= 0:
                        skipped += 1
                        continue
                    with contextlib.redirect_stdout(_SINK):
                        game = deserialize_save_dict_to_game(record["state"])
                        game.sim_mode = True
                        state_vec, move_mat = featurize_decision(
                            game, record["to_move"], moves, greedy=greedy
                        )
                except Exception:
                    skipped += 1
                    continue
                states.append(state_vec)
                move_rows.append(move_mat)
                targets.append((visits / total).astype(np.float32))
                starts.append(starts[-1] + len(moves))
        print(f"  {path}: {len(states)} decisions so far "
              f"({time.perf_counter() - t0:.0f}s)", flush=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        states=np.stack(states),
        moves=np.concatenate(move_rows),
        starts=np.asarray(starts, dtype=np.int64),
        targets=np.concatenate(targets),
        feature_version=FEATURE_VERSION,
        n_state=N_FEATURES,
        n_move=N_MOVE_FEATURES,
    )
    print(f"wrote {out}: {len(states)} decisions, "
          f"{starts[-1]} candidate rows ({skipped} skipped)")


if __name__ == "__main__":
    main()
