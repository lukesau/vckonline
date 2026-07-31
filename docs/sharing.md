# Running jobs on the cluster (notes for Kyle)

Everything runs from `ubuntu-compute` — your shell, your code, your data,
your driver. `ubuntu-storage` only runs the cluster coordinator (the GCS).
You need no sudo and no account privileges there.

## Setup

**Start the worker on compute yourself.** This is the one step that matters:

```bash
./ray-worker-setup            # all cores, or: ./ray-worker-setup 24
```

It runs in the foreground; background it or use tmux.

Why it has to be you: the node's session lives in `$HOME/ray-worker/tmp`, and
Ray creates its unix sockets there owned by whoever started it. A driver
attaches to its *local* node's sockets, and `connect()` on a unix socket needs
**write** permission. Start it yourself and it just works. If someone else
starts it, you get:

```
Failed to connect to socket at address: .../sockets/raylet
```

with a C++ stack trace that looks like a dead raylet and is actually a
permissions error. We lost an hour to that one.

Lukesau brings up the other nodes before a run.

## Running a job

Point a driver at the cluster from compute:

```python
ray.init(address="192.168.1.10:6380", runtime_env={...})
```

`vcko_ray/driver.py` is a working example; `scripts/run-selfplay.sh` is how
it gets invoked. Your tasks schedule across every node in the cluster, not
just compute.

## Things that will bite

**Port is 6380, not 6379.** `redis-server` owns 6379 on the head. Every Ray
tutorial says 6379.

**Ray 2.56.1 and Python 3.12, exactly, on every node.** A mismatch in either
fails to join with an error that doesn't mention versions. It's the most
common reason a worker never shows up in `ray status`.

**`runtime_env` needs four things**, each failing differently if missing:

- `working_dir` — your checkout. Also sets each task's **cwd**, which the nets
  depend on (they load `agent/models/value_v5.npz` by relative path).
- `py_modules` — your driver package, or workers can't import the task.
- `pip` — `working_dir` ships code, not packages. The cluster venv has only Ray.
- `excludes` — the vcko tree is 475 MB, mostly `images/` and `static/`. With
  excludes it's 1.78 MB shipped per node.

**No auth, anywhere.** Reaching the GCS is unauthenticated code execution.
It's firewalled to the LAN — don't expose 6380 or 8265.

**Tasks run as different users per node** (you on compute, `ray` on the head,
lukesau elsewhere). Fine for stateless tasks — that's why generation has
tasks *return* records rather than write files. But a task that reads a local
file only works on the node that has it. If your training needs the dataset
on local disk, say so and we'll tag compute with a custom resource so those
tasks pin there.

**A head restart is the expensive event**, not a worker one — it starts a new
GCS session and every worker has to re-run `ray-worker-setup`. Ask before
anyone restarts `ray-head.service`.

## No quotas

Take what you need. Ray has no preemption; tasks queue and interleave, so a
multi-day job doesn't block anyone. The head contributes only 8 of its 20
CPUs on purpose — it also runs MariaDB, Gitea, Plex and Samba.

GPUs: nothing schedules them. Ray registers the four 1080 Tis when compute
joins, but no task requests `num_gpus`. They're yours.

## Performance, if you touch serialization

`clone_game` was doing **two** full JSON serialize+parse round trips of the
whole game per MCTS iteration; the outer one deep-copied a dict that was
already plain. Removing it gave 1.25x in isolation and ~1.47x in production
at 76-way concurrency — the workload is DRAM-bandwidth-bound, so cutting one
task's memory traffic helps every other task at the same time.

**Another ~20% is still there.** `json.loads(json.dumps(obj,
cls=GameObjectEncoder))` remains at `headless.py:50` and
`game_serialization.py:297`. Those aren't redundant — the encoder is how
objects become dicts — but going through a JSON *string* to do it isn't
necessary. A direct object→dict walker would delete `iterencode` +
`raw_decode`, ~17s of a 138s profile.

`tools/equivalence.py` verifies such a change doesn't alter output: it
replays fixed seeds with the RNG seeded per game and compares every emitted
record. Self-test it against unmodified code first so a PASS means something.
