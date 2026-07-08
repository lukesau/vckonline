# Server (`server.py`)

## Quick start

1. Set up the venv and database — see [agents.md](agents.md).
2. Confirm the SSH tunnel is up:

   ```bash
   python3 scripts/check_db_server.py
   ```

3. Run the server:

   ```bash
   python3 server.py
   ```

   Or with uvicorn directly:

   ```bash
   uvicorn server:app --host 0.0.0.0 --port 8000 --reload
   ```

   The server starts on `http://localhost:8000`.

4. Open `http://localhost:8000` for the dev HTML client.

This is a development/testing server, not production-ready. Games and lobbies are stored in-memory and are lost on restart.

### Client bundle (`static/game/game.js`)

The browser loads a single script from [`static/game/index.html`](../static/game/index.html). Source is split into ordered files under [`static/game/src/`](../static/game/src/):

| File | Responsibility |
|------|----------------|
| `01-core.js` | URL/cookie ids, WebSocket `connect`, idle timer, `mk` / `fmtPhase` / `escapeHtml` |
| `02-render-and-board.js` | Seats, tableau carousel, `render`, center board, card factory |
| `03-modals.js` | Player detail, game over/shutdown, card inspect, action confirm, prompt overlay shell |
| `04-market.js` | Board market hire/build/slay modals |
| `05-prompts.js` | Required-choice and concurrent-action prompt renderers |
| `06-lobby-and-boot.js` | Lobby UI/background and boot `init*` calls |

`static/game/game.js` is a build artifact: it is gitignored, overwritten on every server start (via `build_game_js.build()` in [`server.py`](../server.py)), and must not be edited directly.

To rebuild manually without restarting the server:

```bash
python3 build_game_js.py
```

The build runs `node --check` on the output if Node is installed; otherwise the syntax check is skipped silently.

For the hosted-server API reference (bots, integrations), see [vcko-api.md](vcko-api.md).

## What it is

`server.py` is a FastAPI development server that:

- Maintains in-memory lobbies (`lobbies`)
- Starts games when every member of a lobby is ready
- Stores active games in-memory (`games`)
- Exposes REST endpoints for lobby operations and game actions
- Serves a simple HTML test client at `/`

## In-memory state

The server keeps three top-level collections:

- `lobbies`: dict of `lobby_id -> Lobby` (each `Lobby` holds members, owner_id, preset, name)
- `games`: dict of `game_id -> Game`
- `gamers`: list of `GameMember` (player_id/name/game_id records for in-game players)

There is no persistence; restarting the server resets everything.

## Lobby flow

The server hosts many concurrent lobbies. Lobbies have no name — they
are identified internally by their `lobby_id` and surfaced to clients
purely by their metadata (preset, member list, min-players floor). This
sidesteps the awkwardness of deriving a name from the owner when
ownership transfers or the owner renames themselves. Each lobby has:

- an `owner_id` (initially the creator of the lobby; ownership transfers to the next remaining member if the owner leaves)
- a `preset` chosen from `_VALID_LOBBY_PRESETS = ("current", "base", "flamesandfrost", "shadowvale", "crimsonseas", "random", "draft")`. The preset is what gets passed to `load_game_data` when the game starts. `current` is the live "current format" alias and presently points at the canonical Base Set deal in `game_setup.py`; `base` is the same deal exposed as a stable preset so swapping `current` to a future format won't remove Base Set from the dropdown. Expansion presets (`flamesandfrost`, `shadowvale`, `crimsonseas`) filter the card pools by `expansion` column. `crimsonseas` draws monsters/citizens/events from `expansion='crimsonseas'`, domains from `expansion IN ('crimsonseas','base')`, all dukes (random across every expansion), and the mandatory core Peasant/Knight starters plus the Crimson Seas `-1/-1` optional starter (Coxswain). The optional `-1/-1` starter (Herald=base, Margrave=margraves, Coxswain=crimsonseas) is chosen per preset by expansion; if the expansion has no matching `-1/-1` starter the game simply plays without a doubles/no-payout trigger (no Herald fallback). `random` deals from every implemented card across all expansions, dropping any row whose `is_implemented` predicate fails or whose `/card-image/{kind}/{id}` art file is missing on disk (see `card_filters.keep_for_random`). Banned cards (`banned_cards.json`) are filtered out of every preset's domain/duke deal. Only the lobby owner can change the preset.
- a `min_players` floor in the range `[_MIN_PLAYERS_FLOOR, _MIN_PLAYERS_CEIL]` (`2..5`). The game will not auto-start until the lobby has at least this many members and all of them are ready. Defaults to `2`, which matches historical behavior. Only the lobby owner can change it.
- a `members` list of `LobbyMember` records (display name, ready/debug flags, last-active timestamp).

A player is in at most one lobby at a time and is identified by a `shortuuid` `player_id` issued at create or join time.

Endpoints:

