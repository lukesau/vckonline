DELIMITER //

CREATE PROCEDURE select_base_domains()
BEGIN
    SELECT * FROM domains WHERE expansion = 'base' ORDER BY RAND();
END //

DELIMITER ;
