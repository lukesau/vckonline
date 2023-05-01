DELIMITER //

CREATE PROCEDURE select_base2_citizens()
BEGIN
SELECT * FROM citizens WHERE expansion = "base2"
UNION
SELECT * FROM citizens WHERE expansion = "base1" AND name IN ('Peasant', 'Knight');
END //

DELIMITER ;
