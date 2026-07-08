# Database

## Connection

See [setup.md](setup.md) for creating the database, loading seed data, and installing stored procedures. See [agents.md](agents.md) for venv and connector conventions.

## Overview

The game bootstrap in `game.py` loads card data from the `vckonline` database using stored procedures to select card sets and randomize stacks.

## Stored procedures

The server/game code expects these procedures to exist:

- `select_base1_monsters()`
- `select_base1_citizens()`
- `select_base_monsters()`
- `select_base_citizens()`
- `select_base2_monsters()`
- `select_base2_citizens()`
- `select_base_domains()`
- `select_base_dukes()`
- `select_random_domains()`
- `select_random_dukes()`
- `select_test1_domains()` — hand-picked domain pool for the `test1` preset (crystallized "first set")
- `select_test2_domains()` — random 15 of domain ids 9..24 for the `test2` preset
- `select_all_monsters()` — every row of `monsters` (used by the `random` preset)
- `select_all_citizens()` — every row of `citizens` (used by the `random` preset)
- `select_base_events()` — events where `expansion='base'` (the default events pool)
- `select_all_events()` — every row of `events` (used by the `random` preset)

The Python preset (passed to `load_game_data`) chooses which monster/citizen/domain/duke/event procedures to call. **Preset definitions live in `presets/*.json`** and are loaded at server startup by `preset_registry.py` — that module is the single source of truth for deal wiring, lobby labels, optional-module inclusion (`include_agents` / `include_relics`), and `expansion_only` overrides. `game_setup.load_game_data`, `preset_preview`, and `server._VALID_LOBBY_PRESETS` all read from the registry.

| preset    | monsters                  | citizens                  | domains                  | dukes                 | events                  |
| --------- | ------------------------- | ------------------------- | ------------------------ | --------------------- | ----------------------- |
| `base`    | `select_base_monsters`    | `select_base_citizens`    | `select_random_domains`* | `select_random_dukes` | `select_all_events`     |
| `base1`   | `select_base1_monsters`   | `select_base1_citizens`   | `select_random_domains`  | `select_random_dukes` | `select_all_events`     |
| `base2`   | `select_base2_monsters`   | `select_base2_citizens`   | `select_random_domains`  | `select_random_dukes` | `select_all_events`     |
| `random`   | `select_all_monsters`     | `select_all_citizens`     | `select_random_domains`  | `select_random_dukes` | `select_all_events`     |
| `june2026` | `select_all_monsters`     | `select_all_citizens`     | `select_random_domains`  | `select_random_dukes` | `select_all_events`     |
| `current`  | (alias of `june2026`)     | (alias of `june2026`)     | (alias of `june2026`)    | (alias of `june2026`) | (alias of `june2026`)   |

\* With lobby `expansion_only` on, `base` switches to `select_base_domains` and scopes dukes/events to base only (see `presets/base.json`).

Dukes and events both default to the full cross-expansion pool for every preset (events are post-filtered to drop unimplemented stubs; `random`/`draft` additionally require art via `keep_for_random`). The lobby `expansion_only` option (base / Flames+Frost / Shadowvale only) narrows domains, dukes, and events back to the preset's expansion set — base dukes are mixed into the expansion presets since an expansion alone has too few.

The `base` preset uses the canonical Base Set board: all base1/base2 monster areas are fetched and Python randomly chooses 5 areas; all base1/base2 citizens are fetched and Python randomly chooses one citizen per roll-match stack; base domains and base dukes are randomized by procedure.

The `current` preset is the lobby's "Rotating" alias. It points at whichever dated rotating preset is live — currently `june2026`, defined in `presets/june2026.json` (fixed monster areas + citizen ids; domains/dukes/events randomized across all expansions, Crimson Seas domains excluded; Agents and Relics always included). Rotating to a new month is a JSON edit: add a dated preset file and repoint `presets/current.json`'s `alias`. The dated presets are valid `load_game_data` presets; players reach the live one through "Rotating".

The `random` preset draws from every expansion. Each card-type pool is post-filtered in Python by `card_filters.keep_for_random`, which drops rows the wiki flags as `is_unimplemented` and rows whose `/card-image/{kind}/{id}` art file is missing on disk. Monsters are filtered at the **area** level rather than per-row: if any card in a stack (after `is_extra` exclusion based on player count) fails the predicate, the whole area is dropped — a stack is dealt as a unit and a single unplayable card in it would block normal play of that area. Citizens, domains, dukes, and events are filtered per-row. After filtering, the same area-of-5 / one-citizen-per-roll / sample-15 / banned-cards logic that runs for the curated presets runs here too. If the filter wipes out coverage for any of the ten citizen dice slots (1..9, 11), or fewer than 5 monster areas survive, `load_game_data` raises a clear error rather than dealing an empty stack.

The live server (`server.py`) lets each lobby owner pick from the presets returned by `preset_registry.lobby_selectable_presets()` (see `server.md`); `current` is the default. The `banned_cards.json` `domains` filter is applied to every preset — so if a procedure's pool overlaps the ban list heavily it may return fewer than the 15 domains required and the preset will fail to render.

To install all procedures:

```bash
./sql/run_sql.sh sql/create_all_stored_procedures.sql
```

See `sql/INSTALL_PROCEDURES.md` for additional options (mysql client, interactive MariaDB session, installing individually).

## SQL directory layout

| Path | Purpose |
| ---- | ------- |
| `sql/create_all_stored_procedures.sql`, `sql/select_*_sp.sql` | Stored procedure definitions the app calls at runtime |
| `sql/schema/create_tables.sql`, `sql/create_database.sql` | Database, tables, and user setup |
| `sql/seed/*.sql` | Committed card-data INSERT dumps |
| `sql/insert_*.sql` | INSERT templates for adding new card rows |
| `sql/run_sql.sh`, `sql/load_seed_data.sh` | Apply SQL files to the local database |
| `sql/dumps/` | Generated full-table INSERT dumps from `scripts/dump_tables.py` (gitignored) |

One-off data migration scripts (`fix_*.sql`, `add_*.sql`) were removed after being applied to the live DB. To snapshot current card data, run `scripts/dump_tables.py` (output goes to `sql/dumps/`).

## User / grants setup

If authentication fails after following [setup.md](setup.md), re-run `sql/create_database.sql` as a MariaDB admin user.

## Verifying the DB

See [setup.md](setup.md) for `check_db_server.py` and `tests/test_database.py`.
