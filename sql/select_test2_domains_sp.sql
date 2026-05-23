DELIMITER //

-- Test 2 Domains: 15 random domains drawn from id_domains 9..24.
-- Python applies banned_cards.json on top, so unfinished/banned ids in this
-- range will be dropped. If that leaves fewer than 15 the preset will fail
-- to render; either unban the relevant ids or widen this pool.
CREATE PROCEDURE select_test2_domains()
BEGIN
    SELECT * FROM domains
    WHERE id_domains BETWEEN 9 AND 24
    ORDER BY RAND()
    LIMIT 15;
END //

DELIMITER ;
