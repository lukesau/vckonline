CREATE TABLE vckonline.nobles (
	id_nobles int(11) auto_increment NOT NULL,
	name varchar(45) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL,
	expansion varchar(45) CHARACTER SET latin1 COLLATE latin1_swedish_ci DEFAULT 'base' NOT NULL,
	-- role icons (counted toward tableau/duke icon sums, same as citizens)
	shadow_count int(11) DEFAULT 0 NOT NULL,
	holy_count int(11) DEFAULT 0 NOT NULL,
	soldier_count int(11) DEFAULT 0 NOT NULL,
	worker_count int(11) DEFAULT 0 NOT NULL,
	-- end-game VP multipliers (applied during duke scoring, same pattern as dukes table)
	shadow_multiplier int(11) DEFAULT 0 NOT NULL,
	holy_multiplier int(11) DEFAULT 0 NOT NULL,
	soldier_multiplier int(11) DEFAULT 0 NOT NULL,
	worker_multiplier int(11) DEFAULT 0 NOT NULL,
	monster_multiplier int(11) DEFAULT 0 NOT NULL,
	citizen_multiplier int(11) DEFAULT 0 NOT NULL,
	domain_multiplier int(11) DEFAULT 0 NOT NULL,
	boss_multiplier int(11) DEFAULT 0 NOT NULL,
	minion_multiplier int(11) DEFAULT 0 NOT NULL,
	beast_multiplier int(11) DEFAULT 0 NOT NULL,
	titan_multiplier int(11) DEFAULT 0 NOT NULL,
	goods_multiplier int(11) DEFAULT 0 NOT NULL,
	-- for payouts that require division or user interaction (e.g. 1 VP per 3 gold, 1 VP per 2 wild)
	has_special_duke_payout tinyint(4) DEFAULT 0 NOT NULL,
	special_duke_payout mediumtext CHARACTER SET latin1 COLLATE latin1_swedish_ci DEFAULT NULL NULL,
	PRIMARY KEY (id_nobles)
)
ENGINE=InnoDB
DEFAULT CHARSET=latin1
COLLATE=latin1_swedish_ci;
