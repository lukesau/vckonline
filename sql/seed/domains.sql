TRUNCATE TABLE vckonline.domains;
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (1,'Foxgrove Palisade',9,1,0,1,0,3,0,1,'roll.set_one_die target=6 cost=g:2',NULL,'During your Roll Phase, you may pay 2 Gold to change one die to equal 6.','base'),
	 (2,'The Desert Orchid',9,1,1,0,0,3,0,1,'roll.set_one_die target=1 cost=g_per_owned_role:holy_citizen',NULL,'During your Roll Phase, you may pay 1 Gold * owned Holy Citizens to change one die to equal 1.','base'),
	 (3,'Emerald Stronghold',12,0,1,1,1,5,0,1,'effect.add action.emeraldstronghold',NULL,'During your Action phase, ignore ''+'' when buying Citizens.','base'),
	 (4,'Pratchett''s Plateau',8,0,1,0,1,3,0,1,'effect.add action.pratchettsplateau',NULL,'During your Action phase, Domains cost you 1 Gold less to buy.','base'),
	 (5,'Cathedral of St Aquila',8,0,2,0,0,3,0,1,'action.end manipulate_resources mode=take_from_player take=g:1 optional=true','','At the end of your Action phase, take 1 Gold from a Player of your choice.','base'),
	 (6,'Darktide Harbour',6,1,0,1,1,2,1,0,NULL,'choose <citizens where role==shadow>','Immediately gain a Shadow Citizen from the center stacks.','base'),
	 (7,'Cloudrider''s Camp',8,0,1,1,0,2,1,0,NULL,'s 3 + choose <citizens where role==soldier and gold_cost<=2>','Immediately gain 3 Strength and a Soldier Citizen worth 2 Gold or less.','base'),
	 (8,'The Orb of Urdr',6,1,1,0,0,1,0,1,'action.end manipulate_resources mode=take_from_player take=m:1 optional=true',NULL,'At the end of your Action Phase, take 1 Magic from a Player of your choice.','base'),
	 (9,'Rogue''s Landing',7,1,0,0,1,3,1,0,NULL,'choose <citizens where role==worker>','Immediately gain a Worker Citizen from the center stacks.','base'),
	 (10,'Blood Crow Army',5,0,0,3,0,2,0,1,'action.start manipulate_resources mode=gain gain=s:1',NULL,'At the start of your Action Phase, you gain 1 Strength.','base');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (11,'Eye of Asteraten',8,0,1,1,0,1,1,0,NULL,'s 5 + slay','Immediately gain 5 Strength and you may slay a Monster.','base'),
	 (12,'Cutthroat''s Truce',5,1,1,0,0,1,1,0,NULL,'manipulate_resources mode=take_from_player take=g:3 optional=true','Immediately take 3 Gold from a Player of your choice.','base'),
	 (13,'Halfpenny Hill',6,0,0,0,3,2,0,1,'action.start manipulate_resources mode=gain gain=g:1',NULL,'At the start of your Action Phase, you gain 1 Gold.','base'),
	 (14,'Shattered Hand',7,0,1,0,1,3,1,0,NULL,'choose <citizens where role==holy>','Immediately gain a Holy Citizen from the center stacks.','base'),
	 (15,'Forgotten Sorrows',9,1,0,0,1,3,0,1,'action.hire manipulate_resources mode=gain gain=m:1',NULL,'During your Action Phase, gain 1 Magic when you gain a Citizen.','base'),
	 (16,'Watcher on the Water',6,0,0,2,0,3,1,0,NULL,'return_owned monster v 3 optional','You may immediately return a Monster to their stack to gain 3 Victory Points.','base'),
	 (17,'Gargan''s Embrace',7,0,0,2,0,2,0,1,'roll.on_event doubles v 1',NULL,'During any Roll Phase, gain 1 Victory Point whenever doubles are rolled.','base'),
	 (18,'Nest of the Weaver Witch',6,0,0,0,2,3,1,0,NULL,'return_owned citizen v 3 optional','You may immediately return a Citizen to their stack to gain 3 Victory Points.','base'),
	 (19,'Palace of the Dawn',11,0,0,2,1,4,0,1,'roll.set_one_die subtract=1',NULL,'During your Roll Phase, you may change one die to be -1 its rolled value.','base'),
	 (20,'Grimmwater Keep',10,1,0,0,2,4,1,0,NULL,'choose <citizens where gold_cost<=3>','Immediately gain a Citizen worth 3 Gold or less.','base');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (21,'The Violet Thorn',7,0,1,1,0,3,0,1,'action.slay manipulate_resources mode=gain gain=m:1',NULL,'During your Action Phase, when you slay a Monster gain 1 Magic.','base'),
	 (22,'Purloiner''s Perch',10,2,0,0,0,2,1,0,NULL,'take_owned monster random','Immediately take a random Monster from a Player of your choice.','base'),
	 (23,'Golden Obelisk of Nae',6,0,1,0,1,3,1,0,NULL,'manipulate_resources mode=self_convert pay=m:3 gain=v:3 optional=true','You may immediately pay 3 Magic to gain 3 Victory Points.','base'),
	 (24,'Monolith of Ostendaar',9,0,0,1,1,3,0,1,'action.start manipulate_resources mode=gain gain=m:1',NULL,'At the start of your Action Phase, you gain 1 Magic.','base'),
	 (25,'Ararmartin Ridge',5,0,0,0,2,2,1,0,NULL,'g 3 + build_domain','Immediately gain 3 Gold and you may build a Domain.','flamesandfrost'),
	 (26,'Castle of the Seven Suns',12,1,1,1,1,2,0,1,'immunity.take',NULL,'For the rest of the game opponents cannot take resources or cards from the holder.','flamesandfrost'),
	 (27,'Defiant Ridge',11,0,1,1,1,2,0,1,'effect.add action.defiantridge',NULL,'During your Action Phase, Citizens take 1 less Gold to recruit.','flamesandfrost'),
	 (28,'Den of the Ice Witch',5,2,0,0,0,3,1,0,NULL,'v 1 + banish_center citizen','Immediately Banish a Citizen from the center stacks and gain 1 Victory Point.','flamesandfrost'),
	 (29,'Flame Tongue Mountain',8,0,1,2,0,3,0,1,'roll.on_event doubles m 3',NULL,'During any Roll Phase, gain 3 Magic whenever doubles are rolled.','flamesandfrost'),
	 (30,'Fort Skyler',12,0,1,3,0,3,0,1,'effect.add action.fortskyler',NULL,'During your Action Phase, Monsters take 1 less Strength to slay.','flamesandfrost');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (31,'Hoarfrost Stockade',9,0,1,1,0,4,1,0,NULL,'choose <citizens where role==soldier>','Immediately gain a Soldier Citizen from the center stacks.','flamesandfrost'),
	 (32,'Mines of Croft',15,0,0,1,1,5,0,1,'action.start manipulate_resources mode=self_convert pay=s:2 gain=m:3 optional=true',NULL,'At the start of your Action Phase, you may exchange 2 Strength for 3 Magic.','flamesandfrost'),
	 (33,'New Shilina Tower',9,1,1,0,0,2,0,1,'action.newshilinatower',NULL,'When recruiting a Citizen you may pay with Strength.','flamesandfrost'),
	 (34,'Port of Araby',12,1,0,0,1,3,0,1,'action.start exchange g 1 wild 2',NULL,'At the start of your Action Phase, you may exchange 1 Gold for 2 Wild.','flamesandfrost'),
	 (35,'Red Hollow',7,1,0,1,1,2,0,1,'action.end manipulate_resources mode=take_from_player take=s:1 optional=true',NULL,'At the end of your Action Phase, take 1 Strength from a player of your choice.','flamesandfrost'),
	 (36,'Rime Temple',14,0,1,0,2,4,0,1,'action.end manipulate_resources mode=self_convert pay=g:2 gain=v:1 optional=true',NULL,'At the end of your Action Phase, you may exchange 2 Gold for 1 Victory Point.','flamesandfrost'),
	 (37,'Sunder Bay',8,1,0,0,3,1,1,0,NULL,'banish_player_citizen','Immediately Banish a Citizen that belongs to a Player of your choice. ','flamesandfrost'),
	 (38,'Switch Wind Fortress',12,0,0,4,0,3,0,1,'action.end manipulate_resources mode=self_convert pay=s:2 gain=v:1 optional=true',NULL,'At the end of your Action Phase, you may exchange 2 Strength for 1 Victory Point.','flamesandfrost'),
	 (39,'The Northern Wall',6,0,0,2,0,2,0,1,'action.northernwall',NULL,'During your Roll Phase, you may Banish a Minion Monster from the center stacks.','flamesandfrost'),
	 (40,'Tujjar Haven',9,0,0,0,3,2,1,0,NULL,'count owned_citizens g 1','Immediately gain 1 Gold for each Citizen you own.','flamesandfrost');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (41,'Twilight Palace',12,0,2,1,1,3,0,1,'roll.reroll_one_die',NULL,'During your Roll Phase, you may re-roll one die.','flamesandfrost'),
	 (42,'Wandering Flame',8,2,0,1,0,2,1,0,NULL,'banish_random_player_monster','Immediately banish a random Monster owned by a Player of your choice. ','flamesandfrost'),
	 (43,'Winter Spire',10,1,1,0,0,3,1,0,NULL,'manipulate_resources mode=take_from_player take=m:5 optional=true','Immediately take 5 Magic from a Player of your choice.','flamesandfrost'),
	 (44,'Zafar''s Oasis',9,1,0,0,2,2,1,0,NULL,'exchange wild 9 v 4','You may immediately pay 9 Wild for 4 Victory Points.','flamesandfrost'),
	 (45,'Ancient Tomb',7,0,1,1,1,3,1,0,'','action.modify_monster_strength +3','Immediately add 3 Strength to the cost of a Monster in the center stacks.','shadowvale'),
	 (46,'Blasko Woods',6,0,1,0,1,2,0,1,'action.build manipulate_resources mode=gain gain=m:1',NULL,'During your Action Phase, when you build a Domain gain 1 Magic.','shadowvale'),
	 (47,'Blood Moon Palace',14,2,0,0,1,5,0,1,'roll.reroll_both_dice_pay_magic_2',NULL,'During your Roll Phase, you may pay 2 Magic to reroll both dice.','shadowvale'),
	 (48,'Crystal Lake Encampment',8,0,0,2,0,2,0,1,'roll.on_event doubles s 3',NULL,'During any Roll Phase, gain 3 Strength whenever doubles are rolled.','shadowvale'),
	 (49,'Cursed Cavern',10,1,1,0,1,2,1,0,NULL,'m 4 + concurrent_flip_one_citizen','All players immediately flip a Citizen and you gain 4 Magic.','shadowvale'),
	 (50,'Gray Harbor',7,2,0,0,0,1,1,0,NULL,'manipulate_resources mode=take_from_player take=g:5 optional=true','Immediately take 5 Gold from a Player of your choice.','shadowvale');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (51,'Hobb''s End',7,2,0,1,0,1,1,0,NULL,'steal_citizen gold_cost<=2','Immediately take a Citizen worth 2 gold or less from a Player of your choice.','shadowvale'),
	 (52,'Karloff Castle',13,0,0,2,1,3,0,1,'harvest.gain_per_owned_citizen_name Peasant s 1',NULL,'During your Harvest Phase, gain 1 Strength for each Peasant you own.','shadowvale'),
	 (53,'King Tower',12,0,1,0,2,3,0,1,'action.end manipulate_resources mode=pay_to_player gain=v:1 pay=m:1 optional=true',NULL,'At the end of your Action Phase, pay 1 Magic to a Player of your choice to gain 1 Victory Point.','shadowvale'),
	 (54,'Laborium',11,2,0,0,0,2,1,0,NULL,'s 5 + flip_opponent_citizen','Immediately gain 5 Strength and flip a Citizen owned by a Player of your choice.','shadowvale'),
	 (55,'Legendre''s Keep',6,0,0,2,0,2,1,0,NULL,'banish_center monster + slay','Immediately Banish a Monster from the center stcks, then you may Slay a Monster.','shadowvale'),
	 (56,'Lost Gardens',9,1,0,1,0,3,0,1,'action.end choose g 1 s 1',NULL,'At the end of your Action Phase, you gain 1 Gold or 1 Strength.','shadowvale'),
	 (57,'Maleva''s Temple',12,0,1,1,1,3,0,1,'action.end manipulate_resources mode=self_convert pay=g:1 gain=m:3 optional=true',NULL,'At the end of your Action Phase, you may exchange 1 Gold for 3 Magic.','shadowvale'),
	 (58,'Martin Road',13,1,0,0,2,3,1,0,NULL,'m 5 + choose <citizens where role==soldier>','Immediately gain 5 Magic and a Soldier Citizen from the center stacks.','shadowvale'),
	 (59,'Opera House',13,0,2,1,1,3,0,1,'harvest.on_any_magic_gain m 1',NULL,'During any Harvest Phase, if you gain any Magic from payouts, gain 1 Magic.','shadowvale'),
	 (60,'Pretorius Conclave',8,1,1,1,1,2,1,0,'','choose <citizens>','Immediately gain a Citizen from the center stacks.','shadowvale');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (61,'Raven''s Outpost',8,0,0,2,1,3,0,1,'action.on_opponent_slay s 1',NULL,'During any Action Phase, when an opponent slays a Monster, gain 1 Strength.','shadowvale'),
	 (62,'Shelley Commons',13,0,1,1,1,4,0,1,'action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1 optional=true',NULL,'At the end of your Action phase, pay 1 Gold to a Player of your choice to gain 1 Victory Point.','shadowvale'),
	 (63,'Stoker''s Pass',11,0,0,2,0,3,0,1,'action.end manipulate_resources mode=pay_to_player gain=v:1 pay=s:1 optional=true',NULL,'At the end of your Action Phase, pay 1 Strength to a Player of your choice to gain 1 Victory Point.','shadowvale'),
	 (64,'Tepes Ridge Fortress',8,0,1,1,1,3,0,1,'action.slay manipulate_resources mode=gain gain=g:1',NULL,'During your Action Phase, when you slay a Monster gain 1 Gold.','shadowvale'),
	 (65,'Vin''pryce Barrens',10,0,2,0,0,3,1,0,NULL,'m 5 + slay','Immediately gain 5 Magic and you may slay a Monster from the center stacks.','shadowvale'),
	 (66,'Wisborg',6,0,1,0,1,3,1,0,'','manipulate_resources mode=self_convert pay=g:3 gain=v:3 optional=true','You may immediately pay 3 Gold to gain 3 Victory Points.','shadowvale'),
	 (67,'Avery Hollow',5,0,1,3,0,1,0,1,'roll.exekratys_immune',NULL,'During your Roll Phase, you don''t lose Wild on a 6.','crimsonseas'),
	 (68,'Barbarossa Castle',6,1,0,3,0,2,1,0,'','banish_center noble + choose g 3 s 3 m 3','Immediately gain 3 Wild and Banish a Noble from Amarynth.','crimsonseas'),
	 (69,'Brigand''s Bay',5,1,0,0,1,1,1,0,'','choose <goods>','Immediately take 1 Goods from Araby.','crimsonseas'),
	 (70,'Browncoat''s Sanctum',10,0,1,1,2,2,0,1,'effect.add action.browncoatssanctum',NULL,'During your Action Phase, Tomes cost 1 Gold less to buy.','crimsonseas');
