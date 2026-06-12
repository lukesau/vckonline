"""
Dump all card tables to dated SQL INSERT files in sql/dumps/.
Usage: python scripts/dump_tables.py
"""

import mariadb
from datetime import datetime
from pathlib import Path

DB = dict(user="vckonline", password="vckonline", host="127.0.0.1", database="vckonline", port=3306)
SQL_DIR = Path(__file__).resolve().parent.parent / "sql" / "dumps"

TABLES = [
    # (table_name, id_column, columns_to_backtick_quote)
    ("citizens", "id_citizens",  []),
    ("monsters", "id_monsters",  ["monster_type", "monster_order"]),
    ("domains",  "id_domains",   []),
    ("starters", "id_starters",  []),
    ("dukes",    "id_dukes",     []),
    ("events",   "id_events",    []),
    ("nobles",   "id_nobles",    []),
    ("agents",   "id_agents",    []),
]

BATCH_SIZE = 10


def sql_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def col_name(col, backtick_cols):
    return f"`{col}`" if col in backtick_cols else col


def dump_table(cur, table, id_col, backtick_cols, stamp):
    cur.execute(f"DESCRIBE {table}")
    cols = [r[0] for r in cur.fetchall()]

    cur.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {id_col}")
    rows = cur.fetchall()

    col_list = ",".join(col_name(c, backtick_cols) for c in cols)
    header = f"INSERT INTO vckonline.{table} ({col_list}) VALUES"

    lines = [f"TRUNCATE TABLE vckonline.{table};"]
    batch = []
    for i, row in enumerate(rows):
        batch.append("\t (" + ",".join(sql_val(v) for v in row) + ")")
        if len(batch) == BATCH_SIZE or i == len(rows) - 1:
            lines.append(header)
            lines.append(",\n".join(batch) + ";")
            batch = []

    path = SQL_DIR / f"{table}_{stamp}.sql"
    path.write_text("\n".join(lines) + "\n")
    print(f"  {path.name}  ({len(rows)} rows)")
    return path


def main():
    stamp = datetime.now().strftime("%Y%m%d%H%M")
    SQL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Dumping to sql/dumps/*_{stamp}.sql ...")
    conn = mariadb.connect(**DB)
    cur = conn.cursor()
    for table, id_col, backtick_cols in TABLES:
        dump_table(cur, table, id_col, backtick_cols, stamp)
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
