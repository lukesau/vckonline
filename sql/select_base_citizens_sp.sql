DELIMITER //

CREATE PROCEDURE select_base_citizens()
BEGIN
    SELECT * FROM citizens WHERE expansion IN ('base1', 'base2');
END //

DELIMITER ;
