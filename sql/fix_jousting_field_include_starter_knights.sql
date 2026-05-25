-- Make Jousting Field's harvest passive count starter Knights in addition to
-- citizen Knights. The named-count harvest verb only counts one pool per leg,
-- so we compose two legs with the same ` + ` compounding grammar already used
-- by domain activations (and proposed for the unified effect-string grammar).
-- This mirrors how Warlord's special_payout counts both pools:
--   citizen leg: count owned_citizen_name Knight s 1
--   starter leg: count owned_starter_name Knight s 1
-- Card text: "During your Harvest Phase, gain 1gp * Knight you own."
USE vckonline;

UPDATE domains
SET passive_effect = 'harvest.gain_per_owned_citizen_name Knight g 1 + harvest.gain_per_owned_starter_name Knight g 1'
WHERE name = 'Jousting Field';
