CREATE TABLE IF NOT EXISTS vckonline.agents (
	id_agents int(11) auto_increment NOT NULL,
	name varchar(45) NOT NULL,
	activation_effect longtext DEFAULT NULL,
	activation_effect_text mediumtext NOT NULL DEFAULT '',
	PRIMARY KEY (id_agents)
)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_uca1400_ai_ci;
