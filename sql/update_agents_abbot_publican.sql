-- Agent activation effects: pay a cost, gain 1 VP, then gain a role-specific
-- Citizen of your choice (Abbot = Holy, Publican = Shadow). Bare resource-delta
-- legs (`<r> -N` cost + `v N` gain) replace the older verbose
-- `manipulate_resources mode=self_convert` form.
UPDATE vckonline.agents
SET activation_effect = 'm -5 + v 1 + <citizens where role==holy>'
WHERE name = 'Abbot';

UPDATE vckonline.agents
SET activation_effect = 'g -5 + v 1 + <citizens where role==shadow>'
WHERE name = 'Publican';
