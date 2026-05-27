DELIMITER //

-- All citizens across every expansion. The `random` preset's Python
-- post-filter drops unimplemented/imageless rows, then
-- _choose_one_citizen_per_roll picks one row per roll_match1.
CREATE PROCEDURE select_all_citizens()
BEGIN
    SELECT * FROM citizens;
END //

DELIMITER ;
