-- Thunder Axe is a passive slay-cost reducer (not click-to-use). When the owner
-- slays a Monster they may ignore up to 3 face-value Magic OR 1 face-value
-- Strength of the cost; the waiver is offered inside the slay payment modal and
-- never spends an action of its own (consumes_action stays 0). The caps apply
-- only to the monster's printed cost, never to magic paid as wild Strength.
UPDATE vckonline.relics
SET passive_effect = 'action.slay_discount magic=3 strength=1'
WHERE name = 'Thunder Axe';
