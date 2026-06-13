-- Treant Chest: a both-wild exchange. Pay 3 of any one resource (gold,
-- strength, or magic) to gain 5 of any one resource. This is not a fixed
-- bare-leg trade, so it uses the `exchange wild N wild M` form handled by the
-- relics engine's two-stage pay/gain prompt rather than the payout grammar.
UPDATE vckonline.relics
SET passive_effect = 'exchange wild 3 wild 5',
    passive_effect_text = 'As an action, you may pay 3 of any one resource to gain 5 of any one resource.'
WHERE name = 'Treant Chest';
