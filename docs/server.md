# Server (`server.py`)

## What it is

`server.py` is a FastAPI development server that:

- Maintains in-memory lobbies (`lobbies`)
- Starts games when every member of a lobby is ready
- Stores active games in-memory (`games`)
- Exposes REST endpoints for lobby operations and game actions
- Serves a simple HTML test client at `/`

This server is intended for development/testing, not production.

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
- a `preset` chosen from `_VALID_LOBBY_PRESETS = ("current", "base", "flamesandfrost", "shadowvale", "crimsonseas", "random", "draft")`. The preset is what gets passed to `load_game_data` when the game starts. `current` is the live "current format" alias and presently points at the canonical Base Set deal in `game_setup.py`; `base` is the same deal exposed as a stable preset so swapping `current` to a future format won't remove Base Set from the dropdown. Expansion presets (`flamesandfrost`, `shadowvale`, `crimsonseas`) filter the card pools by `expansion` column. `crimsonseas` draws monsters/citizens/events from `expansion='crimsonseas'`, domains from `expansion IN ('crimsonseas','base')`, all dukes (random across every expansion), and the regular Peasant/Knight starters plus a Crimson Seas `-1/-1` slot starter (falls back to Herald until that card exists). `random` deals from every implemented card across all expansions, dropping any row whose `is_implemented` predicate fails or whose `/card-image/{kind}/{id}` art file is missing on disk (see `card_filters.keep_for_random`). Banned cards (`banned_cards.json`) are filtered out of every preset's domain/duke deal. Only the lobby owner can change the preset.
- a `min_players` floor in the range `[_MIN_PLAYERS_FLOOR, _MIN_PLAYERS_CEIL]` (`2..5`). The game will not auto-start until the lobby has at least this many members and all of them are ready. Defaults to `2`, which matches historical behavior. Only the lobby owner can change it.
- a `members` list of `LobbyMember` records (display name, ready/debug flags, last-active timestamp).

A player is in at most one lobby at a time and is identified by a `shortuuid` `player_id` issued at create or join time.

Endpoints:

- `POST /api/lobby/create` body `{name, preset?, min_players?}` — creates a new lobby and joins it as owner (lobbies are nameless). Returns `{player_id, lobby_id}`.
- `POST /api/lobby/join` body `{name, lobby_id}` — joins an existing lobby. Returns `{player_id, lobby_id}`.
- `POST /api/lobby/leave?player_id=...` — removes the player from their lobby. If the leaver was the owner and other members remain, ownership transfers; if the lobby becomes empty it is deleted.
- `POST /api/lobby/rename` body `{player_id, name}` — updates the player's display name in their current lobby.
- `POST /api/lobby/preset` body `{player_id, preset}` — owner-only; sets the lobby's preset. Resets every member's ready flag so they re-confirm.
- `POST /api/lobby/min_players` body `{player_id, min_players}` — owner-only; sets the lobby's `min_players` floor (clamped to `2..5`). Resets every member's ready flag so they re-confirm under the new floor.
- `POST /api/lobby/ready` body `{player_id, debug_mode?}` — marks the player ready. When every member of the lobby is ready and the member count is at least `lobby.min_players`, a game is started: a new `game_id` (uuid4) is generated, the members are moved into `gamers`, the lobby is dissolved, and `load_game_data(game_id, lobby.preset, game_gamers, debug_mode=any_member_debug)` builds the initial `Game`.
- `POST /api/lobby/unready` body `{player_id}` — clears the ready flag.
- `GET /api/lobby/status?player_id=...` — returns `{lobbies, game_count, valid_presets, min_players_range, in_game, game_id, lobby_id}`. The `lobbies` array contains every open lobby with its members; each lobby payload includes `lobby_id`, `owner_id`, `preset`, `min_players`, and `members`. If `player_id` is supplied, the response also reports whether the player is already in a game and which lobby (if any) they currently belong to.

Lobby cleanup:

- Member idle timeout is `_LOBBY_MEMBER_TIMEOUT_S` (10 minutes). `build_lobby_status_dict` prunes members whose `last_active_time` is older than the cutoff and deletes any lobby that becomes empty as a result. Membership activity is bumped by lobby endpoints and by every `/ws/lobby` `identify` message.

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

Used to respond to a `concurrent_action` gate (see `docs/game.md`). The
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

## Game cleanup

On startup, a background task deletes games inactive for > 180 seconds and prunes the corresponding `gamers` entries.

## Dev HTML client

The root route `/` serves a simple HTML page that calls the lobby endpoints and can fetch a game state.

For run instructions, see `docs/README_SERVER.md`.

