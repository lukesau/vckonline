"""One-off migration: generate human-facing `special_reward_text` for monsters.

Most monster rows ship with an authored `special_reward` effect string but an
empty `special_reward_text`. This script fills the empty text columns with a
human description generated from the effect string, leaving any already-authored
text untouched. Wording follows the handful of rows that were authored by hand
(e.g. equal gold/strength/magic legs collapse into "N Wild").

Dry run (prints planned values, touches nothing):

    python3 scripts/migrate_monster_special_reward_text.py

Apply:

    python3 scripts/migrate_monster_special_reward_text.py --commit

Requires the venv + database (see docs/setup.md).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mariadb

from db_config import DB_CONFIG

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
        return f"{n} Wild"
    label = _RES_LABEL.get(letter, letter)
    if letter in _COUNTABLE and n != 1:
        label += "s"
    return f"{n} {label}"


def _join_or(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return " or ".join(items)


def _strip_q(s):
    return s.strip().strip('"').strip()


def _split_top_level(effect, sep=" + "):
    """Split on ` + ` only at bracket depth 0 (keeps `<citizens + v 1>` intact)."""
    out, depth, buf = [], 0, ""
    i = 0
    s = effect
    while i < len(s):
        ch = s[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if depth == 0 and s[i:i + len(sep)] == sep:
            out.append(buf)
            buf = ""
            i += len(sep)
            continue
        buf += ch
        i += 1
    if buf:
        out.append(buf)
    return [p.strip() for p in out if p.strip()]


def _count_clause(tokens):
    """`count <selector...> <res> <n>` -> (clause, res, n, suffix)."""
    res, n = tokens[-2], tokens[-1]
    sel = tokens[:-2]
    head = sel[0]
    if head == "area":
        area = _strip_q(" ".join(sel[1:]))
        if area.lower().startswith("the "):
            suffix = f"for each Monster you own in {area}"
        else:
            suffix = f"for each {area} Monster you own"
    elif head == "type":
        suffix = f"for each owned {sel[1]}"
    elif head == "owned_monster_name":
        name = _strip_q(" ".join(sel[1:]))
        suffix = f"for each {name} you own"
    elif head.startswith("owned_"):
        suffix = f"per {head}"
    else:
        suffix = f"per {head}"
    return f"gain {_res_phrase(res, n)} {suffix}", res.lower(), int(n), suffix


def _describe_bracket(text):
    """Describe a `<...>` entity/count leg -> lowercase-leading clause."""
    inner = text.strip()
    if inner.startswith("<") and inner.endswith(">"):
        inner = inner[1:-1].strip()
    tokens = inner.split()
    head = tokens[0]
    if head == "count":
        return _count_clause(tokens[1:])[0]
    if head == "domains":
        return "take a Domain"
    if head == "noble":
        return "take a Noble"
    if head == "citizens":
        rest = tokens[1:]
        if rest and rest[0].isdigit():
            return f"take {rest[0]} Citizens"
        joined = " ".join(rest)
        if joined.startswith("where name=="):
            name = joined[len("where name=="):].strip()
            return f"take a {name}"
        if joined.startswith("where gold_cost<="):
            cap = joined[len("where gold_cost<="):].strip()
            return f"take a Citizen that costs {cap} Gold or less"
        if joined.startswith("+"):
            extra = joined[1:].split()
            return f"take a Citizen and gain {_res_phrase(extra[0], extra[1])}"
        return "take a Citizen"
    return inner


def _parse_choose_options(body):
    """Yield options from a choose body as ('res', letter, n) or ('bracket', text)."""
    opts = []
    i = 0
    toks = body
    n = len(toks)
    while i < n:
        if toks[i] == "<":
            depth = 0
            j = i
            while j < n:
                if toks[j] == "<":
                    depth += 1
                elif toks[j] == ">":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            opts.append(("bracket", toks[i:j + 1]))
            i = j + 1
            while i < n and toks[i] == " ":
                i += 1
            continue
        # bare resource pair: letter number
        m = []
        while i < n and toks[i] != " " and toks[i] != "<":
            m.append(toks[i])
            i += 1
        word = "".join(m)
        while i < n and toks[i] == " ":
            i += 1
        if not word:
            continue
        # expect a following number
        num = []
        while i < n and toks[i].isdigit():
            num.append(toks[i])
            i += 1
        while i < n and toks[i] == " ":
            i += 1
        opts.append(("res", word.lower(), int("".join(num))))
    return opts


def _collapse_wild(pairs):
    gsm = {l: v for l, v in pairs if l in ("g", "s", "m")}
    if set(gsm) == {"g", "s", "m"} and len(set(gsm.values())) == 1:
        n = next(iter(gsm.values()))
        out, inserted = [], False
        for l, v in pairs:
            if l in ("g", "s", "m"):
                if not inserted:
                    out.append(("wild", n))
                    inserted = True
            else:
                out.append((l, v))
        return out
    return pairs


def _describe_choose(body):
    opts = _parse_choose_options(body)
    if all(kind == "res" for kind, *_ in opts):
        pairs = [(l, v) for _, l, v in opts]
        pairs = _collapse_wild(pairs)
        return "gain " + _join_or(_res_phrase(l, v) for l, v in pairs)

    # All count-brackets covering g/s/m with one amount + selector -> "N Wild".
    if all(kind == "bracket" for kind, *_ in opts):
        parsed = []
        ok = True
        for _, text in opts:
            inner = text.strip()[1:-1].strip()
            t = inner.split()
            if t and t[0] == "count":
                parsed.append(_count_clause(t[1:]))
            else:
                ok = False
                break
        if ok and len(parsed) == 3:
            res_set = {p[1] for p in parsed}
            n_set = {p[2] for p in parsed}
            suf_set = {p[3] for p in parsed}
            if res_set == {"g", "s", "m"} and len(n_set) == 1 and len(suf_set) == 1:
                return f"gain {next(iter(n_set))} Wild {next(iter(suf_set))}"

    clauses = []
    for kind, *rest in opts:
        if kind == "res":
            l, v = rest
            clauses.append(f"gain {_res_phrase(l, v)}")
        else:
            clauses.append(_describe_bracket(rest[0]))
    return ", or ".join(clauses)


def _describe_leg(leg):
    leg = leg.strip()
    tokens = leg.split()
    head = tokens[0].lower()
    if head == "choose":
        return _describe_choose(leg[len("choose"):].strip())
    if head == "count":
        return _count_clause(tokens[1:])[0]
    if leg.startswith("<"):
        return _describe_bracket(leg)
    if head == "banish_center":
        target = tokens[1].lower() if len(tokens) > 1 else "citizen"
        noun = {"citizen": "Citizen", "domain": "Domain", "noble": "Noble"}.get(target, target.title())
        return f"banish a face-up {noun} from the center stacks"
    if head == "flip_citizen":
        return "flip a Citizen on an opponent's tableau face-down"
    if head == "take_owned":
        return "take a random Monster owned by an opponent"
    return leg


def describe(effect):
    effect = (effect or "").strip()
    if not effect:
        return ""
    legs = _split_top_level(effect)
    clauses = [_describe_leg(l) for l in legs]
    sentence = ", then ".join(c for c in clauses if c)
    if not sentence:
        return ""
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def main():
    commit = "--commit" in sys.argv
    conn = mariadb.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT id_monsters AS id, name, expansion, special_reward AS sr,
               special_reward_text AS txt
        FROM monsters
        WHERE has_special_reward = 1 AND special_reward IS NOT NULL
              AND TRIM(special_reward) <> ''
        ORDER BY id_monsters
        """
    )
    rows = cur.fetchall()

    planned = []
    skipped_authored = 0
    for r in rows:
        existing = (r["txt"] or "").strip()
        if existing:
            skipped_authored += 1
            continue
        text = describe(r["sr"])
        planned.append((r, text))

    # Distinct preview keyed by effect string.
    seen = {}
    for r, text in planned:
        seen.setdefault(r["sr"].strip(), text)
    print(f"\n{'COMMIT' if commit else 'DRY RUN'} — {len(planned)} rows to fill "
          f"({skipped_authored} already authored, {len(seen)} distinct strings)\n")
    for sr, text in seen.items():
        print(f"  {sr!r}\n    -> {text!r}\n")

    if commit:
        for r, text in planned:
            cur.execute(
                "UPDATE monsters SET special_reward_text = ? WHERE id_monsters = ?",
                (text or "", r["id"]),
            )
        conn.commit()
        print(f"committed {len(planned)} rows")
    else:
        print("(dry run — pass --commit to apply)")
    conn.close()


if __name__ == "__main__":
    main()
