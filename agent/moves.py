"""Legal-move enumeration for headless play.

Wraps bots/legal_moves.enumerate_actions and patches known gaps without touching
the repo's file. The engine (engines/player_actions.py) keys prompt responses on
specific verbs and silently ignores anything else; the upstream enumerator emits
the generic "choose <N>" / "accept" forms for several prompts that actually need
dedicated verbs. Verb table extracted from player_actions.py:

  choose_player            -> "choose_player <N>"        (all kinds)
  choose_owned_card        -> "choose_owned_card <N>"    (most kinds)
                              "choose <N>"               (kind=special_payout_choose,
                                                          domain_return_owned stage 2)
  choose_domain_reward     -> "grant_domain <N>"
  choose_domain_to_build   -> "build_domain_pick <N>" / "skip"
  build_domain_payment     -> "build_pay <g> <m>" / "skip"   (magic wilds gold)
  slay_monster_payment     -> "slay_pay <g> <s> <m>" / "skip" (kind=immediate_slay)
  choose_monster_strength  -> "choose_monster <N>"
  domain_choose_resource   -> "choose <N>" into prc["choices"]
  domain_self_convert      -> "confirm_self_convert" / "skip"

Some emitted moves may be speculative (e.g. "skip" on a prompt that disallows
it); the engine ignores those harmlessly and the driver just tries the next
candidate, failing loudly only when no candidate progresses the game.
"""

from bots.legal_moves import enumerate_actions as _enumerate_actions

_OWNED_CARD_PLAIN_CHOOSE_KINDS = {"special_payout_choose"}

# ---------------------------------------------------------------------------
# Standard actions (hire / build / slay / take): re-implemented with the
# engine's true effective costs. The upstream enumerator pays printed costs,
# which the engine rejects once duplicate-name surcharges, role prerequisites,
# exact-payment and wild-magic rules kick in — under random play that starves
# stack depletion and games stop terminating.
# ---------------------------------------------------------------------------


def _player_flag(player, flag):
    """Mirror Game._player_has_action_effect_flag for wire/view player data."""
    for g in player.get("granted_effects") or []:
        if str(g or "").strip().lower() == flag:
            return True
    for d in player.get("owned_domains") or []:
        if d.get("is_flipped"):
            continue
        effect = str(d.get("passive_effect") or "").strip().lower()
        if effect == flag or (effect.startswith("effect.add ") and effect[len("effect.add "):].strip() == flag):
            return True
    return False


def _gold_magic_payment(gold, magic, cost):
    """Engine-exact payment for a gold cost with magic wild: total == cost,
    >=1 gold whenever magic is used. Returns payment dict or None."""
    if cost <= 0:
        return {"gold": 0, "strength": 0, "magic": 0}
    gp = min(gold, cost)
    mp = cost - gp
    if mp > 0 and (gp < 1 or mp > magic):
        return None
    return {"gold": gp, "strength": 0, "magic": mp}


def _all_grid_tops(state, grids):
    for grid_name in grids:
        for stack in state.get(grid_name) or []:
            if isinstance(stack, list) and stack:
                top = stack[-1]
                if top and top.get("is_accessible"):
                    yield top


