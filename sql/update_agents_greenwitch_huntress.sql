-- Agents 7 (Green Witch) and 8 (Huntress): take a random Monster from another
-- player's tableau; that player gains 1 VP. Both route through the `take_owned`
-- "take" operator so Castle of the Seven Suns (`immunity.take`) blocks them.
--
-- The only difference is the destination of the taken Monster:
--   Green Witch -> to=stack  (returned to its board stack)
--   Huntress    -> to=self   (joins the engaging player's tableau)
UPDATE vckonline.agents
SET activation_effect = 'take_owned monster random to=stack victim_vp=1'
WHERE name = 'Green Witch';

UPDATE vckonline.agents
SET activation_effect = 'take_owned monster random to=self victim_vp=1'
WHERE name = 'Huntress';
