DELIMITER //

CREATE PROCEDURE select_base1_citizens()
BEGIN
SELECT * FROM citizens WHERE expansion = "base1";
END //

DELIMITER ;
