-- Agent 4: Bishop
-- "Steal 5 Gold or 5 Magic from another player. That player gains 1 Victory Point."
--
-- Reuses the citizen `steal` operator (victim -> resource prompt) so Castle of
-- the Seven Suns (`immunity.take`) blocks it and resting seats are skipped. The
-- `victim_vp=1` trailer grants the stolen-from player 1 VP as compensation.
UPDATE vckonline.agents
SET activation_effect = 'steal g 5 m 5 victim_vp=1'
WHERE name = 'Bishop';
