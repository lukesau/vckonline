TRUNCATE TABLE vckonline.citizens;
INSERT INTO vckonline.citizens (id_citizens,name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,vp_payout_on_turn,vp_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,special_citizen,expansion,special_payout_text) VALUES
	 (1,'Cleric',3,1,-1,0,1,0,0,0,0,0,0,3,1,0,0,0,0,NULL,NULL,NULL,NULL,0,'base1',''),
	 (2,'Merchant',2,2,-1,0,0,0,1,0,1,0,0,0,0,0,0,1,0,'choose g 2 m 2',NULL,'Choose between 2 Gold and 2 Magic.',NULL,0,'base1',''),
	 (3,'Mercenary',3,3,-1,1,0,0,0,1,0,1,0,0,0,0,0,0,1,NULL,'exchange s 1 g 2',NULL,'Exchange 1 Strength for 2 Gold.',0,'base1',''),
	 (4,'Archer',4,4,-1,0,0,1,0,0,0,2,1,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'base1',''),
	 (5,'Peasant',2,5,-1,0,0,0,1,1,1,0,0,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'base1',''),
	 (6,'Knight',2,6,-1,0,0,1,0,0,0,1,1,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'base1',''),
	 (7,'Rogue',2,7,-1,1,0,0,0,2,1,2,1,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'base1',''),
	 (8,'Champion',2,8,-1,0,0,1,0,0,0,4,0,0,0,0,0,0,1,NULL,'exchange g 1 s 4',NULL,'Exchange 1 Gold for 4 Strength.',0,'base1',''),
	 (9,'Paladin',2,9,10,0,1,0,0,0,0,1,0,2,0,0,0,0,1,NULL,'exchange s 1 m 3',NULL,'Exchange 1 Strength for 3 Magic.',0,'base1',''),
	 (10,'Butcher',1,11,12,0,0,0,1,0,4,0,0,0,0,0,0,1,0,'count owned_worker g 2',NULL,'Gain 2 Gold for each Worker Citizen you own.',NULL,0,'base1','');
INSERT INTO vckonline.citizens (id_citizens,name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,vp_payout_on_turn,vp_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,special_citizen,expansion,special_payout_text) VALUES
	 (11,'Monk',3,1,-1,0,1,0,0,1,0,0,0,2,0,0,0,0,1,NULL,'exchange g 1 m 2',NULL,'Exchange 1 Gold for 2 Magic.',0,'base2',''),
	 (12,'Blacksmith',3,2,-1,0,0,0,1,0,1,0,0,0,0,0,0,1,0,'count owned_soldier g 1',NULL,'Gain 1 Gold for each Soldier Citizen you own.',NULL,0,'base2',''),
	 (13,'Alchemist',3,3,-1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,'exchange g 1 m 3','exchange m 1 g 2','Exchange 1 Gold for 3 Magic.','Exchange 1 Magic for 2 Gold.',0,'base2',''),
	 (14,'Wizard',4,4,-1,0,0,1,0,0,0,1,0,1,1,0,0,0,0,NULL,NULL,NULL,NULL,0,'base2',''),
	 (15,'Thief',2,7,-1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,'steal g 3 m 3','choose g 2 m 2','Steal 3 Gold or 3 Magic from an opponent.','Choose between 2 Gold and 2 Magic.',0,'base2',''),
	 (16,'Warlord',2,8,-1,0,0,1,0,0,0,0,0,0,0,0,0,1,1,'count owned_soldier s 1','count owned_citizen_name Knight s 1 + count owned_starter_name Knight s 1','Gain 1 Strength for each Soldier you own.','Gain 1 Strength for each Knight you own.',0,'base2',''),
	 (17,'Priestess',2,9,10,0,1,0,0,0,0,2,0,1,0,0,0,0,1,NULL,'exchange m 1 s 3',NULL,'Exchange 1 Magic for 3 Strength.',0,'base2',''),
	 (18,'Miner',1,11,12,0,0,0,1,0,4,0,0,0,0,0,0,1,0,'g 1 + count owned_domains g 1',NULL,'Gain 1 Gold, plus 1 Gold for each Domain you own.',NULL,0,'base2',''),
	 (19,'Summoner',1,1,-1,0,1,0,0,0,0,0,0,0,0,0,0,1,1,'exchange m 1 s 3','exchange s 1 m 2','Exchange 1 Magic for 3 Strength.','Exchange 1 Strength for 2 Magic.',0,'flamesandfrost',''),
	 (20,'Bard',2,2,-1,0,0,0,1,0,1,0,0,0,0,0,0,1,0,'choose g 2 v 1',NULL,'Choose between 2 Gold and 1 Victory Point.',NULL,0,'flamesandfrost','');
