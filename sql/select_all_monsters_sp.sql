DELIMITER //

-- All monsters across every expansion. The `random` preset's Python
-- post-filter (card_filters.keep_for_random) drops unimplemented or
-- imageless rows; the area-pick (5 of N) and stack assembly stay in
-- game_setup.py.
CREATE PROCEDURE select_all_monsters()
BEGIN
    SELECT * FROM monsters;
END //

DELIMITER ;
