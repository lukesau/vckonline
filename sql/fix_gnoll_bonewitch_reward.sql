-- Fill in Gnoll Bonewitch's special reward using a `banish_center` payout verb
-- combined with the existing `choose <citizens>` payout via the standard compound
-- " + " operator.
--
-- Grammar:
--   banish_center <kind> [optional]
--     kind:     citizen   (future: monster, ...)
--     optional: literal "optional" flag when actor may decline
--
-- "Banish" is a permanent removal: the chosen card leaves the center stacks
-- and lands on the single global game.banish_pile (shared across all players).
-- This is distinct from `flip_citizen` / Cursed Cavern (face-down but recoverable
-- and still on the owner's tableau), and distinct from banishing an owned card.
--
-- Compound chaining: when leg 1 (banish) opens its choose_owned_card prompt, the
-- remaining legs are stashed via _set_payout_continuation and resume automatically
-- after the banish handler clears the prompt. So the player banishes a citizen,
-- then immediately gets the choose <citizens> prompt to pick a board citizen.
--
-- Card text: "Banish a Citizen and gain a Citizen from the center stacks."
USE vckonline;

UPDATE monsters
SET special_reward = 'banish_center citizen + choose <citizens>'
WHERE name = 'Gnoll Bonewitch';
