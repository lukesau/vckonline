"""One-off cleanup: expand resource shorthand in event human-text columns.

Replaces `Ngp`/`Nsp`/`Nmp` (e.g. "1sp") with "N Strength"/"N Gold"/"N Magic"
in the events table's authored text columns (`roll_effect_text`,
`activation_effect_text`, `passive_effect_text`, `special_reward_text`).

Dry run (prints planned changes, touches nothing):

    python3 scripts/fix_event_text_shorthand.py

Apply:

    python3 scripts/fix_event_text_shorthand.py --commit

Requires the venv + SSH tunnel (see docs/agents.md).
"""

import re
import sys

import mariadb

DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

_COLUMNS = (
    "roll_effect_text",
    "activation_effect_text",
    "passive_effect_text",
    "special_reward_text",
)

_LABEL = {"g": "Gold", "s": "Strength", "m": "Magic"}
_PATTERN = re.compile(r"\b(\d+)\s*([gsm])p\b", re.IGNORECASE)


def _expand(text):
    if not text:
        return text
    return _PATTERN.sub(lambda m: f"{m.group(1)} {_LABEL[m.group(2).lower()]}", text)


def main():
    commit = "--commit" in sys.argv
    conn = mariadb.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    cols = ", ".join(_COLUMNS)
    cur.execute(f"SELECT id_events AS id, name, {cols} FROM events ORDER BY id_events")
    rows = cur.fetchall()

    changes = []
    for r in rows:
        for col in _COLUMNS:
            old = r[col]
            new = _expand(old)
            if new != old:
                changes.append((r["id"], r["name"], col, old, new))

    print(f"\n{'COMMIT' if commit else 'DRY RUN'} — {len(changes)} field(s) to update\n")
    for cid, name, col, old, new in changes:
        print(f"{cid:>3} {name} [{col}]")
        print(f"    - {old!r}")
        print(f"    + {new!r}")

    if commit:
        for cid, _, col, _, new in changes:
            cur.execute(f"UPDATE events SET {col} = ? WHERE id_events = ?", (new, cid))
        conn.commit()
        print(f"\ncommitted {len(changes)} field(s)")
    else:
        print("\n(dry run — pass --commit to apply)")
    conn.close()


if __name__ == "__main__":
    main()
