-- Initial agent activation effects: pure resource trades (Captain, Prefect, Treasurer).
UPDATE vckonline.agents
SET activation_effect = 'manipulate_resources mode=self_convert pay=s:10 gain=v:5'
WHERE name = 'Captain';

UPDATE vckonline.agents
SET activation_effect = 'manipulate_resources mode=self_convert pay=m:10 gain=v:5'
WHERE name = 'Prefect';

UPDATE vckonline.agents
SET activation_effect = 'manipulate_resources mode=self_convert pay=g:10 gain=v:5'
WHERE name = 'Treasurer';
