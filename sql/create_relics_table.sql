CREATE TABLE IF NOT EXISTS vckonline.relics (
	id_relics int(11) auto_increment NOT NULL,
	name varchar(45) NOT NULL,
	passive_effect longtext DEFAULT NULL,
	passive_effect_text mediumtext NOT NULL DEFAULT '',
	consumes_action tinyint(1) NOT NULL DEFAULT 0,
	PRIMARY KEY (id_relics)
)
ENGINE=InnoDB
DEFAULT CHARSET=utf8mb4
COLLATE=utf8mb4_uca1400_ai_ci;
