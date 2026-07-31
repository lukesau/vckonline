#!/usr/bin/env bash
# Run vcko selfplay generation against the Ray cluster on ubuntu-storage.
#
# Resume is automatic: completed games are recorded in data/ledger.jsonl and
# skipped on the next run. Stop with Ctrl-C once to drain in-flight games;
# Ctrl-C twice to abort immediately.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# vcko_ray lives inside this checkout now, so the repo root IS the engine
# root. Override only to run against a second checkout.
VCKO_ROOT="${VCKO_ROOT:-$REPO}"
RAY_VENV="${RAY_VENV:-/opt/ray-head/venv}"
RAY_ADDRESS="${RAY_ADDRESS:-192.168.1.10:6380}"

if [[ ! -x "$RAY_VENV/bin/python" ]]; then
    echo "ERROR: Ray venv not found at $RAY_VENV (deploy ray-head first)" >&2
    exit 1
fi

cd "$REPO"
export PYTHONPATH="$REPO${PYTHONPATH:+:$PYTHONPATH}"

# Drivers connect to the cluster session dir as a core worker. That requires
# membership in the `ray` group (logs/events + raylet unix socket). deploy.sh
# adds lukesau to ray, but existing login sessions need logout/login or sg.
_in_ray_group() { id -nG | tr ' ' '\n' | grep -qx ray; }

if ! _in_ray_group; then
    if command -v sg >/dev/null 2>&1 && getent group ray >/dev/null; then
        echo "note: activating ray group for this run (re-login to make permanent)" >&2
        cmd=( "$RAY_VENV/bin/python" -m vcko_ray.driver
              --vcko-root "$VCKO_ROOT" --address "$RAY_ADDRESS" "$@" )
        exec sg ray -c "cd $(printf '%q' "$REPO") && PYTHONPATH=$(printf '%q' "$REPO") exec $(printf '%q ' "${cmd[@]}")"
    fi
    echo "ERROR: not in group 'ray'. Run: newgrp ray   then retry, or re-login." >&2
    exit 1
fi

exec "$RAY_VENV/bin/python" -m vcko_ray.driver \
    --vcko-root "$VCKO_ROOT" \
    --address "$RAY_ADDRESS" \
    "$@"
