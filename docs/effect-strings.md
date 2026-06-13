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
| Barbarossa Castle | `banish_center noble + choose g 3 s 3 m 3` | Crimson Seas: prompt to banish one face-up Amarynth Noble (the slot refills from the noble deck), then choose 3 Wild (gold / strength / magic). Compound legs can't lead with `choose`, so banish is listed first; resolution order doesn't matter. |
| Brigand's Bay | `choose <goods>` | Crimson Seas: prompt to take any 1 face-up Araby Goods for free (no gold, no map); Araby then refreshes (cascade + redraw). `<goods>` expands to one pick per filled Araby slot, like `<noble>` / `t 1`. |
| Daak Harbor | `choose t 1` | Crimson Seas: prompt to take any 1 face-up Nae Aerie Tome for free (no gold, no map); Nae Aerie then refreshes (cascade + redraw). |
| Solo's Haven | `refresh_tomes` | Crimson Seas: flip all of the owner's spent (face-down) Tomes back face-up, so Tomes used earlier this turn can be reused immediately (e.g. pay for Solo's Haven with Tomes, then reuse them to buy something else the same turn). Bare verb; applies immediately with no prompt. |
| Dampiar's Workshop | `g 3 + p 1 + sail` | Crimson Seas: gain 3 Gold + 1 Map, then a `may_sail` prompt offers one **free Sail** (buy goods / buy tomes / rescue noble / sail to Exekratys). The bonus sail spends no regular action but still pays its own gold/map cost (the +1 Map funds it). `sail` is a bare verb (like `slay` / `build_domain`) and must be the tail of the compound. Declining resumes the turn. |

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
| Avery Hollow | `roll.exekratys_immune` | Crimson Seas flag: the owner is exempt from the Exekratys 6-roll offering during **their own** Roll Phase (they keep their Wild instead of placing one in the pool). Subject to the recurring-passive build-turn cooldown. |
| Browncoat's Sanctum | `effect.add action.browncoatssanctum` | Crimson Seas flag: Tomes cost the owner 1 gold less per Tome when buying from Nae Aerie. Subject to the recurring-passive build-turn cooldown. |
| Port of Drake | `effect.add action.portofdrake` | Crimson Seas flag: Goods cost the owner 1 gold less per Goods when buying from Araby. Subject to the recurring-passive build-turn cooldown. |
| Murat Reis | `effect.add action.muratreis` | Crimson Seas flag: when rescuing a Noble from Amarynth, the owner ignores the "+Wild" surcharge (+1 per Noble already in their tableau), paying a flat 9 of one resource type (+ 1 map). The noble-rescue analog of Emerald Stronghold's citizen `+` waiver. Subject to the recurring-passive build-turn cooldown. |
| Tabula Tower | `action.end manipulate_resources mode=self_convert pay=g:1 gain=p:1 optional=true` | Crimson Seas end-of-action optional trade: the owner may pay 1 Gold to gain 1 Map. Uses the generic `domain_self_convert` prompt; `p` is Map. Subject to the recurring-passive build-turn cooldown. |

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
| Recruit the King's Guard | activation | `place_kings_guard` | The only event that introduces a brand-new citizen stack. On reveal it drops the set-aside King's Guard citizens (`expansion = "kingsguard"` AND `special_citizen = 1`) on top of the event card so they can be hired like any board stack. Un-exhausting the event returns the un-hired guards to reserve (hired ones stay); re-revealing restores exactly that many. Hiring the whole stack leaves the event in place with nothing to hire (no "double exhaust") |
| Flaming Devourer | roll_effect | `banish_center_citizen optional` | Monster event. While in play, when a 4 is rolled, the active player may banish one accessible citizen from the center stacks. The `optional` token makes the prompt skippable. |
| Giants of Ostendaar | roll_effect + special_reward | `banish_center_domain optional` / `<domains>` | Monster event. While in play, when a 5 is rolled, the active player may banish one face-up domain from the center stacks; the next domain in that stack is revealed immediately (or the slot refills from the exhausted deck). Slaying it grants a free domain (`<domains>`). |
| Leviathan | roll_effect + special_reward | `add_self_slay_cost s 1 max=10` / `count owned_monsters v 1` | Monster event. While in play, when a 6 is rolled, 1 Strength token is added to the Leviathan, raising its own slay cost by 1 (printed + tokens), capped at +10. Slaying it grants 1 VP per owned Monster (the slain Leviathan counts). |
| Skeleton Army | roll_effect + special_reward | `flip_citizen targeted optional` / `choose g 4 t 1` | Monster event. While in play, when a 3 is rolled, the active player may flip one citizen on an opponent's tableau face-down (it stays inactive but is counted at end-game scoring); the prompt reuses the monster reward's targeted-flip flow and `optional` makes it skippable. The slay reward "Gain 4 Gold or 1 Tome": outside Crimson Seas the tome (`t`) leg is dropped (player just takes the gold); inside Crimson Seas the tome leg expands into one pick per face-up Nae Aerie tome, and choosing one takes it for free (no gold, no map) and refreshes the Nae Aerie row. |
| Ghost Ship | activation + roll_effect + special_reward | `add_self_gold_pool 1` / `add_self_gold_pool 1` / `gain_self_gold_pool` | Monster event with `roll_match1 == -1` (the "every roll phase" sentinel). On reveal, and at the end of **every** roll phase while in play, the active player places 1 Gold from their supply onto the card (a player short on gold places only what they have). The accumulated `gold_pool` is stored on the card (serialized, runtime-only like the `extra_*` costs). Whoever slays the ship claims the whole pool via `gain_self_gold_pool` (reads `game._immediate_slay_source_card`). |
| Pirate Blockade | roll_effect + special_reward | `block_recruit_matching_roll` / `choose g 4 p 2` | Monster event with `roll_match1 == -1`. While in play, during the active player's **Action Phase**, no citizen whose roll match (`roll_match1`/`roll_match2`) equals either die or the dice sum may be recruited or gained — this covers the Recruit a Citizen action and any Monster/Domain citizen grant. Enforcement is an on-demand in-play scan (`Game._citizen_blocked_by_pirate_blockade`), so slaying the ship lifts the restriction immediately; the roll effect firing just logs the blocked values. The slay reward "Gain 4 Gold or 2 Maps" reuses the existing map (`p`) handling. |

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
- `place_kings_guard` (Recruit the King's Guard) is an opaque activation key, not
  a parsed grammar. The King's Guard citizens are set aside at game setup
  (`game.kings_guard_pool`, only armed when the event is dealt to the deck) and
  the count mirrors the board citizen stack depth (5 at 2-4 players, 6 at 5).
  On reveal the engine places the whole reserve on top of the event's own board
  stack (any grid); only the top guard is accessible, the rest are face-up. The
  guards are hireable through the normal hire path (the engine and client both
  search every grid for the accessible top). When the event un-exhausts, the
  un-hired guards are pulled back to `kings_guard_pool`
  (`EventsEngine.retract_kings_guard_from_stack`, invoked from
  `_unexhaust_stack_top_if_present`) and the event recycles into the deck; a
  later re-reveal restores exactly the retracted count. Guards already hired into
  a tableau are never touched.
- Monster-event `roll_effect` verbs are dispatched by `DiceEngine._execute_event_roll_effect`
  against the FINAL dice each roll phase. `roll_match1` selects when they fire:
  a positive value matches that die or the dice sum, and the sentinel `-1` means
  "every roll phase" (Ghost Ship, Pirate Blockade). Verbs:
  `all_lose <r> N`, `add_slay_cost <r> N` (player picks a board monster),
  `add_self_slay_cost <r> N [max=K]` (accrue onto this card),
  `banish_center_citizen|banish_center_domain [optional]`,
  `flip_citizen targeted [optional]`, `add_self_gold_pool N` (active player moves
  N gold onto this card's `gold_pool`), and `block_recruit_matching_roll`
  (Pirate Blockade marker — no state mutation; the recruit/gain block is enforced
  on demand). `gain_self_gold_pool` is the matching slay reward that pays out the
  accumulated pool.
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
| Dragonkin Ravagers | `count type Minion g 3` | Gain 3g per owned Minion-type monster (any area) |
| Wereshark | `choose <count type Beast g 2> <count type Beast s 2> <count type Beast m 2>` | "Gain 2 Wild per owned Beast": pick g/s/m, each scaling 2 per owned Beast-type monster |
| Gargan Soul Hunters | `choose <citizens 3> <noble>` | "Gain 3 Citizens or 1 Noble" (Crimson Seas). The `<citizens 3>` leg chains three single-citizen picks; the `<noble>` leg expands into one free pick per face-up Amarynth noble. |
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
count owned_monsters g 1        # count monster cards owned (Leviathan ships `count owned_monsters v 1`)
count owned_citizen_name X g 1  # count face-up owned citizens named X (Jousting Field citizen leg)
count owned_starter_name X g 1  # count starter citizens named X (Jousting Field starter leg)
count owned_monster_name X g 1  # count owned monsters named X (Crimson Seas scaling rewards/costs)
count area Hills g 1            # count by monster area slain
count type Minion g 1          # count owned monsters by monster_type (Minion/Titan/Warden/Boss/Beast), any area
```

`count type <Type> <res> <mult>` scales by the player's owned monsters of a
given `monster_type` (the slain card is already in the owned pile, so a Boss
that rewards `count type Beast ...` does not count itself). It works as a bare
reward (`count type Minion g 3`) and inside a `choose` bracket
(`choose <count type Beast g 2> <count type Beast s 2> <count type Beast m 2>`
encodes "Gain 2 Wild per owned Beast"). Valid types are the five in
`Constants.types`; the token is rejected (no payout) for anything else.

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
and render with `/images/map.png`. Maps are earned through `choose`/payout legs
and can be spent by Sail actions; `manipulate_resources mode=self_convert`
also supports `gain=p:N` for Tabula Tower-style trades.

`t` = **tome**, another Crimson Seas resource. It appears as a `choose` leg
(e.g. Skeleton Army's `choose g 4 t 1`). Outside Crimson Seas the tome leg is
dropped from the prompt (same as `p` maps) so the player is left with the card's
non-tome out. Inside Crimson Seas a "gain 1 Tome" lets the player take any one
of the face-up Nae Aerie tomes for free: `_expand_choose_options_for_prompt`
turns the `t 1` leg into one `tome.choice` option per filled tome slot (carrying
`tome_type` + `slot_index`), and `_apply_choose_option` routes `tome.choice`
through `PlayerActionsEngine.take_tome_from_slot` (append to `Player.owned_tomes`,
then waterfall-refresh the row — no gold, no map). The leg is filtered out when
no tome slots are filled. Only single-tome gains (`t 1`) are supported.

#### `<noble>` and `<citizens N>` bracket legs

Two bracket legs back Gargan Soul Hunters' reward (`choose <citizens 3> <noble>`,
"Gain 3 Citizens or 1 Noble"):

- `<noble>` — a Crimson Seas "gain 1 Noble" leg, the noble analogue of the `t`
  tome leg. `_expand_choose_options_for_prompt` turns it into one `noble.choice`
  option per face-up Amarynth slot (carrying `noble_id`, `name`, `slot_index`),
  and `_apply_choose_option` routes `noble.choice` through
  `PlayerActionsEngine.take_noble_from_slot` — the chosen noble is taken for free
  (no resources, no map) and the emptied slot refills directly from the deck (no
  cascade, matching `rescue_noble`). The leg is dropped outside Crimson Seas or
  when no noble is face-up.
- `<citizens N>` — "gain N citizens of your choice". It is **not** a new
  multi-citizen mechanic: it is a single prompt option (`citizens_chain`) that,
  once picked, stashes a `pending_payout_continuation` of N bare `<citizens>`
  legs. The existing continuation machinery then opens (and resolves) one
  ordinary single-citizen pick at a time, stopping early if the board runs out.
  The leg is filtered out when no citizen is claimable.

Maps are gated to the **Crimson Seas preset** via `Game.crimson_seas_enabled()` (true
only when `preset == "crimsonseas"`). Crimson Seas citizens/monsters can still
appear in other presets (e.g. `random`), but they always have a non-map "out",
so outside Crimson Seas the engine drops `p` legs from `choose` prompts, rejects
the `+1 Map` standard action, and the client hides the map score pill and the
`+1 Map` button. Any incidental standalone `p N` gain still increments
`map_score` silently — it just isn't shown.

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

### 4c. `sail` — bare verb that opens an immediate may-Sail prompt (Crimson Seas)

Used by Dampiar's Workshop (`g 3 + p 1 + sail`). The engine treats a bare
`sail` token as: "the controlling player may immediately take one **free Sail**
action." Like `slay`/`build_domain` it appears as the tail of a compound so the
resource legs apply first (the `p 1` leg hands the player the Map the sail
needs).

```
sail                # bare verb; tail of a compound, e.g. "g 3 + p 1 + sail"
```

Resolution (action phase only):

- Opens `action_required.action = "may_sail"` with
  `pending_required_choice.kind = "sail_opportunity"`, and flags
  `pending_bonus_sail = <player_id>`.
- While that flag is set, `consume_player_action` lets exactly one sail action
  (`buy_goods` / `buy_tomes` / `rescue_noble` / `sail_exekratys`) run **without
  spending a regular action** and without being blocked by the prompt. The sail
  still pays its own gold/map cost.
- On success the server calls `resolve_bonus_sail_if_consumed`, which clears the
  flag + prompt and resumes the domain activation follow-up (restores
  `standard_action` or ends the turn). A failed sail rolls back to the still-open
  prompt so the player can retry.
- Declining (`act_on_required_action` with `skip`) clears the bonus and resumes.

The `may_sail` prompt is minimizable, so the player can also pick a specific
target (e.g. a particular Amarynth Noble) directly on the Sail mat instead of
using the prompt's destination buttons.

### 4d. `recruit` — bare verb that opens an immediate may-recruit-a-Citizen prompt

Used by the **Town Crier** agent (`g -3 + v 1 + recruit`). It is the one-shot
version of Emerald Stronghold's passive (`action.emeraldstronghold`): the
controlling player may immediately recruit one Citizen, paying its normal Gold
cost but **ignoring the +1-per-owned-copy duplicate surcharge**. Like
`slay` / `sail` / `build_domain` it is the tail of a compound so the resource
legs apply first (here `g -3` pays the engage cost and `v 1` grants the VP).

```
recruit             # bare verb; tail of a compound, e.g. "g -3 + v 1 + recruit"
```

Resolution (action phase only):

- Opens `action_required.action = "may_recruit"` with
  `pending_required_choice.kind = "recruit_opportunity"`, and flags
  `pending_bonus_recruit = <player_id>`. If no accessible Citizen is on the
  board the effect is silently skipped (no prompt) and the turn resumes.
- While that flag is set, `consume_player_action` lets exactly one `hire_citizen`
  run **without spending a regular action** and without being blocked by the
  prompt; `hire_citizen` waives the duplicate surcharge for that recruit (same
  code path as the Emerald Stronghold flag). The recruit still pays the
  Citizen's base Gold cost.
- On success the server calls `resolve_bonus_recruit_if_consumed`, which clears
  the flag + prompt and resumes the activation follow-up (restores
  `standard_action` or ends the turn). A failed hire rolls back to the still-open
  prompt so the player can retry.
- Declining (`act_on_required_action` with `skip`) clears the bonus and resumes.

The `may_recruit` prompt is minimizable, so the player picks the Citizen via the
normal market UI rather than from the prompt itself.

### 4e. `flip_opponent_domain` / `flip_domain targeted` — flip an opponent's Domain face-down

Used by the **Sapper** agent (`s -3 + flip_opponent_domain`). The domain analogue
of `flip_opponent_citizen` / `flip_citizen targeted`: a two-stage targeted prompt
(`choose_player` → `choose_owned_card`) that flips one of a chosen opponent's
face-up tableau Domains face-down. `flip_opponent_domain` is the agent-friendly
alias that injects the `choose_player` `explain` line; `flip_domain targeted
[optional]` is the canonical form.

```
flip_opponent_domain          # alias used by Sapper
flip_domain targeted          # canonical; `optional` adds a skip button
```

Resolution and semantics:

- Eligible targets are opponents who are negative-effect targets and own at least
  one unflipped Domain. If none exist the effect is silently lost (logged); the
  agent target gate (`_agent_has_valid_target`) also blocks engaging Sapper when
  there is no legal target.
- The flip sets `Domain.is_flipped = True` and hides the card (face-down). While
  flipped the Domain's power is **suppressed everywhere**: every passive-application
  loop (action.start/hire/build/slay events, the action.end manipulate queue,
  roll-phase die/doubles passives, harvest passives, and `_player_has_action_effect_flag`)
  consults the shared `_domain_power_suppressed(d)` chokepoint, which returns true
  for a flipped domain (and for the existing build-turn cooldown).
- A flipped Domain still **counts** as an owned domain for "per owned domain"
  effects and its build-time VP is unaffected — only its ongoing power is disabled.
- At the end of the game `unflip_all_domains_for_final_scoring()` restores every
  flipped Domain face-up before scoring, so it is scored as usual.

### 4f. `take_owned monster random` — take a random Monster from a tableau (Green Witch / Huntress)

The agent **Green Witch** (`take_owned monster random to=stack victim_vp=1`) and
**Huntress** (`take_owned monster random to=self victim_vp=1`) reuse the existing
`take_owned` operator (also used by some domain/monster effects). They are
"take" effects, so **Castle of the Seven Suns (`immunity.take`)** blocks them and
resting seats are not eligible targets.

```
take_owned <kind> <pick> [optional] [to=self|stack] [victim_vp=N]
  kind:       monster | citizen
  pick:       random
  optional:   activator may decline
  to=:        destination of the taken card — self (default; joins the
              activator's tableau) or stack (monster only; returned to its
              board stack). Omitting `to=` preserves the legacy "to self" behavior.
  victim_vp=  non-negative VP granted to the player the card was taken from
              (default 0).
```

Resolution: opens a `choose_player` prompt (`pending_required_choice.kind =
"domain_take_owned"`) listing eligible opponents who own ≥1 card of the kind; a
random card is then transferred to the chosen destination and the victim gains
`victim_vp`. The agent target gate refuses to engage when no eligible opponent
exists, so the player never spends an action for nothing.

### 4g. Final base agents: Baron / Brute Squad / King's Herald

These agents use existing compound payout grammar:

```
g -5 + count owned_domains v 1              # Baron
g -10 + <citizens> + banish_center citizen  # Brute Squad
banish_owned citizen + v 2                  # King's Herald
```

Notes:

- `count owned_domains v 1` counts whole owned Domain cards (flipped domains still
  count as owned; only their passive power is suppressed).
- Brute Squad chains two blocking legs: the first prompt gains a Citizen from the
  center stacks, then the continuation opens a `banish_center citizen` prompt.
  The agent target gate requires at least one accessible center Citizen before
  the agent can be engaged.
- King's Herald opens a `banish_owned citizen` prompt, then the continuation
  grants 2 VP. Its agent target gate requires the player to own at least one
  Citizen, preventing a free 2 VP when there is nothing to banish.

### 4a. `steal` — citizens (harvest) and the Bishop agent (action phase)

The thief-style verb. Lists one or more resource options the controller may
steal from a single chosen opponent. The controller picks the opponent first,
then (if multiple resource options are given) which resource to take.
Stealing is capped at the victim's current pool, so a victim with fewer than
`N` of the requested resource just loses what they have. `immunity.take`
holders and resting seats are excluded as victims.

```
steal g 3                  # steal up to 3g from a chosen opponent
steal g 3 m 3              # steal up to 3g OR up to 3m from a chosen opponent
steal g 5 m 5 victim_vp=1  # Bishop agent: + grant the victim 1 VP as compensation
```

The optional `victim_vp=N` trailer grants the stolen-from player N VP (the
**Bishop** agent gives 1 VP). Default 0.

On citizens, steal effects fire in a dedicated pre-phase at the start of harvest
before any normal citizen payouts — see "Harvest steal pre-phase" in
`docs/game.md`. The Bishop agent reuses the same victim→resource prompt during
the **action phase**; when the choice is applied outside harvest the engine
resumes the activation follow-up instead of the harvest pipeline. Its agent
target gate refuses to engage when no eligible victim exists.

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
