TRUNCATE TABLE vckonline.agents;
INSERT INTO vckonline.agents (id_agents,name,activation_effect,activation_effect_text) VALUES
	 (1,'Abbot','m -5 + v 1 + <citizens where role==holy>','Pay 5 Magic to gain 1 Victory Point and gain a Holy Citizen.'),
	 (2,'Assassin','g -3 + flip_opponent_citizen','Pay 3 Gold to flip a Citizen from another player''s tableau. While flipped, that Citizen does not activate in the Harvest Phase.'),
	 (3,'Baron','g -5 + count owned_domains v 1','Pay 5 Gold to gain 1 Victory Point for each Domain you own.'),
	 (4,'Bishop','steal g 5 m 5 victim_vp=1','Steal 5 Gold or 5 Magic from another player. That player gains 1 Victory Point.'),
	 (5,'Brute Squad','g -10 + <citizens> + banish_center citizen','Pay 10 Gold to gain a Citizen and banish a Citizen from the center stacks.'),
	 (6,'Captain','s -10 + v 5','Pay 10 Strength to gain 5 Victory Points.'),
	 (7,'Green Witch','take_owned monster random to=stack victim_vp=1','Take a random Monster from another player''s tableau and return it to its stack. That player gains 1 Victory Point.'),
	 (8,'Huntress','take_owned monster random to=self victim_vp=1','Take a random Monster from another player''s tableau. That player gains 1 Victory Point.'),
	 (9,'King''s Herald','banish_owned citizen + v 2','Banish a Citizen from your own tableau to gain 2 Victory Points.'),
	 (10,'Prefect','m -10 + v 5','Pay 10 Magic to gain 5 Victory Points.');
INSERT INTO vckonline.agents (id_agents,name,activation_effect,activation_effect_text) VALUES
	 (11,'Publican','g -5 + v 1 + <citizens where role==shadow>','Pay 5 Gold to gain 1 Victory Point and gain a Shadow Citizen.'),
	 (12,'Sapper','s -3 + flip_opponent_domain','Pay 3 Strength to flip a Domain from another player''s tableau. While flipped, that Domain power may not be used. At the end of the game, flip the Domain face-up and score it as usual.'),
	 (13,'Squire','g -1 + s 3 + slay','Pay 1 Gold to gain 3 Strength and you may immediately slay a Monster.'),
	 (14,'Town Crier','g -3 + v 1 + recruit','Pay 3 Gold to gain 1 Victory Point and you may recruit a Citizen, ignoring increased Gold cost for owning copies of that Citizen.'),
	 (15,'Treasurer','g -10 + v 5','Pay 10 Gold to gain 5 Victory Points.');
