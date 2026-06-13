-- Group 1 relic effects: pure resource trades (Gold Bastion, Lich Sword,
-- Philosopher's Tome). The relic power lives in `passive_effect` using the same
-- bare-leg payout grammar as agents. The relic affordability gate reads the
-- leading bare negative leg as the activation cost, so any pay-to-gain relic
-- must list its cost leg first.
-- (Treant Chest is a both-wild exchange; see update_relics_treant_chest_wild.sql.)
UPDATE vckonline.relics
SET passive_effect = 's 1 + g 1'
WHERE name = 'Gold Bastion';

UPDATE vckonline.relics
SET passive_effect = 's -1 + m 3'
WHERE name = 'Lich Sword';

UPDATE vckonline.relics
SET passive_effect = 'm -4 + g 3 + v 1'
WHERE name = 'Philosopher''s Tome';
