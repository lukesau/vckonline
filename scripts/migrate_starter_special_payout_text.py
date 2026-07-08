"""One-off migration: give starters per-turn special-payout human text columns.

Mirrors the citizen change: adds `special_payout_on_turn_text` and
`special_payout_off_turn_text` to the `starters` table and populates them from
the effect strings, instead of the legacy combined `card_text` field. Only
starters with a special payout (Herald, Margrave, Coxswain) get text; the
plain starters (Peasant, Knight) keep NULL.

Dry run (prints planned values, touches nothing):

    python3 scripts/migrate_starter_special_payout_text.py

Apply:

    python3 scripts/migrate_starter_special_payout_text.py --commit

Requires the venv + SSH tunnel (see docs/agents.md).
"""

import sys

import mariadb

DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

_RES_LABEL = {
    "g": "Gold",
    "s": "Strength",
    "m": "Magic",
    "v": "Victory Point",
    "vp": "Victory Point",
    "p": "Map",
    "t": "Tome",
}
_COUNTABLE = {"v", "vp", "p", "t"}


def _res_phrase(letter, n):
    letter = letter.lower()
    n = int(n)
    if letter == "wild":
        return f"{n} of any one resource"
    label = _RES_LABEL.get(letter, letter)
    if letter in _COUNTABLE and n != 1:
        label += "s"
    return f"{n} {label}"


def _join_and(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _clause(leg):
    """Return a lowercase-leading imperative clause for a single effect leg."""
    tokens = leg.split()
    verb = tokens[0].lower()
    if verb == "choose":
        pairs = tokens[1:]
        opts = [_res_phrase(pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)]
        return f"choose between {_join_and(opts)}"
    if verb == "exchange":
        pay, pay_n, gain, gain_n = tokens[1], tokens[2], tokens[3], tokens[4]
        return f"exchange {_res_phrase(pay, pay_n)} for {_res_phrase(gain, gain_n)}"
    if len(tokens) == 2 and (verb in _RES_LABEL or verb == "wild"):
        return f"gain {_res_phrase(tokens[0], tokens[1])}"
    return leg.strip()


def describe(effect):
    effect = (effect or "").strip()
    if not effect:
        return ""
    legs = [l.strip() for l in effect.split(" + ") if l.strip()]
    sentence = ", then ".join(_clause(l) for l in legs)
    if not sentence:
        return ""
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def ensure_columns(cur):
    cur.execute("SHOW COLUMNS FROM starters")
    cols = {row["Field"] for row in cur.fetchall()}
    if "special_payout_on_turn_text" not in cols:
        cur.execute(
            "ALTER TABLE starters ADD COLUMN special_payout_on_turn_text mediumtext "
            "DEFAULT NULL AFTER special_payout_off_turn"
        )
        print("added column special_payout_on_turn_text")
    if "special_payout_off_turn_text" not in cols:
        cur.execute(
            "ALTER TABLE starters ADD COLUMN special_payout_off_turn_text mediumtext "
            "DEFAULT NULL AFTER special_payout_on_turn_text"
        )
        print("added column special_payout_off_turn_text")


def main():
    commit = "--commit" in sys.argv
    conn = mariadb.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)

    if commit:
        ensure_columns(cur)
        conn.commit()

    cur.execute(
        """
        SELECT id_starters AS id, name, expansion,
               has_special_payout_on_turn AS hon, has_special_payout_off_turn AS hoff,
               special_payout_on_turn AS son, special_payout_off_turn AS soff
        FROM starters
        WHERE has_special_payout_on_turn = 1 OR has_special_payout_off_turn = 1
        ORDER BY id_starters
        """
    )
    rows = cur.fetchall()
    planned = []
    for r in rows:
        on_text = describe(r["son"]) if r["hon"] else ""
        off_text = describe(r["soff"]) if r["hoff"] else ""
        planned.append((r, on_text, off_text))

    print(f"\n{'COMMIT' if commit else 'DRY RUN'} — {len(planned)} starters with special payouts\n")
    for r, on_text, off_text in planned:
        print("=" * 64)
        print(f"{r['id']:>3}  {r['name']} [{r['expansion']}]")
        if r["hon"]:
            print(f"  on  : {r['son']!r}\n      -> {on_text!r}")
        if r["hoff"]:
            print(f"  off : {r['soff']!r}\n      -> {off_text!r}")

    if commit:
        for r, on_text, off_text in planned:
            cur.execute(
                "UPDATE starters SET special_payout_on_turn_text = ?, "
                "special_payout_off_turn_text = ? WHERE id_starters = ?",
                (on_text or None, off_text or None, r["id"]),
            )
        conn.commit()
        print(f"\ncommitted {len(planned)} rows")
    else:
        print("\n(dry run — pass --commit to apply)")
    conn.close()


if __name__ == "__main__":
    main()
