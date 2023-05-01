DELIMITER //

CREATE PROCEDURE select_base1_monsters()
BEGIN
SELECT * FROM monsters WHERE expansion = "base1";
END //

DELIMITER ;
