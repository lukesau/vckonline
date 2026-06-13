-- Passive "buy a Domain" relics. These are not click-to-use and do not spend
-- an action; they trigger automatically during a Domain build, so they use the
-- `action.build_domain ...` trigger-marker grammar (consumes_action stays 0).
--   Evermap     -- may ignore exactly one missing Domain role requirement.
--   Violet Ring -- gain 2 Victory Points whenever you buy a Domain.
UPDATE vckonline.relics
SET passive_effect = 'action.build_domain ignore_requirement 1'
WHERE name = 'Evermap';

UPDATE vckonline.relics
SET passive_effect = 'action.build_domain v 2'
WHERE name = 'Violet Ring';
