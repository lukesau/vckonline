-- Create all stored procedures for VCK Online
-- Run this file as the vckonline user (or any user with CREATE ROUTINE privilege on vckonline database)
-- Usage: mysql -u vckonline -p vckonline < create_all_stored_procedures.sql
-- Or interactively: source create_all_stored_procedures.sql;

DELIMITER //

-- Drop existing procedures if they exist (to allow re-running this script)
DROP PROCEDURE IF EXISTS select_base1_citizens //
DROP PROCEDURE IF EXISTS select_base1_monsters //
DROP PROCEDURE IF EXISTS select_base1_domains //
DROP PROCEDURE IF EXISTS select_base_citizens //
DROP PROCEDURE IF EXISTS select_base_monsters //
DROP PROCEDURE IF EXISTS select_base_dukes //
DROP PROCEDURE IF EXISTS select_base2_citizens //
DROP PROCEDURE IF EXISTS select_base2_monsters //
DROP PROCEDURE IF EXISTS select_base2_domains //
DROP PROCEDURE IF EXISTS select_base_domains //
DROP PROCEDURE IF EXISTS select_random_domains //
DROP PROCEDURE IF EXISTS select_random_dukes //
DROP PROCEDURE IF EXISTS select_test1_domains //
DROP PROCEDURE IF EXISTS select_test2_domains //
DROP PROCEDURE IF EXISTS select_all_monsters //
DROP PROCEDURE IF EXISTS select_all_citizens //
DROP PROCEDURE IF EXISTS select_base_events //
DROP PROCEDURE IF EXISTS select_all_events //

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

-- Base Citizens
CREATE PROCEDURE select_base_citizens()
BEGIN
    SELECT * FROM citizens WHERE expansion IN ('base1', 'base2');
END //

-- Base Monsters
CREATE PROCEDURE select_base_monsters()
BEGIN
    SELECT * FROM monsters WHERE expansion IN ('base1', 'base2');
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
    SELECT * FROM monsters WHERE expansion IN ('base2', 'gnolls', 'undeadsamurai');
END //

-- Base Domains (shared by base1/base2)
CREATE PROCEDURE select_base_domains()
BEGIN
    SELECT * FROM domains WHERE expansion = 'base' ORDER BY RAND();
END //

-- Base Dukes
CREATE PROCEDURE select_base_dukes()
BEGIN
    SELECT * FROM dukes WHERE expansion = 'base' ORDER BY RAND();
END //

-- Random Domains (returns all rows; caller trims to what it needs after bans)
CREATE PROCEDURE select_random_domains()
BEGIN
    SELECT * FROM domains ORDER BY RAND();
END //

-- Random Dukes
CREATE PROCEDURE select_random_dukes()
BEGIN
    SELECT * FROM dukes ORDER BY RAND();
END //

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

-- All monsters across every expansion. The `random` preset's Python
-- post-filter (card_filters.keep_for_random) drops unimplemented or
-- imageless rows; the area-pick (5 of N) and stack assembly stay in
-- game_setup.py.
CREATE PROCEDURE select_all_monsters()
BEGIN
    SELECT * FROM monsters;
END //

-- All citizens across every expansion. The `random` preset's Python
-- post-filter drops unimplemented/imageless rows, then
-- _choose_one_citizen_per_roll picks one row per roll_match1.
CREATE PROCEDURE select_all_citizens()
BEGIN
    SELECT * FROM citizens;
END //

-- Base-set events. Used by `current` / `base` / `test1` / `test2`.
CREATE PROCEDURE select_base_events()
BEGIN
    SELECT * FROM events WHERE expansion = 'base' ORDER BY id_events;
END //

-- All events across every expansion. Used by the `random` preset.
-- Python post-filter drops unimplemented/imageless rows.
CREATE PROCEDURE select_all_events()
BEGIN
    SELECT * FROM events ORDER BY id_events;
END //

DELIMITER ;

-- Verify procedures were created
SHOW PROCEDURE STATUS WHERE Db = 'vckonline';

