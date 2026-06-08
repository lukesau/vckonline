-- Crimson Seas monsters with scaling slay costs and scaling special rewards.
-- Flat vp_reward on each row is unchanged (printed VP payout, separate from special_reward).

UPDATE monsters SET
  has_special_cost = 1,
  special_cost = 'count owned_monster_name "Araby Brigands" s 1 + count owned_monster_name "Araby Brigands" m 1',
  has_special_reward = 1,
  special_reward = 'count owned_monster_name "Araby Brigands" v 1'
WHERE id_monsters BETWEEN 141 AND 145;

UPDATE monsters SET
  has_special_cost = 1,
  special_cost = 'count owned_monster_name "Goblin Pirates" s 1',
  has_special_reward = 1,
  special_reward = 'count owned_monster_name "Goblin Pirates" g 3'
WHERE id_monsters BETWEEN 148 AND 152;

UPDATE monsters SET
  has_special_cost = 1,
  special_cost = 'count owned_monster_name "Sea Drake" m 1',
  has_special_reward = 1,
  special_reward = 'count owned_monster_name "Sea Drake" s 3'
WHERE id_monsters BETWEEN 155 AND 159;

UPDATE monsters SET
  has_special_cost = 1,
  special_cost = 'count owned_monster_name "Harpies" m 1',
  has_special_reward = 1,
  special_reward = 'choose <count owned_monster_name "Harpies" g 2> <count owned_monster_name "Harpies" s 2> <count owned_monster_name "Harpies" m 2>'
WHERE id_monsters BETWEEN 162 AND 166;

UPDATE monsters SET
  has_special_cost = 1,
  special_cost = 'count owned_monster_name "Bryne" s 1',
  has_special_reward = 1,
  special_reward = 'choose g 2 p 1'
WHERE id_monsters BETWEEN 169 AND 173;

-- Boss special rewards scale by owned monster_type (count type ...), counted
-- across every area, not just the Boss's own area.
UPDATE monsters SET
  has_special_reward = 1,
  special_reward = 'count type Minion g 3',
  special_reward_text = 'Gain 3 Gold for each owned Minion.'
WHERE id_monsters = 154;

UPDATE monsters SET
  has_special_reward = 1,
  special_reward = 'choose <count type Beast g 2> <count type Beast s 2> <count type Beast m 2>',
  special_reward_text = 'Gain 2 Wild for each owned Beast.'
WHERE id_monsters = 168;
