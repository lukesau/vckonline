INSERT INTO vckonline.relics
(id_relics, name, passive_effect, passive_effect_text)
VALUES
	(1, 'Cornelius Ring', NULL, 'Gain 1 Gold and you may buy a Domain.'),
	(2, 'Dragon Orb', NULL, 'As an action, you may banish one of your Monsters and gain 5 Gold.'),
	(3, 'Evermap', NULL, 'When you buy a Domain, you may ignore 1 Domain requirement.'),
	(4, 'Fire Lance', NULL, 'As an action, you may banish a Beast from the center stacks to gain 2 Gold.'),
	(5, 'Gold Bastion', NULL, 'As an action, gain 1 Strength and 1 Gold.'),
	(6, 'Lich Sword', NULL, 'As an action, you may pay 1 Strength to gain 3 Magic.'),
	(7, 'Mask of Asteraten', NULL, 'As an action, gain 1 Strength and you may slay a Monster.'),
	(8, 'Philosopher''s Tome', NULL, 'As an action, you may pay 4 Magic to gain 3 Gold and 1 Victory Point.'),
	(9, 'St. Aquila''s Statue', NULL, 'As an action, gain 1 Gold and you may recruit a Citizen.'),
	(10, 'Staff of Urdr', NULL, 'As an action, you may banish one of your Citizens and gain 4 Magic.'),
	(11, 'Thunder Axe', NULL, 'When you slay a Monster, you may ignore up to 3 Magic or 1 Strength of the cost.'),
	(12, 'Treant Chest', NULL, 'As an action, you may pay 3 Magic to gain 5 Gold.'),
	(13, 'Violet Ring', NULL, 'When you buy a Domain, gain 2 Victory Points.')
ON DUPLICATE KEY UPDATE
	name = VALUES(name),
	passive_effect = VALUES(passive_effect),
	passive_effect_text = VALUES(passive_effect_text);
