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

### 5-player "resting" seat

At exactly 5 players the rulebook adds a *resting* mechanic: each turn the
player who would have rolled immediately before the active player sits the
harvest out completely. They do **not** harvest on-turn or off-turn, do not
fire any of their citizens during the steal pre-phase, and do not get the
end-of-harvest "no payout" consolation prompt either. The resting seat
rotates with the active seat so every player rests exactly once every 5
turns.

`Game.resting_player_id()` is the source of truth. At 5 players it returns
`player_list[(turn_index - 1) % 5].player_id`; at any other player count it
returns `None` and the engine behaves exactly as before.

The skip is implemented in one place — `_harvest_player_id_order_starting_active`
filters the resting seat out of the harvest turn order, which is what both
the interactive harvest loop (`_harvest_run_automation_until_blocked`) and
the silent batch path (`harvest_phase`) iterate. `_harvest_complete_finalize`
also excludes the resting seat from `pending_harvest_choices` so its
`no_payout` starter (if any) does not fire for that player.

The end-of-harvest "no payout" / "doubles" outcome is entirely card-driven:
the only thing that can fire is an owned -1/-1 starter (e.g. Herald,
Margrave) via its `activation_trigger`, and it pays exactly what the card
depicts. There is no default consolation — a player who owns no such starter
(or a hypothetical board with no -1/-1 starter at all) gets nothing on the
no_payout and doubles outcomes. `_harvest_complete_finalize` enqueues a
player for the finalize-bonus gate only when they own a `no_payout` starter.

`resting_player_id` is exposed on the serialized game state; clients render
a "Resting" badge on that player's tableau (see `static/game/src/02-render-and-board.js`
and the dev client's harvest-delta strip).

#### "Not in play" — negative-effect immunity

While a seat is resting it is treated as "not in play" for negative
citizen / domain / monster / event effects: it is filtered out of every
target candidate list the engine builds. Specifically:

- citizen `steal ...` (Thief) — resting opponents drop out of the victim
  list alongside `immunity.take` holders (Castle of the Seven Suns).
- event `all_lose g|s|m N` — the resting seat is logged but loses zero.
- domain `concurrent_flip_one_citizen` (Cursed Cavern) — the resting
  seat is not added to the concurrent flip pending list.
- monster reward `flip_citizen targeted` — resting opponents drop out
  of the player-choice options.
- domain Sunder Bay (`_execute_banish_player_citizen_payout`) — resting
  opponents drop out of the banish target list.
- domain `take_from_player` mode in `_manipulate_candidates_other_players`
  — filtered alongside `immunity.take`. `pay_to_player` mode is positive
  for the target so the resting seat stays eligible.
- domain `take_owned` (`_prompt_take_owned_card`) — resting opponents
  and `immunity.take` holders both drop out of the player options.

The single source of truth is `Game._player_is_negative_effect_target(p)`,
which returns `False` exactly when `_player_is_resting(p)` is true. New
negative-targeting effects should call the helper rather than re-checking
`resting_player_id` directly.

#### `immunity.take` (Castle of the Seven Suns)

Castle of the Seven Suns reads, with the operator-icon legend, "Opponents
Cannot Take You" — and "you" is defined as "you as a player AND any of
your cards or Resources". The narrower `immunity.take` passive therefore
covers every "take" surface (resource AND card) but does not cover other
operators (`banish`, `flip`, event `all_lose`).

- Surfaces blocked: citizen `steal` (Thief), domain `take_from_player`
  (Cathedral of St Aquila, Orb of Urdr), domain `take_owned`.
- Surfaces NOT blocked: Sunder Bay banish (`_execute_banish_player_citizen_payout`),
  Cursed Cavern concurrent flip (`_begin_concurrent_flip_one_citizen`),
  monster reward `flip_citizen targeted` (`_execute_flip_citizen_payout`),
  event `all_lose g|s|m N`.

The helper is `Game._player_has_take_immunity(p)`. The legacy passive
string `immunity.steal` is still accepted for back-compat — pre-migration
DB rows continue to work — but every new card or migration should use
`immunity.take`.

#### Domain stack depth

At 2-4 players each of the five domain stacks is dealt 3 cards deep with
the top face-up (15 domains total). At 5 players each stack is dealt 4
cards deep with 3 hidden + 1 face-up (20 domains total) — see
`game_setup.py` (`domain_stack_depth = 4 if n == 5 else 3`). When a domain
is built, the next card in that stack is revealed immediately as the final
step of the Build a Domain action (base-rules step 5), so a buried domain
becomes face-up the moment the card above it is purchased.
`_reveal_hidden_domain_stack_tops` runs at turn end only as a defensive
no-op safety net.

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

### End-of-harvest `no_payout` bonus and the `doubles` interaction

A -1/-1 starter (Herald, Margrave, Coxswain) carries an `activation_trigger`
with two independent legs:

- **`doubles`** — fires in-band during the harvest scan whenever the final
  dice are a matching pair (`_build_harvest_slots`).
- **`no_payout`** — fires at the very end of harvest, but only if *none* of
  that player's cards activated this harvest (`_harvest_complete_finalize`
  → `_activate_finalize_bonus_for`).

**Default: fires at most once per harvest.** By default a -1/-1 starter's own
in-band doubles activation counts as "a card fired" and therefore suppresses
its own end-of-harvest `no_payout` leg, so on a doubles roll that activates no
other card the starter pays out exactly **once**. This is the behavior for the
Margrave (`doubles_or_no_payout`) and the Crimson Seas Coxswain
(`doubles_or_no_payout`) — the rulebook is explicit that the Coxswain "does not
activate two times if both conditions are met". This gate is not
preset-specific, so the once-only default applies in every game mode.

