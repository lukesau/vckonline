# Installing Stored Procedures

All stored procedure SQL files are ready to use. You have several options:

## Prerequisites

1. **SSH Port Forwarding** - Make sure you have an active SSH tunnel:
   ```bash
   ssh -L 3306:localhost:3306 lukesau.com
   ```
   Keep this terminal open while running SQL commands.

2. **MySQL Client** - Install if needed:
   ```bash
   brew install mysql-client
   ```
   
   To add mysql-client to your PATH permanently, add to `~/.zshrc`:
   ```bash
   echo 'export PATH="/opt/homebrew/opt/mysql-client/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```

## Option 1: Use the Helper Script (Easiest)

```bash
./sql/run_sql.sh sql/create_all_stored_procedures.sql
```

## Option 2: Use MySQL Client Directly

If mysql is in your PATH (added to ~/.zshrc), you can use:

```bash
mysql -h 127.0.0.1 -P 3306 -u vckonline -p vckonline < sql/create_all_stored_procedures.sql
```

Or use the full path:

```bash
/opt/homebrew/opt/mysql-client/bin/mysql -h 127.0.0.1 -P 3306 -u vckonline -p vckonline < sql/create_all_stored_procedures.sql
```

**Note:** The `-h 127.0.0.1 -P 3306` flags connect through your SSH tunnel to the remote database.

## Option 3: Interactive MariaDB Session

If you're already logged into MariaDB on the server:

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

Or using mysql client directly:

```bash
/opt/homebrew/Cellar/mysql-client/9.5.0/bin/mysql -h 127.0.0.1 -P 3306 -u vckonline -p vckonline < sql/select_base1_citizens_sp.sql
# ... repeat for each file
```

Or interactively in MariaDB on the server:

```sql
source sql/select_base1_citizens_sp.sql;
source sql/select_base1_monsters_sp.sql;
source sql/select_base_citizens_sp.sql;
source sql/select_base_monsters_sp.sql;
source sql/select_base2_citizens_sp.sql;
source sql/select_base2_monsters_sp.sql;
source sql/select_base_domains_sp.sql;
source sql/select_base_dukes_sp.sql;
source sql/select_random_domains_sp.sql;
source sql/select_random_dukes_sp.sql;
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

