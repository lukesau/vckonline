-- Agents 3, 5, and 9.
--
-- Baron: pay 5 Gold, then gain 1 VP per owned Domain.
-- Brute Squad: pay 10 Gold, gain a Citizen, then banish a Citizen from the center stacks.
-- King's Herald: banish one of your own tableau Citizens, then gain 2 VP.
UPDATE vckonline.agents
SET activation_effect = 'g -5 + count owned_domains v 1'
WHERE name = 'Baron';

UPDATE vckonline.agents
SET activation_effect = 'g -10 + <citizens> + banish_center citizen'
WHERE name = 'Brute Squad';

UPDATE vckonline.agents
SET activation_effect = 'banish_owned citizen + v 2'
WHERE name = 'King''s Herald';
