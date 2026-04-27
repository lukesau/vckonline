-- Create all stored procedures for VCK Online
-- Run this file as the vckonline user (or any user with CREATE ROUTINE privilege on vckonline database)
-- Usage: mysql -u vckonline -p vckonline < create_all_stored_procedures.sql
-- Or interactively: source create_all_stored_procedures.sql;

DELIMITER //

-- Drop existing procedures if they exist (to allow re-running this script)
DROP PROCEDURE IF EXISTS select_base1_citizens //
DROP PROCEDURE IF EXISTS select_base1_monsters //
DROP PROCEDURE IF EXISTS select_base2_citizens //
DROP PROCEDURE IF EXISTS select_base2_monsters //
DROP PROCEDURE IF EXISTS select_random_domains //
DROP PROCEDURE IF EXISTS select_random_dukes //

-- Base 1 Citizens
CREATE PROCEDURE select_base1_citizens()
BEGIN
    SELECT * FROM citizens WHERE expansion = "base1";
END //

-- Base 1 Monsters
CREATE PROCEDURE select_base1_monsters()
BEGIN
    SELECT * FROM monsters WHERE expansion = "base1";
END //

-- Base 2 Citizens
CREATE PROCEDURE select_base2_citizens()
BEGIN
    SELECT * FROM citizens WHERE expansion = "base2"
    UNION
    SELECT * FROM citizens WHERE expansion = "base1" AND name IN ('Peasant', 'Knight');
END //

-- Base 2 Monsters
CREATE PROCEDURE select_base2_monsters()
BEGIN
    DECLARE chosen_area1 VARCHAR(255);
    DECLARE chosen_area2 VARCHAR(255);
    SET chosen_area1 = (
        SELECT area FROM monsters WHERE expansion = 'base1' GROUP BY area ORDER BY RAND() LIMIT 1
    );
    SET chosen_area2 = (
        SELECT area FROM monsters WHERE expansion = 'base1' AND area <> chosen_area1 ORDER BY RAND() LIMIT 1
    );
    SELECT id_monsters, name, area, monster_type, monster_order, 
           strength_cost, magic_cost, vp_reward, gold_reward, strength_reward, magic_reward,
           has_special_reward, special_reward, has_special_cost, special_cost, is_extra, expansion
    FROM monsters
    WHERE expansion = 'base2'
    UNION
    SELECT id_monsters, name, area, monster_type, monster_order, 
           strength_cost, magic_cost, vp_reward, gold_reward, strength_reward, magic_reward,
           has_special_reward, special_reward, has_special_cost, special_cost, is_extra, expansion
    FROM monsters
    WHERE expansion = 'base1' AND area IN (chosen_area1, chosen_area2);
END //

-- Random Domains
CREATE PROCEDURE select_random_domains()
BEGIN
    SELECT * FROM domains ORDER BY RAND() LIMIT 15;
END //

-- Random Dukes
CREATE PROCEDURE select_random_dukes()
BEGIN
    SELECT * FROM dukes ORDER BY RAND();
END //

DELIMITER ;

-- Verify procedures were created
SHOW PROCEDURE STATUS WHERE Db = 'vckonline';

