-- Fill in Gnoll Pack Lord's special reward as an OR choice between an area-scaling
-- resource gain and a center-stack citizen, using the existing `choose <A> <B>` grammar.
--
-- Grammar (already supported, no engine changes for this card):
--   choose <count area <area> <resource> <multiplier>> <citizens>
-- Same shape that the `_normalize_choose_command` docstring documents via the
-- "choose <count area Forest g 2> <citizens + v 1>" example.
--
-- One engine prerequisite for this card: `count area` previously hardcoded the area
-- set to Constants.areas (the 5 base areas), which would have rejected expansion
-- areas like "Gnolls". `owned_monster_attributes` and `_parse_choose_inner_option`
-- now derive the allowed area list from `self.monster_stack_areas` (the 5 areas
-- actually in play this game), falling back to Constants.areas for legacy state.
--
-- Card text (icons): "Gain 1 gold per Gnoll you own  OR  Gain a Citizen from the
-- center stacks." Picking the gnoll-scaling option awards
-- `owned_monster_attributes['Gnolls'] * 1` gold; picking the citizen option claims
-- one accessible center-stack citizen via the standard `<citizens>` filter.
USE vckonline;

UPDATE monsters
SET special_reward = 'choose <count area Gnolls g 1> <citizens>'
WHERE name = 'Gnoll Pack Lord';
