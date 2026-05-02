# Server (`server.py`)

## What it is

`server.py` is a FastAPI development server that:

- Maintains an in-memory lobby (`lobby`)
- Starts games when all lobby players are ready
- Stores active games in-memory (`games`)
- Exposes REST endpoints for lobby operations and game actions
- Serves a simple HTML test client at `/`

This server is intended for development/testing, not production.

## In-memory state

The server keeps three top-level collections:

- `lobby`: list of `LobbyMember` (players waiting to start a game)
- `games`: dict of `game_id -> Game`
- `gamers`: list of `GameMember` (player_id/name/game_id records for in-game players)

There is no persistence; restarting the server resets everything.

## Lobby flow

High-level flow:

- `POST /api/lobby/join`: creates a `LobbyMember` with a `shortuuid` `player_id`
- `POST /api/lobby/ready`: marks the player ready; when all lobby players are ready (and there are at least 2), it starts a game:
  - generates a new `game_id` (uuid4)
  - moves ready lobby members into `gamers` for that `game_id`
  - calls `load_game_data(game_id, "base1", game_gamers)` and constructs `Game(game_state)`
- `GET /api/lobby/status`: returns lobby members + whether the requesting player is already in a game

Lobby cleanup:

- `GET /api/lobby/status` prunes lobby members inactive for > 60 seconds

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

