-- Populate machine-readable effect strings for the kingsguard / undeadsamurai
-- non-monster Event cards. Events 10 (Recruit the King's Guard) and 16 (Undead
-- Samurai Lord) are intentionally left for later — their mechanics need design
-- clarification. See engines/events.py and docs/effect-strings.md "Events".
USE vckonline;

-- Bog Witch's Proposal: "All players may immediately pay 3 Magic for 2 Victory Points."
UPDATE events
SET activation_effect = 'all_may self_convert pay=m:3 gain=v:2'
WHERE id_events = 7;

-- Gift from the Fae: "The Active player immediately gains 2 Magic. All other players gain 1 Magic."
UPDATE events
SET activation_effect = 'active_gain m 2 + others_gain m 1'
WHERE id_events = 8;

-- Quell Rebellion: "All players may immediately pay 3 Strength for 2 Victory Points."
UPDATE events
SET activation_effect = 'all_may self_convert pay=s:3 gain=v:2'
WHERE id_events = 9;

-- Twin Bandits of Pyth: "During any Roll Phase, when doubles are rolled all
-- players lose 1 Gold, 1 Strength, and 1 Magic." This is a passive roll
-- trigger; the seed data mislabeled it as an activation, so flip the flags.
UPDATE events
SET has_activation_effect = 0,
    has_passive_effect = 1,
    activation_effect = NULL,
    passive_effect = 'roll.on_event doubles all_lose g 1 + all_lose s 1 + all_lose m 1'
WHERE id_events = 11;

-- Blood Plague: "All players immediately lose 2 Strength."
UPDATE events
SET activation_effect = 'all_lose s 2'
WHERE id_events = 12;

-- Queen's Day Festival: "The Active player immediately gains 2 Gold. All other players gain 1 Gold."
UPDATE events
SET activation_effect = 'active_gain g 2 + others_gain g 1'
WHERE id_events = 13;

-- Tax Collection: "All players may immediately pay 3 Gold for 2 Victory Points."
UPDATE events
SET activation_effect = 'all_may self_convert pay=g:3 gain=v:2'
WHERE id_events = 14;

-- Tribute to the King: "All players may immediately pay 1 Gold, 1 Strength, and
-- 1 Magic for 2 Victory Points." Compound cost: pay every leg (no substitution).
UPDATE events
SET activation_effect = 'all_may self_convert pay=g:1,s:1,m:1 gain=v:2'
WHERE id_events = 15;

-- Undead Samurai Lord (a monster event). On reveal it scatters the set-aside
-- Undead Samurai minions (monsters 57-61) across the board, one per player in
-- turn order (each placed on a non-exhausted stack, blocking the card beneath).
-- When the Lord is slain its `count area` reward gives the slayer 1 VP per owned
-- Undead Samurai, then any minions still on the board are banished.
--   * activation_effect drives the one-time placement sequence.
--   * special_reward differs from the monster-stack Undead Samurai Lord (#63),
--     which grants magic; the EVENT version grants VP.
-- The event and the Undead Samurai monster area are mutually exclusive at setup.
UPDATE events
SET has_activation_effect = 1,
    activation_effect = 'seq all_must place_reserve_monster pool=undead_samurai',
    has_special_reward = 1,
    special_reward = 'count area "Undead Samurai" v 1'
WHERE id_events = 16;