INSERT INTO vckonline.domains (id_domains,name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,effect_text,expansion) VALUES
	 (71,'Daak Harbor',6,0,2,2,0,1,1,0,'','choose t 1','Immediately take 1 Tome from Nae Aerie.','crimsonseas'),
	 (72,'Dampiar''s Workshop',6,1,0,1,1,3,1,0,'','g 3 + p 1 + sail','Immediately gain 3 Gold + 1 Map and you may Sail.','crimsonseas'),
	 (73,'Murat Reis',9,0,2,0,2,2,0,1,'effect.add action.muratreis',NULL,'During your Action Phase, ignore +Wild cost when rescuing a Noble.','crimsonseas'),
	 (74,'Port of Drake',12,1,0,0,2,3,0,1,'effect.add action.portofdrake',NULL,'During your Action Phase, Goods cost 1 Gold less to buy.','crimsonseas'),
	 (75,'Solo''s Haven',6,1,1,1,1,3,1,0,'','refresh_tomes','Immediately flip all of your Tomes face-up.','crimsonseas'),
	 (76,'Tabula Tower',11,2,0,0,1,3,0,1,'action.end manipulate_resources mode=self_convert pay=g:1 gain=p:1 optional=true',NULL,'At the end of your Action Phase, you may exchange 1 Gold for 1 Map.','crimsonseas'),
	 (77,'Coliseum',15,1,0,2,0,5,1,0,NULL,'count owned_citizens s 1','Immediately gain 1 Strength for each Citizen you own.','promo'),
	 (78,'Jousting Field',13,1,0,1,1,3,0,1,'harvest.gain_per_owned_citizen_name Knight g 1 + harvest.gain_per_owned_starter_name Knight g 1',NULL,'During your Harvest Phase, gain 1 Gold for each Knight you own.','promo'),
	 (79,'The Tower',10,1,1,1,1,2,0,1,'action.end manipulate_resources mode=self_convert pay=m:2 gain=v:1 optional=true',NULL,'At the end of your Action Phase, you may exchange 2 Magic for 1 Victory Point.','promo'),
	 (80,'Ullamalizatli Court',11,0,1,0,2,3,1,0,NULL,'count owned_citizens m 1','Immediately gain 1 Magic for each Citizen you own.','promo');
