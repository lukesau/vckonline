"""The unit of work: one selfplay game, as a Ray task.

One game rather than a chunk of 130. At the measured pace (12-38 min/game
depending on cohort) a single game is already a well-sized Ray task: long
enough that scheduling overhead is noise, short enough that a retry costs
minutes instead of days and that a slow node can't hold up a cohort.
"""
from __future__ import annotations

import gzip
import json
import random

import ray


def _play(seed: int, cfg: dict) -> tuple[int, bytes]:
    """Play one game, return its records as a gzip member.

    Returns gzip BYTES rather than a list of dicts for two reasons: it is
    ~4x smaller through the object store (~550KB vs ~2MB per game), and gzip
    members concatenate — so the driver appends the blob to a shard file
    verbatim, with no decompress/recompress cycle. A shard built this way is
    an ordinary multi-member .jsonl.gz that gzip and Python read normally.
    """
    # agent.* resolves via runtime_env working_dir; the value/policy nets are
    # loaded from RELATIVE paths (agent/models/value_v5.npz), so this only
    # works because Ray sets cwd to the working_dir copy. See docs/porting.md.
    from agent.selfplay import build_records, play_selfplay_game

    # play_selfplay_game passes `seed` only to new_game() — the deal. Policy
    # temperature sampling reads the GLOBAL random module (selfplay.py:64),
    # which upstream never reseeds, so a game is not reproducible from its
    # seed alone. Seeding here makes the task genuinely deterministic, which
    # is what lets a Ray retry reproduce the same game rather than silently
    # generating a different one under the same ledger entry.
    random.seed(seed)

    result = play_selfplay_game(
        seed,
        policy_name=cfg["policy"],
        iterations=cfg["iterations"],
        collect_states=True,
        record_visits=cfg["record_visits"],
        preset=cfg["preset"],
        num_players=cfg["players"],
        turn_priors=cfg["turn_priors"],
    )
    if result is None:
        # Upstream returns None for a stuck/overlong game and main() counts it
        # as "skipped". Not an error - the driver records it and moves on.
        return 0, b""

    samples, game = result
    # Shared with selfplay.py's CLI path deliberately: both write into the same
    # shard files, so a divergence in record shape would corrupt the dataset
    # silently. This used to be a copy of that loop.
    lines = [json.dumps(r) for r in build_records(samples, game)]
    if not lines:
        return 0, b""
    return len(lines), gzip.compress(("\n".join(lines) + "\n").encode("utf-8"))


# num_cpus=1 because the game loop is genuinely single-threaded (measured:
# CPU time == wall time). The env vars stop numpy/BLAS from spawning a pool
# per task - harmless for Kyle's 34 hand-launched processes, but under Ray
# every concurrent task would spawn one and oversubscribe the node against
# Ray's own accounting.
@ray.remote(num_cpus=1, max_retries=2)
def play_game(seed: int, cfg: dict) -> tuple[int, int, bytes]:
    n_records, blob = _play(seed, cfg)
    return seed, n_records, blob
