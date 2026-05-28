-- Fill in Purser's special_payout_on_turn (citizen #48, Crimson Seas).
-- Card text: "Gain 1 gold for each Citizen you own."
--
-- Uses the existing `count owned_citizens <res> <mult>` verb already wired
-- into the citizen harvest path (game.py `execute_special_payout`). The
-- engine counts the active (unflipped) citizens in the player's tableau,
-- so the payout naturally scales with the tableau and excludes flipped
-- citizens — consistent with how `count owned_citizen_name` and other
-- per-citizen verbs treat the flipped state, and with the rule that a
-- flipped citizen sits out the harvest entirely.
--
-- Includes the Purser itself in the count (the Purser is a citizen in
-- `owned_citizens` at harvest time). Same self-counting convention as
-- Butcher (`count owned_worker g 2`, where the Butcher itself contributes
-- one worker pip).
USE vckonline;

UPDATE citizens
SET special_payout_on_turn = 'count owned_citizens g 1'
WHERE name = 'Purser';
