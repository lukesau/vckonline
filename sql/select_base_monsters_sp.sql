DELIMITER //

CREATE PROCEDURE select_base_monsters()
BEGIN
    SELECT * FROM monsters WHERE expansion IN ('base1', 'base2');
END //

DELIMITER ;
