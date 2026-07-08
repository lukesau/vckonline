# Installing Stored Procedures

All stored procedure SQL files are ready to use. You have several options:

## Prerequisites

1. **Database running** — see [docs/setup.md](../docs/setup.md). Probe with `python3 scripts/check_db_server.py`.

2. **MySQL client** — install if needed (e.g. `brew install mysql-client` on macOS).

## Option 1: Use the Helper Script (Easiest)

```bash
./sql/run_sql.sh sql/create_all_stored_procedures.sql
```

## Option 2: Use MySQL Client Directly

Requires `.env` with `VCKO_DB_PASSWORD` set (or export the vars manually):

```bash
set -a && source .env && set +a
export MYSQL_PWD="$VCKO_DB_PASSWORD"
mysql -h "$VCKO_DB_HOST" -P "$VCKO_DB_PORT" -u "$VCKO_DB_USER" "$VCKO_DB_NAME" < sql/create_all_stored_procedures.sql
unset MYSQL_PWD
```

## Option 3: Interactive MariaDB Session

```sql
source sql/create_all_stored_procedures.sql;
```

## Option 4: Install Individually

Run each procedure file separately using the helper script:

```bash
./sql/run_sql.sh sql/select_base1_citizens_sp.sql
./sql/run_sql.sh sql/select_base1_monsters_sp.sql
./sql/run_sql.sh sql/select_base_citizens_sp.sql
./sql/run_sql.sh sql/select_base_monsters_sp.sql
./sql/run_sql.sh sql/select_base2_citizens_sp.sql
./sql/run_sql.sh sql/select_base2_monsters_sp.sql
./sql/run_sql.sh sql/select_base_domains_sp.sql
./sql/run_sql.sh sql/select_base_dukes_sp.sql
./sql/run_sql.sh sql/select_random_domains_sp.sql
./sql/run_sql.sh sql/select_random_dukes_sp.sql
./sql/run_sql.sh sql/select_test1_domains_sp.sql
./sql/run_sql.sh sql/select_test2_domains_sp.sql
```

## Verify Installation

After installing, verify with:

```sql
SHOW PROCEDURE STATUS WHERE Db = 'vckonline';
```

Or run the test script:

```bash
python3 tests/test_database.py
```

## What Each Procedure Does

- **select_base1_citizens()** - Returns all citizens from base game 1
- **select_base1_monsters()** - Returns all monsters from base game 1
- **select_base_citizens()** - Returns all base1/base2 citizens; Python chooses one citizen per roll-match stack for the canonical base preset
- **select_base_monsters()** - Returns all base1/base2 monster areas; Python chooses 5 areas for the canonical base preset
- **select_base2_citizens()** - Returns base game 2 citizens + Peasant and Knight from base1
- **select_base2_monsters()** - Returns base2 plus gnolls and undead samurai monsters
- **select_base_domains()** - Returns base domains in random order
- **select_base_dukes()** - Returns base dukes in random order
- **select_random_domains()** - Returns all domains in random order
- **select_random_dukes()** - Returns all dukes in random order
- **select_test1_domains()** - Hand-picked 15 domains (ids 1..8 and 93..99), shuffled. Used by the `test1` preset to reproduce the original "first set" the engine was built around.
- **select_test2_domains()** - 15 random domains drawn from ids 9..24, treated as unbanned. Used by the `test2` preset.