- `POST /api/lobby/create` body `{name, preset?, min_players?}` — creates a new lobby and joins it as owner (lobbies are nameless). Returns `{player_id, lobby_id}`.
- `POST /api/lobby/join` body `{name, lobby_id, player_id?}` — joins an existing lobby. Returns `{player_id, lobby_id}`. Pass the caller's persistent `player_id` (from `vck_client`) so the server can recover from a duplicate join: if that `player_id` is already a member of this lobby (e.g. the user hit "back" and re-joined) the existing member is reused and only its display name is refreshed instead of creating a clone that can never ready up. If the `player_id` is sitting in a different lobby it is removed from there first (one client occupies one lobby).
- `POST /api/lobby/leave?player_id=...` — removes the player from their lobby. If the leaver was the owner and other members remain, ownership transfers; if the lobby becomes empty it is deleted.
- `POST /api/lobby/kick` body `{player_id, target_player_id}` — owner-only; removes another member (`target_player_id`) from the owner's lobby. Shares the leave path's ownership-transfer / empty-cleanup / draft-cancel behavior. The owner cannot kick themselves (use leave). The kicked client detects it is no longer a member on the next `lobby_status` broadcast and returns to the browse step.
- `POST /api/lobby/rename` body `{player_id, name}` — updates the player's display name in their current lobby.
- `POST /api/lobby/preset` body `{player_id, preset}` — owner-only; sets the lobby's preset. Resets every member's ready flag so they re-confirm.
- `POST /api/lobby/min_players` body `{player_id, min_players}` — owner-only; sets the lobby's `min_players` floor (clamped to `2..5`). Resets every member's ready flag so they re-confirm under the new floor.
- `POST /api/lobby/ready` body `{player_id, debug_mode?}` — marks the player ready. When every member of the lobby is ready and the member count is at least `lobby.min_players`, a game is started: a new `game_id` (uuid4) is generated, the members are moved into `gamers`, the lobby is dissolved, and `load_game_data(game_id, lobby.preset, game_gamers, debug_mode=any_member_debug)` builds the initial `Game`.
- `POST /api/lobby/unready` body `{player_id}` — clears the ready flag.
- `GET /api/lobby/status?player_id=...` — returns `{lobbies, game_count, valid_presets, min_players_range, in_game, game_id, lobby_id}`. The `lobbies` array contains every open lobby with its members; each lobby payload includes `lobby_id`, `owner_id`, `preset`, `min_players`, and `members`. If `player_id` is supplied, the response also reports whether the player is already in a game and which lobby (if any) they currently belong to.
- `GET /api/lobby/active-games` — returns `{games: [...]}` with lightweight metadata for every active, non-shutdown game. The lobby client uses this when the user clicks the active-games count and offers a Spectate button for each row.

Spectator mode uses the normal game page with only `game_id` in the query string (`/?game_id=...`) and no `player_id`. Spectators receive the same hidden-info-safe projection used for non-owning viewers (notably hidden duke stubs), connect to `/ws/game/{game_id}` without a player id, and can fetch `/api/game/{game_id}/state` without a `player_id`. The client treats this mode as read-only: prompts render as observer/waiting prompts, "Peek board" is available for blocking prompts, and market/action controls are suppressed.

## Timeouts and cleanup

Lobby cleanup:

- Member idle timeout is `_LOBBY_MEMBER_TIMEOUT_S` (10 minutes). `build_lobby_status_dict` prunes members whose `last_active_time` is older than the cutoff and deletes any lobby that becomes empty as a result. Membership activity is bumped by lobby endpoints and by every `/ws/lobby` `identify` message.

Game idle cleanup:

- A background task runs every 30 seconds and deletes games whose `last_audience_time` is older than 30 minutes (`_GAME_IDLE_TIMEOUT_S`). Audience time is bumped by seated-player `GET /state`, `POST /action`, rejoin, event-slay-cost, and `/ws/game` connects. Games stuck on a prompt with no one watching are reclaimed after the timeout. The server never auto-plays on behalf of idle players.

Action shot clock (display only):

- While the active player is waiting on a standard action during the action phase, the server arms a 3-minute (`SHOT_CLOCK_SECONDS = 180`) countdown exposed to the client as `hurry_up_deadline`. This is a nag timer only — it does not force a play or end the game.

## Game API

- `GET /api/game/{game_id}/state`: returns the current game state encoded using `GameObjectEncoder` (from `game.py`)
- `POST /api/game/{game_id}/action`: performs a game action and returns the updated game state

Supported `action_type` values currently include:

- `hire_citizen`
- `build_domain`
- `slay_monster`
- `take_resource`
- `harvest_card`
- `act_on_required_action` (sequential, single-player follow-ups)
- `submit_concurrent_action` (non-ordered, multi-player prompts; see below)
- `roll_phase`
- `harvest_phase`
- `play_turn`

### `submit_concurrent_action`

Used to respond to a `concurrent_action` gate (see `game.md`). The
serialized game state exposes a `concurrent_action` object with `kind`,
`pending`, and `completed` lists; while `pending` is non-empty no other
turn-based action will succeed. Request body:

```
{
  "player_id": "<pid>",
  "action_type": "submit_concurrent_action",
  "kind": "choose_duke",          // optional sanity check
  "response": "<opaque string>"   // handler-specific payload
}
```

The server validates that the player is in `pending` and that `kind`
(if provided) matches the active gate. Players may submit in any order;
when the last pending player submits, the engine auto-advances out of
the setup gate.

## Dev HTML client

The root route `/` serves a simple HTML page that calls the lobby endpoints and can fetch a game state.
