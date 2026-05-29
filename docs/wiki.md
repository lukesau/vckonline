# Card Wiki (`/wiki`)

## What it is

`/wiki` is a read-only browser for the raw `vckonline` MariaDB tables. It is **not** a wiki in the wiki-software sense (no editing, no pages, no auth) — it's a card-database explorer that surfaces every row of every card table with images and a filterable UI.

Use it for:

- Sanity-checking edits to `citizens`, `monsters`, `domains`, `dukes`, `starters` without spinning up a game.
- Browsing effect strings and rules text across the whole DB.
- Finding banned/unfinished/unreleased cards (they are intentionally shown).

It does **not** apply `banned_cards.json` filtering, expansion gating, or any preset/stored-procedure logic. Every row is loaded.

## Where it lives

| Component | Path |
|-----------|------|
| HTML/CSS/JS client | `static/wiki/` |
| DB loader | `wiki_data.py` |
| FastAPI routes | `server.py` — `GET /wiki`, `GET /api/wiki/cards` |
| Card images (reused) | `/card-image/{kind}/{id}` endpoint in `server.py` |

## Endpoints

- `GET /wiki` — serves `static/wiki/index.html`.
- `GET /api/wiki/cards` — returns `{ counts: {citizens, monsters, domains, dukes, starters}, cards: {...} }`. Response shape per card matches the corresponding `cards.py` class's `to_dict()` output, with three additions:
  - `domains` and `dukes` entries include `is_banned` (looked up against `banned_cards.json`).
  - `citizens`, `monsters`, and `domains` entries include `is_unimplemented` — true when the row has a special/effect flag set but the corresponding text column is `NULL` or whitespace-only. See [Unimplemented detection](#unimplemented-detection) below.
  - Every entry includes `has_alt_image` — true when an `alt_<kind>_<id>_*.{jpg,jpeg,png,webp}` file exists in the matching `images/` subdirectory. The client renders an "Alt" toggle for those cards. See [Alternate artwork](#alternate-artwork) below.
- `GET /api/wiki/cards?refresh=1` — bust the in-memory cache and reload from the DB. Useful when you edit a row and want to see it without restarting the server.

The wiki uses the existing `/card-image/{kind}/{id}` endpoint for art. To request the alternate artwork, append `?variant=alt`; the endpoint then looks for a file beginning with `alt_<kind>_<id>_` instead of `<kind>_<id>_`. Other callers of `/card-image/...` are unaffected — they keep getting the canonical art by default.

## Caching

The first call to `/api/wiki/cards` runs `wiki_data.load_all_cards_for_wiki()` against the DB and caches the result in module-level state on `server.py` (`_wiki_cards_cache`). Every subsequent request returns the cached payload until the process restarts or someone hits `?refresh=1`. Card data is essentially static between restarts, so this avoids a DB hit per page-load.

## DB requirements

Same as the game itself — `vckonline` user on `127.0.0.1:3306` with the standard SSH tunnel from `docs/database.md`. The wiki uses direct `SELECT * FROM <table>` queries, so it does **not** require the stored procedures listed in `docs/database.md` (those are still required for normal game play).

If the DB is unreachable, `/api/wiki/cards` returns `503` with a `detail` describing the error. The client renders the message in the status bar.

## UI features

- Type tabs (Citizens / Monsters / Domains / Dukes / Starters) with row counts.
- Free-text search across name, expansion, area, monster type, and every effect/text field.
- Per-type filter chips: expansion, citizen role, citizen roll-match signature, monster area/type, domain effect kind, banned-only, implementation status (Implemented / Unimplemented). The citizen roll-match chips are derived from the data: any unique combination of positive `roll_match1`/`roll_match2` values becomes a chip (e.g. `3`, `9/10`, `7/8`); negative/zero sentinels are ignored.
- Responsive card grid using `400×570` art from `images/{kind}s/`.
- Click any card → modal with full art, stats, role badges, raw effect strings, payouts, and (for dukes) the full multiplier matrix.
- Banned entries render a red `Banned` badge but are still listed.
- Unimplemented entries (see below) render a yellow `Unimplemented` badge but are still listed.

## Unimplemented detection

A row is flagged as `is_unimplemented` when one of its `has_*` flags is truthy but the matching text column is `NULL` or whitespace-only. The convention across the codebase is that the `has_*` boolean gates whether the engine will try to resolve an effect string, so a flagged row with no text is an authored stub that has not been filled in yet. The predicates live in `card_filters.py` and are imported by both `wiki_data.py` (to render the badge) and `game_setup.py` (to filter the `random` preset's card pool — see `docs/database.md`), so a card the wiki shows as Unimplemented is the same card the random preset refuses to deal.

| Card type | Trigger columns |
|-----------|-----------------|
| Citizens  | `has_special_payout_on_turn` + `special_payout_on_turn`, `has_special_payout_off_turn` + `special_payout_off_turn` |
| Monsters  | `has_special_reward` + `special_reward`, `has_special_cost` + `special_cost` |
| Domains   | `has_passive_effect` + `passive_effect`, `has_activation_effect` + `activation_effect` |

Dukes and starters are not flagged today — dukes are pure stat multipliers, and starters use the same payout columns as citizens but no production starter ships with an unfilled special.

## Alternate artwork

Some cards have a second piece of artwork on disk. The convention is that the alternate file lives in the same `images/<kind>s/` directory as the canonical art and starts with `alt_`, keeping the same `<kind>_<id>_<slug>` skeleton. For example:

- `images/monsters/monster_13_death_knight.jpg` — canonical
- `images/monsters/alt_monster_13_death_knight.jpg` — alternate

`wiki_data._scan_alt_card_ids` walks each `images/<kind>s/` directory once per `/api/wiki/cards` call and collects the integer ids of any files matching `^alt_<kind>_(\d+)_.*\.(jpg|jpeg|png|webp)$`. Every card entry then gets a `has_alt_image` boolean. The scan is keyed off `<kind>` exactly, so an `alt_monster_13_*` file does not flag domain id 13.

The wiki UI uses that flag to render a small "Alt" toggle on the grid card and a "Show alternate artwork" / "Show original artwork" button in the detail modal. Clicking either swaps the image's `src` from `/card-image/<kind>/<id>` to `/card-image/<kind>/<id>?variant=alt` and back. The selection lives only in JS state (`state.altSelections`, a `Set` of `${type}_${id}` keys) — refreshing the page resets every card to canonical art.

Today only monster cards ship alternates, but the flag and toggle work uniformly for citizens, monsters, domains, dukes, and starters; drop a matching `alt_<kind>_<id>_*` file into the right directory and the wiki picks it up on the next cache refresh (`?refresh=1` or server restart).
