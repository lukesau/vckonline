-- special_duke_payout string format:
--   floor_div <resource> <divisor> <vp>   => floor(count/divisor) * vp  (e.g. "floor_div gold 3 1")
--   wild_choose <divisor> <vp>            => user selects which resource counts as wild; floor(chosen/divisor) * vp

INSERT INTO `vckonline`.`nobles`
(`name`, `expansion`,
 `shadow_count`, `holy_count`, `soldier_count`, `worker_count`,
 `shadow_multiplier`, `holy_multiplier`, `soldier_multiplier`, `worker_multiplier`,
 `monster_multiplier`, `citizen_multiplier`, `domain_multiplier`, `boss_multiplier`,
 `minion_multiplier`, `beast_multiplier`, `titan_multiplier`, `goods_multiplier`,
 `has_special_duke_payout`, `special_duke_payout`)
VALUES
-- 01 Augur Kawleen: Shadow x1 | 2 VP per owned Shadow
('Augur Kawleen',         'base', 1,0,0,0,  2,0,0,0, 0,0,0,0, 0,0,0,0,  0,NULL),

-- 02 Beasthunter Benrick: Shadow x1 | 3 VP per owned Beast
('Beasthunter Benrick',   'base', 1,0,0,0,  0,0,0,0, 0,0,0,0, 0,3,0,0,  0,NULL),

-- 03 Doom Chun''nan: Soldier x1 | 2 VP per owned Minion
('Doom Chun''nan',        'base', 0,0,1,0,  0,0,0,0, 0,0,0,0, 2,0,0,0,  0,NULL),

-- 04 Dray: Shadow x1 | 1 VP per 2 Wild (user selects resource at scoring)
('Dray',                  'base', 1,0,0,0,  0,0,0,0, 0,0,0,0, 0,0,0,0,  1,'wild_choose 2 1'),

-- 05 Huntmaster Heller: Soldier x1 | 1 VP per owned Monster
('Huntmaster Heller',     'base', 0,0,1,0,  0,0,0,0, 1,0,0,0, 0,0,0,0,  0,NULL),

-- 06 Izmael the Provider: Worker x1 | 1 VP per owned Worker
('Izmael the Provider',   'base', 0,0,0,1,  0,0,0,1, 0,0,0,0, 0,0,0,0,  0,NULL),

-- 07 J''ilko the Just: Worker x1 | 1 VP per owned Citizen
('J''ilko the Just',      'base', 0,0,0,1,  0,0,0,0, 0,1,0,0, 0,0,0,0,  0,NULL),

-- 08 Julian the Honorable: Worker x1 | 2 VP per owned Domain
('Julian the Honorable',  'base', 0,0,0,1,  0,0,0,0, 0,0,2,0, 0,0,0,0,  0,NULL),

-- 09 Kiko the Monster Slayer: Holy x1 | 5 VP per owned Boss
('Kiko the Monster Slayer','base', 0,1,0,0,  0,0,0,0, 0,0,0,5, 0,0,0,0,  0,NULL),

-- 10 Mikal the Moneylender: Worker x1 | 1 VP per 3 Gold
('Mikal the Moneylender', 'base', 0,0,0,1,  0,0,0,0, 0,0,0,0, 0,0,0,0,  1,'floor_div gold 3 1'),

-- 11 Phanther: Soldier x1 | 1 VP per 3 Strength
('Phanther',              'base', 0,0,1,0,  0,0,0,0, 0,0,0,0, 0,0,0,0,  1,'floor_div strength 3 1'),

-- 12 Saint Rebeka of Rollingwood: Holy x1 | 2 VP per Holy
('Saint Rebeka of Rollingwood','base', 0,1,0,0,  0,2,0,0, 0,0,0,0, 0,0,0,0,  0,NULL),

-- 13 Sir Robert Clark III: Shadow x1 | 1 VP per owned Goods
('Sir Robert Clark III',  'base', 1,0,0,0,  0,0,0,0, 0,0,0,0, 0,0,0,1,  0,NULL),

-- 14 Solan Karanga: Soldier x1 | 1 VP per owned Soldier
('Solan Karanga',         'base', 0,0,1,0,  0,0,1,0, 0,0,0,0, 0,0,0,0,  0,NULL),

-- 15 Sorceress Bouman: Holy x1 | 1 VP per 3 Magic
('Sorceress Bouman',      'base', 0,1,0,0,  0,0,0,0, 0,0,0,0, 0,0,0,0,  1,'floor_div magic 3 1'),

-- 16 Troll Hunter Grable: Holy x1 | 4 VP per Titan
('Troll Hunter Grable',   'base', 0,1,0,0,  0,0,0,0, 0,0,0,0, 0,0,4,0,  0,NULL);
