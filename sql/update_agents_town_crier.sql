-- Agent 14: Town Crier
-- "Pay 3 Gold to gain 1 Victory Point and you may recruit a Citizen, ignoring
--  increased Gold cost for owning copies of that Citizen."
--
-- One-shot version of Emerald Stronghold's passive (ignore the +1-per-owned-copy
-- surcharge). `g -3` pays the engage cost, `v 1` grants the Victory Point, and
-- `recruit` opens the `may_recruit` bonus: one free Citizen recruit that spends
-- no regular action and waives the duplicate surcharge (the recruit still pays
-- the Citizen's base Gold cost). Bare verb; must be the tail of the compound.
UPDATE vckonline.agents
SET activation_effect = 'g -3 + v 1 + recruit'
WHERE name = 'Town Crier';
