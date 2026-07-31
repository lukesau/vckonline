"""Campaign driver: allocates seeds, fans games out over Ray, assembles shards.

Replaces run_gen_v2.sh. Resume is skip-completed-work: every finished game is
appended to a ledger; on restart the driver queues only seeds not yet listed.

Usage:
    python -m vcko_ray.driver
    python -m vcko_ray.driver --campaign mp3p_search --limit 20
    python -m vcko_ray.driver --status
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import tomllib
from collections import Counter, deque
from pathlib import Path

import ray

from vcko_ray.task import play_game

# This package lives inside the basegame-vcko checkout, so the repo root IS
# the engine root. Before the merge these were two trees and the driver had to
# be pointed at the engine with --vcko-root; that pointer no longer exists to
# get wrong. VCKO_ROOT still overrides, for running against a second checkout.
REPO = Path(__file__).resolve().parent.parent
DEFAULT_VCKO_ROOT = Path(os.environ.get("VCKO_ROOT", str(REPO))).expanduser()
DEFAULT_RAY_ADDRESS = os.environ.get("RAY_ADDRESS", "192.168.1.10:6380")


def load_campaigns(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def read_ledger(path: Path) -> set[tuple[str, int]]:
    """Seeds already generated, as (campaign, seed).

    Tolerates a truncated final line: the ledger is appended to while games
    are in flight, so an interrupted run can leave one partial entry. That is
    the only line it is ever safe to lose, and skipping it just means the
    corresponding game is replayed.
    """
    done: set[tuple[str, int]] = set()
    if not path.exists():
        return done
    with open(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            done.add((e["campaign"], e["seed"]))
    return done


def resolve_paths(cfgs: dict, campaigns_path: Path) -> tuple[Path, Path]:
    out_dir = Path(cfgs["output"]["dir"])
    if not out_dir.is_absolute():
        out_dir = REPO / out_dir
    ledger_path = Path(cfgs["output"]["ledger"])
    if not ledger_path.is_absolute():
        ledger_path = REPO / ledger_path
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    return out_dir, ledger_path


def game_seed(c: dict, game_index: int, per_shard: int) -> int:
    """Map a cohort game index to the selfplay seed.

    run_gen_v2.sh uses `base + chunk*1000 + offset` (chunk = game_index //
    games_per_shard). Set chunk_stride=1000 on a campaign to match. Without
    chunk_stride, seeds are contiguous: base + game_index.
    """
    base = c["seed_base"]
    stride = c.get("chunk_stride")
    if stride is None:
        return base + game_index
    chunk = game_index // per_shard
    offset = game_index % per_shard
    return base + chunk * stride + offset


def plan(cfgs: dict, done: set, only: str | None, limit: int | None) -> list[dict]:
    """Expand campaigns into the individual games still outstanding."""
    defaults = cfgs.get("defaults", {})
    default_shard = cfgs["output"]["games_per_shard"]
    work = []
    for name, c in cfgs["campaigns"].items():
        if only and name != only:
            continue
        # Test campaigns only run when named explicitly with --campaign.
        # Otherwise a plain full run quietly emits a few 25-iteration junk
        # games, which are harmless in isolation (own shard files) but get
        # swept up by a later data/*.jsonl.gz glob during feature extraction.
        if c.get("test") and not only:
            continue
        per_shard = c.get("games_per_shard", default_shard)
        cfg = {**defaults, "players": c["players"], "iterations": c["iterations"],
               "policy_priors": c.get("policy_priors",
                                      defaults.get("policy_priors", False))}
        for i in range(c["games"]):
            seed = game_seed(c, i, per_shard)
            if (name, seed) in done:
                continue
            work.append({
                "campaign": name,
                "seed": seed,
                "shard": f"{name}_chunk{i // per_shard}.jsonl.gz",
                "cfg": cfg,
            })

    # Cohorts run sequentially - the queue is FIFO and campaigns are appended
    # in the order they appear in campaigns.toml, so all of deep2p_2k finishes
    # before mp3p_search starts. This differs from run_gen_v2.sh, which ran all
    # 34 chunks concurrently and so advanced every cohort together.
    #
    # Left sequential deliberately. Interleaving was tried and reverted: it is
    # only worth the complexity if you need a balanced partial dataset before
    # the whole run finishes, and you can get the same effect more simply by
    # running one cohort at a time with --campaign.
    if limit:
        work = work[:limit]
    return work


def print_status(cfgs: dict, ledger_path: Path, out_dir: Path) -> None:
    """Show progress from the ledger — no Ray connection needed."""
    done = read_ledger(ledger_path)
    default_shard = cfgs["output"]["games_per_shard"]
    print(f"ledger: {ledger_path}")
    print(f"shards: {out_dir}\n")

    totals = Counter()
    for name, c in cfgs["campaigns"].items():
        per_shard = c.get("games_per_shard", default_shard)
        n_shards = (c["games"] + per_shard - 1) // per_shard
        completed = sum(
            1 for i in range(c["games"])
            if (name, game_seed(c, i, per_shard)) in done
        )
        # Test campaigns are excluded from the totals because plan() excludes
        # them from runs (they only execute when named with --campaign).
        # Counting them here made a finished cohort set report "8 remaining"
        # forever, since nothing would ever run them.
        if not c.get("test"):
            totals["games"] += c["games"]
            totals["done"] += completed
        pct = 100.0 * completed / c["games"] if c["games"] else 0
        marker = "  (test)" if c.get("test") else ""
        print(f"  {name:16s}  {completed:5d}/{c['games']:<5d}  ({pct:5.1f}%)  "
              f"{n_shards} shards @ {per_shard}/shard{marker}")

    remaining = totals["games"] - totals["done"]
    print(f"\ntotal: {totals['done']}/{totals['games']} done, {remaining} remaining")
    if remaining == 0 and totals["games"]:
        print("(campaign complete — nothing left to run)")


def run(work: list[dict], out_dir: Path, ledger_path: Path, in_flight: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    pending: dict = {}
    queue = list(work)
    completed = skipped = records = 0
    started = time.time()
    # Completion timestamps for a windowed rate. A cumulative average
    # (total/elapsed) is badly misleading here: deep2p games take ~50min, so
    # nothing finishes for the first ~50min while the clock runs, and the
    # average then climbs asymptotically toward the true rate - which reads
    # as "getting faster" when nothing changed. It is worst during a drain,
    # where in-flight is falling and real throughput with it, while the
    # cumulative number keeps rising.
    recent: deque = deque(maxlen=40)
    stopping = False

    def _stop(signum, frame):
        nonlocal stopping
        if not stopping:
            stopping = True
            print("\n-> stopping: no new games will be submitted, "
                  "in-flight games will be allowed to finish (Ctrl-C again to abort)",
                  flush=True)
        else:
            raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    ledger = open(ledger_path, "a")

    while (queue and not stopping) or pending:
        while queue and not stopping and len(pending) < in_flight:
            item = queue.pop(0)
            ref = play_game.remote(item["seed"], item["cfg"])
            pending[ref] = item

        if not pending:
            break
        ready, _ = ray.wait(list(pending), num_returns=1, timeout=30.0)
        for ref in ready:
            item = pending.pop(ref)
            try:
                seed, n_records, blob = ray.get(ref)
            except Exception as exc:  # noqa: BLE001 - a dead game must not kill the run
                print(f"   FAILED {item['campaign']} seed={item['seed']}: "
                      f"{type(exc).__name__}: {exc}", flush=True)
                continue
            if blob:
                shard = out_dir / item["shard"]
                with open(shard, "ab") as fh:
                    fh.write(blob)
                    fh.flush()
                    os.fsync(fh.fileno())
                records += n_records
                completed += 1
            else:
                skipped += 1
            ledger.write(json.dumps({
                "campaign": item["campaign"], "seed": seed,
                "records": n_records, "shard": item["shard"],
                "ts": int(time.time()),
            }) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())

            recent.append(time.time())
            total = completed + skipped
            if total % 5 == 0 or not queue:
                # Rate over the window of recent completions, not since start.
                if len(recent) >= 2:
                    span = recent[-1] - recent[0]
                    rate = (len(recent) - 1) / span * 3600 if span > 0 else 0.0
                else:
                    rate = 0.0
                avg = total / max(time.time() - started, 1e-9) * 3600
                print(f"   {total} games ({skipped} skipped), {records} records, "
                      f"{len(pending)} in flight, {rate:.0f} games/hr "
                      f"(avg {avg:.0f})", flush=True)

    ledger.close()
    return completed


def runtime_env(vcko_root: Path) -> dict:
    """Everything a worker needs to run a task.

    No `py_modules`. Before vcko_ray lived inside the engine checkout, this
    package sat in a separate tree that `working_dir` did not cover, so it had
    to be shipped separately - and forgetting it produced
    `ModuleNotFoundError: No module named 'vcko_ray'` from inside the task,
    which points at the worker rather than at the runtime_env. Now that the
    package is under the checkout, working_dir carries it.

    `excludes` is still load-bearing: the tree is ~475MB, almost all of it
    images/ and static/ (web UI) plus data/ (generated shards, gigabytes and
    growing). With these it ships ~1.8MB per node.

    `pip` is separate from working_dir on purpose - working_dir ships CODE,
    not PACKAGES, and the cluster venv deliberately carries only Ray. numpy is
    pinned to what the original run used; the nets are numpy archives, so a
    major version drift is a real risk.

    The thread caps matter under Ray specifically: the game loop is
    single-threaded, but numpy would otherwise spawn a pool per task and
    oversubscribe the node against Ray's own CPU accounting.
    """
    return {
        "working_dir": str(vcko_root),
        "excludes": ["data", "images", "static", ".venv", ".git",
                     "__pycache__", "tests", "harvest", "logs"],
        "pip": ["numpy==2.5.1", "python-dotenv", "shortuuid"],
        "env_vars": {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                     "OPENBLAS_NUM_THREADS": "1"},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcko-root", default=str(DEFAULT_VCKO_ROOT),
                    help=f"basegame-vcko checkout (default: {DEFAULT_VCKO_ROOT})")
    ap.add_argument("--campaigns", default=str(REPO / "campaigns.toml"))
    ap.add_argument("--campaign", default=None, help="run only this cohort")
    ap.add_argument("--limit", type=int, default=None, help="cap games (smoke tests)")
    ap.add_argument("--address", default=DEFAULT_RAY_ADDRESS,
                    help="Ray cluster GCS address, or 'local' for embedded")
    ap.add_argument("--in-flight", type=int, default=None,
                    help="max concurrent games (default: 2x cluster CPUs)")
    ap.add_argument("--status", action="store_true",
                    help="print ledger progress and exit (no Ray connection)")
    args = ap.parse_args()

    cfgs = load_campaigns(Path(args.campaigns))
    out_dir, ledger_path = resolve_paths(cfgs, Path(args.campaigns))

    if args.status:
        print_status(cfgs, ledger_path, out_dir)
        return 0

    vcko_root = Path(args.vcko_root).expanduser().resolve()
    if not (vcko_root / "agent").is_dir():
        print(f"ERROR: no agent/ under {vcko_root}", file=sys.stderr)
        return 1

    ray.init(address=args.address, runtime_env=runtime_env(vcko_root))

    cluster_cpus = int(ray.cluster_resources().get("CPU", 1))
    in_flight = args.in_flight or max(cluster_cpus * 2, 4)

    done = read_ledger(ledger_path)
    work = plan(cfgs, done, args.campaign, args.limit)
    print(f"cluster: {cluster_cpus} CPUs | ledger: {len(done)} games already done")
    print(f"queued:  {len(work)} games | in-flight cap: {in_flight}")
    print(f"shards:  {out_dir}\n")
    if not work:
        print("nothing to do.")
        return 0

    completed = run(work, out_dir, ledger_path, in_flight)
    print(f"\ndone: {completed} games written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
