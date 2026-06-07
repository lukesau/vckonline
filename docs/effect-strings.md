# Effect String Syntax

This document covers how effect strings work across the three card tables (citizens, domains, monsters), where the syntax currently diverges, and the proposed unified grammar.

---

## Current state by table

### Citizens — `special_payout_on_turn` / `special_payout_off_turn`

| Card | String | Meaning |
|---|---|---|
| Merchant | `choose g 2 m 2` | Pick one: +2g or +2m |
| Mercenary | `exchange s 1 g 2` | Pay 1s, gain 2g |
| Champion | `exchange g 1 s 4` | Pay 1g, gain 4s |
| Paladin | `exchange s 1 m 3` | Pay 1s, gain 3m |
| Butcher | `count owned_worker g 2` | Gain 2g per owned Worker citizen |
| Miner | `g 1 + count owned_domains g 1` | Gain 1g, then +1g per owned Domain |
| Purser | `count owned_citizens g 1` | Gain 1g per owned face-up Citizen (including the Purser; excluding flipped peers; not counting starter citizens) |
| Thief (on-turn) | `steal g 3 m 3` | Choose an opponent, then steal 3g or 3m from them |
| Thief (off-turn) | `choose g 2 m 2` | Pick one: +2g or +2m |
| Hydromancer (on-turn) | `choose m 2 p 1` | Pick one: +2 magic or +1 map (Crimson Seas) |
| Engineer (on-turn) | `choose g 2 s 2 p 1` | Pick one: +2 gold, +2 strength, or +1 map (Crimson Seas) |
| Smuggler (on-turn) | `choose g 4 p 2` | Pick one: +4 gold or +2 maps (Crimson Seas) |

### Domains — `activation_effect`

| Card | String | Meaning |
|---|---|---|
| Ancient Tomb | `action.modify_monster_strength +3` | Prompt: add 3 to a monster's strength cost |
| Pretorius Conclave | `choose <citizens>` | Prompt: take any citizen from the board |
| Cursed Cavern | `m 4 + concurrent_flip_one_citizen` | Gain 4m; all players flip a citizen |
| Darktide Harbour | `choose <citizens where role==shadow>` | Prompt: take a shadow citizen |
| Cloudrider's Camp | `s 3 + choose <citizens where role==soldier and gold_cost<=2>` | Gain 3s; prompt: take a soldier citizen worth ≤2g |
| Wisborg | `manipulate_resources mode=self_convert pay=g:3 gain=v:3 optional=true` | Optionally pay 3g to gain 3vp |
| Eye of Asteraten | `s 5 + slay` | Gain 5s, then prompt to slay an accessible monster (with normal payment) or pass |

### Domains — `passive_effect`

| Card | String | Meaning |
|---|---|---|
| Jousting Field | `harvest.gain_per_owned_citizen_name Knight g 1 + harvest.gain_per_owned_starter_name Knight g 1` | Harvest phase: gain 1g per Knight owned (citizens + starters) |
| Foxgrove Palisade | `roll.set_one_die target=6 cost=g:2` | Roll phase: pay 2g to set a die to 6 |
| The Desert Orchid | `roll.set_one_die target=1 cost=g_per_owned_role:holy_citizen` | Roll phase: pay 1g per holy citizen to set a die to 1 |
| Emerald Stronghold | `effect.add action.emeraldstronghold` | Flag: ignore + when buying citizens |
| Pratchett's Plateau | `effect.add action.pratchettsplateau` | Flag: domains cost 1g less |
| Shelley Commons | `action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1 optional=true` | End of action: optionally pay 1g to a player for 1vp |
| Cathedral of St Aquila | `action.end manipulate_resources mode=take_from_player take=g:1 optional=true` | End of action: optionally take 1g from a player |
| King Tower | `action.end manipulate_resources mode=pay_to_player gain=v:1 pay=m:1 optional=true` | End of action: optionally pay 1m to a player for 1vp |
| The Orb of Urdr | `action.end manipulate_resources mode=take_from_player take=m:1 optional=true` | End of action: optionally take 1m from a player |
| Castle of the Seven Suns | `immunity.take` | Opponents cannot take resources or cards from the holder. Covers `steal`, `take_from_player`, and `take_owned`; does NOT cover `banish` / `flip` / event `all_lose`. The legacy string `immunity.steal` is also accepted for back-compat. |
| The Violet Thorn | `action.slay manipulate_resources mode=gain gain=m:1` | Action phase: when **you** slay a Monster, gain 1 Magic (slayer-only; routes through `action.<verb>` gain passives) |
| Raven's Outpost | `action.on_opponent_slay s 1` | Action phase: when an **opponent** slays a Monster, gain 1 Strength (every owner except the slayer). The sibling verb `action.on_any_slay <r> <n>` fires for every owner including the slayer. |

