-- Fill in Undead Samurai Rider's special reward using a new `flip_citizen` payout verb.
-- Grammar: flip_citizen <variant> [optional]
--   variant:  targeted  -- slayer picks one player, then one of that player's unflipped
--                          tableau citizens, and flips it face-down.
--             (future: self, all_opponents, ...)
--   optional: literal "optional" flag when the actor may decline at either stage
-- Reuses the existing _citizen_set_flipped machinery (same face-down semantics as
-- Cursed Cavern's concurrent flip): flipped citizens skip harvest payouts and don't
-- count for roll-phase per-role spends. Resolves through a two-stage prompt
-- (choose_player -> choose_owned_card) with prc.kind="monster_flip_citizen_targeted".
-- Card text: "Flip a Citizen in the tableau of a player of your choice."
USE vckonline;

UPDATE monsters
SET special_reward = 'flip_citizen targeted'
WHERE name = 'Undead Samurai Rider';