INSERT INTO vckonline.citizens (id_citizens,name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,vp_payout_on_turn,vp_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,special_citizen,expansion,special_payout_text) VALUES
	 (21,'Sorceress',3,3,-1,1,0,0,0,0,0,0,0,1,0,0,0,1,1,'choose g 1 s 1 m 1','exchange m 1 wild 2','Choose between 1 Gold, 1 Strength, and 1 Magic.','Exchange 1 Magic for 2 of any one resource.',0,'flamesandfrost',''),
	 (22,'Barbarian',4,4,-1,0,0,1,0,0,0,2,0,0,0,0,0,0,1,NULL,'exchange g 1 s 2',NULL,'Exchange 1 Gold for 2 Strength.',0,'flamesandfrost',''),
	 (23,'Peasant',3,5,-1,1,0,0,1,0,1,0,0,0,0,0,0,1,0,'choose g 1 s 1',NULL,'Choose between 1 Gold and 1 Strength.',NULL,0,'flamesandfrost',''),
	 (24,'Knight',3,6,-1,0,1,1,0,0,0,0,1,0,0,0,0,1,0,'choose s 1 m 1',NULL,'Choose between 1 Strength and 1 Magic.',NULL,0,'flamesandfrost',''),
	 (25,'Condottiere',2,7,-1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,'choose g 4 s 4','choose g 2 s 2','Choose between 4 Gold and 4 Strength.','Choose between 2 Gold and 2 Strength.',0,'flamesandfrost',''),
	 (26,'Bogatyr',1,8,-1,0,0,1,0,0,0,3,0,0,0,0,0,0,1,NULL,'exchange wild 1 s 4',NULL,'Exchange 1 of any one resource for 4 Strength.',0,'flamesandfrost',''),
	 (27,'Templar',3,9,10,0,1,0,0,0,0,2,1,2,1,0,0,0,0,NULL,NULL,NULL,NULL,0,'flamesandfrost',''),
	 (28,'Baker',1,11,12,0,0,0,1,0,2,0,0,0,0,0,1,1,0,'count owned_soldier g 2',NULL,'Gain 2 Gold for each Soldier Citizen you own.',NULL,0,'flamesandfrost',''),
	 (29,'Exorcist',1,1,-1,0,1,0,0,0,0,0,0,2,1,0,0,0,0,NULL,NULL,NULL,NULL,0,'shadowvale',''),
	 (30,'Lumberjack',2,2,-1,0,0,0,1,1,0,1,0,0,0,0,0,0,1,NULL,'choose s 1 g 1',NULL,'Choose between 1 Strength and 1 Gold.',0,'shadowvale','');
