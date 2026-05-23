DELIMITER //

CREATE PROCEDURE select_random_domains()
BEGIN
    SELECT * FROM domains ORDER BY RAND();
END //

DELIMITER ;
