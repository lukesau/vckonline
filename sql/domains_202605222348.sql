INSERT INTO vckonline.domains (name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,`text`,expansion) VALUES
	 ('Foxgrove Palisade',9,1,0,1,0,3,0,1,'roll.set_one_die target=6 cost=g:2',NULL,'During your Roll Phase, you may pay 2gp to change one die to equal 6.','base'),
	 ('The Desert Orchid',9,1,1,0,0,3,0,1,'roll.set_one_die target=1 cost=g_per_owned_role:holy_citizen',NULL,'During your Roll Phase, you may pay 1gp * owned Holy Citizens to change one die to equal 1.','base'),
	 ('Emerald Stronghold',12,0,1,1,1,5,0,1,'effect.add action.emeraldstronghold',NULL,'During your Action phase, ignore ''+'' when buying Citizens.','base'),
	 ('Pratchett''s Plateau',8,0,1,0,1,3,0,1,'effect.add action.pratchettsplateau',NULL,'During your Action phase, Domains cost you 1gp less to buy.','base'),
	 ('Cathedral of St Aquila',8,0,2,0,0,3,0,1,'action.end manipulate_resources mode=take_from_player take=g:1 optional=true','','At the end of your Action phase, take 1gp from a Player of your choice.','base'),
	 ('Darktide Harbour',6,1,0,1,1,2,1,0,NULL,'choose <citizens where role==shadow>','Immediately gain a Shadow Citizen from the center stacks.','base'),
	 ('Cloudrider''s Camp',8,0,1,1,0,2,1,0,NULL,'s 3 + choose <citizens where role==soldier and gold_cost<=2>','Immediately gain 3sp and a Soldier Citizen worth 2gp or less.','base'),
	 ('The Orb of Urdr',6,1,1,0,0,1,0,1,'action.end manipulate_resources mode=take_from_player take=m:1 optional=true',NULL,'At the end of your Action Phase, take 1mp from a Player of your choice.','base'),
	 ('Rogue''s Landing',7,1,0,0,1,3,1,0,NULL,'choose <citizens where role==worker>','Immediately gain a Worker Citizen from the center stacks.','base'),
	 ('Blood Crow Army',5,0,0,3,0,2,0,1,'action.start manipulate_resources mode=gain gain=s:1',NULL,'At the start of your Action Phase, you gain 1sp.','base');
INSERT INTO vckonline.domains (name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,`text`,expansion) VALUES
	 ('Eye of Asteraten',8,0,1,1,0,1,1,0,NULL,'s 5 + grant_action slay','Immediately gain 5sp and you may slay a Monster.','base'),
	 ('Cutthroat''s Truce',5,1,1,0,0,1,1,0,NULL,'manipulate_resources mode=take_from_player take=g:3 optional=true','Immediately take 3gp from a Player of your choice.','base'),
	 ('Halfpenny Hill',6,0,0,0,3,2,0,1,'action.start manipulate_resources mode=gain gain=g:1',NULL,'At the start of your Action Phase, you gain 1gp.','base'),
	 ('Shattered Hand',7,0,1,0,1,3,1,0,NULL,'choose <citizens where role==holy>','Immediately gain a Holy Citizen from the center stacks.','base'),
	 ('Forgotten Sorrows',9,1,0,0,1,3,0,1,'action.hire manipulate_resources mode=gain gain=m:1',NULL,'During your Action Phase, gain 1mp when you gain a Citizen.','base'),
	 ('Watcher on the Water',6,0,0,2,0,3,1,0,NULL,NULL,'You may immediately return a Monster to their stack to gain 3vp','base'),
	 ('Gargan''s Embrace',7,0,0,2,0,2,0,1,'effect.add roll.gargansembrace',NULL,'During any Roll Phase, gain 1vp whenever doubles are rolled.','base'),
	 ('Nest of the Weaver Witch',6,0,0,0,2,3,1,0,NULL,NULL,'You may immediately return a Citizen to their stack to gain 3vp','base'),
	 ('Palace of the Dawn',11,0,0,2,1,4,0,1,'roll.set_one_die subtract=1',NULL,'During your Roll Phase, you may change one die to be -1 its rolled value.','base'),
	 ('Grimmwater Keep',10,1,0,0,2,4,1,0,NULL,'choose <citizens where gold_cost<=3>','Immediately gain a Citizen worth 3gp or less.','base');
INSERT INTO vckonline.domains (name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,`text`,expansion) VALUES
	 ('The Violet Thorn',7,0,1,1,0,3,0,1,NULL,NULL,'During your Action Phase, when you slay a Monster gain 1mp','base'),
	 ('Purloiner''s Perch',10,2,0,0,0,2,1,0,NULL,NULL,'Immediately take a random Monster from a Player of your choice.','base'),
	 ('Golden Obelisk of Nae',6,0,1,0,1,3,1,0,NULL,'manipulate_resources mode=self_convert pay=m:3 gain=v:3 optional=true','You may immediately pay 3mp to gain 3vp','base'),
	 ('Monolith of Ostendaar',9,0,0,1,1,3,0,1,'action.start manipulate_resources mode=gain gain=m:1',NULL,'At the start of your Action Phase, you gain 1mp.','base'),
	 ('Wisborg',6,0,1,0,1,3,1,0,'','manipulate_resources mode=self_convert pay=g:3 gain=v:3 optional=true','You may immediately pay 3gp to gain 3vp.',NULL),
	 ('King Tower',12,0,1,0,2,3,0,1,'action.end manipulate_resources mode=pay_to_player gain=v:1 pay=m:1 optional=true',NULL,'At the end of your Action Phase, pay 1mp to a Player of your choice to gain 1vp.',NULL),
	 ('Cursed Cavern',10,1,1,0,1,2,1,0,NULL,'m 4 + concurrent_flip_one_citizen','All players immediately flip a Citizen and you gain 4mp.',NULL),
	 ('Shelley Commons',13,0,1,1,1,4,0,1,'action.end manipulate_resources mode=pay_to_player gain=v:1 pay=g:1 optional=true',NULL,'At the end of your Action phase, pay 1gp to a Player of your choice to gain 1vp.',NULL),
	 ('Pretorius Conclave',8,1,1,1,1,2,1,0,'','choose <citizens>','Immediately gain a Citizen from the center stacks.',NULL),
	 ('Ancient Tomb',7,0,1,1,1,3,1,0,'','action.modify_monster_strength +3','Immediately add 3sp to a Monster Strength value.',NULL);
INSERT INTO vckonline.domains (name,gold_cost,shadow_count,holy_count,soldier_count,worker_count,vp_reward,has_activation_effect,has_passive_effect,passive_effect,activation_effect,`text`,expansion) VALUES
	 ('Jousting Field',13,1,0,1,1,3,0,1,'harvest.gain_per_owned_citizen_name Knight g 1',NULL,'During your Harvest Phase, gain 1gp * Knight you own.',NULL);
