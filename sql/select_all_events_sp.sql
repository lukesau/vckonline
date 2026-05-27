DELIMITER //

-- All events across every expansion. The `random` preset's Python
-- post-filter (card_filters.keep_for_random) drops unimplemented or
-- imageless rows; the n-out-of-pool sample stays in game_setup.py.
CREATE PROCEDURE select_all_events()
BEGIN
    SELECT * FROM events ORDER BY id_events;
END //

DELIMITER ;
