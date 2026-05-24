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
- `GET /api/wiki/cards` — returns `{ counts: {citizens, monsters, domains, dukes, starters}, cards: {...} }`. Response shape per card matches the corresponding `cards.py` class's `to_dict()` output, with one addition: `domains` and `dukes` entries include `is_banned` (looked up against `banned_cards.json`).
- `GET /api/wiki/cards?refresh=1` — bust the in-memory cache and reload from the DB. Useful when you edit a row and want to see it without restarting the server.

The wiki uses the existing `/card-image/{kind}/{id}` endpoint for art — no new image plumbing.

## Caching

The first call to `/api/wiki/cards` runs `wiki_data.load_all_cards_for_wiki()` against the DB and caches the result in module-level state on `server.py` (`_wiki_cards_cache`). Every subsequent request returns the cached payload until the process restarts or someone hits `?refresh=1`. Card data is essentially static between restarts, so this avoids a DB hit per page-load.

## DB requirements

Same as the game itself — `vckonline` user on `127.0.0.1:3306` with the standard SSH tunnel from `docs/database.md`. The wiki uses direct `SELECT * FROM <table>` queries, so it does **not** require the stored procedures listed in `docs/database.md` (those are still required for normal game play).

If the DB is unreachable, `/api/wiki/cards` returns `503` with a `detail` describing the error. The client renders the message in the status bar.

## UI features

- Type tabs (Citizens / Monsters / Domains / Dukes / Starters) with row counts.
- Free-text search across name, expansion, area, monster type, and every effect/text field.
- Per-type filter chips: expansion, citizen role, monster area/type, domain effect kind, banned-only.
- Responsive card grid using `400×570` art from `images/{kind}s/`.
- Click any card → modal with full art, stats, role badges, raw effect strings, payouts, and (for dukes) the full multiplier matrix.
- Banned entries render a red `Banned` badge but are still listed.