def _enumerate_standard(state, player_id):
    me = None
    for p in state.get("player_list") or []:
        if p.get("player_id") == player_id:
            me = p
            break
    if me is None:
        return []
    gold = int(me.get("gold_score") or 0)
    strength = int(me.get("strength_score") or 0)
    magic = int(me.get("magic_score") or 0)
    moves = []

    resources = ["gold", "strength", "magic"]
    if (state.get("preset") or "") == "crimsonseas":
        resources.append("map")
    for resource in resources:
        moves.append({"player_id": player_id, "action_type": "take_resource", "resource": resource})

    has_emerald = _player_flag(me, "action.emeraldstronghold")
    has_defiant = _player_flag(me, "action.defiantridge")
    has_pratchett = _player_flag(me, "action.pratchettsplateau")
    has_blessed = _player_flag(me, "action.blessedlands")
    has_fortskyler = _player_flag(me, "action.fortskyler")
    has_darklord = _player_flag(me, "action.darklordrising")

    owned_names = [
        c.get("name") for c in me.get("owned_citizens") or [] if not c.get("is_flipped")
    ] + [s.get("name") for s in me.get("owned_starters") or []]

    # King's Guard event can drop hirable citizens on any grid; engine scans all.
    for top in _all_grid_tops(state, ("citizen_grid", "monster_grid", "domain_grid")):
        cid = top.get("citizen_id")
        if cid is None:
            continue
        cost = int(top.get("gold_cost") or 0)
        if not has_emerald:
            cost += sum(1 for n in owned_names if n == top.get("name"))
        if has_defiant:
            cost = max(0, cost - 1)
        pay = _gold_magic_payment(gold, magic, cost)
        if pay is not None:
            moves.append({
                "player_id": player_id, "action_type": "hire_citizen",
                "citizen_id": cid, "payment": pay,
            })

    role_have = {"shadow": 0, "holy": 0, "soldier": 0, "worker": 0}
    for c in list(me.get("owned_citizens") or []) + list(me.get("owned_nobles") or []):
        for role in role_have:
            role_have[role] += int(c.get(f"{role}_count") or 0)

    for stack in state.get("domain_grid") or []:
        if not (isinstance(stack, list) and stack):
            continue
        top = stack[-1]
        if not top or not top.get("is_accessible") or not top.get("is_visible", True):
            continue
        did = top.get("domain_id")
        if did is None:
            continue
        if any(role_have[r] < int(top.get(f"{r}_count") or 0) for r in role_have):
            continue
        cost = int(top.get("gold_cost") or 0)
        if has_pratchett:
            cost = max(0, cost - 1)
        # Blessed Lands discount is event-scaled and not derivable from the
        # snapshot; probe plausible discounts (rejected variants are skipped).
        costs = {cost}
        if has_blessed:
            costs.update(max(0, cost - d) for d in (1, 2, 3))
        for c in sorted(costs, reverse=True):
            pay = _gold_magic_payment(gold, magic, c)
            if pay is not None:
                moves.append({
                    "player_id": player_id, "action_type": "build_domain",
                    "domain_id": did, "payment": pay,
                })

    for top in _all_grid_tops(state, ("monster_grid", "citizen_grid", "domain_grid")):
        is_event = top.get("event_id") is not None
        if not is_event and top.get("monster_id") is None:
            continue
        s_cost = int(top.get("strength_cost") or 0) + int(top.get("extra_strength_cost") or 0)
        m_cost = int(top.get("magic_cost") or 0) + int(top.get("extra_magic_cost") or 0)
        g_cost = int(top.get("extra_gold_cost") or 0)
        if top.get("has_special_cost"):
            continue  # player-dependent delta we can't compute from snapshot
        if has_fortskyler:
            s_cost = max(0, s_cost - 1)
        m_costs = [m_cost] + ([m_cost + 1, m_cost + 2] if has_darklord else [])
        for mc in m_costs:
            if gold < g_cost or strength < s_cost or magic < mc:
                continue
            move = {
                "player_id": player_id, "action_type": "slay_monster",
                "payment": {"gold": g_cost, "strength": s_cost, "magic": mc},
            }
            if is_event:
                move["event_id"] = top.get("event_id")
            else:
                move["monster_id"] = top.get("monster_id")
            moves.append(move)

    return moves


def _act(player_id, action_string):
    return {
        "player_id": player_id,
        "action_type": "act_on_required_action",
        "action": action_string,
    }


def _player_scores(state, player_id):
    for p in state.get("player_list") or []:
        if p.get("player_id") == player_id:
            return (
                int(p.get("gold_score") or 0),
                int(p.get("strength_score") or 0),
                int(p.get("magic_score") or 0),
            )
    return (0, 0, 0)


def parse_roll_modifiers(me):
    """Owned roll.set_one_die modifiers -> [(domain_id, kind, value, gold_cost)].

    Grammar (sql/seed/domains.sql): `roll.set_one_die target=N cost=g:X`,
    `... target=N cost=g_per_owned_role:holy_citizen`, `... subtract=1` (free).
    """
    mods = []
    role_counts = None
    for d in me.get("owned_domains") or []:
        if d.get("is_flipped"):
            continue
        effect = str(d.get("passive_effect") or "").strip()
        if not effect.startswith("roll.set_one_die"):
            continue
        kv = dict(tok.split("=", 1) for tok in effect.split()[1:] if "=" in tok)
        cost_spec = (kv.get("cost") or "").strip()
        cost = 0
        if cost_spec.startswith("g:"):
            cost = int(cost_spec[2:])
        elif cost_spec.startswith("g_per_owned_role:"):
            role = cost_spec.split(":", 1)[1].replace("_citizen", "")
            if role_counts is None:
                role_counts = {}
                for c in me.get("owned_citizens") or []:
                    if c.get("is_flipped"):
                        continue
                    for r in ("shadow", "holy", "soldier", "worker"):
                        role_counts[r] = role_counts.get(r, 0) + int(c.get(f"{r}_count") or 0)
            cost = role_counts.get(role, 0)
        if "target" in kv:
            mods.append((d.get("domain_id"), "target", int(kv["target"]), cost))
        elif "subtract" in kv:
            mods.append((d.get("domain_id"), "subtract", int(kv["subtract"]), cost))
    return mods


