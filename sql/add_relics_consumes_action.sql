-- Add the `consumes_action` flag to relics. A relic whose printed text reads
-- "As an action ..." spends one standard action when used; the rest are free
-- (Cornelius Ring) or triggered/passive (Evermap, Thunder Axe, Violet Ring).
ALTER TABLE vckonline.relics
    ADD COLUMN IF NOT EXISTS consumes_action tinyint(1) NOT NULL DEFAULT 0;

-- "As an action" relics: spend an action when used.
UPDATE vckonline.relics
SET consumes_action = 1
WHERE name IN (
    'Dragon Orb',
    'Fire Lance',
    'Gold Bastion',
    'Lich Sword',
    'Mask of Asteraten',
    'Philosopher''s Tome',
    'St. Aquila''s Statue',
    'Staff of Urdr',
    'Treant Chest'
);

-- Free / triggered relics: no action spent.
UPDATE vckonline.relics
SET consumes_action = 0
WHERE name IN (
    'Cornelius Ring',
    'Evermap',
    'Thunder Axe',
    'Violet Ring'
);
