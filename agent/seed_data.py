"""Parse sql/seed/*.sql INSERT statements into in-memory tables (list-of-dict rows).

The seed dumps are simple multi-row INSERTs with explicit column lists and
literal values (ints, single-quoted strings with '' or backslash escapes, NULL),
so a small hand-rolled parser is enough — no SQL library, no database.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = REPO_ROOT / "sql" / "seed"

_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+(?:[`\"]?\w+[`\"]?\.)?[`\"]?(\w+)[`\"]?\s*\(([^)]*)\)\s*VALUES",
    re.IGNORECASE,
)

_INT_RE = re.compile(r"^-?\d+$")


def _parse_value(token):
    token = token.strip()
    if not token:
        return None
    if token.upper() == "NULL":
        return None
    if token[0] == "'":
        body = token[1:-1]
        # '' → ' first, then backslash escapes
        body = body.replace("''", "'")
        body = re.sub(r"\\(.)", r"\1", body)
        return body
    if _INT_RE.match(token):
        return int(token)
    try:
        return float(token)
    except ValueError:
        return token


def _parse_tuples(text, start):
    """Parse `(v, v, ...), (v, ...), ... ;` starting at `start`. Returns (rows, end_index)."""
    rows = []
    i = start
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == ";":
            i += 1
            break
        if text[i] != "(":
            raise ValueError(f"Expected '(' at offset {i}: {text[i:i+40]!r}")
        i += 1
        values = []
        buf = []
        in_string = False
        while i < n:
            ch = text[i]
            if in_string:
                if ch == "\\":
                    buf.append(text[i : i + 2])
                    i += 2
                    continue
                if ch == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        buf.append("''")
                        i += 2
                        continue
                    in_string = False
                buf.append(ch)
                i += 1
                continue
            if ch == "'":
                in_string = True
                buf.append(ch)
                i += 1
                continue
            if ch == ",":
                values.append(_parse_value("".join(buf)))
                buf = []
                i += 1
                continue
            if ch == ")":
                values.append(_parse_value("".join(buf)))
                i += 1
                break
            buf.append(ch)
            i += 1
        rows.append(values)
    return rows, i


def parse_seed_sql(text):
    """Return {table_name: [row_dict, ...]} for every INSERT in `text`."""
    tables = {}
    pos = 0
    while True:
        m = _INSERT_RE.search(text, pos)
        if not m:
            break
        table = m.group(1)
        columns = [c.strip().strip('`"') for c in m.group(2).split(",")]
        raw_rows, pos = _parse_tuples(text, m.end())
        out = tables.setdefault(table, [])
        for values in raw_rows:
            if len(values) != len(columns):
                raise ValueError(
                    f"{table}: row has {len(values)} values for {len(columns)} columns: {values!r}"
                )
            out.append(dict(zip(columns, values)))
    return tables


def load_seed_tables(seed_dir=SEED_DIR):
    """Parse every .sql file in the seed directory into one merged table dict."""
    tables = {}
    for path in sorted(Path(seed_dir).glob("*.sql")):
        parsed = parse_seed_sql(path.read_text(encoding="utf-8"))
        for name, rows in parsed.items():
            tables.setdefault(name, []).extend(rows)
    return tables
