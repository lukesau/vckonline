-- Initial agent activation effects: pure resource trades (Captain, Prefect, Treasurer).
-- Bare resource-delta legs (`<r> -N` cost + `v N` gain) — the agent affordability
-- gate reads the leading bare negative leg as the engage cost.
UPDATE vckonline.agents
SET activation_effect = 's -10 + v 5'
WHERE name = 'Captain';

UPDATE vckonline.agents
SET activation_effect = 'm -10 + v 5'
WHERE name = 'Prefect';

UPDATE vckonline.agents
SET activation_effect = 'g -10 + v 5'
WHERE name = 'Treasurer';
