INSERT INTO vckonline.relics
(id_relics, name, passive_effect, passive_effect_text, consumes_action)
VALUES
	(1, 'Cornelius Ring', 'g 1 + build_domain', 'As an action, gain 1 Gold and you may buy a Domain.', 1),
	(2, 'Dragon Orb', 'banish_owned monster + g 5', 'As an action, you may banish one of your Monsters and gain 5 Gold.', 1),
	(3, 'Evermap', 'action.build_domain ignore_requirement 1 or m 1', 'When you buy a Domain, you may ignore 1 Domain requirement or gain 1 Magic.', 0),
	(4, 'Fire Lance', 'banish_center monster type=minion + g 2', 'As an action, you may banish a Minion from the center stacks to gain 2 Gold.', 1),
	(5, 'Gold Bastion', 's 1 + g 1', 'As an action, gain 1 Strength and 1 Gold.', 1),
	(6, 'Lich Sword', 's -1 + m 3', 'As an action, you may pay 1 Strength to gain 3 Magic.', 1),
	(7, 'Mask of Asteraten', 's 1 + slay', 'As an action, gain 1 Strength and you may slay a Monster.', 1),
	(8, 'Philosopher''s Tome', 'm -4 + g 3 + v 1', 'As an action, you may pay 4 Magic to gain 3 Gold and 1 Victory Point.', 1),
	(9, 'St. Aquila''s Statue', 'g 1 + recruit', 'As an action, gain 1 Gold and you may recruit a Citizen.', 1),
	(10, 'Staff of Urdr', 'banish_owned citizen + m 4', 'As an action, you may banish one of your Citizens and gain 4 Magic.', 1),
	(11, 'Thunder Axe', 'action.slay_discount magic=1 strength=1', 'When you slay a Monster, you may ignore 1 Magic or 1 Strength of the cost.', 0),
	(12, 'Treant Chest', 'exchange wild 3 wild 5', 'As an action, you may pay 3 of any one resource to gain 5 of any one resource.', 1),
	(13, 'Violet Ring', 'action.build_domain v 2', 'When you buy a Domain, gain 2 Victory Points.', 0)
ON DUPLICATE KEY UPDATE
	name = VALUES(name),
	passive_effect = VALUES(passive_effect),
	passive_effect_text = VALUES(passive_effect_text),
	consumes_action = VALUES(consumes_action);
