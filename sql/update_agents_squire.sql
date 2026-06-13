-- Agent 13: Squire
-- "Pay 1 Gold to gain 3 Strength and you may immediately slay a Monster."
--
-- `g -1` pays the engage cost, `s 3` grants the Strength, and `slay` opens the
-- existing immediate may-slay-a-Monster prompt (same bare verb used by Eye of
-- Asteraten's `s 5 + slay`): the player may slay one accessible Monster paying
-- its normal cost, or pass. Bare verb; must be the tail of the compound.
UPDATE vckonline.agents
SET activation_effect = 'g -1 + s 3 + slay'
WHERE name = 'Squire';
