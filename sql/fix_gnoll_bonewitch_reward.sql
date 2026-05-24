-- Fill in Gnoll Bonewitch's special reward using a `discard_center` payout verb
-- combined with the existing `choose <citizens>` payout via the standard compound
-- " + " operator.
--
-- Grammar:
--   discard_center <kind> [optional]
--     kind:     citizen   (future: monster, ...)
--     optional: literal "optional" flag when actor may decline
--
-- "Discard" is a permanent removal: the chosen card leaves the center stacks
-- and lands on the single global game.discard_pile (shared across all players).
-- This is distinct from `flip_citizen` / Cursed Cavern (face-down but recoverable
-- and still on the owner's tableau), and distinct from discarding an owned card.
--
-- Compound chaining: when leg 1 (discard) opens its choose_owned_card prompt, the
-- remaining legs are stashed via _set_payout_continuation and resume automatically
-- after the discard handler clears the prompt. So the player discards a citizen,
-- then immediately gets the choose <citizens> prompt to pick a board citizen.
--
-- Card text: "Discard a Citizen and gain a Citizen from the center stacks."
USE vckonline;

UPDATE monsters
SET special_reward = 'discard_center citizen + choose <citizens>'
WHERE name = 'Gnoll Bonewitch';
