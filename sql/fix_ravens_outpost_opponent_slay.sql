-- Raven's Outpost only triggers when an OPPONENT slays a Monster, not when the
-- owner does. The seed data used `action.on_any_slay s 1`, which fired for every
-- player including the slayer. Switch to the opponent-only verb and align the
-- card text with the rulebook:
--   "Raven's Outpost: This Domain is only activated when one of your opponents
--    slays a Monster, not when you slay a Monster."
-- Grammar: action.on_opponent_slay <g|s|m|v> <int>  (engines/harvest.py
-- _apply_reactive_slay_passives skips the slayer for this verb).
USE vckonline;

UPDATE domains
SET passive_effect = 'action.on_opponent_slay s 1',
    effect_text = 'During any Action Phase, when an opponent slays a Monster, gain 1 Strength.'
WHERE name = "Raven's Outpost";
