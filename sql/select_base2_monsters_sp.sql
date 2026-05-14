DELIMITER //

CREATE PROCEDURE select_base2_monsters()
BEGIN
    SELECT * FROM monsters WHERE expansion IN ('base2', 'gnolls', 'undeadsamurai');
END //

DELIMITER ;