### Events — `activation_effect` / `passive_effect`

Non-monster Event cards (`is_monster = 0`) fire when flipped off the Exhausted
stack onto a board stack (slay / hire / build / banish / free-take / harvest
payout — all routed through `EventsEngine.reveal_exhausted_onto_stack`). An
`activation_effect` fires once per reveal; a `passive_effect` applies while the
card sits in play on a board stack. Because returning a card to a center stack
un-exhausts the event back into the deck, the same event can be re-revealed and
re-fire later. (Monster events keep their `roll_effect` / slay behavior — see
`docs/game.md`.)

Audience prefixes decide who resolves an activation:

| Prefix | Who | Resolution |
|---|---|---|
| `active_may` | active player | optional sequential prompt |
| `all_may` | every eligible player | optional, concurrent (unordered) |
| `all_must` | every eligible player | mandatory, concurrent (unordered) |
| `active_choose` | active player | mandatory, pick exactly one option |
| `active_lose` / `others_lose` / `all_lose` | active / non-active / everyone | immediate, no prompt |
| `active_gain` / `others_gain` / `all_gain` | active / non-active / everyone | immediate, no prompt |
| `all_gain_per_owned` | everyone | immediate, no prompt; gain scales per owned card |
| `seq all_must` / `seq all_may` | every eligible player | sequential, **in turn order** (active player first) |
| `grant_all` (passive) | everyone | grants a named flag for the rest of the game |

The resting seat (5-player) is "not in play" and is excluded from every
**negative** event audience (losses, mandatory pay/banish, sequential `seq`
queues). Positive gains still reach everyone. Immediate losses floor at 0.