def _enumerate_finalize_roll(state, player_id, me):
    pr = state.get("pending_roll") or {}
    r1 = int(pr.get("rolled_die_one") or 0)
    r2 = int(pr.get("rolled_die_two") or 0)
    keep = {"player_id": player_id, "action_type": "finalize_roll"}
    if not (1 <= r1 <= 6 and 1 <= r2 <= 6):
        return [keep]
    gold = int(me.get("gold_score") or 0)
    mods = parse_roll_modifiers(me)
    if not mods:
        return [keep]

    def modified(rolled, kind, value):
        fd = value if kind == "target" else rolled - value
        return fd if 1 <= fd <= 6 and fd != rolled else None

    seen = {(r1, r2)}
    moves = [keep]

    def add(fd1, fd2, cost):
        if (fd1, fd2) in seen or cost > gold:
            return
        seen.add((fd1, fd2))
        moves.append({
            "player_id": player_id, "action_type": "finalize_roll",
            "die_one": fd1, "die_two": fd2, "_mod_cost_gold": cost,
        })

    for did_a, kind_a, val_a, cost_a in mods:
        f1 = modified(r1, kind_a, val_a)
        f2 = modified(r2, kind_a, val_a)
        if f1 is not None:
            add(f1, r2, cost_a)
        if f2 is not None:
            add(r1, f2, cost_a)
        # two modifiers: different dice, different source domains
        for did_b, kind_b, val_b, cost_b in mods:
            if did_b == did_a:
                continue
            g2 = modified(r2, kind_b, val_b)
            if f1 is not None and g2 is not None:
                add(f1, g2, cost_a + cost_b)
    return moves


def enumerate_moves(state, player_id):
    req = state.get("action_required") or {}
    action = (req.get("action") or "").strip()
    prc = state.get("pending_required_choice") or {}
    if req.get("id") != player_id:
        return _enumerate_actions(state, player_id)

    if action == "finalize_roll":
        for p in state.get("player_list") or []:
            if p.get("player_id") == player_id:
                return _enumerate_finalize_roll(state, player_id, p)
        return [{"player_id": player_id, "action_type": "finalize_roll"}]

    if (
        action == "standard_action"
        and (state.get("phase") or "").strip() == "action"
        and int(state.get("actions_remaining") or 0) > 0
        and player_id not in ((state.get("concurrent_action") or {}).get("pending") or [])
    ):
        return _enumerate_standard(state, player_id)

    options = prc.get("options") or []
    kind = (prc.get("kind") or "").strip()

    if action == "choose_player":
        moves = [_act(player_id, f"choose_player {i + 1}") for i in range(len(options))]
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "choose_owned_card":
        if kind in _OWNED_CARD_PLAIN_CHOOSE_KINDS:
            moves = [_act(player_id, f"choose {i + 1}") for i in range(len(options))]
        elif kind == "domain_return_owned":
            # Two stages share this action name; probe both verb forms.
            moves = [_act(player_id, f"choose_owned_card {i + 1}") for i in range(len(options))]
            moves += [_act(player_id, f"choose {i + 1}") for i in range(len(options))]
        else:
            moves = [_act(player_id, f"choose_owned_card {i + 1}") for i in range(len(options))]
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "choose_domain_reward":
        moves = [_act(player_id, f"grant_domain {i + 1}") for i in range(len(options))]
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "choose_domain_to_build":
        moves = [_act(player_id, f"build_domain_pick {i + 1}") for i in range(len(options))]
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "build_domain_payment":
        # Magic is a wild for the gold cost; offer gold-first and all-magic.
        gold, _, magic = _player_scores(state, player_id)
        cost = int(prc.get("gold_cost") or 0)
        moves = []
        gp = min(gold, cost)
        if gp + magic >= cost:
            moves.append(_act(player_id, f"build_pay {gp} {cost - gp}"))
        if cost <= magic:
            moves.append(_act(player_id, f"build_pay 0 {cost}"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "slay_monster_payment" and kind == "immediate_slay":
        gold, strength, magic = _player_scores(state, player_id)
        gc = int(prc.get("gold_cost") or 0)
        sc = int(prc.get("strength_cost") or 0)
        mc = int(prc.get("magic_cost") or 0)
        moves = []
        if gold >= gc and strength >= sc and magic >= mc:
            moves.append(_act(player_id, f"slay_pay {gc} {sc} {mc}"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "harvest_wild_gain_exchange":
        moves = [_act(player_id, f"wild_gain_resource {r}") for r in ("g", "s", "m")]
        moves.append(_act(player_id, "skip_harvest_exchange"))
        return moves

    if action == "harvest_wild_cost_exchange":
        cost_options = prc.get("cost_options") or []
        moves = [
            _act(player_id, f"wild_cost_resource {o['resource']}")
            for o in cost_options
            if o.get("resource")
        ]
        moves.append(_act(player_id, "skip_harvest_exchange"))
        return moves

    if action == "choose_monster_strength":
        return [_act(player_id, f"choose_monster {i + 1}") for i in range(len(options))]

    if action == "domain_choose_resource":
        choices = prc.get("choices") or []
        return [_act(player_id, f"choose {i + 1}") for i in range(len(choices))]

    if action == "domain_self_convert":
        return [_act(player_id, "confirm_self_convert"), _act(player_id, "skip")]

    if action == "event_sequence" and (prc.get("verb") or "") == "place_reserve_monster":
        # Engine wants "place <monster|citizen|domain> <idx>" from
        # placement_options (upstream emits numeric grid indexes, rejected).
        return [
            _act(player_id, f"place {t['grid']} {t['idx']}")
            for t in prc.get("placement_options") or []
        ]

    return _enumerate_actions(state, player_id)
