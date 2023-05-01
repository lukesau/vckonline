DELIMITER //

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

DELIMITER ;
