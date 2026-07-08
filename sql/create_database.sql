-- Create the vckonline database and application user.
-- Run as a MariaDB admin, e.g.: mysql -u root -p < sql/create_database.sql

CREATE DATABASE IF NOT EXISTS vckonline
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_uca1400_ai_ci;

CREATE USER IF NOT EXISTS 'vckonline'@'localhost' IDENTIFIED BY 'vckonline';

GRANT ALL PRIVILEGES ON vckonline.* TO 'vckonline'@'localhost';

FLUSH PRIVILEGES;
