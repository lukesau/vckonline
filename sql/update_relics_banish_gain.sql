-- Action relics that banish a selected card, then grant resources through the
-- payout continuation system.
UPDATE vckonline.relics
SET passive_effect = 'banish_owned monster + g 5'
WHERE name = 'Dragon Orb';

UPDATE vckonline.relics
SET passive_effect = 'banish_center monster type=minion + g 2'
WHERE name = 'Fire Lance';

UPDATE vckonline.relics
SET passive_effect = 'banish_owned citizen + m 4'
WHERE name = 'Staff of Urdr';
