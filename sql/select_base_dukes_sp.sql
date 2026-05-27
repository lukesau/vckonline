DELIMITER //

CREATE PROCEDURE select_base_dukes()
BEGIN
    SELECT * FROM dukes WHERE expansion = 'base' ORDER BY RAND();
END //

DELIMITER ;
