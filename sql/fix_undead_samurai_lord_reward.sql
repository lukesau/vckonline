-- Fill in Undead Samurai Lord's special reward: 1 magic per Undead Samurai monster
-- the slayer owns. Uses the existing `count area <area> <res> <mult>` payout grammar.
--
-- Multi-word area names (e.g. "Undead Samurai") are double-quoted so the engine's
-- whitespace tokenizer treats them as a single token. The new `_tokenize_payout`
-- helper consumes everything between matching double quotes as one token (quotes
-- are stripped); `_emit_payout_token` re-emits the quotes during choose-string
-- normalization so the canonical form round-trips. Single-word areas (Gnolls,
-- Forest, ...) can be left bare and are unaffected.
--
-- Note: this card is a bare `count area ...` payout rather than a `choose <...>`
-- since there is only one option (no OR alternative). The `case "count" / case "area"`
-- branch in `execute_special_payout` resolves it directly.
--
-- Engine prerequisite this card relies on (already in place): area validation and
-- counting derive from `self.monster_stack_areas` via `_active_areas()`, so any
-- expansion area in play this game (Gnolls, Undead Samurai, ...) participates.
--
-- Card text (icons): "1 magic per Undead Samurai monster you own."
USE vckonline;

UPDATE monsters
SET special_reward = 'count area "Undead Samurai" m 1'
WHERE name = 'Undead Samurai Lord';
