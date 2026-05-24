-- Fill in activation_effect strings for the two "return a card to its stack" domains.
-- Grammar: return_owned <kind> <resource> <amount> [optional]
--   kind:     monster | citizen
--   resource: g | s | m | v
--   amount:   non-negative int
--   optional: literal "optional" flag (when present, player may decline the effect)
--
-- Card text:
--   Watcher on the Water:        "You may immediately return a Monster to their stack to gain 3vp"
--   Nest of the Weaver Witch:    "You may immediately return a Citizen to their stack to gain 3vp"
USE vckonline;

UPDATE domains
SET activation_effect = 'return_owned monster v 3 optional'
WHERE name = 'Watcher on the Water';

UPDATE domains
SET activation_effect = 'return_owned citizen v 3 optional'
WHERE name = 'Nest of the Weaver Witch';
