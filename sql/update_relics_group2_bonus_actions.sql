-- Group 2 relic effects: resource gain plus an optional bonus action prompt.
-- These use the same bare-leg payout grammar and prompt verbs as implemented
-- agent/domain effects:
--   slay         -> immediate may-slay prompt
--   recruit      -> may-recruit prompt
--   build_domain -> optional domain-build prompt
UPDATE vckonline.relics
SET passive_effect = 'g 1 + build_domain'
WHERE name = 'Cornelius Ring';

UPDATE vckonline.relics
SET passive_effect = 's 1 + slay'
WHERE name = 'Mask of Asteraten';

UPDATE vckonline.relics
SET passive_effect = 'g 1 + recruit'
WHERE name = 'St. Aquila''s Statue';
