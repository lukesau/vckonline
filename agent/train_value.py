"""Train the value net on self-play data.

Usage:
  python -m agent.train_value --data agent/data/selfplay_v1.npz --out agent/models/value_v1.npz
"""

import argparse
from pathlib import Path

import numpy as np

from agent.value_net import ValueNet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="agent/data/selfplay_v1.npz")
    parser.add_argument("--out", default="agent/models/value_v1.npz")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--hidden", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    data = np.load(args.data)
    x, y = data["x"].astype(np.float32), data["y"].astype(np.float32)
    print(f"training on {len(x)} positions x {x.shape[1]} features "
          f"(mean outcome {y.mean():.3f})")
    net = ValueNet(n_in=x.shape[1], n_hidden=args.hidden, seed=args.seed)
    net.train(x, y, epochs=args.epochs, lr=args.lr, seed=args.seed)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    net.save(out)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
