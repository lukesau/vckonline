DELIMITER //

-- Base-set events. Used by the `current` / `base` / `test1` / `test2`
-- presets — anything that wants the original 5-event Exhausted pool.
-- `random` uses `select_all_events` instead.
CREATE PROCEDURE select_base_events()
BEGIN
    SELECT * FROM events WHERE expansion = 'base' ORDER BY id_events;
END //

DELIMITER ;
