# VCK Online API

This document describes how to play VCK Online over HTTP and WebSocket against the **hosted game server** at [https://vcko.lukesau.com](https://vcko.lukesau.com). Clients (bots, CLI harnesses, integrations) talk only to that server — no local backend, database, or repo checkout is required.

The API is the same surface the web client and debug page use: REST for lobby and game actions, optional WebSockets for live state. A bot can create or join lobbies, ready up alongside human players in the browser, and play full games as a normal peer.

**Audience:** bot authors, integration tests, headless clients.

**Engine reference (optional):** the game engine and web client live in the [basegame-vcko](https://github.com/lukesau/basegame-vcko) repo (`docs/game.md`, `docs/effect-strings.md`) if you need prompt semantics beyond this guide.

---

## Quick start

**Server:** `https://vcko.lukesau.com`

Minimal bot loop:

1. `POST https://vcko.lukesau.com/api/lobby/create` or `.../join` → store `player_id`
2. `POST .../api/lobby/ready` → wait for `game_id`
3. Poll `GET .../api/game/{game_id}/state?player_id=...` (or subscribe to WebSocket)
4. When it is your turn, `POST .../api/game/{game_id}/action`
5. Repeat until `phase == "game_over"`

HTTP-only polling is sufficient. WebSockets (`wss://vcko.lukesau.com/ws/...`) reduce latency but are not required.

---

## Base URL and transport

| Item | Value |
|------|-------|
| **API origin** | `https://vcko.lukesau.com` |
| **Web UI** | `https://vcko.lukesau.com/` (humans join lobbies here) |
| **Lobby WebSocket** | `wss://vcko.lukesau.com/ws/lobby` |
| **Game WebSocket** | `wss://vcko.lukesau.com/ws/game/{game_id}?player_id=...` |
| Content-Type | `application/json` on all POST bodies |
| CORS | `*` (any origin) |
| Auth | **None** — identity is an opaque `player_id` string you persist locally |

All paths below are relative to the API origin unless a full URL is given.

Games and lobbies are ephemeral server-side state. A missing game (404 with `drop_stored_game`) means the match is over or was cleaned up — clear your stored `game_id` and return to the lobby flow.

### HTTP vs WebSocket

| Concern | HTTP | WebSocket |
|---------|------|-----------|
| Lobby list / ready | `GET/POST /api/lobby/*` | `WS /ws/lobby` pushes `lobby_status` |
| Game state | `GET /api/game/{id}/state` | `WS /ws/game/{id}?player_id=` pushes `state` |
| Take actions | `POST /api/game/{id}/action` | *(not supported — actions are always HTTP)* |

Recommended hybrid: WebSocket for state pushes + HTTP for actions. A minimal bot can poll `GET /state` every 1–3 seconds instead.

---

## Identity and session

There is no login. The server issues IDs and trusts whoever presents them.

### `player_id`

- Issued by `POST /api/lobby/create` or `POST /api/lobby/join` (shortuuid string).
- **Persist it** across reconnects. Pass the same `player_id` on re-join so the server reuses your lobby seat instead of creating a duplicate member.
- A player may be in **at most one lobby** at a time. Joining a new lobby removes you from the old one.

### `game_id`

- Issued when a lobby starts (`POST /api/lobby/ready` response, or WebSocket `game_started`).
- Store alongside `player_id` for the duration of the game.

### Rejoin codes

After game start each human seat gets a code like `BLUE-FOX-42` in the `my_rejoin_code` field of game state (only visible to that player). Recover a dropped session with:

```
POST /api/game/{game_id}/rejoin
{"rejoin_code": "BLUE-FOX-42"}
→ {"game_id": "...", "player_id": "...", "message": "..."}
```

Rate-limited to 12 attempts per 60 seconds per game.

### Spectator mode

Omit `player_id` on state fetch and WebSocket connect. You receive a read-only projection (opponent dukes hidden). No actions are accepted.

---

## End-to-end lifecycle

```
┌─────────────┐     create/join      ┌─────────────┐
│   Lobby     │ ──────────────────►  │  All ready  │
│  (REST/WS)  │     ready up         │  + min met  │
└─────────────┘                      └──────┬──────┘
                                            │ game_id
                                            ▼
┌─────────────┐   poll or WS state   ┌─────────────┐
│  Game over  │ ◄──────────────────  │  In-game    │
│  / abandon  │   POST /action       │  play loop  │
└─────────────┘                      └─────────────┘
```

### Lobby phase

1. **Create** — `POST /api/lobby/create` with display `name`. You become owner.
2. **Join** — other bots/players `POST /api/lobby/join` with `lobby_id`.
3. **Configure** (owner only) — preset, `min_players` (2–5), expansion flags, duke count, etc. Changing settings clears everyone's ready flag.
4. **Ready** — each member `POST /api/lobby/ready`. Optional `debug_mode: true` gives 100/100/100 resources and rigged dice (any member's debug flag enables it for the whole game).
5. **Start** — when `len(members) >= lobby.min_players` (at least 2) and every member is ready, the server creates `game_id`, dissolves the lobby, and broadcasts `game_started`.

### In-game phase

1. Fetch state: `GET /api/game/{game_id}/state?player_id={player_id}`
2. Inspect `phase`, `action_required`, `concurrent_action`, `active_player_id`
3. Submit the appropriate action (see [Decision loop](#decision-loop-for-bots))
4. Response includes fresh `game_state`; WebSocket subscribers also get a `state` push

### Draft preset

If the lobby preset is `draft`, readying up starts an in-lobby draft instead of a game immediately. Poll `GET /api/lobby/status?player_id=...` — when `draft` is present, vote via `POST /api/lobby/draft/vote` until the draft completes and a game starts.

| Draft phase | `vote` payload |
|-------------|----------------|
| `agents` | boolean or `"yes"` / `"no"` |
| `relics` | boolean or `"yes"` / `"no"` |
| `monsters` | list of area name strings (up to 5) |
| `starters` | integer starter id |
| `citizens` | integer citizen id |

---

## Lobby API

All paths are relative to the server origin.

### `POST /api/lobby/create`

Create a lobby and join as owner.

```json
{
  "name": "Bot Alpha",
  "preset": "current",
  "min_players": 2,
  "expansion_only": false,
  "duke_select_count": 2,
  "random_no_optional_modules": false
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `name` | *(required)* | Display name (normalized server-side) |
| `preset` | `"current"` | See [Presets](#presets) |
| `min_players` | `2` | Floor 2–5; game won't start below this count |
| `expansion_only` | `false` | Restrict domains/dukes to expansion cards |
| `duke_select_count` | `2` | `2` or `3` dukes dealt per player |
| `random_no_optional_modules` | `false` | Random preset only: skip optional Crimson Seas modules |

**Response:** `{"player_id": "...", "lobby_id": "...", "message": "..."}`

### `POST /api/lobby/join`

```json
{"name": "Bot Beta", "lobby_id": "...", "player_id": "..."}
```

Pass your persisted `player_id` when re-joining the same lobby after a disconnect.

**Response:** `{"player_id": "...", "lobby_id": "...", "message": "..."}`

### `POST /api/lobby/leave?player_id={player_id}`

Leave the current lobby. Owner transfer or lobby deletion happens automatically.

### `POST /api/lobby/kick`

Owner only.

```json
{"player_id": "<owner>", "target_player_id": "<member to remove>"}
```

### `POST /api/lobby/rename`

```json
{"player_id": "...", "name": "New Display Name"}
```

### Owner settings

All reset every member's ready flag.

| Endpoint | Body |
|----------|------|
| `POST /api/lobby/preset` | `{"player_id", "preset"}` |
| `POST /api/lobby/min_players` | `{"player_id", "min_players"}` (2–5) |
| `POST /api/lobby/expansion_only` | `{"player_id", "expansion_only"}` |
| `POST /api/lobby/duke_select_count` | `{"player_id", "duke_select_count"}` (2 or 3) |
| `POST /api/lobby/random_no_optional_modules` | `{"player_id", "random_no_optional_modules"}` |

### `POST /api/lobby/ready`

```json
{"player_id": "...", "debug_mode": false}
```

**Responses:**

| Condition | Response |
|-----------|----------|
| Still waiting | `{"message": "Player ready", "all_ready": true/false}` |
| Draft lobby | `{"message": "Draft starting", "draft_starting": true}` |
| Game started | `{"message": "Game started", "game_id": "...", "players": [{"player_id", "name"}, ...]}` |

### `POST /api/lobby/unready`

```json
{"player_id": "..."}
```

### `GET /api/lobby/status?player_id={optional}`

```json
{
  "lobbies": [{
    "lobby_id": "...",
    "owner_id": "...",
    "preset": "current",
    "min_players": 2,
    "expansion_only": false,
    "duke_select_count": 2,
    "random_no_optional_modules": false,
    "members": [{
      "player_id": "...",
      "name": "...",
      "is_ready": false,
      "debug_mode": false
    }]
  }],
  "game_count": 3,
  "valid_presets": ["base", "crimsonseas", "current", "draft", ...],
  "min_players_range": [2, 5],
  "in_game": false,
  "game_id": null,
  "lobby_id": null,
  "draft": { }
}
```

When `player_id` is supplied and that player is in a lobby, `lobby_id` is set. When they are in an active game, `in_game: true` and `game_id` is set. The `draft` object is present during an active draft (phase, timer, candidates, your vote, tallies).

### `POST /api/lobby/draft/vote`

```json
{"player_id": "...", "vote": <phase-specific>}
```

### `GET /api/lobby/active-games`

Lightweight list of spectatable in-progress games.

### `GET /api/lobby/preset-preview?preset=...&expansion_only=...&players=...&duke_select_count=...`

Card pool preview for a preset. May return 503 if the preview service is temporarily unavailable.

---

## Game API

### `GET /api/game/{game_id}/state?player_id={optional}`

Returns the full game JSON for the viewer. Side effects on fetch:

- Auto-advances `roll` and `harvest` phases as far as the engine can without player input
- Arms the hurry-up timer when waiting on a player's standard action

**404:** `{"detail": "Game not found", "drop_stored_game": true}` — clear your stored `game_id`.

### `POST /api/game/{game_id}/action`

Perform a game action.

**Success:** `{"message": "Action performed", "game_state": { ... }}`

**Request body** — all actions require `player_id` and `action_type`. Additional fields depend on the action (see [Action types](#action-types)).

### `POST /api/game/{game_id}/apply_event_slay_cost`

Resolve a pending event slay-cost choice (when `pending_event_slay_cost` is set in state).

```json
{"player_id": "...", "monster_id": 12}
```
or
```json
{"player_id": "...", "event_id": 5}
```

### `POST /api/game/{game_id}/rejoin`

```json
{"rejoin_code": "BLUE-FOX-42"}
```

### `POST /api/game/{game_id}/abandon`

```json
{"player_id": "..."}
```

Ends the game for everyone. A 30-second shutdown countdown begins (`shutdown.redirect_at`); then the game is deleted.

### Dev-only

| Endpoint | Purpose |
|----------|---------|
| `GET /api/game/{game_id}/history` | Snapshot breadcrumb trail |
| `POST /api/game/{game_id}/back` | Undo one action-phase snapshot |

---

## WebSocket protocol

Connect with `wss://` (secure WebSocket) on the same host as the HTTP API.

### Lobby — `wss://vcko.lukesau.com/ws/lobby`

**Client → server** (after connect):

```json
{"type": "identify", "player_id": "<your id or null>"}
```

Send `identify` again after you receive a `player_id` from create/join. This bumps your activity timestamp and personalizes the snapshot.

**Server → client:**

| `type` | Payload |
|--------|---------|
| `lobby_status` | Same shape as `GET /api/lobby/status` (includes `type` field) |
| `game_started` | `{"type": "game_started", "game_id": "...", "player_ids": ["...", ...]}` |

The server pushes `lobby_status` on every lobby mutation and sends an initial snapshot on connect.

### Game — `wss://vcko.lukesau.com/ws/game/{game_id}?player_id={optional}`

**Client → server:** no actionable messages (text pings are fine).

**Server → client:**

| `type` | Payload |
|--------|---------|
| `state` | `{"type": "state", "state": { ...full game JSON... }}` |
| `error` | `{"type": "error", "code": 4004, "message": "Game not found", "drop_stored_game": true}` then connection closes |

Each connection receives a per-viewer projection (your dukes visible to you; opponents get stubs).

---

## Game state — fields a bot must read

The state object is large. These fields drive bot decisions:

| Field | Meaning |
|-------|---------|
| `phase` | `setup`, `roll`, `roll_pending`, `harvest`, `action`, `cleanup`, `game_over` |
| `active_player_id` | Whose turn it is |
| `actions_remaining` | Standard actions left this turn (usually 2, sometimes more) |
| `action_required` | `{"id": "<player_id>", "action": "<prompt kind>"}` — sequential prompt blocking progress |
| `pending_required_choice` | Structured options for the current `action_required` prompt |
| `concurrent_action` | Multi-player simultaneous gate (see below) |
| `player_list` | Scores, owned cards, resources per player |
| `citizen_grid`, `domain_grid`, `monster_grid` | Board stacks (top card per stack is actionable when `is_accessible`) |
| `die_one`, `die_two`, `die_sum`, `pending_roll` | Dice state during roll phase |
| `harvest_order`, `harvest_slots` | Harvest automation state |
| `agents_slots`, `goods_slots`, `tome_slots`, `noble_slots` | Expansion modules (Crimson Seas) |
| `exekratys_resources` | Exekratys pool |
| `pending_event_slay_cost` | Needs `POST /apply_event_slay_cost` before harvest continues |
| `hurry_up_seconds_remaining` | Shot clock; server auto-takes lowest resource if it expires |
| `shutdown` | Game ending (`reason`, `redirect_at`, `initiated_by`) |
| `my_rejoin_code` | Your rejoin code (only in authenticated view) |
| `resting_player_id` | At 5 players, who sits out this harvest |
| `game_log` | Human-readable event log |
| `tick_id` | Monotonic counter; useful to detect stale state |

### Hidden information

Opponent `owned_dukes` are stubbed (`duke_id: 0`, `is_visible: false`) unless you are that player. All other information in your player-specific state fetch is authoritative for your bot.

---

## Decision loop for bots

On each state update, evaluate **in this priority order**:

```
1. if phase == "game_over" → stop
2. if shutdown and reason != "game_over" → handle redirect / exit
3. if concurrent_action.pending includes my player_id
     → POST submit_concurrent_action
4. if action_required.id == my player_id
     → resolve prompt (act_on_required_action, finalize_roll, harvest_card, etc.)
5. if pending_event_slay_cost and I'm the chooser
     → POST /apply_event_slay_cost
6. if phase == "action" and active_player_id == my player_id
     and action_required.action == "standard_action"
     → take_resource / hire_citizen / build_domain / slay_monster / ...
7. else → wait (poll again)
```

**Blocking rules:**

- While `concurrent_action.pending` is non-empty, no standard turn actions succeed.
- While `action_required.id` is set to someone, the engine is waiting on that prompt.
- `roll_phase` and `harvest_phase` action types are rejected — the server auto-advances these on state fetch.

### Hurry-up timer

During the action phase, if the active player is idle on `standard_action` for **180 seconds**, the server automatically performs `take_resource` for their lowest resource. Bots should act before this fires in competitive play.

---

## Action types

All via `POST /api/game/{game_id}/action`.

### Standard action phase

Require `active_player_id == player_id`, `actions_remaining > 0`, and `action_required.action == "standard_action"`.

| `action_type` | Required fields | Notes |
|---------------|-----------------|-------|
| `take_resource` | `resource`: `"gold"` \| `"strength"` \| `"magic"` \| `"map"` | |
| `hire_citizen` | `citizen_id`, `payment` or `gold_cost`/`magic_cost` | Optional `tome_payment` |
| `build_domain` | `domain_id`, `payment` or `gold_cost`/`magic_cost` | Optional `tome_payment` |
| `slay_monster` | `monster_id` or `event_id`, `payment` or `strength_cost`/`magic_cost` | Optional `thunder_axe`: `"magic"` \| `"strength"` |
| `engage_agent` | `agent_slot_index` | Crimson Seas |
| `use_relic` | — | May or may not consume an action |
| `buy_goods` | `slot_indices` (list), `payment` | Araby goods |
| `buy_tomes` | `slot_indices`, `payment` | Nae Aerie tomes |
| `sail_exekratys` | `resource`: `"gold"` \| `"strength"` \| `"magic"` | |
| `rescue_noble` | `slot_index`, `resource` | Optional `tome_payment` |

**Payment object:**

```json
"payment": {"gold": 3, "strength": 0, "magic": 1}
```

Legacy scalar fields (`gold_cost`, `strength_cost`, `magic_cost`) still work. `payment` takes precedence when both are set.

**Tome payment** (face-up tomes flipped to pay, Crimson Seas):

```json
"tome_payment": {"gold": 1, "strength": 0, "magic": 0}
```

### Roll phase

| `action_type` | When | Fields |
|---------------|------|--------|
| `finalize_roll` | `action_required.action == "finalize_roll"` | Optional `die_one`, `die_two` (1–6) for modifiers |
| `reroll_pending_die` | Pending reroll prompt | `die_one`: `1` or `2` (which die to reroll) |
| `reroll_both_dice` | Both dice reroll available | — |

`finalize_roll` with no die overrides keeps the natural roll. With overrides, the server validates owned roll-modifier domains and charges gold.

After `finalize_roll`, the server auto-advances through harvest until blocked.

### Harvest phase

| `action_type` | When | Fields |
|---------------|------|--------|
| `harvest_card` | Manual harvest slot | `harvest_slot_key` e.g. `"citizen:3:0"` |
| `play_turn` | Dev convenience | Advances through roll+harvest to action phase |

Most harvest steps auto-resolve on `GET /state`. Interactive harvest payouts use `concurrent_action` kind `harvest_choices` or sequential `action_required` prompts.

### Prompt resolution

| `action_type` | When | Fields |
|---------------|------|--------|
| `act_on_required_action` | `action_required.id == player_id` | `action`: opaque string (see below) |
| `submit_concurrent_action` | `player_id` in `concurrent_action.pending` | `response`, optional `kind` |

### Rejected

| `action_type` | Why |
|---------------|-----|
| `roll_phase` | Automatic on state fetch |
| `harvest_phase` | Automatic on state fetch |

---

## Sequential prompts (`act_on_required_action`)

When `action_required.id` equals your `player_id`, inspect `action_required.action` and `pending_required_choice` to determine valid responses. Submit:

```json
{
  "player_id": "...",
  "action_type": "act_on_required_action",
  "action": "<response string>"
}
```

### Common `action_required.action` values

| Action | Typical response strings | Context in `pending_required_choice` |
|--------|--------------------------|--------------------------------------|
| `standard_action` | *(use market action types instead)* | Your turn — hire, build, slay, take resource |
| `finalize_roll` | *(use `finalize_roll` action type)* | `pending_roll`, owned roll-modifier domains |
| `choose_monster_slay` | `"<stack_index>"` or `"skip"` | `options` list of slayable monsters |
| `slay_monster_payment` | `"pay"` or payment split | costs in `pending_required_choice` |
| `choose_domain_to_build` | `"<stack_index>"` | build reward from slay/hire |
| `build_domain_payment` | `"pay"` with affordability check | domain cost |
| `choose_domain_reward` | `"<stack_index>"` | free domain pick |
| `choose_owned_card` | `"<index>"` | banish/return/flip targets on your tableau |
| `choose_player` | `"<index>"` (1-based in UI) or `"pay <res> <player_id>"` | victim selection |
| `choose_monster_strength` | `"<index>"` | Ancient Tomb +3 strength |
| `domain_self_convert` | `"accept"` or `"skip"` | optional bank trade |
| `domain_choose_resource` | `"g"`, `"s"`, `"m"`, `"v"` | pick a resource type |
| `may_sail` | `"accept"` or `"skip"` | bonus free sail |
| `may_recruit` | `"accept"` or `"skip"` | bonus recruit |
| `harvest_steal` | `"steal_victim <N>"` then `"steal_resource <res>"` | Thief steal — see `stage` |
| `harvest_optional_exchange` | `"accept"` or `"skip"` | optional harvest exchange |
| `harvest_wild_gain_exchange` | `"choose <N>"` (1-based) | pick gain option |
| `harvest_wild_cost_exchange` | `"accept"` or `"skip"` | pay-to-gain |
| `relic_wild_exchange` | `"relic_pay <res>"` / `"relic_gain <res>"` | two-stage relic flow |
| `exekratys_offering` | resource choice | Exekratys 6-roll |
| `event_slay_cost_choice` | monster/event index | Leviathan-style roll effect |
| `event_gain_action` | `"accept"` or `"skip"` | pay magic for +1 action |
| `event_active_choose` | `"choose <N>"` (1-based) | active player picks event branch |
| `event_sequence` | verb-specific (see below) | sequential event queue |

For **`choose`**-style prompts (harvest payouts, citizen effects), responses are often `"choose <N>"` (1-based index into `pending_required_choice` options) or `"skip"` when optional.

For **`event_sequence`**, inspect `pending_required_choice.verb`:

| Verb | Response |
|------|----------|
| `pay_to_chosen` | `"pay <res> <target_player_id>"` |
| `banish_center_citizen` | `"<stack_index>"` |
| `banish_owned_citizen` | `"<card_index>"` or `"skip"` |
| `place_reserve_monster` | `"place <grid_index> <stack_index>"` |

The web client source in the engine repo (`static/game/src/05-prompts.js`) is the authoritative mapping from each prompt shape to response strings. When building a bot, search that file for the `action_required.action` value you need.

---

## Concurrent actions (`submit_concurrent_action`)

When multiple players must respond simultaneously:

```json
{
  "player_id": "...",
  "action_type": "submit_concurrent_action",
  "kind": "choose_duke",
  "response": "42"
}
```

`kind` is optional but recommended as a sanity check. The game blocks until `concurrent_action.pending` is empty.

### Registered kinds

| `kind` | `response` format | When |
|--------|-------------------|------|
| `choose_duke` | duke id integer as string | Setup — keep one dealt duke |
| `choose_relic` | relic id integer as string | Setup — keep one dealt relic |
| `flip_one_citizen` | citizen index as string | Cursed Cavern, event effects |
| `harvest_choices` | `"<prompt_id>\|<payload>"` | Interactive harvest payouts |
| `event_self_convert` | `"accept"` or `"skip"` | Concurrent event pay-for-VP |
| `event_banish_citizen_for_reward` | citizen index or `"skip"` | Concurrent event banish |

### `harvest_choices` detail

`concurrent_action.data.prompts[your_player_id]` is a **list** of pending harvest decisions. Each entry has an `id`. Submit:

```
response: "<prompt_id>|accept"
response: "<prompt_id>|choose 2"
response: "<prompt_id>|skip"
```

Exact payloads mirror the sequential `act_on_required_action` strings, prefixed with the prompt id. Resolve payouts in any order. When your list empties, you drop off `pending`.

---

## Presets

Lobby-selectable presets come from `presets/*.json` where `"lobby_selectable": true`. Common values:

| Preset | Notes |
|--------|-------|
| `current` | Live format alias (presently `june2026`) |
| `base` | Stable base-set deal |
| `flamesandfrost`, `shadowvale`, `crimsonseas` | Expansion-filtered pools |
| `random` | All implemented cards with art on disk |
| `draft` | Pre-game draft in lobby |
| `june2026` | Rotating curated set |

Owner-only: `expansion_only` restricts domains/dukes to the expansion. `duke_select_count` of 3 deals an extra duke to choose from.

---

## Timeouts and cleanup

| Timer | Duration | Effect |
|-------|----------|--------|
| Lobby member idle | 600 s (10 min) | Pruned from lobby |
| Game idle | 180 s | Entire game deleted |
| Hurry-up (action phase) | 180 s | Auto `take_resource` (lowest) |
| Abandon shutdown | 30 s | Game destroyed, redirect to lobby |
| Rejoin rate limit | 12 / 60 s | Per game |

Touch lobby endpoints or send WebSocket `identify` to stay active in lobby. Game actions and state fetches refresh game activity.

---

## Errors

FastAPI returns `{"detail": "message"}` or `{"detail": [...]}` for validation errors.

| Code | Meaning |
|------|---------|
| 400 | Bad request / illegal game action (`detail` explains) |
| 403 | Not owner / not in game / not draft participant |
| 404 | Lobby, player, or game not found |
| 409 | Conflict (no active draft, etc.) |
| 429 | Rejoin rate limited |
| 500 | Server/engine failure |
| 503 | Preset preview DB unavailable |

Game-not-found 404s include `"drop_stored_game": true` — discard your cached `game_id`.

---

## Example: two-bot game

```bash
BASE=https://vcko.lukesau.com

# Bot A creates
curl -s -X POST $BASE/api/lobby/create \
  -H 'Content-Type: application/json' \
  -d '{"name":"BotA","preset":"base","min_players":2}' | jq .
# → note player_id, lobby_id

# Bot B joins
curl -s -X POST $BASE/api/lobby/join \
  -H 'Content-Type: application/json' \
  -d '{"name":"BotB","lobby_id":"<lobby_id>"}' | jq .

# Both ready
curl -s -X POST $BASE/api/lobby/ready \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"<botA_id>"}' | jq .
curl -s -X POST $BASE/api/lobby/ready \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"<botB_id>"}' | jq .
# → game_id

# Poll state
curl -s "$BASE/api/game/<game_id>/state?player_id=<botA_id>" | jq '.phase, .action_required, .concurrent_action'

# Duke selection (if in concurrent setup)
curl -s -X POST $BASE/api/game/<game_id>/action \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"<botA_id>","action_type":"submit_concurrent_action","kind":"choose_duke","response":"1"}' | jq '.game_state.phase'

# Take a resource on your turn
curl -s -X POST $BASE/api/game/<game_id>/action \
  -H 'Content-Type: application/json' \
  -d '{"player_id":"<botA_id>","action_type":"take_resource","resource":"gold"}' | jq '.game_state.actions_remaining'
```

### Joining humans in the browser

1. Bot creates lobby via API, shares `lobby_id` (visible in `GET /api/lobby/status`).
2. Human opens [https://vcko.lukesau.com/](https://vcko.lukesau.com/), enters name, joins the lobby from the list.
3. Bot and human both ready → same `game_id`.
4. Human plays in the browser; bot plays via API. Both are full peers.

---

## Example: HTTP-only bot skeleton (Python)

```python
import time
import requests

BASE = "https://vcko.lukesau.com"
SESSION = requests.Session()

def create(name):
    r = SESSION.post(f"{BASE}/api/lobby/create", json={"name": name, "min_players": 2})
    r.raise_for_status()
    return r.json()["player_id"], r.json()["lobby_id"]

def ready(player_id):
    r = SESSION.post(f"{BASE}/api/lobby/ready", json={"player_id": player_id})
    r.raise_for_status()
    return r.json().get("game_id")

def state(game_id, player_id):
    r = SESSION.get(f"{BASE}/api/game/{game_id}/state", params={"player_id": player_id})
    r.raise_for_status()
    return r.json()

def act(game_id, body):
    r = SESSION.post(f"{BASE}/api/game/{game_id}/action", json=body)
    r.raise_for_status()
    return r.json()["game_state"]

def play_tick(game_id, player_id, st):
    ca = st.get("concurrent_action") or {}
    if player_id in (ca.get("pending") or []):
        kind = ca.get("kind")
        if kind == "choose_duke":
            me = next(p for p in st["player_list"] if p["player_id"] == player_id)
            duke_id = me["owned_dukes"][0]["duke_id"]
            return act(game_id, {
                "player_id": player_id,
                "action_type": "submit_concurrent_action",
                "kind": kind,
                "response": str(duke_id),
            })
    req = st.get("action_required") or {}
    if req.get("id") == player_id and req.get("action") == "standard_action":
        return act(game_id, {
            "player_id": player_id,
            "action_type": "take_resource",
            "resource": "gold",
        })
    return st

pid, lobby_id = create("SimpleBot")
print("Waiting for opponent…")
while True:
    time.sleep(2)
    lob = SESSION.get(f"{BASE}/api/lobby/status", params={"player_id": pid}).json()
    if lob.get("in_game"):
        gid = lob["game_id"]
        break
    members = next(l for l in lob["lobbies"] if l["lobby_id"] == lobby_id)["members"]
    if len(members) >= 2 and not any(m["player_id"] == pid and m["is_ready"] for m in members):
        ready(pid)

st = state(gid, pid)
while st.get("phase") != "game_over":
  st = play_tick(gid, pid, st) or state(gid, pid)
  time.sleep(1)
```

Replace `play_tick` with real strategy. For prompt-to-action mappings beyond the tables in this doc, see the web client source in the engine repo (`static/game/src/05-prompts.js`).

---

## In-repo bots

This repository includes a Python bot package for headless matches against the hosted server:

```bash
python3 scripts/run_bot_match.py --preset base --poll-interval 1.5
```

- **`bots/client.py`** — HTTP client (`VckoClient`) for lobby and game endpoints
- **`bots/legal_moves.py`** — client-side legal move enumeration from state JSON
- **`bots/control_bot.py`** / **`bots/game_logic_bot.py`** — two bot classes (both random for checkpoint 1)
- **`bots/runner.py`** — creates a 2-player lobby and runs both bots in parallel threads

No local server or database is required. Both bots use `debug_mode: true` on ready by default (100/100/100 resources). Pass `--no-debug` for a normal game.

Unit tests: `python3 -m unittest tests.test_bot_legal_moves -v`

---

## Card images (optional)

Bots that render boards can fetch artwork from the same host:

```
GET https://vcko.lukesau.com/card-image/{card_type}/{card_id}?variant=
GET https://vcko.lukesau.com/card-image-variants/{card_type}/{card_id}
```

`card_type`: `monster`, `citizen`, `domain`, `duke`, `starter`, `event`, `noble`, `agent`, `relic`, `exhausted`.

---

## Further reading (engine repo)

These live in the [basegame-vcko](https://github.com/lukesau/basegame-vcko) repository and are useful when implementing prompt handlers, not for running a server:

| Doc / path | Role |
|------------|------|
| `static/game/src/05-prompts.js` | Prompt → `act_on_required_action` response strings |
| `static/game/src/06-lobby-and-boot.js` | Lobby REST + WebSocket client patterns |
| `game_concurrent.py` | Concurrent action kind handlers |
| `docs/game.md` | Engine phases, harvest, roll finalization |
| `docs/effect-strings.md` | Card effect grammar behind many prompts |
