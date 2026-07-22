"""State featurization for the learned value function.

extract(game, viewer_pid) -> fixed-length float vector, viewer-relative
(my side first, opponent second, then differences and global board state).
Uses the engine's own endgame scorer for projected VP and GreedyPolicy's
income model, so the features share semantics with everything else.
2-player only for now.
"""

import numpy as np

from agent.policies import GreedyPolicy

FEATURE_VERSION = 1

_greedy = GreedyPolicy()


def _player_features(game, player, projected_vp):
    rates = _greedy._rates(player)
    citizens = [c for c in player.owned_citizens if not getattr(c, "is_flipped", False)]
    income = sum(_greedy._citizen_income_per_roll(c, rates, player) for c in citizens)
    income += sum(
        _greedy._citizen_income_per_roll(s, rates, player) for s in player.owned_starters
    )
    roles = player.calc_roles()
    steering = any(
        str(getattr(d, "passive_effect", "") or "").startswith("roll.")
        for d in player.owned_domains
        if not getattr(d, "is_flipped", False)
    )
    return [
        player.gold_score / 20.0,
        player.strength_score / 20.0,
        player.magic_score / 20.0,
        player.victory_score / 50.0,
        projected_vp / 100.0,
        len(citizens) / 10.0,
        len(player.owned_domains) / 6.0,
        len(player.owned_monsters) / 8.0,
        roles["shadow_count"] / 8.0,
        roles["holy_count"] / 8.0,
        roles["soldier_count"] / 8.0,
        roles["worker_count"] / 8.0,
        income / 3.0,
        1.0 if steering else 0.0,
    ]


def extract(game, viewer_pid):
    me = opp = None
    for p in game.player_list:
        if p.player_id == viewer_pid:
            me = p
        else:
            opp = p
    if me is None or opp is None:
        raise ValueError(f"viewer {viewer_pid!r} not found or not a 2-player game")

    try:
        scores = {s["player_id"]: int(s["total_vp"]) for s in game.endgame._calculate_final_scores()}
    except Exception:
        scores = {p.player_id: int(p.victory_score) for p in game.player_list}
    my_proj = scores.get(me.player_id, 0)
    opp_proj = scores.get(opp.player_id, 0)

    features = _player_features(game, me, my_proj)
    features += _player_features(game, opp, opp_proj)

    n_players = len(game.player_list)
    monsters_left = sum(len(s) for s in game.monster_grid)
    domains_left = sum(len(s) for s in game.domain_grid)
    citizen_stacks = [len(s) for s in game.citizen_grid] or [0]
    active = game.player_list[game.turn_index].player_id if game.player_list else None
    features += [
        (my_proj - opp_proj) / 50.0,
        (me.gold_score + me.strength_score + me.magic_score
         - opp.gold_score - opp.strength_score - opp.magic_score) / 40.0,
        int(game.turn_number or 0) / 32.0,
        int(game.exhausted_count or 0) / (2.0 * n_players),
        monsters_left / 34.0,
        domains_left / 15.0,
        min(citizen_stacks) / 5.0,
        sum(citizen_stacks) / 50.0,
        1.0 if active == viewer_pid else 0.0,
        1.0 if getattr(me, "is_first", False) else 0.0,
        1.0 if game.end_game_triggered else 0.0,
    ]
    return np.asarray(features, dtype=np.float32)


N_FEATURES = 2 * 14 + 11
