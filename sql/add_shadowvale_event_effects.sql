-- Populate machine-readable activation_effect / passive_effect strings for the
-- shadowvale non-monster Event cards (ids 23-30). The has_*_effect flags were
-- already set; these are the strings the engine parses (see engines/events.py
-- and docs/effect-strings.md "Events").
--
-- Audience prefixes:
--   active_choose -- active player picks exactly one option
--   all_gain_per_owned -- immediate scaled gain, no prompt
--   seq all_must / seq all_may -- "in turn order" sequential resolution
--                                 (active player first, resting seat excluded)
--   grant_all <flag> -- passive: grant a rest-of-game flag to every player
--   roll.on_event <trigger> <legs> -- passive roll trigger (legs joined by " + ")
USE vckonline;

-- Alms for the Poor: "In turn order, all players must immediately pay 2 Wild to
-- a player of their choice, if able." Wild = pay 2 of one chosen resource.
UPDATE events
SET activation_effect = 'seq all_must pay_to_chosen pay=wild:2'
WHERE id_events = 23;

-- Blessed Lands: "For the rest of the game, all Domains cost 2 Gold less to build."
UPDATE events
SET passive_effect = 'grant_all action.blessedlands'
WHERE id_events = 24;

-- Dark Lord Rising: "For the rest of the game, all Monsters cost 1 Magic more to slay."
UPDATE events
SET passive_effect = 'grant_all action.darklordrising'
WHERE id_events = 25;

-- Golden Idol: "The Active player may immediately gain 2 Gold or all players may gain 4 Magic."
UPDATE events
SET activation_effect = 'active_choose self_gain:g:2 | all_gain:m:4'
WHERE id_events = 26;

-- Good Omen: "During any Roll Phase, when doubles are rolled, all players gain 1 Gold, 1 Strength, and 1 Magic."
UPDATE events
SET passive_effect = 'roll.on_event doubles all_gain g 1 + all_gain s 1 + all_gain m 1'
WHERE id_events = 27;

-- Night Terror: "In turn order, each player must immediately Banish a Citizen from the center stacks."
UPDATE events
SET activation_effect = 'seq all_must banish_center_citizen'
WHERE id_events = 28;

-- Untapped Potential: "All players immediately gain 1 Magic for each Citizen they own."
UPDATE events
SET activation_effect = 'all_gain_per_owned gain=m:1 per=citizen'
WHERE id_events = 29;

-- Worthy Sacrifice: "In turn order, each player may immediately Banish one of their Citizens to gain 3 Victory Points."
UPDATE events
SET activation_effect = 'seq all_may banish_owned_citizen gain=v:3'
WHERE id_events = 30;
