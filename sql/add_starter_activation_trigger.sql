-- Adds the `activation_trigger` column to the `starters` table and seeds Herald.
--
-- The column captures non-dice activation conditions that can't be expressed
-- via roll_match1/roll_match2. Recognized values:
--   ''                        -> use roll_match (default; existing rows unchanged)
--   'doubles'                 -> fires when both dice show the same face
--   'no_payout'               -> fires at end of harvest if the player gained
--                                nothing in g/s/m this harvest
--   'doubles_or_no_payout'    -> both of the above (Herald)
--
-- Roll match values stay readable as dice values; the engine treats triggered
-- starters as ignoring the roll_match columns entirely.

ALTER TABLE vckonline.starters
    ADD COLUMN activation_trigger VARCHAR(64)
        CHARACTER SET latin1 COLLATE latin1_swedish_ci
        NOT NULL DEFAULT ''
        AFTER special_payout_off_turn;

UPDATE vckonline.starters
   SET roll_match1 = -1,
       roll_match2 = -1,
       activation_trigger = 'doubles_or_no_payout'
 WHERE name = 'Herald';
