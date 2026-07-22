"""Re-extract feature vectors from stored self-play states.

Feature engineering loop: edit agent/features.py, re-run this (no game
replays needed), retrain.

Usage:
  python -m agent.extract_features --states "agent/data/sp2_chunk*.jsonl.gz" \
      --out agent/data/selfplay_v2.npz
"""

import argparse
import glob
import gzip
import json
import time
from pathlib import Path

import numpy as np

from agent.features import FEATURE_VERSION, extract


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", required=True,
                        help="glob of .jsonl.gz state files from agent.selfplay --store-states")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from game_serialization import deserialize_save_dict_to_game

    paths = sorted(glob.glob(args.states))
    if not paths:
        raise SystemExit(f"no files match {args.states!r}")
    xs, ys = [], []
    bad = 0
    start = time.perf_counter()
    for path in paths:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        record = json.loads(line)
                        game = deserialize_save_dict_to_game(record["state"])
                        for viewer, outcome in record["outcomes"].items():
                            xs.append(extract(game, viewer))
                            ys.append(float(outcome))
                    except Exception:
                        bad += 1
        except (EOFError, OSError):
            # still-being-written / truncated gzip stream: keep what we got
            bad += 1
        print(f"  {path}: {len(xs)} rows so far ({time.perf_counter() - start:.0f}s)", flush=True)
    x = np.stack(xs)
    y = np.asarray(ys, dtype=np.float32)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, x=x, y=y, feature_version=FEATURE_VERSION)
    print(f"wrote {out}: {len(x)} rows x {x.shape[1]} features ({bad} bad records)")


if __name__ == "__main__":
    main()
