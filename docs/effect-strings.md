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
```

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
