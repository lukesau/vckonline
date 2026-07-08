-- MySQL dump 10.13  Distrib 9.6.0, for macos26.2 (arm64)
--
-- Host: 127.0.0.1    Database: vckonline
-- ------------------------------------------------------
-- Server version	5.5.5-10.11.14-MariaDB-0ubuntu0.24.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `citizens`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `citizens` (
  `id_citizens` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `gold_cost` int(11) NOT NULL,
  `roll_match1` int(11) NOT NULL,
  `roll_match2` int(11) DEFAULT 0,
  `shadow_count` int(11) NOT NULL DEFAULT 0,
  `holy_count` int(11) NOT NULL DEFAULT 0,
  `soldier_count` int(11) NOT NULL DEFAULT 0,
  `worker_count` int(11) NOT NULL DEFAULT 0,
  `gold_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `gold_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `strength_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `strength_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `magic_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `magic_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `vp_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `vp_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `has_special_payout_on_turn` tinyint(4) NOT NULL DEFAULT 0,
  `has_special_payout_off_turn` tinyint(4) NOT NULL DEFAULT 0,
  `special_payout_on_turn` mediumtext DEFAULT NULL,
  `special_payout_off_turn` mediumtext DEFAULT NULL,
  `special_payout_on_turn_text` mediumtext DEFAULT NULL,
  `special_payout_off_turn_text` mediumtext DEFAULT NULL,
  `special_citizen` tinyint(4) NOT NULL DEFAULT 0,
  `expansion` varchar(45) DEFAULT NULL,
  `special_payout_text` mediumtext NOT NULL DEFAULT '',
  PRIMARY KEY (`id_citizens`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `monsters`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `monsters` (
  `id_monsters` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `area` varchar(45) NOT NULL,
  `monster_type` varchar(45) NOT NULL,
  `monster_order` int(11) NOT NULL,
  `strength_cost` int(11) NOT NULL,
  `magic_cost` int(11) DEFAULT 0,
  `vp_reward` int(11) NOT NULL,
  `gold_reward` int(11) DEFAULT 0,
  `strength_reward` int(11) DEFAULT 0,
  `magic_reward` int(11) DEFAULT 0,
  `has_special_reward` tinyint(4) DEFAULT 0,
  `special_reward` longtext DEFAULT NULL,
  `has_special_cost` tinyint(4) DEFAULT NULL,
  `special_cost` longtext DEFAULT NULL,
  `is_extra` tinyint(4) DEFAULT 0,
  `expansion` varchar(45) DEFAULT NULL,
  `special_reward_text` mediumtext NOT NULL DEFAULT '',
  PRIMARY KEY (`id_monsters`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `domains`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `domains` (
  `id_domains` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `gold_cost` int(11) NOT NULL,
  `shadow_count` int(11) NOT NULL DEFAULT 0,
  `holy_count` int(11) NOT NULL DEFAULT 0,
  `soldier_count` int(11) NOT NULL DEFAULT 0,
  `worker_count` int(11) NOT NULL DEFAULT 0,
  `vp_reward` int(11) NOT NULL,
  `has_activation_effect` tinyint(4) NOT NULL DEFAULT 0,
  `has_passive_effect` tinyint(4) NOT NULL DEFAULT 0,
  `passive_effect` longtext DEFAULT NULL,
  `activation_effect` longtext DEFAULT NULL,
  `effect_text` mediumtext NOT NULL,
  `expansion` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id_domains`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dukes`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dukes` (
  `id_dukes` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `gold_mult` int(11) NOT NULL DEFAULT 0,
  `strength_mult` int(11) NOT NULL DEFAULT 0,
  `magic_mult` int(11) NOT NULL DEFAULT 0,
  `shadow_mult` int(11) NOT NULL DEFAULT 0,
  `holy_mult` int(11) NOT NULL DEFAULT 0,
  `soldier_mult` int(11) NOT NULL DEFAULT 0,
  `worker_mult` int(11) NOT NULL DEFAULT 0,
  `monster_mult` int(11) NOT NULL DEFAULT 0,
  `citizen_mult` int(11) NOT NULL DEFAULT 0,
  `domain_mult` int(11) NOT NULL DEFAULT 0,
  `boss_mult` int(11) NOT NULL DEFAULT 0,
  `minion_mult` int(11) NOT NULL DEFAULT 0,
  `beast_mult` int(11) NOT NULL DEFAULT 0,
  `titan_mult` int(11) NOT NULL DEFAULT 0,
  `expansion` varchar(45) DEFAULT NULL,
  `card_text` mediumtext NOT NULL DEFAULT '',
  PRIMARY KEY (`id_dukes`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `starters`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `starters` (
  `id_starters` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `roll_match1` int(11) NOT NULL,
  `roll_match2` int(11) DEFAULT 0,
  `gold_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `gold_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `strength_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `strength_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `magic_payout_on_turn` int(11) NOT NULL DEFAULT 0,
  `magic_payout_off_turn` int(11) NOT NULL DEFAULT 0,
  `has_special_payout_on_turn` tinyint(4) NOT NULL DEFAULT 0,
  `has_special_payout_off_turn` tinyint(4) NOT NULL DEFAULT 0,
  `special_payout_on_turn` mediumtext DEFAULT NULL,
  `special_payout_off_turn` mediumtext DEFAULT NULL,
  `special_payout_on_turn_text` mediumtext DEFAULT NULL,
  `special_payout_off_turn_text` mediumtext DEFAULT NULL,
  `activation_trigger` varchar(64) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL DEFAULT '',
  `expansion` varchar(45) DEFAULT NULL,
  `card_text` mediumtext NOT NULL DEFAULT '',
  PRIMARY KEY (`id_starters`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `events`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `events` (
  `id_events` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `roll_match1` int(11) NOT NULL,
  `roll_effect` longtext DEFAULT NULL,
  `has_roll_effect` tinyint(4) NOT NULL DEFAULT 0,
  `is_monster` tinyint(4) NOT NULL DEFAULT 0,
  `has_activation_effect` tinyint(4) NOT NULL DEFAULT 0,
  `has_passive_effect` tinyint(4) NOT NULL DEFAULT 0,
  `strength_cost` int(11) NOT NULL DEFAULT 0,
  `magic_cost` int(11) NOT NULL DEFAULT 0,
  `monster_type` varchar(45) DEFAULT NULL,
  `vp_reward` int(11) NOT NULL DEFAULT 0,
  `gold_reward` int(11) NOT NULL DEFAULT 0,
  `strength_reward` int(11) NOT NULL DEFAULT 0,
  `magic_reward` int(11) NOT NULL DEFAULT 0,
  `has_special_reward` tinyint(4) NOT NULL DEFAULT 0,
  `special_reward` longtext DEFAULT NULL,
  `roll_effect_text` mediumtext NOT NULL DEFAULT '',
  `special_reward_text` mediumtext NOT NULL DEFAULT '',
  `activation_effect_text` mediumtext NOT NULL DEFAULT '',
  `passive_effect_text` mediumtext NOT NULL DEFAULT '',
  `activation_effect` longtext DEFAULT NULL,
  `passive_effect` longtext DEFAULT NULL,
  `expansion` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id_events`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `nobles`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `nobles` (
  `id_nobles` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `expansion` varchar(45) NOT NULL DEFAULT 'base',
  `shadow_count` int(11) NOT NULL DEFAULT 0,
  `holy_count` int(11) NOT NULL DEFAULT 0,
  `soldier_count` int(11) NOT NULL DEFAULT 0,
  `worker_count` int(11) NOT NULL DEFAULT 0,
  `shadow_multiplier` int(11) NOT NULL DEFAULT 0,
  `holy_multiplier` int(11) NOT NULL DEFAULT 0,
  `soldier_multiplier` int(11) NOT NULL DEFAULT 0,
  `worker_multiplier` int(11) NOT NULL DEFAULT 0,
  `monster_multiplier` int(11) NOT NULL DEFAULT 0,
  `citizen_multiplier` int(11) NOT NULL DEFAULT 0,
  `domain_multiplier` int(11) NOT NULL DEFAULT 0,
  `boss_multiplier` int(11) NOT NULL DEFAULT 0,
  `minion_multiplier` int(11) NOT NULL DEFAULT 0,
  `beast_multiplier` int(11) NOT NULL DEFAULT 0,
  `titan_multiplier` int(11) NOT NULL DEFAULT 0,
  `goods_multiplier` int(11) NOT NULL DEFAULT 0,
  `has_special_duke_payout` tinyint(4) NOT NULL DEFAULT 0,
  `special_duke_payout` mediumtext DEFAULT NULL,
  PRIMARY KEY (`id_nobles`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_swedish_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `agents`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agents` (
  `id_agents` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `activation_effect` longtext DEFAULT NULL,
  `activation_effect_text` mediumtext NOT NULL DEFAULT '',
  PRIMARY KEY (`id_agents`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `relics`
--

/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `relics` (
  `id_relics` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(45) NOT NULL,
  `passive_effect` longtext DEFAULT NULL,
  `passive_effect_text` mediumtext NOT NULL DEFAULT '',
  `consumes_action` tinyint(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id_relics`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_uca1400_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-08 11:29:16