INSERT INTO vckonline.citizens (id_citizens,name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,vp_payout_on_turn,vp_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,special_citizen,expansion,special_payout_text) VALUES
	 (31,'Bandit',3,3,-1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,'steal g 1','exchange s 1 g 2','Steal 1 Gold from an opponent.','Exchange 1 Strength for 2 Gold.',0,'shadowvale',''),
	 (32,'Hunter',4,4,-1,0,0,1,0,0,0,2,0,0,0,0,0,0,1,NULL,'exchange m 1 s 2',NULL,'Exchange 1 Magic for 2 Strength.',0,'shadowvale',''),
	 (33,'Peasant',3,5,-1,0,1,0,1,0,1,0,0,0,0,0,0,1,0,'choose g 1 m 1',NULL,'Choose between 1 Gold and 1 Magic.',NULL,0,'shadowvale',''),
	 (34,'Knight',3,6,-1,1,0,1,0,0,0,0,1,0,0,0,0,1,0,'choose s 1 g 1',NULL,'Choose between 1 Strength and 1 Gold.',NULL,0,'shadowvale',''),
	 (35,'Necromancer',4,7,-1,1,0,0,0,0,0,0,0,3,0,0,0,0,1,NULL,'exchange s 1 m 4',NULL,'Exchange 1 Strength for 4 Magic.',0,'shadowvale',''),
	 (36,'Guardian',1,8,-1,0,0,1,0,0,0,3,3,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'shadowvale',''),
	 (37,'Dragoon',3,9,10,0,1,0,0,0,0,0,1,2,1,0,0,1,0,'slay',NULL,'You may immediately slay an accessible Monster, paying its normal cost.',NULL,0,'shadowvale',''),
	 (38,'Inventor',1,11,12,0,0,0,1,5,5,0,0,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'shadowvale',''),
	 (39,'Hydromancer',1,1,-1,0,1,0,0,0,0,0,0,0,0,0,0,1,1,'choose m 2 p 1','exchange m 1 s 2','Choose between 2 Magic and 1 Map.','Exchange 1 Magic for 2 Strength.',0,'crimsonseas','On-turn, choose between 2 Magic and 1 Map. Off-turn, exchange 1 Magic for 2 Strength.'),
	 (40,'Engineer',2,2,-1,0,0,0,1,0,0,0,0,0,0,0,0,1,1,'choose g 2 s 2 p 1','choose g 1 s 1','Choose between 2 Gold, 2 Strength, and 1 Map.','Choose between 1 Gold and 1 Strength.',0,'crimsonseas','On-turn, choose between 2 Gold, 2 Strength, and 1 Map. Off-turn, choose between 1 Gold and 1 Strength. ');
INSERT INTO vckonline.citizens (id_citizens,name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,vp_payout_on_turn,vp_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,special_citizen,expansion,special_payout_text) VALUES
	 (41,'Vitki',3,3,-1,1,0,0,0,0,0,0,0,0,0,0,0,1,1,'steal m 1','choose g 1 s 1 m 1','Steal 1 Magic from an opponent.','Choose between 1 Gold, 1 Strength, and 1 Magic.',0,'crimsonseas',''),
	 (42,'Marauder',1,4,-1,0,0,1,0,0,0,0,0,0,0,0,0,1,1,'choose g 1 s 1','choose g 1 s 1','Choose between 1 Gold and 1 Strength.','Choose between 1 Gold and 1 Strength.',0,'crimsonseas',''),
	 (43,'Peasant',2,5,-1,0,0,0,1,0,1,0,0,0,0,0,0,1,0,'exchange s 1 g 2',NULL,'Exchange 1 Strength for 2 Gold.',NULL,0,'crimsonseas',''),
	 (44,'Knight',2,6,-1,0,0,1,0,0,0,0,1,0,0,0,0,1,0,'exchange g 1 s 2',NULL,'Exchange 1 Gold for 2 Strength.',NULL,0,'crimsonseas',''),
	 (45,'Smuggler',1,7,-1,1,0,0,0,0,2,0,0,0,0,0,0,1,0,'choose g 4 p 2',NULL,'Choose between 4 Gold and 2 Maps.',NULL,0,'crimsonseas','On-turn, choose between 4 Gold and 2 Maps. Off-turn, take 2 Gold.'),
	 (46,'Dreadnaught',3,8,-1,0,0,1,0,0,0,1,4,0,0,0,0,0,0,NULL,NULL,NULL,NULL,0,'crimsonseas',''),
	 (47,'Conjurer',4,9,10,0,1,0,0,0,0,0,0,1,3,0,0,0,0,NULL,NULL,NULL,NULL,0,'crimsonseas',''),
	 (48,'Purser',1,11,12,0,0,0,1,0,4,0,0,0,0,0,0,1,0,'count owned_citizens g 1',NULL,'Gain 1 Gold for each face-up Citizen you own.',NULL,0,'crimsonseas',''),
	 (49,'King''s Guard',3,7,8,0,0,1,0,0,0,2,2,0,0,0,0,0,0,NULL,NULL,NULL,NULL,1,'kingsguard','');
