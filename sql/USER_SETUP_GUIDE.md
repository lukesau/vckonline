# MariaDB User Setup Guide for VCK Online

Run these commands interactively in MariaDB as root to investigate and fix the user setup.

## Investigation Commands

### 1. Check if the database exists
```sql
SHOW DATABASES LIKE 'vckonline';
```

### 2. Check if the user exists and from which hosts
```sql
SELECT User, Host FROM mysql.user WHERE User = 'vckonline';
```

### 3. Check current privileges (if user exists)
```sql
SHOW GRANTS FOR 'vckonline'@'localhost';
SHOW GRANTS FOR 'vckonline'@'127.0.0.1';
SHOW GRANTS FOR 'vckonline'@'%';
```

### 4. Check if database has data (if database exists)
```sql
USE vckonline;
SHOW TABLES;
```

### 5. Verify data exists in key tables
```sql
SELECT COUNT(*) AS citizens_count FROM citizens;
SELECT COUNT(*) AS monsters_count FROM monsters;
SELECT COUNT(*) AS domains_count FROM domains;
SELECT COUNT(*) AS dukes_count FROM dukes;
SELECT COUNT(*) AS starters_count FROM starters;
```

## Fix Commands

### Scenario A: User doesn't exist - Create new user

```sql
-- Create user for localhost connections
CREATE USER 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';

-- Create user for 127.0.0.1 connections (SSH tunnel)
CREATE USER 'vckonline'@'127.0.0.1' IDENTIFIED BY 'vckonline';

-- Create user for remote connections (optional, for direct connections)
CREATE USER 'vckonline'@'%' IDENTIFIED BY 'vckonline';

-- Grant privileges
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'127.0.0.1';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'%';

-- Apply changes
FLUSH PRIVILEGES;
```

### Scenario B: User exists but password is wrong - Reset password

```sql
-- Reset password for existing user
ALTER USER 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';
ALTER USER 'vckonline'@'127.0.0.1' IDENTIFIED BY 'vckonline';
ALTER USER 'vckonline'@'%' IDENTIFIED BY 'vckonline';

-- Ensure privileges are granted
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'127.0.0.1';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'%';

-- Apply changes
FLUSH PRIVILEGES;
```

### Scenario C: User exists but lacks privileges - Grant privileges

```sql
-- Grant privileges
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'127.0.0.1';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'%';

-- Apply changes
FLUSH PRIVILEGES;
```

## Verification

After running the fix commands, verify the setup:

```sql
-- Check user exists
SELECT User, Host FROM mysql.user WHERE User = 'vckonline';

-- Check privileges
SHOW GRANTS FOR 'vckonline'@'localhost';
SHOW GRANTS FOR 'vckonline'@'127.0.0.1';

-- Test connection (from another terminal, not in MariaDB)
-- mysql -u vckonline -p vckonline
-- Password: vckonline
```

## Quick Fix (All-in-One)

If you're confident the database exists with data, run this complete setup:

```sql
-- Create users if they don't exist (will error if they do, that's OK)
CREATE USER IF NOT EXISTS 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';
CREATE USER IF NOT EXISTS 'vckonline'@'127.0.0.1' IDENTIFIED BY 'vckonline';
CREATE USER IF NOT EXISTS 'vckonline'@'%' IDENTIFIED BY 'vckonline';

-- Grant privileges (safe to run even if already granted)
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'127.0.0.1';
GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'%';

-- Apply changes
FLUSH PRIVILEGES;

-- Verify
SHOW GRANTS FOR 'vckonline'@'localhost';
```

