-- Rewrite Gargan's Embrace passive into the new parametrized roll-event grammar.
-- Grammar: roll.on_event <event> <resource> <amount>
--   event:    doubles  (future: sum N, die N, ...)
--   resource: g | s | m | v
--   amount:   positive int
-- Card text: "During any Roll Phase, gain 1vp whenever doubles are rolled."
USE vckonline;

UPDATE domains
SET passive_effect = 'roll.on_event doubles v 1'
WHERE name = 'Gargan''s Embrace';
