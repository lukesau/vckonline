# Game engine (`game.py`)

## Key types

`game.py` defines the core runtime objects used by the server:

- `Game`: contains the current game board state and implements actions/phases
- `Player`: per-player scores and owned cards
- `LobbyMember` / `GameMember`: lightweight records used by the server for lobby/game membership

It also provides:

- `load_game_data(...)`: builds an initial `game_state` dict by pulling data from MariaDB and dealing stacks
- `SummaryEncoder` and `GameObjectEncoder`: JSON encoders used by the server to serialize game state

## Game lifecycle

At runtime (via the server):

- `server.py` calls `load_game_data(game_id, preset, game_gamers)` to create a starting `game_state`
- The server wraps that dict in a `Game` object: `Game(game_state)`
- The server exposes the game via `/api/game/{game_id}/state` and `/api/game/{game_id}/action`

The `Game` object tracks:

- `player_list`
- `monster_grid`, `citizen_grid`, `domain_grid`
- dice: `die_one`, `die_two`, `die_sum`
- `effects`
- `action_required` (used to block on per-player, sequential “choose …” actions)
- `concurrent_action` (used to block on non-ordered, multi-player prompts; see “Concurrent actions” below)
- `last_active_time` (used by the server for cleanup)

## DB-backed bootstrap (`load_game_data`)

`load_game_data` is responsible for:

- Fetching cards using stored procedures:
  - citizens/monsters depend on the `preset` (e.g. `"base1"` / `"base2"`)
  - domains and dukes are randomized via procedures
  - starters are selected via a direct `SELECT * FROM starters`
- Creating `Player` instances from the lobby/game membership list
- Randomizing player order and dealing initial cards
- Dealing stacks onto the board:
  - monsters grouped by area, then 5 areas selected
  - citizens grouped by roll match, placed into 10 stacks (special-cased for roll 11)
  - domains dealt into 5 stacks of 3, with the top visible/accessible

This function currently assumes local DB connectivity via `127.0.0.1:3306` (typically via SSH port forward).

See `docs/database.md` for DB setup and stored procedure installation.

## Actions & phases

The server routes map `action_type` strings to methods on `Game`.

Common paths:

- `roll_phase()` rolls two dice and computes a sum
- `harvest_phase()` pays out from owned starters/citizens for all players based on the roll
- `hire_citizen(...)`, `build_domain(...)`, `slay_monster(...)` mutate board stacks and player resources

### “choose …” actions

Some special payouts set `action_required` and start a background thread that waits until `act_on_required_action` updates `action_required` with a choice.

This is a dev-oriented approach; it allows the REST API to supply a follow-up choice via `act_on_required_action` while the game engine waits.

## Concurrent actions (non-ordered prompts)

Some prompts are not turn-based: every participating player should be able to
respond at the same time, in any order, and the game must wait until **all**
of them have submitted before progressing. The starting duke selection is the
first example — every player simultaneously discards down to one of the dukes
they were dealt.

These are modeled with `Game.concurrent_action`, which is independent from
`action_required`:

```
concurrent_action = {
    "kind": "choose_duke",      # routes to a handler in CONCURRENT_HANDLERS
    "pending":   ["pid1", "pid3"],
    "completed": ["pid2"],
    "responses": { "pid2": <opaque payload> },
    "data":      { ... }        # handler-specific extras (often empty)
}
```

Engine semantics:

- While `concurrent_action.pending` is non-empty, `advance_tick()` returns
  `False`. No phase transitions happen, no harvest progresses, and no
  per-player turn actions are accepted. `is_blocked_on_concurrent_action()`
  exposes the same predicate.
- Players submit via `Game.submit_concurrent_action(player_id, response, kind=...)`.
  The handler's `apply()` validates and applies that player's response
  immediately (so per-player effects don't have to wait for the others).
- When the last pending player submits, the handler's `finalize()` runs
  (for any cross-player resolution), `concurrent_action` is cleared, and
  if the engine was sitting in setup it advances forward.

### Adding a new concurrent action kind

1. Implement a handler class with:
   - `apply(self, game, player_id, response)` — validate + apply per-player
     side effects. Raise `ValueError` to reject a submission (the player
     stays in `pending`).
   - `finalize(self, game)` — optional; runs once after every participant
     has submitted.
2. Register it in `CONCURRENT_HANDLERS` keyed by `kind`.
3. Build the prompt with `_new_concurrent_action(kind, participant_ids, data=...)`
   and assign it to `game.concurrent_action` at the point in the engine
   where the gate should appear.
4. On the client, register a renderer in the `CONCURRENT_RENDERERS` map in
   the dev client (server.py HTML) keyed on the same `kind`.

Because the engine itself only knows "block while pending is non-empty",
the concurrent gate is fully reusable — no engine changes are required to
add new kinds (mulligan, simultaneous discard, voting, etc.).

