INSERT INTO vckonline.agents
(id_agents, name, activation_effect, activation_effect_text)
VALUES
	(1, 'Abbot', NULL, 'Pay 5 Magic to gain 1 Victory Point and you may recruit a Holy Citizen.'),
	(2, 'Assassin', NULL, 'Pay 3 Gold to flip a Citizen from another player''s tableau. While flipped, that Citizen does not activate in the Harvest Phase.'),
	(3, 'Baron', NULL, 'Pay 5 Gold to gain 1 Victory Point for each Domain you own.'),
	(4, 'Bishop', NULL, 'Pay 5 Gold or 5 Magic to choose another player. That player gains 1 Victory Point.'),
	(5, 'Brute Squad', NULL, 'Pay 10 Gold to gain a Citizen and banish a Citizen from the center stacks.'),
	(6, 'Captain', NULL, 'Pay 10 Strength to gain 5 Victory Points.'),
	(7, 'Green Witch', NULL, 'Take a random Monster from another player''s tableau and return it to its stack. That player gains 1 Victory Point.'),
	(8, 'Huntress', NULL, 'Take a random Monster from another player''s tableau. That player gains 1 Victory Point.'),
	(9, 'King''s Herald', NULL, 'Banish a Citizen to gain 2 Victory Points.'),
	(10, 'Prefect', NULL, 'Pay 10 Magic to gain 5 Victory Points.'),
	(11, 'Publican', NULL, 'Pay 5 Gold to gain 1 Victory Point and you may recruit a Worker Citizen.'),
	(12, 'Sapper', NULL, 'Pay 3 Strength to flip a Domain from another player''s tableau. While flipped, that Domain power may not be used.'),
	(13, 'Squire', NULL, 'Pay 1 Gold to gain 3 Strength and you may immediately slay a Monster.'),
	(14, 'Town Crier', NULL, 'Pay 3 Gold to gain 1 Victory Point and you may recruit a Citizen, ignoring the Gold cost.'),
	(15, 'Treasurer', NULL, 'Pay 10 Gold to gain 5 Victory Points.')
ON DUPLICATE KEY UPDATE
	name = VALUES(name),
	activation_effect = VALUES(activation_effect),
	activation_effect_text = VALUES(activation_effect_text);
