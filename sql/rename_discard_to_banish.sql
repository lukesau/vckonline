-- One-shot migration: rename the "discard" mechanic to "banish" across any
-- monster/citizen/domain payout strings that were installed before the rename.
-- The engine now only recognizes `banish_center` / `banish_owned` (see
-- `_execute_banish_center_payout` / `_execute_banish_owned_payout` in game.py),
-- so any rows still using the old verbs would be a no-op at runtime.
--
-- Safe to re-run: each REPLACE is gated on a LIKE filter, so rows already
-- carrying the new verb (or not using the mechanic at all) are skipped.
USE vckonline;

UPDATE monsters
SET special_reward = REPLACE(special_reward, 'discard_center ', 'banish_center ')
WHERE special_reward LIKE '%discard_center %';

UPDATE monsters
SET special_reward = REPLACE(special_reward, 'discard_owned ', 'banish_owned ')
WHERE special_reward LIKE '%discard_owned %';

UPDATE citizens
SET special_payout_on_turn = REPLACE(special_payout_on_turn, 'discard_center ', 'banish_center ')
WHERE special_payout_on_turn LIKE '%discard_center %';

UPDATE citizens
SET special_payout_on_turn = REPLACE(special_payout_on_turn, 'discard_owned ', 'banish_owned ')
WHERE special_payout_on_turn LIKE '%discard_owned %';

UPDATE citizens
SET special_payout_off_turn = REPLACE(special_payout_off_turn, 'discard_center ', 'banish_center ')
WHERE special_payout_off_turn LIKE '%discard_center %';

UPDATE citizens
SET special_payout_off_turn = REPLACE(special_payout_off_turn, 'discard_owned ', 'banish_owned ')
WHERE special_payout_off_turn LIKE '%discard_owned %';

UPDATE domains
SET activation_effect = REPLACE(activation_effect, 'discard_center ', 'banish_center ')
WHERE activation_effect LIKE '%discard_center %';

UPDATE domains
SET activation_effect = REPLACE(activation_effect, 'discard_owned ', 'banish_owned ')
WHERE activation_effect LIKE '%discard_owned %';

UPDATE domains
SET passive_effect = REPLACE(passive_effect, 'discard_center ', 'banish_center ')
WHERE passive_effect LIKE '%discard_center %';

UPDATE domains
SET passive_effect = REPLACE(passive_effect, 'discard_owned ', 'banish_owned ')
WHERE passive_effect LIKE '%discard_owned %';