| Card | Column | String | Meaning |
|---|---|---|---|
| A Call To Arms | activation | `all_may banish_owned_citizen role=soldier gain=v:3` | Each player may banish one owned Soldier citizen for 3 VP |
| The Wizards of Nae | activation | `active_may gain_action pay=m:3` | Active player may pay 3m for +1 action (Action Phase only) |
| Support The Empire | activation | `all_may self_convert pay=wild:5 gain=v:3` | Each player may pay 5 of one chosen resource (g/s/m) for 3 VP |
| The Key and Blade | activation | `active_lose g 3 + others_lose g 1` | Active player loses 3g; every other player loses 1g |
| A Betrayal of Bonds | activation | `all_must flip_citizen` | Each player with a citizen must flip one face-down (reuses Cursed Cavern's concurrent flip) |
| Curse of The North | passive | `roll.on_event doubles all_lose m 3` | While in play: on a doubles roll, all players lose 3m |
| Alms for the Poor | activation | `seq all_must pay_to_chosen pay=wild:2` | In turn order, each player pays 2 of one resource to a chosen other player (if able) |
| Blessed Lands | passive | `grant_all action.blessedlands` | Rest of game: all Domains cost 2 gold less to build |
| Dark Lord Rising | passive | `grant_all action.darklordrising` | Rest of game: all Monsters cost 1 magic more to slay |
| Golden Idol | activation | `active_choose self_gain:g:2 \| all_gain:m:4` | Active player picks: gain 2g, OR all players gain 4m |
| Good Omen | passive | `roll.on_event doubles all_gain g 1 + all_gain s 1 + all_gain m 1` | While in play: on doubles, all players gain 1g/1s/1m |
| Night Terror | activation | `seq all_must banish_center_citizen` | In turn order, each player banishes the top citizen of a chosen center stack |
| Untapped Potential | activation | `all_gain_per_owned gain=m:1 per=citizen` | Each player immediately gains 1m per owned citizen |
| Worthy Sacrifice | activation | `seq all_may banish_owned_citizen gain=v:3` | In turn order, each player may banish one owned citizen for 3 VP |
| Bog Witch's Proposal | activation | `all_may self_convert pay=m:3 gain=v:2` | Each player may pay 3m for 2 VP |
| Gift from the Fae | activation | `active_gain m 2 + others_gain m 1` | Active player gains 2m; every other player gains 1m |
| Quell Rebellion | activation | `all_may self_convert pay=s:3 gain=v:2` | Each player may pay 3s for 2 VP |
| Twin Bandits of Pyth | passive | `roll.on_event doubles all_lose g 1 + all_lose s 1 + all_lose m 1` | While in play: on doubles, all players lose 1g/1s/1m |
| Blood Plague | activation | `all_lose s 2` | All players immediately lose 2s |
| Queen's Day Festival | activation | `active_gain g 2 + others_gain g 1` | Active player gains 2g; every other player gains 1g |
| Tax Collection | activation | `all_may self_convert pay=g:3 gain=v:2` | Each player may pay 3g for 2 VP |
| Tribute to the King | activation | `all_may self_convert pay=g:1,s:1,m:1 gain=v:2` | Each player may pay 1g + 1s + 1m (all three) for 2 VP |
| Undead Samurai Lord | activation + special_reward | `seq all_must place_reserve_monster pool=undead_samurai` / `count area "Undead Samurai" v 1` | Monster event. On reveal, in turn order each player places one set-aside Undead Samurai minion on a non-exhausted stack (any grid; it blocks the card beneath). Slaying the Lord gives 1 VP per owned Undead Samurai, then banishes any minions still on the board |

Notes on reuse:

- `self_convert pay=<r>:N gain=<r>:M` mirrors the domain bank-trade verb;
  `pay=wild:N` lets each player choose which resource (g/s/m) to spend. A
  **compound** cost `pay=<r>:N,<r>:M,...` (comma-separated, no wild/v legs)
  requires the player to pay *every* leg together; the prompt is a single
  accept/decline (no resource substitution).
- `flip_citizen` reuses the `flip_one_citizen` concurrent handler (Cursed Cavern).
- `roll.on_event <trigger> <legs>` fires while the event is in play. Legs are
  ` + `-joined `all_lose|all_gain <res> <amt>` clauses; losses skip the resting
  seat, gains reach everyone.
- `active_choose <opt> | <opt>` options are `self_gain:<r>:N` (active player only)
  or `all_gain:<r>:N` (everyone). The active player must pick exactly one.
- `seq ...` resolves **in turn order** starting with the active player and
  proceeding around the table; the 5-player resting seat is skipped for the
  harvest-style verbs. Players with no legal move are auto-skipped. Verbs:
  `pay_to_chosen pay=<r|wild>:N`, `banish_center_citizen`,
  `banish_owned_citizen gain=<r>:N [role=...]`, `place_reserve_monster pool=<name>`.
  Exception: `place_reserve_monster` uses the **full** table order (the resting
  seat still places), so all five minions can be scattered at 5 players.
- `place_reserve_monster` (monster events only) pulls from a set-aside reserve of
  monster cards (`game.undead_samurai_pool`, armed at setup) and lets each player
  drop one on a non-exhausted center stack of any grid. The placed monster sits on
  top and blocks the card beneath until slain. This is the only activation that
  fires on a **monster** event reveal; it is guarded by `game.undead_samurai_placed`
  so a re-revealed Lord event never scatters a second wave. The Undead Samurai Lord
  event and the Undead Samurai monster *area* are mutually exclusive at setup (same
  cards, two rule sets): if the area is dealt to the board the event is dropped from
  the deck. When the Lord is slain, `EventsEngine.on_undead_samurai_lord_slain`
  banishes any minions still on the board (owned minions are kept and were already
  tallied for the Lord's `count area "Undead Samurai" v 1` VP reward).
- `grant_all <flag>` is a "rest of the game" passive: on reveal it grants the
  named flag (e.g. `action.blessedlands`, `action.darklordrising`) to every
  player's `granted_effects` (idempotent). The grant is tied to the card being
  in play — if the event un-exhausts back into the deck (a card returned to its
  center stack), the flag is revoked from all players until it is re-revealed.
  These reuse the existing
  `_player_has_action_effect_flag` cost machinery — Blessed Lands subtracts from
  domain build cost, Dark Lord Rising adds to monster slay magic. The modifiers
  are uniform across players, so the server bakes them into the serialized board
  for display while validation applies them via the per-player flag.

### Monsters — `special_reward`

| Card | String | Meaning |
|---|---|---|
| Goblin Mage | `choose g 1 m 1` | Pick one: +1g or +1m |
| Goblin Bomber | `choose g 2 m 2 s 2` | Pick one: +2g, +2m, or +2s |
| Goblin King | `count area Hills g 1` | Gain 1g per Hills monster slain |
| Skeleton King | `count area Ruins g 2` | Gain 2g per Ruins monster slain |
| Bane Spider | `choose g 3 <citizens where name==Knight>` | Pick one: +3g or take a Knight citizen |
| Ettercap | `choose <citizens where gold_cost<=2>` | Take a citizen worth ≤2g |
| Spider Queen | `choose <count area Forest g 2> <citizens + v 1>` | Pick one: 2g per Forest monster slain, or take a citizen and gain 1vp |
| Satyr Mage | `choose g 5 m 5 s 5` | Pick one: +5g, +5m, or +5s |
| Troll | `count area Valley m 2` | Gain 2m per Valley monster slain |
| Dire Bear | `choose g 2 m 2` | Pick one: +2g or +2m |
| Orc Warrior | `choose <citizens where gold_cost<=3>` | Take a citizen worth ≤3g |
| Orc Batrider | `choose <citizens>` | Take any citizen |
| Orc Chieftain | `count area Mountain g 2` | Gain 2g per Mountain monster slain |
| (compound reward) | `<domains> + <citizens>` | Take a free domain, then take a free citizen (prompts open in order; reverse order also supported). |

---

## Where the syntax diverges

### 1. Resource notation — two forms

Citizens and monsters use positional shorthand; domain KV pairs use colon notation:

```
# positional (citizens, monsters)
choose g 2 m 2
count owned_worker g 2

# colon inside KV values (domain passives)
action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1
manipulate_resources mode=self_convert pay=g:3 gain=v:3
roll.set_one_die cost=g:2
```

### 2. `count` — same structure, different second word

The various `count` patterns are syntactically parallel but semantically distinct. No unification needed beyond being aware they share a parser.

```
count owned_worker g 2          # count by citizen role pip totals (sum of worker_count on each owned citizen, scaling 2g per pip)
count owned_citizens g 1        # count face-up citizen cards (Purser); excludes flipped citizens, excludes starters
count owned_domains g 1         # count domain cards (Miner)
count owned_monsters g 1        # count monster cards owned (reserved; no shipped card uses this yet)
count owned_citizen_name X g 1  # count face-up owned citizens named X (Jousting Field citizen leg)
count owned_starter_name X g 1  # count starter citizens named X (Jousting Field starter leg)
count area Hills g 1            # count by monster area slain
```

The card-pool family (`owned_citizens` / `owned_domains` / `owned_monsters`)
counts whole cards, not role pips. Flipped citizens are excluded from
`owned_citizens` so the count matches the harvest-eligibility rule — a
flipped citizen sits out its own payout, so it should not contribute to
"per owned citizen" payouts either. Domains and monsters have no flipped
state.

### 3. `choose` — brackets sometimes, not always

The bracket vs no-bracket distinction does carry real meaning and is worth keeping:

```
choose g 1 m 1                              # pick one of these resource amounts
choose g 3 <citizens where name==Knight>    # pick a resource amount OR an entity
choose <citizens where gold_cost<=2>        # pick an entity from a filtered set
choose m 2 p 1                              # pick one: +2 magic or +1 map (Crimson Seas)
```

#### Resource letters

`g` = gold, `s` = strength, `m` = magic, `v`/`vp` = victory points, and `p` =
**map** (the Crimson Seas "sail" resource). `m` was already magic, so maps use
`p`. Maps are tracked on `Player.map_score`, surface in `harvest_delta["map"]`,
and render with `/images/map.png`. There is currently no way to *spend* maps —
they are only earned (citizen payouts, the `+1 Map` standard action) and shown.

### 4. `exchange` — only exists in citizens

No equivalent pattern in domains or monsters. Could be expressed as a compound but `exchange` is readable:

```
exchange s 1 g 2    # pay 1s, receive 2g
```

### 4b. `slay` — bare verb that opens an immediate may-slay-a-Monster prompt

Used by domain activations (and, by design, future citizen harvest payouts).
The engine treats a bare `slay` token as: "the controlling player may
immediately slay one accessible monster, paying its normal strength/magic
cost." It replaces the older `grant_action slay` mechanic of accruing a
free-slay action token to spend later.

```
slay                # bare verb; usually appears as the tail of a compound, e.g. "s 5 + slay"
```

Resolution differs by phase:

- **Action phase (domain activation):** the prompt opens immediately. Stage 1
  (`action_required.action = "choose_monster_slay"`) lists every accessible
  monster top + a Pass button. Stage 2 (`action_required.action =
  "slay_monster_payment"`) collects the strength/magic payment and slays.
- **Harvest phase (citizen payout):** the slay opportunity is queued onto
  `pending_harvest_slays` and drained at the end of the harvest scan, so the
  slay's reward always resolves *after* every other harvest payout including
  special payouts (across all players). Each pending slay opens the same
  two-stage prompt in turn order.

`pending_required_choice.kind = "immediate_slay"` is the discriminator on
both stages; `resume_kind` (`"domain_activation"` or `"harvest_pending_slay"`)
tells the engine where to resume after the slay or pass.

### 4a. `steal` — only exists in citizens

The thief-style verb. Lists one or more resource options the controller may
steal from a single chosen opponent. The controller picks the opponent first,
then (if multiple resource options are given) which resource to take.
Stealing is capped at the victim's current pool, so a victim with fewer than
`N` of the requested resource just loses what they have.

```
steal g 3        # steal up to 3g from a chosen opponent
steal g 3 m 3    # steal up to 3g OR up to 3m from a chosen opponent
```

Steal effects fire in a dedicated pre-phase at the start of harvest before
any normal citizen payouts — see "Harvest steal pre-phase" in
`docs/game.md`.

### 5. `.` is doing three different jobs

```
harvest.gain_per_owned_citizen_name ...   # dot = phase separator (phase.verb)
roll.set_one_die ...                       # dot = phase separator (phase.verb)
action.end manipulate_resources ...       # dot = phase separator, then space, then verb
action.modify_monster_strength +3        # dot = namespace separator, not timing
effect.add action.emeraldstronghold      # dot = verb separator, then dot = namespace
```

### 6. `manipulate_resources` wrapper verbosity

The `mode=` value is doing the same work as a first-word verb. The wrapper adds noise:

```
# current
action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1 optional=true

# without the wrapper — same information
action.end pay_to_player g 1 v 1 optional
```

---

## Proposed unified grammar

### Core rules

1. **`.` means phase prefix only.** The left side is always a timing trigger (`harvest`, `roll`, `action.end`). Bare verbs have no dot.
2. **Resource amounts are always positional: `g N`.** Colon notation (`g:N`) only appears inside `=` assignments in KV strings where a space would be ambiguous.
3. **`choose` uses brackets for entity picks, bare words for resource picks.** Mixed is allowed: `choose g 3 <citizens where name==Knight>`.
4. **Compound effects use ` + `.** Each leg is a self-contained effect: `m 4 + concurrent_flip_one_citizen`. Compound dispatch happens before bracket shortcuts, so legs can themselves be bare `<domains>` / `<citizens>` (e.g. `<domains> + <citizens>` for a monster reward of "1 free citizen + 1 free domain"). The split scans top-level ` + ` only, so a ` + ` inside `<...>` (for example a citizens-where extras clause `<citizens + v 1>`) is never treated as a compound separator.

### Proposed rewrites

**Domain activation:**

```
# before → after
action.modify_monster_strength +3                             → modify_monster_strength 3
m 4 + concurrent_flip_one_citizen                             → no change
manipulate_resources mode=self_convert pay=g:3 gain=v:3 ...  → self_convert g 3 v 3 optional
choose <citizens where role==shadow>                          → no change
s 3 + choose <citizens where role==soldier and gold_cost<=2>  → no change
```

**Domain passive:**

```
# before → after
action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1 optional=true  → action.end pay_to_player g 1 v 1 optional
action.end manipulate_resources mode=take_from_player take=g:1 optional=true        → action.end take_from_player g 1 optional
action.end manipulate_resources mode=pay_to_player gain=v:1 pay=m:1 optional=true  → action.end pay_to_player m 1 v 1 optional
action.end manipulate_resources mode=take_from_player take=m:1 optional=true        → action.end take_from_player m 1 optional

harvest.gain_per_owned_citizen_name Knight g 1   → no change
harvest.gain_per_owned_starter_name Knight g 1   → no change (sibling verb; counts starter pool)
roll.set_one_die target=6 cost=g:2               → no change
effect.add action.emeraldstronghold              → no change
```

**Citizens and monsters:** no changes needed — syntax is already consistent within each table and the proposed rules codify what they already do.

---

## What stays as parsed strings vs opaque keys

All effects in the tables above are **parsed strings** — a new card with different numbers works without any code change.

The only candidates for opaque keys are effects with branching prompt logic unique to a single card that cannot be generalized with different parameters:

- `concurrent_flip_one_citizen` (Cursed Cavern) — multi-player concurrent event
- `modify_monster_strength 3` (Ancient Tomb) — board-state mutation prompt

Even these stay as strings under the unified grammar; they just dispatch to named functions rather than an inline parsing branch. The DB string is the key; the function is the implementation.
