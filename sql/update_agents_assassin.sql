-- Agent 2: Assassin
-- "Pay 3 Gold to flip a Citizen from another player's tableau. While flipped,
--  that Citizen does not activate in the Harvest Phase."
--
-- The leading bare cost leg `g -3` deducts 3 Gold to the bank (no resource
-- gain); `flip_opponent_citizen` reuses the existing targeted citizen-flip
-- prompt (choose a player, then one of their unflipped tableau citizens).
UPDATE vckonline.agents
SET activation_effect = 'g -3 + flip_opponent_citizen'
WHERE name = 'Assassin';
