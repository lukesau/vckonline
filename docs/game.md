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

### Debug mode (`debug_mode`)

When the lobby's "Debug mode" checkbox is on, `load_game_data` is called
with `debug_mode=True` and each player receives, in addition to the
normal starting hand:

- 100 gold / 100 strength / 100 magic instead of the printed starting pool
- One copy of every accessible board citizen (one citizen per roll-match
  stack, popped off the top so the next card down becomes accessible)
- A fresh copy of every roll-modifier domain listed in
  `DEBUG_ROLL_MODIFIER_DOMAIN_IDS` (Foxgrove Palisade, The Desert Orchid,
  Palace of the Dawn). These are pulled with a direct
  `SELECT * FROM domains WHERE id_domains IN (...)` and added to each
  player's `owned_domains`. The grant itself is "illegal" relative to the
  printed game (every player owns three uniques), but the same IDs are
  also filtered out of the random board deal so nobody can purchase a
  second copy on top of the grant.

Because that filter would shrink the curated `test1` / `test2` domain
pools below the 15 cards the board needs (test1 includes ids 1 and 2;
test2 ranges 9..24 LIMIT 15 includes 19), debug mode also overrides only
those presets' domain query to `select_random_domains` so the filter
always has headroom. Other presets keep their configured domain pool.
Citizens and monsters still come from the preset's respective procs.

The roll-modifier domains plug into the same `_apply_roll_modification`
path real game-built domains use (no engine special-casing), so a debug
player can steer up to ONE die per modifier via the standard
`finalize_roll` prompt. Per-modifier reachable final values are: 6 (via
Foxgrove, 2g), 1 (via Desert Orchid, 1g per owned holy citizen), and
rolled-1 (via Palace of the Dawn, free). The engine allows up to two
modifiers per roll provided they target different dice and are sourced
from different cards — so a debug player can apply at most two of the
three granted domains per roll, "discarding" the third. See the
rigged-dice + doubles tables below for the complete reachable pairings.

#### Rigged dice (`DEBUG_DIE_ONE_VALUES`, `DEBUG_DIE_TWO_VALUES`)

In debug mode `Game.roll_phase()` does not call `random.randint(1, 6)`
for the dice. It picks each die out of constrained value sets defined in
`game_setup.py`:

```
DEBUG_DIE_ONE_VALUES = (2, 3)
DEBUG_DIE_TWO_VALUES = (4, 5)
```

The split is chosen so that the three granted roll-modifier domains can
collectively reach every value 1..6 on at least one die. The flag is
stored on the `Game` object as `self.debug_mode` (initialised from
`game_state["debug_mode"]`) and is also re-emitted by `GameObjectEncoder`
so clients can show a "this game is rigged" indicator if desired.
Everything downstream of the RNG (`pending_roll`, `finalize_roll`,
`_apply_roll_modification`, harvest matching, `roll_events`) is
unchanged — only the source distribution of `d1` / `d2` differs.

Reachability per natural roll (each cell lists the final dice you can
finalise into, given the one-modifier-per-roll constraint):

| Natural   | Keep      | Foxgrove (=6, 2g) | Desert Orchid (=1) | Palace (-1) |
|-----------|-----------|-------------------|--------------------|-------------|
| (2, 4)    | (2, 4)    | (6, 4) / (2, 6)   | (1, 4) / (2, 1)    | (1, 4) / (2, 3) |
| (2, 5)    | (2, 5)    | (6, 5) / (2, 6)   | (1, 5) / (2, 1)    | (1, 5) / (2, 4) |
| (3, 4)    | (3, 4)    | (6, 4) / (3, 6)   | (1, 4) / (3, 1)    | (2, 4) / (3, 3) |
| (3, 5)    | (3, 5)    | (6, 5) / (3, 6)   | (1, 5) / (3, 1)    | (2, 5) / (3, 4) |

##### Doubles in debug mode

`self.roll_events` and `self.die_one == self.die_two` both read off the
FINAL (post-modification) dice, so the starter `activation_trigger
doubles` leg and `roll.on_event doubles ...` passives agree on whether
the roll counted as doubles. In debug mode the rigged value sets `{2,3}`
and `{4,5}` are disjoint, so natural doubles can never happen — every
doubles in debug mode has to come through a modifier:

| Natural | → Final | Cost   | Modifier(s)                                                |
|---------|---------|--------|------------------------------------------------------------|
| (3, 4)  | (3, 3)  | 0g     | Palace `subtract=1` on die 2 (single modifier)             |
| (2, 4)  | (1, 1)  | 0g + H | Palace `subtract=1` on die 1 + Desert Orchid on die 2      |
| (2, 5)  | (1, 1)  | 0g + H | Palace `subtract=1` on die 1 + Desert Orchid on die 2      |

(H = the player's owned-holy-citizen count, charged as gold for Desert
Orchid.) Everything else is unreachable: Foxgrove (`target=6`) on both
dice would require the same card twice (rejected), Desert Orchid
(`target=1`) on both dice ditto, Palace on both dice ditto, and no
single-modifier path other than `(3, 4) → (3, 3)` finishes on a
matching pair. So doubles in debug mode is gated on rolling one of those
three natural pairs and burning the right modifier(s); it's NOT
on-demand.

## Actions & phases

The server routes map `action_type` strings to methods on `Game`.

Common paths:

