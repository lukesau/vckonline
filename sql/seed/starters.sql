TRUNCATE TABLE vckonline.starters;
INSERT INTO vckonline.starters (id_starters,name,roll_match1,roll_match2,gold_payout_on_turn,gold_payout_off_turn,strength_payout_on_turn,strength_payout_off_turn,magic_payout_on_turn,magic_payout_off_turn,has_special_payout_on_turn,has_special_payout_off_turn,special_payout_on_turn,special_payout_off_turn,special_payout_on_turn_text,special_payout_off_turn_text,activation_trigger,expansion,card_text) VALUES
	 (1,'Peasant',5,-1,1,1,0,0,0,0,0,0,'','',NULL,NULL,'','base',''),
	 (2,'Knight',6,-1,0,0,1,1,0,0,0,0,'','',NULL,NULL,'','base',''),
	 (3,'Herald',-1,-1,0,0,0,0,0,0,1,1,'choose g 1 s 1 m 1','choose g 1 s 1 m 1','Choose between 1 Gold, 1 Strength, and 1 Magic.','Choose between 1 Gold, 1 Strength, and 1 Magic.','doubles_or_no_payout_twice','base',''),
	 (4,'Margrave',-1,-1,1,0,1,0,1,0,0,1,'','exchange wild 1 v 1',NULL,'Exchange 1 of any one resource for 1 Victory Point.','doubles_or_no_payout','margraves',''),
	 (5,'Coxswain',-1,-1,0,0,0,0,0,0,1,1,'p 1 + choose g 2 s 2 m 2','choose g 2 s 2 m 2 p 1','Gain 1 Map, then choose between 2 Gold, 2 Strength, and 2 Magic.','Choose between 2 Gold, 2 Strength, 2 Magic, and 1 Map.','doubles_or_no_payout','crimsonseas','');
