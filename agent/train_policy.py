"""Train the policy head on extracted visit-distribution data.

Usage:
  python -m agent.train_policy --data agent/data/policy_v1_data.npz \
      --out agent/models/policy_v1.npz
"""

import argparse
from pathlib import Path

import numpy as np

from agent.policy_net import PolicyNet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    data = np.load(args.data)
    states = data["states"].astype(np.float32)
    moves = data["moves"].astype(np.float32)
    starts = data["starts"]
    targets = data["targets"].astype(np.float32)
    n_dec = len(starts) - 1
    print(f"training on {n_dec} decisions, {len(moves)} candidate rows "
          f"({len(moves) / max(1, n_dec):.1f} avg candidates)")
    net = PolicyNet(n_state=states.shape[1], n_move=moves.shape[1],
                    n_hidden=args.hidden, seed=args.seed)
    net.train(states, moves, starts, targets, epochs=args.epochs,
              lr=args.lr, seed=args.seed)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    net.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
