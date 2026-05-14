INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Cleric',3,1,-1,0,1,0,0,0,0,0,0,3,1,0,0,NULL,NULL,0,'base1'),
	 ('Merchant',2,2,-1,0,0,0,1,0,1,0,0,0,0,1,0,'choose g 2 m 2',NULL,0,'base1'),
	 ('Mercenary',3,3,-1,1,0,0,0,1,0,1,0,0,0,0,1,NULL,'exchange s 1 g 2',0,'base1'),
	 ('Archer',4,4,-1,0,0,1,0,0,0,2,1,0,0,0,0,NULL,NULL,0,'base1'),
	 ('Peasant',2,5,-1,0,0,0,1,1,1,0,0,0,0,0,0,NULL,NULL,0,'base1'),
	 ('Knight',2,6,-1,0,0,1,0,0,0,1,1,0,0,0,0,NULL,NULL,0,'base1'),
	 ('Rogue',2,7,-1,1,0,0,0,2,1,2,1,0,0,0,0,NULL,NULL,0,'base1'),
	 ('Champion',2,8,-1,0,0,1,0,0,0,4,0,0,0,0,1,NULL,'exchange g 1 s 4',0,'base1'),
	 ('Paladin',2,9,10,0,1,0,0,0,0,1,0,2,0,0,1,NULL,'exchange s 1 m 3',0,'base1'),
	 ('Butcher',1,11,12,0,0,0,1,0,4,0,0,0,0,1,0,'count owned_worker g 2',NULL,0,'base1');
INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Exorcist',1,1,-1,0,1,0,0,0,0,0,0,2,1,0,0,NULL,NULL,0,'shadowvale'),
	 ('Lumberjack',2,2,-1,0,0,0,1,1,0,1,0,0,0,0,1,NULL,NULL,0,'shadowvale'),
	 ('Bandit',3,3,-1,1,0,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'shadowvale'),
	 ('Hunter',4,4,-1,0,0,1,0,0,0,2,0,0,0,0,1,NULL,NULL,0,'shadowvale'),
	 ('Peasant',3,5,-1,0,1,0,1,0,1,0,0,0,0,1,0,NULL,NULL,0,'shadowvale'),
	 ('Knight',3,6,-1,1,0,1,0,0,0,0,1,0,0,1,0,NULL,NULL,0,'shadowvale'),
	 ('Necromancer',4,7,-1,1,0,0,0,0,0,0,0,3,0,0,1,NULL,NULL,0,'shadowvale'),
	 ('Guardian',1,8,-1,0,0,1,0,0,0,3,3,0,0,0,0,NULL,NULL,0,'shadowvale'),
	 ('Dragoon',3,9,10,0,1,0,0,0,0,0,1,2,1,1,0,NULL,NULL,0,'shadowvale'),
	 ('Inventor',1,11,12,0,0,0,1,5,5,0,0,0,0,0,0,NULL,NULL,0,'shadowvale');
INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Summoner',1,1,-1,0,1,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'flamesandfrost'),
	 ('Bard',2,2,-1,0,0,0,1,0,1,0,0,0,0,1,0,NULL,NULL,0,'flamesandfrost'),
	 ('Sorceress',3,3,-1,1,0,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'flamesandfrost'),
	 ('Barbarian',4,4,-1,0,0,1,0,0,0,2,0,0,0,0,1,NULL,NULL,0,'flamesandfrost'),
	 ('Peasant',2,5,-1,0,0,0,1,1,1,0,0,0,0,1,0,NULL,NULL,0,'flamesandfrost'),
	 ('Knight',2,6,-1,0,0,1,0,0,0,1,1,0,0,1,0,NULL,NULL,0,'flamesandfrost'),
	 ('Condottiere',2,7,-1,1,0,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'flamesandfrost'),
	 ('Bogatyr',1,8,-1,0,0,1,0,0,0,3,0,0,0,0,1,NULL,NULL,0,'flamesandfrost'),
	 ('Templar',3,9,10,0,1,0,0,0,0,2,1,2,1,0,0,NULL,NULL,0,'flamesandfrost'),
	 ('Baker',1,11,12,0,0,0,1,0,0,0,0,0,0,1,1,NULL,NULL,0,'flamesandfrost');
INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Monk',3,1,-1,0,1,0,0,1,0,0,0,2,0,0,1,NULL,'exchange g 1 m 2',0,'base2'),
	 ('Blacksmith',3,2,-1,0,0,0,1,0,1,0,0,0,0,1,0,'count owned_soldier g 1',NULL,0,'base2'),
	 ('Alchemist',3,3,-1,1,0,0,0,0,0,0,0,0,0,1,1,'exchange g 1 m 3','exchange m 1 g 2',0,'base2'),
	 ('Wizard',4,4,-1,0,0,1,0,0,0,1,0,1,1,0,0,NULL,NULL,0,'base2'),
	 ('Thief',2,7,-1,1,0,0,0,0,0,0,0,0,0,1,1,'steal g 3 m 3','choose g 2 m 2',0,'base2'),
	 ('Warlord',2,8,-1,0,0,1,0,0,0,0,0,0,0,1,1,'count owned_soldier s 1','count owned_citizen_name Knight s 1',0,'base2'),
	 ('Priestess',2,9,10,0,1,0,0,0,0,2,0,1,0,0,1,NULL,'exchange m 1 s 3',0,'base2'),
	 ('Miner',1,11,12,0,0,0,1,0,4,0,0,0,0,1,0,'g 1 + count owned_domains g 1',NULL,0,'base2'),
	 ('Hydromancer',1,1,-1,0,1,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'crimsonseas'),
	 ('Engineer',2,2,-1,0,0,0,1,0,0,0,0,0,0,1,1,NULL,NULL,0,'crimsonseas');
INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Vitki',3,3,-1,1,0,0,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'crimsonseas'),
	 ('Marauder',1,4,-1,0,0,1,0,0,0,0,0,0,0,1,1,NULL,NULL,0,'crimsonseas'),
	 ('Peasant',2,5,-1,0,0,0,1,0,1,0,0,0,0,1,0,NULL,NULL,0,'crimsonseas'),
	 ('Knight',2,6,-1,0,0,1,0,0,0,0,1,0,0,1,0,NULL,NULL,0,'crimsonseas'),
	 ('Smuggler',1,7,-1,1,0,0,0,0,2,0,0,0,0,1,0,NULL,NULL,0,'crimsonseas'),
	 ('Dreadnaught',3,8,-1,0,0,1,0,0,0,1,4,0,0,0,0,NULL,NULL,0,'crimsonseas'),
	 ('Conjurer',4,9,10,0,1,0,0,0,0,0,0,1,3,0,0,NULL,NULL,0,'crimsonseas'),
	 ('Purser',1,11,12,0,0,0,1,0,4,0,0,0,0,1,0,NULL,NULL,0,'crimsonseas'),
	 ('King''s Guard',3,7,8,0,0,1,0,0,0,2,2,0,0,0,0,NULL,NULL,1,'kingsguard'),
	 ('Peasant',3,5,-1,1,0,0,1,0,1,0,0,0,0,1,0,'choose g 1 s 1',NULL,0,'peasantandknight');
INSERT INTO vckonline.citizens (name,gold_cost,roll_match1,roll_match2,shadow_count,holy_count,soldier_count,worker_count,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_citizen,expansion) VALUES
	 ('Knight',3,6,-1,0,1,1,0,0,0,0,1,0,0,1,0,'choose s 1 m 1',NULL,0,'peasantandknight');
