"""One-off migration: split citizen special-payout human text into per-turn columns.

Adds `special_payout_on_turn_text` and `special_payout_off_turn_text` to the
`citizens` table, migrates any authored text out of the legacy combined
`special_payout_text` column where it can be split, and generates human-facing
descriptions for every citizen that has a special-payout effect string but no
authored text yet.

Run a dry run first (prints the planned per-row values, touches nothing):

    python3 scripts/migrate_citizen_special_payout_text.py

Then commit the changes:

    python3 scripts/migrate_citizen_special_payout_text.py --commit

Requires the venv + database (see docs/setup.md).
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

# Mass nouns never pluralize; countable resources do.
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

_ROLE_LABEL = {
    "owned_worker": "Worker",
    "owned_soldier": "Soldier",
    "owned_holy": "Holy",
    "owned_shadow": "Shadow",
}


def _res_phrase(letter, n):
    letter = letter.lower()
    n = int(n)
    if letter == "wild":
        return f"{n} of any one resource"
    label = _RES_LABEL.get(letter, letter)
    if letter in _COUNTABLE and n != 1:
        label = label + "s"
    return f"{n} {label}"


def _join_with(items, conj):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return ", ".join(items[:-1]) + f", {conj} " + items[-1]


def _join_and(items):
    return _join_with(items, "and")


def _join_or(items):
    return _join_with(items, "or")


def _count_fragment(tokens):
    # tokens after the leading "count": <selector...> <res> <n>
    res, n = tokens[-2], tokens[-1]
    selector = tokens[:-2]
    head = selector[0]
    gain = _res_phrase(res, n)
    if head in _ROLE_LABEL:
        return f"{gain} for each {_ROLE_LABEL[head]} you own"
    if head == "owned_domains":
        return f"{gain} for each Domain you own"
    if head == "owned_monsters":
        return f"{gain} for each Monster you own"
    if head == "owned_citizens":
        return f"{gain} for each face-up Citizen you own"
    if head in ("owned_citizen_name", "owned_starter_name", "owned_monster_name"):
        name = selector[1]
        return f"{gain} for each {name} you own"
    return f"{gain} per {head}"


def _describe_leg(leg):
    """Return (kind, text) for a single (non-compound) effect leg.

    kind is "gain" when the leg is a bare/`count` resource gain (so sibling
    gain legs can be merged into one sentence); otherwise "sentence".
    """
    tokens = leg.split()
    if not tokens:
        return "sentence", ""
    verb = tokens[0].lower()

    if verb == "choose":
        pairs = tokens[1:]
        opts = [_res_phrase(pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)]
        return "sentence", f"Choose between {_join_and(opts)}."

    if verb == "exchange":
        pay, pay_n, gain, gain_n = tokens[1], tokens[2], tokens[3], tokens[4]
        return "sentence", f"Exchange {_res_phrase(pay, pay_n)} for {_res_phrase(gain, gain_n)}."

    if verb == "steal":
        rest = tokens[1:]
        opts = [_res_phrase(rest[i], rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
        return "sentence", f"Steal {_join_or(opts)} from an opponent."

    if verb == "slay":
        return "sentence", "You may immediately slay an accessible Monster, paying its normal cost."

    if verb == "count":
        return "gain", _count_fragment(tokens[1:])

    # bare resource gain, e.g. "g 1"
    if len(tokens) == 2 and (tokens[0].lower() in _RES_LABEL or tokens[0].lower() == "wild"):
        return "gain", _res_phrase(tokens[0], tokens[1])

    return "sentence", leg.strip()


def describe(effect):
    effect = (effect or "").strip()
    if not effect:
        return ""
    legs = [l.strip() for l in effect.split(" + ") if l.strip()]
    descs = [_describe_leg(l) for l in legs]
    if all(kind == "gain" for kind, _ in descs):
        # dedupe identical fragments (e.g. Knight citizen + Knight starter legs)
        frags = []
        for _, text in descs:
            if text not in frags:
                frags.append(text)
        joined = ", plus ".join(frags)
        return f"Gain {joined}."
    return " ".join(text for _, text in descs)


def _split_legacy(text):
    """Best-effort split of a combined 'On-turn, ... Off-turn, ...' string."""
    text = (text or "").strip()
    if not text:
        return "", ""
    low = text.lower()
    idx = low.find("off-turn")
    if idx == -1:
        idx = low.find("off turn")
    if idx == -1:
        return _strip_prefix(text), ""
    on_part = text[:idx].strip().rstrip(".").strip()
    off_part = text[idx:].strip()
    return _strip_prefix(on_part), _strip_prefix(off_part)


def _strip_prefix(part):
    part = (part or "").strip()
    for pref in ("on-turn,", "on turn,", "off-turn,", "off turn,", "on-turn", "off-turn"):
        if part.lower().startswith(pref):
            part = part[len(pref):].strip()
            break
    if not part:
        return ""
    part = part[0].upper() + part[1:]
    if not part.endswith("."):
        part = part + "."
    return part


def plan(cur):
    cur.execute(
        """
        SELECT id_citizens, name, expansion,
               has_special_payout_on_turn AS hon, has_special_payout_off_turn AS hoff,
               special_payout_on_turn AS son, special_payout_off_turn AS soff,
               special_payout_text AS legacy
        FROM citizens
        WHERE has_special_payout_on_turn = 1 OR has_special_payout_off_turn = 1
        ORDER BY id_citizens
        """
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        legacy_on, legacy_off = _split_legacy(r["legacy"])
        on_text = ""
        off_text = ""
        if r["hon"]:
            on_text = legacy_on or describe(r["son"])
        if r["hoff"]:
            off_text = legacy_off or describe(r["soff"])
        out.append((r, on_text, off_text))
    return out


def ensure_columns(cur):
    cur.execute("SHOW COLUMNS FROM citizens")
    cols = {row["Field"] for row in cur.fetchall()}
    if "special_payout_on_turn_text" not in cols:
        cur.execute(
            "ALTER TABLE citizens ADD COLUMN special_payout_on_turn_text mediumtext "
            "DEFAULT NULL AFTER special_payout_off_turn"
        )
        print("added column special_payout_on_turn_text")
    if "special_payout_off_turn_text" not in cols:
        cur.execute(
            "ALTER TABLE citizens ADD COLUMN special_payout_off_turn_text mediumtext "
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

    rows = plan(cur)
    print(f"\n{'COMMIT' if commit else 'DRY RUN'} — {len(rows)} citizens with special payouts\n")
    for r, on_text, off_text in rows:
        print("=" * 72)
        print(f"{r['id_citizens']:>3}  {r['name']} [{r['expansion']}]")
        if r["hon"]:
            print(f"  on  : {r['son']!r}")
            print(f"      -> {on_text!r}")
        if r["hoff"]:
            print(f"  off : {r['soff']!r}")
            print(f"      -> {off_text!r}")

    if commit:
        for r, on_text, off_text in rows:
            cur.execute(
                "UPDATE citizens SET special_payout_on_turn_text = ?, "
                "special_payout_off_turn_text = ? WHERE id_citizens = ?",
                (on_text or None, off_text or None, r["id_citizens"]),
            )
        conn.commit()
        print(f"\ncommitted {len(rows)} rows")
    else:
        print("\n(dry run — pass --commit to apply)")

    conn.close()


if __name__ == "__main__":
    main()
