-- Frost Ogre and Wendigo were stored with a bare `<citizens>` special_reward.
-- The engine's `execute_special_payout` has no top-level handler for bare
-- `<citizens>` (only `<domains>` is matched at that level), so the token falls
-- through to the default `case _:` branch and returns the `[-9999, 0, 0, 0]`
-- sentinel WITHOUT opening a citizen-pick prompt. When the slay was triggered
-- from a may-slay prompt (e.g. Dragoon harvest payout), that sentinel then
-- leaked into the player's gold (see the engine fix in `slay_monster` for the
-- defense-in-depth side of this bug).
--
-- The canonical form used by every other "gain any citizen" monster
-- (Gnolls, Orc Batrider, Gnoll Bonewitch, etc.) is `choose <citizens>`, which
-- correctly routes through the `case "choose":` branch and opens the
-- pick-a-citizen prompt. Normalize Frost Ogre + Wendigo to match.
--
-- Card text: "Gain a Citizen from the center stacks."
USE vckonline;

UPDATE monsters
SET special_reward = 'choose <citizens>'
WHERE name IN ('Frost Ogre', 'Wendigo')
  AND special_reward = '<citizens>';