- `roll_phase()` rolls two dice and computes a sum
- `harvest_phase()` pays out from owned starters/citizens for all players based on the roll
- `hire_citizen(...)`, `build_domain(...)`, `slay_monster(...)` mutate board stacks and player resources

### Roll finalization and dice modification

After `roll_phase()` runs, the engine enters `roll_pending` with
`action_required.action = "finalize_roll"` for the active player. The client
calls `finalize_roll(player_id, die_one=..., die_two=...)` to either keep the
rolled dice or apply one or two dice-modifying effects (e.g. Foxgrove
Palisade's `roll.set_one_die`). `_apply_roll_modification` validates the
proposed `(fd1, fd2)` against the player's owned `roll.set_one_die` domains
and, if legal, charges gold and writes one game-log line per applied
modifier.

The rule is "up to one modifier per CHANGED die":

- **0 dice changed**: trivially legal, no effects applied.
- **1 die changed**: exactly one matching, affordable effect from the
  player's tableau is charged and logged.
- **2 dice changed**: two matching effects sourced by DIFFERENT owned
  domains. Each card's text says "during your Roll Phase, you may ...
  change one die", i.e. one activation per phase per card, so the engine
  refuses to fire the same `domain_id` against both dice (see
  `_roll_modifier_same_source`). The combined gold cost (sum of both
  individual costs) must be affordable; charges land in a single
  finalize_roll transaction.

Unmatched / impossible / unaffordable combinations raise
`ValueError("Illegal roll modification")`. Costs are resolved from the
player's pre-modification state — fine in practice because no currently
supported `roll.set_one_die` cost spec depends on anything that mutates
between picks (only static gold or per-owned-role counts, neither of
which change mid-roll).

The two clients (`static/game/src/05-prompts.js` and
`static/dev-client/dev-client.js`) drive `finalize_roll` through a
two-stage prompt: stage 1 lists every legal `(die, modifier)` option (the
unchanged classic UI). Picking one stashes it locally as the "first
modifier" and re-renders into stage 2, which shows the staged choice, a
Confirm button (submits using just the first modifier), a Back button,
and any legal second-modifier buttons scoped to the OTHER die / a
different source domain / the player's remaining gold budget. Picking a
stage-2 button submits both modifiers in one `finalize_roll` call. The
engine validates whatever final `(fd1, fd2)` arrives independently of
the client's UI sequencing.

Two important invariants:

- `self.roll_events` is computed from the FINAL (post-modification) dice via
  `_compute_roll_events`. Anything that wants to know "did doubles happen
  this turn?" reads `roll_events`. A player who spent modifiers to land on
  e.g. doubles legitimately triggered the event — `roll_events`,
  `self.die_one == self.die_two`, and `_apply_board_event_roll_effects` all
  agree on what "the roll" was.
- `_apply_board_event_roll_effects(fd1, fd2)` fires Event-card roll effects
  against the FINAL dice. A roll modifier can therefore legitimately steer
  into or out of an Event trigger (same reasoning as above).

### “choose …” actions

Some special payouts set `action_required` and start a background thread that waits until `act_on_required_action` updates `action_required` with a choice.

This is a dev-oriented approach; it allows the REST API to supply a follow-up choice via `act_on_required_action` while the game engine waits.

### Harvest steal pre-phase

Citizens with a `steal ...` special payout (currently Thief, but the engine
treats `steal` as a generic verb so future cards can use it) resolve in a
dedicated pre-phase at the very start of harvest, before any normal citizen
or starter payouts fire. The active player resolves all of their pending
steals first, then each other player in normal harvest turn order (active
player first, then around the board).

Each individual steal opens a `harvest_steal` prompt with two stages on
`pending_required_choice`:

- `stage: "victim"` — `victim_options` lists every opponent. The controller
  responds with `act_on_required_action` action `steal_victim <N>` (1-indexed).
- `stage: "resource"` — only when the steal verb listed more than one
  resource option. `resource_options` lists each `{resource, amount}` pair
  and the controller responds with `steal_resource <N>` (1-indexed). When
  the steal verb only lists one resource, the engine skips this stage and
  applies the steal immediately after the victim is chosen.

While a `harvest_steal` prompt is pending, `advance_tick()` blocks just like
it does for `manual_harvest` / `harvest_optional_exchange`. After the steal
resolves, the engine resumes the harvest pre-phase scan and only moves on
to regular harvest payouts once every player's steals have resolved.

### Deferred may-slay-a-Monster prompts

Bare-verb `slay` payouts (see `docs/effect-strings.md`) opened by citizen
harvest payouts do **not** prompt mid-harvest. They append entries to
`pending_harvest_slays`, and `_harvest_run_automation_until_blocked` calls
`_drain_pending_harvest_slays` *after* every player's regular and special
payouts complete, but *before* `_harvest_complete_finalize`. This guarantees
the slay's monster reward (and any chained `special_reward`) resolves last,
after every other payout for every player.

Each drained entry opens the same two-stage `immediate_slay` prompt the
domain activation uses (`choose_monster_slay` → `slay_monster_payment`),
distinguished by `pending_required_choice.resume_kind = "harvest_pending_slay"`
so the post-resolve hook resumes the queue drain instead of the action-phase
follow-up. Silent batch harvest (`harvest_phase()`) skips and clears any
queued entries since there is no UI to prompt against.

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

