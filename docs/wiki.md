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
| FastAPI routes | `server.py` — `GET /wiki`, `GET /api/wiki/cards`, `GET /api/wiki/rulebooks` |
| Card images (reused) | `/card-image/{kind}/{id}` endpoint in `server.py` |
| Rulebook PDFs | `static/rulebooks/*.pdf` (served via the `/static` mount) |
| Rule card images | `static/rulebooks/rule_card_<front\|back>_<slug>.<png\|jpg\|jpeg>` |

## Endpoints

- `GET /wiki` — serves `static/wiki/index.html`.
- `GET /api/wiki/cards` — returns `{ counts: {citizens, monsters, domains, dukes, starters, events, nobles}, cards: {...} }`. Response shape per card matches the corresponding `cards.py` class's `to_dict()` output, with three additions:
  - `domains`, `dukes`, and `relics` entries include `is_banned` (looked up against `banned_cards.json`).
  - `citizens`, `monsters`, and `domains` entries include `is_unimplemented` — true when the row has a special/effect flag set but the corresponding text column is `NULL` or whitespace-only. See [Unimplemented detection](#unimplemented-detection) below.
  - Every entry includes `alt_variants` — a sorted list of the alternate-artwork variant tokens that exist on disk for that card (e.g. `["alt"]` or `["alt_01", …, "alt_05"]`), plus `has_alt_image` (`true` when `alt_variants` is non-empty, kept for backwards compatibility). The client renders an "Alt" control for those cards. See [Alternate artwork](#alternate-artwork) below.
- `GET /api/wiki/cards?refresh=1` — bust the in-memory cache and reload from the DB. Useful when you edit a row and want to see it without restarting the server.
- `GET /card-image-variants/{kind}/{id}` — returns `{ "variants": [...] }`, the same token list, scanned live. Used by the in-game Margrave artwork chooser so the client never hard-codes how many alternates exist.
- `GET /api/wiki/rulebooks` — returns `{ "rulebooks": [{ "name", "url" }, ...], "rule_cards": [{ "name", "slug", "front_url", "back_url" }, ...] }`. Everything lives in `static/rulebooks/`: PDFs become `rulebooks`, and files named `rule_card_<front|back>_<slug>.<png|jpg|jpeg>` are grouped into front/back `rule_cards` by slug. Drop in files and they appear on the next page load — no restart needed. The `name` is the slug with underscores turned into spaces and title-cased; for names that can't be derived from a filename (e.g. apostrophes like `King's Guard` from `kings_guard`), add an entry to `_RULE_CARD_NAME_OVERRIDES` in `server.py`.

The wiki uses the existing `/card-image/{kind}/{id}` endpoint for art. To request an alternate, append `?variant=<token>` (e.g. `?variant=alt` or `?variant=alt_01`); the endpoint then looks for a file beginning with `<token>_<kind>_<id>_` instead of `<kind>_<id>_`. The token is restricted to `[a-z0-9_]+` so it is safe to splice into a filename prefix. Other callers of `/card-image/...` are unaffected — they keep getting the canonical art by default.

## Caching

The first call to `/api/wiki/cards` runs `wiki_data.load_all_cards_for_wiki()` against the DB and caches the result in module-level state on `server.py` (`_wiki_cards_cache`). Every subsequent request returns the cached payload until the process restarts or someone hits `?refresh=1`. Card data is essentially static between restarts, so this avoids a DB hit per page-load.

## DB requirements

Same as the game itself — see [agents.md](agents.md) for connection setup. The wiki uses direct `SELECT * FROM <table>` queries, so it does **not** require the stored procedures listed in [database.md](database.md) (those are still required for normal game play).

If the DB is unreachable, `/api/wiki/cards` returns `503` with a `detail` describing the error. The client renders the message in the status bar.

## UI features

- Type tabs (Citizens / Monsters / Domains / Dukes / Starters / Events / Nobles) with row counts, plus a **Rulebooks** tab. That tab shows PDFs in `static/rulebooks/` as new-tab links and rule cards (also in `static/rulebooks/`) in the same card grid style as DB cards. Rule cards open an image-only modal and use the existing Alt button styling as a front/back toggle. The Rulebooks tab needs no DB, so it stays reachable even when the card data fails to load.
- Free-text search across name, expansion, area, monster type, and every effect/text field.
- Per-type filter chips: expansion, citizen role, citizen roll-match signature, monster area/type, domain effect kind, banned-only. The citizen roll-match chips are derived from the data: any unique combination of positive `roll_match1`/`roll_match2` values becomes a chip (e.g. `3`, `9/10`, `7/8`); negative/zero sentinels are ignored.
- Responsive card grid using `400×570` art from `images/{kind}s/`.
- Click any card → modal with full art, stats, role badges, raw effect strings, payouts, and (for dukes and nobles) the full multiplier matrix.
  - Citizen/starter payout boxes (On turn / Off turn) only render non-zero Gold/Strength/Magic rows, and fold each turn's special payout into the same box. When a citizen or starter has authored human text (`special_payout_on_turn_text` / `special_payout_off_turn_text`) it shows as the headline, with the raw effect string (`special_payout_on_turn` / `special_payout_off_turn`) underneath in muted monospace. Cards without authored text just show the raw effect string. (Both `citizens` and `starters` carry the two per-turn text columns; the legacy combined `special_payout_text` / `card_text` fields are no longer used.)
  - Domains render a single **Effect** section: the generic `effect_text` (rules text) shows prominently, with the raw `activation_effect` / `passive_effect` string(s) underneath in muted monospace (labeled Activation/Passive only when a domain has both).
  - Monsters render the authored `special_reward_text` prominently in the **Special reward** section with the raw `special_reward` string underneath in muted monospace; the **Special cost** section shows the raw `special_cost` string (no human text column). Reward/cost stat chips render with explicit `+`/`-` signs (slay costs negative, rewards positive); zero rewards are omitted.
  - Events render one section per populated effect (**Roll effect** / **Activation effect** / **Passive effect** / **Special reward**), each showing the authored `<effect>_text` prominently with the raw `<effect>` string underneath in muted monospace.
- Banned entries render a red `Banned` badge but are still listed.
- Unimplemented entries (see below) render a yellow `Unimplemented` badge but are still listed.

## Unimplemented detection

A row is flagged as `is_unimplemented` when the engine-resolvable effect string the engine would run is `NULL` or whitespace-only. For most card types a `has_*` boolean gates whether the engine will try to resolve that string, so a flagged row with no string is an authored stub that has not been filled in yet. Agents and relics have **no** `has_*` gate — every agent always has an activation effect and every relic always has a passive effect — so for those types the machine column being empty is itself the stub signal (the human-facing `*_effect_text` may still be authored). The predicates live in `card_filters.py` and are imported by both `wiki_data.py` (to render the badge) and `game_setup.py` (to filter the `random` preset's card pool — see [database.md](database.md)), so a card the wiki shows as Unimplemented is the same card the random preset refuses to deal.

| Card type | Trigger columns |
|-----------|-----------------|
| Citizens  | `has_special_payout_on_turn` + `special_payout_on_turn`, `has_special_payout_off_turn` + `special_payout_off_turn` |
| Monsters  | `has_special_reward` + `special_reward`, `has_special_cost` + `special_cost` |
| Domains   | `has_passive_effect` + `passive_effect`, `has_activation_effect` + `activation_effect` |
| Starters  | `has_special_payout_on_turn` + `special_payout_on_turn`, `has_special_payout_off_turn` + `special_payout_off_turn` |
| Events    | `has_roll_effect` + `roll_effect`, `has_activation_effect` + `activation_effect`, `has_passive_effect` + `passive_effect`, `has_special_reward` + `special_reward` |
| Nobles    | `has_special_duke_payout` + `special_duke_payout` |
| Agents    | `activation_effect` (no `has_*` flag — always required) |
| Relics    | `passive_effect` (no `has_*` flag — always required) |

Dukes are never flagged — they are pure stat multipliers with no effect string, so there is nothing to leave unfilled. Every other type is covered. Note that today most starters and nobles ship fully implemented (no unfilled special), so those badges only appear if a future stub is added, whereas every agent and relic currently has a `NULL` machine effect and so shows as Unimplemented.

## Alternate artwork

Some cards have extra artwork on disk. Alternates live in the same `images/<kind>s/` directory as the canonical art and prefix a **variant token** onto the canonical `<kind>_<id>_<slug>` skeleton. Two conventions are supported:

- `alt` — a single alternate (`alt_<kind>_<id>_<slug>`):
  - `images/monsters/monster_13_death_knight.jpg` — canonical
  - `images/monsters/alt_monster_13_death_knight.jpg` — alternate (token `alt`)
- `alt_NN` — numbered alternates (`alt_NN_<kind>_<id>_<slug>`), for cards with several alternates:
  - `images/starters/starter_04_margrave.jpg` — canonical
  - `images/starters/alt_01_starter_04_margrave.jpg` … `alt_05_…` — alternates (tokens `alt_01`…`alt_05`)

`card_filters.list_card_image_variants(kind, id)` is the single source of truth. It scans each `images/<kind>s/` directory once (cached at import) and, for every file matching `^<token>_<kind>_<id>_…`, records the token (validated against `[a-z0-9_]+`). `wiki_data.py` calls it to populate each card's `alt_variants` list and `has_alt_image` boolean; `server.py` exposes the same scan at `/card-image-variants/{kind}/{id}`. The scan is keyed off `<kind>` and `<id>` exactly, so an `alt_monster_13_*` file does not flag domain id 13.

The wiki UI uses `alt_variants` to render the artwork controls:

- **No alternates** → no "Alt" control.
- **One alternate** → a small "Alt" toggle (grid) / "Show alternate artwork" button (modal) that swaps between the canonical art and the single alternate.
- **Multiple alternates** → clicking "Alt" opens a chooser overlay laid over the card art with a thumbnail for **Original** plus each alternate; picking one swaps the image `src` to `?variant=<token>`.

Selections live only in JS state (`state.altSelections`, a `Map` of `${type}_${id}` → token) and persist between the grid and the detail modal for the session — refreshing the page resets every card to canonical art. If an alternate file fails to load, the `<img>` error handler strips the `?variant=` query and retries the canonical art before showing "no image".

Drop a matching `<token>_<kind>_<id>_*` file into the right directory and the wiki picks it up on the next cache refresh (`?refresh=1` or server restart).

The same convention powers the **in-game artwork chooser**. The game client fetches the bulk `GET /card-image-variants` map once on load to learn which cards have alternates, then renders a small top-right "Alt" control on any face-up card that supports them: a single alternate toggles in place, multiple alternates open a draft-styled chooser overlay (Original + each variant). Choices persist per viewer in `localStorage` (`vck_card_art_variants`, a `{"<type>_<id>": "<token>"}` map) and are applied through the client's `cardImageUrl`. The Margrave starter is a special case in `openCardArtChooser`: its chooser omits the "Original" tile because `alt_02` is a byte-for-byte duplicate of the canonical art.
