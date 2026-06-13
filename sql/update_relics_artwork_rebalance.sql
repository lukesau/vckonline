-- Relic rebalance to match new artwork text.
--   Cornelius Ring -- now costs an action (consumes_action 0 -> 1); effect
--                     string is unchanged ("g 1 + build_domain").
--   Evermap        -- when you buy a Domain, ignore 1 requirement OR gain 1
--                     Magic (was: ignore 1 requirement only).
--   Thunder Axe    -- slay-cost waiver capped at 1 Magic OR 1 Strength
--                     (was: up to 3 Magic OR 1 Strength).
UPDATE vckonline.relics
SET passive_effect_text = 'As an action, gain 1 Gold and you may buy a Domain.',
    consumes_action = 1
WHERE name = 'Cornelius Ring';

UPDATE vckonline.relics
SET passive_effect = 'action.build_domain ignore_requirement 1 or m 1',
    passive_effect_text = 'When you buy a Domain, you may ignore 1 Domain requirement or gain 1 Magic.'
WHERE name = 'Evermap';

UPDATE vckonline.relics
SET passive_effect = 'action.slay_discount magic=1 strength=1',
    passive_effect_text = 'When you slay a Monster, you may ignore 1 Magic or 1 Strength of the cost.'
WHERE name = 'Thunder Axe';
