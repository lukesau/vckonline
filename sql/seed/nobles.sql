TRUNCATE TABLE vckonline.nobles;
INSERT INTO vckonline.nobles (id_nobles,name,expansion,shadow_count,holy_count,soldier_count,worker_count,shadow_multiplier,holy_multiplier,soldier_multiplier,worker_multiplier,monster_multiplier,citizen_multiplier,domain_multiplier,boss_multiplier,minion_multiplier,beast_multiplier,titan_multiplier,goods_multiplier,has_special_duke_payout,special_duke_payout) VALUES
	 (1,'Augur Kawleen','base',1,0,0,0,2,0,0,0,0,0,0,0,0,0,0,0,0,NULL),
	 (2,'Beasthunter Benrick','base',1,0,0,0,0,0,0,0,0,0,0,0,0,3,0,0,0,NULL),
	 (3,'Doom Chun''nan','base',0,0,1,0,0,0,0,0,0,0,0,0,2,0,0,0,0,NULL),
	 (4,'Dray','base',1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,'wild_choose 2 1'),
	 (5,'Huntmaster Heller','base',0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,0,NULL),
	 (6,'Izmael the Provider','base',0,0,0,1,0,0,0,1,0,0,0,0,0,0,0,0,0,NULL),
	 (7,'J''ilko the Just','base',0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,NULL),
	 (8,'Julian the Honorable','base',0,0,0,1,0,0,0,0,0,0,2,0,0,0,0,0,0,NULL),
	 (9,'Kiko the Monster Slayer','base',0,1,0,0,0,0,0,0,0,0,0,5,0,0,0,0,0,NULL),
	 (10,'Mikal the Moneylender','base',0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,1,'floor_div gold 3 1');
INSERT INTO vckonline.nobles (id_nobles,name,expansion,shadow_count,holy_count,soldier_count,worker_count,shadow_multiplier,holy_multiplier,soldier_multiplier,worker_multiplier,monster_multiplier,citizen_multiplier,domain_multiplier,boss_multiplier,minion_multiplier,beast_multiplier,titan_multiplier,goods_multiplier,has_special_duke_payout,special_duke_payout) VALUES
	 (11,'Phanther','base',0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,1,'floor_div strength 3 1'),
	 (12,'Saint Rebeka of Rollingwood','base',0,1,0,0,0,2,0,0,0,0,0,0,0,0,0,0,0,NULL),
	 (13,'Sir Robert Clark III','base',1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,NULL),
	 (14,'Solan Karanga','base',0,0,1,0,0,0,1,0,0,0,0,0,0,0,0,0,0,NULL),
	 (15,'Sorceress Bouman','base',0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,'floor_div magic 3 1'),
	 (16,'Troll Hunter Grable','base',0,1,0,0,0,0,0,0,0,0,0,0,0,0,4,0,0,NULL);
