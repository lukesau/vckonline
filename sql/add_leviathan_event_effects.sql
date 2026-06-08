UPDATE events
SET roll_effect = 'add_self_slay_cost s 1 max=10',
    special_reward = 'count owned_monsters v 1'
WHERE id_events = 34;
