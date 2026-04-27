-- ============================================
-- VCK Online Database User Setup Commands
-- Run these interactively in MariaDB as root
-- ============================================

-- Step 1: Check if the database exists
SHOW DATABASES LIKE 'vckonline';

-- Step 2: Check if the user exists
SELECT User, Host FROM mysql.user WHERE User = 'vckonline';

-- Step 3: Check current user privileges (if user exists)
SHOW GRANTS FOR 'vckonline'@'localhost';
SHOW GRANTS FOR 'vckonline'@'%';

-- Step 4: Check what tables exist in the database (if it exists)
USE vckonline;
SHOW TABLES;

-- Step 5: Check table row counts to verify data exists
SELECT 
    'citizens' AS table_name, COUNT(*) AS row_count FROM citizens
UNION ALL
SELECT 'monsters', COUNT(*) FROM monsters
UNION ALL
SELECT 'domains', COUNT(*) FROM domains
UNION ALL
SELECT 'dukes', COUNT(*) FROM dukes
UNION ALL
SELECT 'starters', COUNT(*) FROM starters;

-- ============================================
-- FIX COMMANDS (run only if needed)
-- ============================================

-- Option A: If user doesn't exist, create it
-- CREATE USER 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';
-- CREATE USER 'vckonline'@'127.0.0.1' IDENTIFIED BY 'vckonline';
-- CREATE USER 'vckonline'@'%' IDENTIFIED BY 'vckonline';

-- Option B: If user exists but password is wrong, reset it
-- ALTER USER 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';
-- ALTER USER 'vckonline'@'127.0.0.1' IDENTIFIED BY 'vckonline';
-- ALTER USER 'vckonline'@'%' IDENTIFIED BY 'vckonline';

-- Grant all privileges on vckonline database
-- GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';
-- GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'127.0.0.1';
-- GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'%';

-- Flush privileges to apply changes
-- FLUSH PRIVILEGES;

-- Verify the grants after creating/fixing
-- SHOW GRANTS FOR 'vckonline'@'localhost';

