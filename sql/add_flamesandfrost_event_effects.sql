-- Populate machine-readable activation_effect / passive_effect strings for the
-- flamesandfrost non-monster Event cards (ids 17-22). The human-readable
-- *_text columns were already authored; these are the strings the engine
-- parses (see engines/events.py and docs/effect-strings.md "Events").
--
-- Audience prefixes:
--   active_may  -- active player optional prompt
--   all_may     -- each eligible player resolves concurrently (optional)
--   all_must    -- each eligible player resolves concurrently (mandatory)
--   active_lose / others_lose / all_lose -- immediate, no prompt
-- Passive roll trigger: `roll.on_event <event> all_lose <res> <amt>`.
USE vckonline;

-- A Call To Arms: "All players may immediately banish a Soldier Citizen for 3 Victory Points."
UPDATE events
SET activation_effect = 'all_may banish_owned_citizen role=soldier gain=v:3'
WHERE id_events = 17;

-- The Wizards of Nae: "The Active player may immediately pay 3 Magic for an additional action."
UPDATE events
SET activation_effect = 'active_may gain_action pay=m:3'
WHERE id_events = 18;

-- Support The Empire: "All players may immediately pay 5 Wild for 3 Victory Points."
-- "Wild" = each player chooses one resource type (g/s/m) and pays 5 of it.
UPDATE events
SET activation_effect = 'all_may self_convert pay=wild:5 gain=v:3'
WHERE id_events = 19;

-- Curse of The North: "During any Roll Phase, when doubles are rolled all players lose 3 Magic."
UPDATE events
SET passive_effect = 'roll.on_event doubles all_lose m 3'
WHERE id_events = 20;

-- The Key and Blade: "The Active player immediately loses 3 Gold. All other players lose 1 Gold."
UPDATE events
SET activation_effect = 'active_lose g 3 + others_lose g 1'
WHERE id_events = 21;

-- A Betrayal of Bonds: "All players must immediately flip a Citizen."
UPDATE events
SET activation_effect = 'all_must flip_citizen'
WHERE id_events = 22;