**Herald exception (`doubles_or_no_payout_twice`).** The base-set Herald is the
sole starter that fires **twice** — once for doubles, once for no_payout — on a
doubles roll which does not activate any dice-value citizens. The `twice` marker
makes the `no_payout` suppression check ignore the Herald's *own* in-band
doubles activation when deciding whether "a card fired". Every other activation
(the Peasant on 5, the Knight on 6, any citizen, or any other starter) still
suppresses `no_payout`.

`_harvest_complete_finalize` builds `activated_pids` by walking each player's
consumed slot keys and skipping the keys returned by
`_no_payout_starter_own_doubles_slot_keys` (which returns the doubles-leg slot
only for a `twice` starter — i.e. the Herald). A Herald player whose only
activation was that doubles leg therefore still appears in the end-of-harvest
bonus gate; a Margrave/Coxswain player in the same situation does not.

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

## Crimson Seas rule deltas

The Crimson Seas expansion changes a few base rules. Beyond the maps/tomes/
goods/nobles machinery, two engine-level rule deltas are worth calling out:

- **Nobles count toward Domain build prerequisites.** "Build a Domain" now
  reads "the Citizens *and/or* Nobles in your tableau must have Citizen Role
  icons that match those on the Domain card." Nobles carry the same
  shadow/holy/soldier/worker counts as Citizens, so
  `Game._player_build_role_totals` sums both `owned_citizens` and
  `owned_nobles`. This single helper backs both the direct `build_domain`
  gate and the Ararmartin Ridge "may build" offer
  (`_execute_build_domain_activation_payout`). Outside Crimson Seas a player
  has no Nobles, so the tally is unchanged in every other mode.

- **Three new end-game conditions.** In addition to "all monsters slain",
  "all domains built", and "exhausted stacks filled",
  `_check_end_game_condition` ends a Crimson Seas game when a Goods, Tome, or
  Noble slot row "must be replenished, but there are not enough tokens to fill
  in all 3 slots." After a take, `_packed_island_slots` (Goods/Tomes) and the
  direct Noble refill leave an unfillable slot as `None`, so a falsy entry in a
  3-slot row is the signal that a required replenish could not complete. These
  checks are gated on `crimson_seas_enabled()` (the slot rows are empty in
  every other preset). Like the other end conditions, the game then plays out
  the rest of the round before `_finalize_game` runs.

### Crimson Seas end-game scoring

`_calculate_final_scores` adds three Crimson-Seas-only VP sources on top of
base VP and the Duke (all gated on `crimson_seas_enabled()`), exposed on each
score entry as `tome_vp` / `goods_vp` / `noble_vp` plus a
`crimson_vp_breakdown` list of `{label, vp, detail}` lines for the
scoring-details UI:

- **Tomes** — 1 VP per owned Tome (`len(owned_tomes)`).
- **Goods** — scored per type in four independent "waves" (one per
  `game_setup.GOODS_TYPES`). Within a type the VP rises with count via
  `GOODS_VP_BY_COUNT = (0, 2, 4, 7, 12, 18, 25)` (tokens cap at 6 per type).
  Holding 2 of one type and 1 of another scores `4 + 2`, never tiered together.
- **Nobles** — each owned Noble scores like a Duke (`_compute_noble_breakdown`):
  a role/type/count multiplier (`shadow_multiplier` … `goods_multiplier`,
  `monster/citizen/domain/boss/minion/beast/titan_multiplier`) or a
  `special_duke_payout` string. Role-icon multipliers count icons across
  Citizens, Domains, **and** Nobles — the rulebook's explicit scoring note —
  which is why `Player.calc_roles` folds Nobles into the role pool (this also
  means a Duke scoring on role icons counts your Nobles' icons in a Crimson
  Seas game).

  `special_duke_payout` grammar (resolved by `_noble_special_payout_vp`):
  - `floor_div <gold|strength|magic> <divisor> <vp>` → `(resource // divisor) * vp`
    (e.g. Mikal the Moneylender: `floor_div gold 3 1` = 1 VP per 3 gold).
  - `wild_choose <divisor> <vp>` → choose your single best resource type;
    `(best // divisor) * vp` (e.g. Dray: `wild_choose 2 1` = 1 VP per 2 of one
    chosen resource).

  Rescued Nobles are cards, so they also count toward the tie-break
  `tableau_size`.

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

### Harvest decisions gate (`harvest_choices`)

The harvest gate is a richer use of the concurrent subsystem. Rather than one
opaque response per player, `concurrent_action.data.prompts[player_id]` is a
**list** of decision snapshots — every interactive harvest payout that player
owns this roll, drained up front by `_collect_harvest_prompts_for`. The client
shows them all at once so the player can redeem them in whatever order they
like (opponents only see a "deciding / finished" status, never the specific
payout). Each snapshot carries a unique `id` (allocated via
`_alloc_prompt_id`, counter stashed in `data.prompt_seq`), and the client
submits `response = "<prompt_id>|<payload>"` so the handler knows which payout
is being resolved.

When a player resolves a decision the handler removes it, then tops up the list
via `_collect_harvest_prompts_for(..., fire_magic_passive=False)` to pick up any
follow-up prompt (a chained `choose`, the next leg of a compound payout) plus
slots left undrained behind a stashed `pending_payout_continuation`. The
end-of-harvest `on_any_magic_gain` passive is deferred until a player's list
empties so a magic-granting exchange they haven't redeemed yet is still counted
(pure-automatic harvesters fire it immediately during the initial drain). The
wild-exchange resolvers re-check affordability before paying, so a payout
redeemed after another spent the same resource can never push a balance
negative.

