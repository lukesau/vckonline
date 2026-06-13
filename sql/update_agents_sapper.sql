-- Agent 12: Sapper
-- "Pay 3 Strength to flip a Domain from another player's tableau. While flipped,
--  that Domain power may not be used. At the end of the game, flip the Domain
--  face-up and score it as usual."
--
-- `s -3` pays the engage cost; `flip_opponent_domain` opens the targeted
-- domain-flip prompt (choose a player, then one of their unflipped tableau
-- domains). A flipped domain's passive power is suppressed (it is skipped by
-- every passive-application loop) and it is restored face-up before final
-- scoring. Bare verb; must be the tail of the compound.
UPDATE vckonline.agents
SET activation_effect = 's -3 + flip_opponent_domain'
WHERE name = 'Sapper';
