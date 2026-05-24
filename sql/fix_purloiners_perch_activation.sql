-- Fill in Purloiner's Perch's activation using a new `take_owned` activation grammar.
-- Grammar: take_owned <kind> <pick> [optional]
--   kind:     monster | citizen   (Purloiner's Perch uses monster)
--   pick:     random              (future: choose -- let activator pick the specific card)
--   optional: literal "optional" flag when the activator may decline
-- Designed as the symmetric inverse of return_owned: instead of returning one of
-- your own cards to its board stack, you transfer one of someone else's owned cards
-- to yourself. Resolves through the existing `choose_player` prompt (same verb as
-- domain_manipulate_player), with prc.kind="domain_take_owned" as the discriminator.
-- Card text: "Immediately take a random Monster from a Player of your choice."
USE vckonline;

UPDATE domains
SET activation_effect = 'take_owned monster random'
WHERE name = 'Purloiner''s Perch';
