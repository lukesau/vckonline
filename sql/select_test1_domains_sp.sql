DELIMITER //

-- Test 1 Domains: crystallized "first set" the engine was originally built around.
-- Hand-picked pool of exactly 15 base-set domains, shuffled into stack order.
-- Python still applies banned_cards.json on top, so any id banned there will
-- be dropped and the format will fail to render if the remaining count < 15.
CREATE PROCEDURE select_test1_domains()
BEGIN
    SELECT * FROM domains
    WHERE id_domains IN (1,2,3,4,5,6,7,8,93,94,95,96,97,98,99)
    ORDER BY RAND();
END //

DELIMITER ;
