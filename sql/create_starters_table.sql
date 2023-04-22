CREATE TABLE vckonline.starters (
	idstarters int(11) auto_increment NOT NULL,
	name varchar(45) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL,
	roll_match1 int(11) NOT NULL,
	roll_match2 int(11) DEFAULT 0 NULL,
	gold_payout_on_turn int(11) DEFAULT 0 NOT NULL,
	gold_payout_off_turn int(11) DEFAULT 0 NOT NULL,
	strength_payout_on_turn int(11) DEFAULT 0 NOT NULL,
	strength_payout_off_turn int(11) DEFAULT 0 NOT NULL,
	magic_payout_on_turn int(11) DEFAULT 0 NOT NULL,
	magic_payout_off_turn int(11) DEFAULT 0 NOT NULL,
	has_special_payout_on_turn tinyint(4) DEFAULT 0 NOT NULL,
	has_special_payout_off_turn tinyint(4) DEFAULT 0 NOT NULL,
	special_payout_on_turn mediumtext CHARACTER SET latin1 COLLATE latin1_swedish_ci DEFAULT NULL NULL,
	special_payout_off_turn mediumtext CHARACTER SET latin1 COLLATE latin1_swedish_ci DEFAULT NULL NULL,
    PRIMARY KEY (idstarters)
)
ENGINE=InnoDB
DEFAULT CHARSET=latin1
COLLATE=latin1_swedish_ci;
