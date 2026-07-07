"""Enumerate legal moves from a game-state snapshot (checkpoint-1 client-side)."""

RESOURCES = ("gold", "strength", "magic", "map")

BINARY_PROMPTS = frozenset({
    "domain_self_convert",
    "may_sail",
    "may_recruit",
    "harvest_optional_exchange",
    "harvest_wild_cost_exchange",
    "event_gain_action",
})

CHOOSE_N_PROMPTS = frozenset({
    "choose_domain_to_build",
    "choose_domain_reward",
    "choose_owned_card",
    "choose_player",
    "choose_monster_strength",
    "event_active_choose",
})

CHOOSE_MONSTER_SLAY_PREFIX = "choose_monster_slay"


def _player_by_id(state, player_id):
    for p in state.get("player_list") or []:
        if p.get("player_id") == player_id:
            return p
    return None


def _top_of_stack(stack):
    if not isinstance(stack, list) or not stack:
        return None
    return stack[-1]


def _accessible_grid_tops(grid):
    tops = []
    if not isinstance(grid, list):
        return tops
    for stack in grid:
        top = _top_of_stack(stack)
        if top and top.get("is_accessible"):
            tops.append(top)
    return tops


def _act(player_id, action_string):
    return {
        "player_id": player_id,
        "action_type": "act_on_required_action",
        "action": action_string,
    }


def _concurrent(player_id, kind, response):
    move = {
        "player_id": player_id,
        "action_type": "submit_concurrent_action",
        "response": response,
    }
    if kind:
        move["kind"] = kind
    return move


def _enumerate_concurrent(state, player_id):
    ca = state.get("concurrent_action") or {}
    pending = ca.get("pending") or []
    if player_id not in pending:
        return []
    kind = (ca.get("kind") or "").strip()
    moves = []

    if kind == "choose_duke":
        me = _player_by_id(state, player_id)
        if me:
            for d in me.get("owned_dukes") or []:
                did = d.get("duke_id")
                if did:
                    moves.append(_concurrent(player_id, kind, str(did)))
        return moves

    if kind == "choose_relic":
        me = _player_by_id(state, player_id)
        if me:
            for r in me.get("owned_relics") or []:
                rid = r.get("relic_id")
                if rid:
                    moves.append(_concurrent(player_id, kind, str(rid)))
        return moves

    if kind == "flip_one_citizen":
        me = _player_by_id(state, player_id)
        if me:
            for i, c in enumerate(me.get("owned_citizens") or []):
                if not c.get("is_flipped"):
                    moves.append(_concurrent(player_id, kind, str(i)))
        return moves

    if kind == "harvest_choices":
        data = ca.get("data") or {}
        prompts = data.get("prompts") or {}
        my_prompts = prompts.get(player_id) or prompts.get(str(player_id)) or []
        if not isinstance(my_prompts, list):
            my_prompts = [my_prompts]
        for prompt in my_prompts:
            if not isinstance(prompt, dict):
                continue
            pid = prompt.get("id")
            if not pid:
                continue
            prefix = f"{pid}|"
            sub = (prompt.get("sub_kind") or "").strip()
            prc = prompt.get("pending_required_choice") or {}
            if sub == "harvest_optional_exchange":
                moves.append(_concurrent(player_id, kind, prefix + "confirm_harvest_exchange"))
                moves.append(_concurrent(player_id, kind, prefix + "skip_harvest_exchange"))
            elif sub == "harvest_wild_cost_exchange":
                for opt in prc.get("cost_options") or []:
                    r = (opt.get("resource") or "").lower()
                    if r:
                        moves.append(_concurrent(player_id, kind, prefix + f"wild_cost_resource {r}"))
                moves.append(_concurrent(player_id, kind, prefix + "skip_harvest_exchange"))
            elif sub == "harvest_wild_gain_exchange":
                for r in ("g", "s", "m"):
                    moves.append(_concurrent(player_id, kind, prefix + f"wild_gain_resource {r}"))
                moves.append(_concurrent(player_id, kind, prefix + "skip_harvest_exchange"))
            elif sub == "bonus_resource_choice":
                for r in ("gold", "strength", "magic"):
                    moves.append(_concurrent(player_id, kind, prefix + r))
            elif sub == "harvest_choose":
                options = prc.get("options") or []
                for i in range(len(options)):
                    moves.append(_concurrent(player_id, kind, prefix + f"choose {i + 1}"))
            else:
                moves.append(_concurrent(player_id, kind, prefix + "accept"))
                moves.append(_concurrent(player_id, kind, prefix + "skip"))
        if not moves and not my_prompts:
            return []
        return moves

    if kind == "event_self_convert":
        data = ca.get("data") or {}
        pay_kind = (data.get("pay_kind") or "").lower()
        moves.append(_concurrent(player_id, kind, "skip"))
        if pay_kind == "wild":
            for r in ("g", "s", "m"):
                moves.append(_concurrent(player_id, kind, r))
        else:
            moves.append(_concurrent(player_id, kind, "accept"))
        return moves

    if kind == "event_banish_citizen_for_reward":
        me = _player_by_id(state, player_id)
        moves.append(_concurrent(player_id, kind, "skip"))
        if me:
            for i, c in enumerate(me.get("owned_citizens") or []):
                moves.append(_concurrent(player_id, kind, str(i)))
        return moves

    moves.append(_concurrent(player_id, kind, "skip"))
    return moves


def _enumerate_required_prompt(state, player_id):
    req = state.get("action_required") or {}
    if req.get("id") != player_id:
        return []
    action = (req.get("action") or "").strip()
    if action == "standard_action":
        return []

    prc = state.get("pending_required_choice") or {}
    moves = []

    if action == "finalize_roll":
        moves.append({
            "player_id": player_id,
            "action_type": "finalize_roll",
        })
        return moves

    if action == "event_slay_cost_choice":
        return _enumerate_event_slay_cost(state, player_id)

    if action.startswith(CHOOSE_MONSTER_SLAY_PREFIX) or action == "choose_monster_slay":
        options = prc.get("options") or []
        for i in range(len(options)):
            moves.append(_act(player_id, f"choose_monster_slay {i + 1}"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action in BINARY_PROMPTS:
        moves.append(_act(player_id, "accept"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "slay_monster_payment" or action == "build_domain_payment":
        moves.append(_act(player_id, "pay"))
        return moves

    if action == "domain_choose_resource":
        for r in ("g", "s", "m", "v"):
            moves.append(_act(player_id, r))
        return moves

    if action == "relic_wild_exchange":
        stage = (prc.get("stage") or "").lower()
        if stage == "pay":
            for r in ("g", "s", "m"):
                moves.append(_act(player_id, f"relic_pay {r}"))
        elif stage == "gain":
            for r in ("g", "s", "m"):
                moves.append(_act(player_id, f"relic_gain {r}"))
        else:
            moves.append(_act(player_id, "relic_pay g"))
            moves.append(_act(player_id, "relic_gain g"))
        return moves

    if action == "manual_harvest":
        for slot in state.get("harvest_prompt_slots") or []:
            sk = (slot.get("slot_key") or "").strip()
            if sk:
                moves.append({
                    "player_id": player_id,
                    "action_type": "harvest_card",
                    "harvest_slot_key": sk,
                })
        return moves

    if action == "exekratys_offering":
        for opt in prc.get("options") or []:
            res = (opt.get("resource") or "").strip()
            if res:
                moves.append(_act(player_id, f"exekratys_offering {res}"))
        return moves

    if action == "bonus_resource_choice":
        for r in ("gold", "strength", "magic"):
            moves.append(_act(player_id, r))
        return moves

    if action == "harvest_steal":
        stage = (prc.get("stage") or "victim").lower()
        if stage == "victim":
            for i in range(len(prc.get("victim_options") or [])):
                moves.append(_act(player_id, f"steal_victim {i + 1}"))
        elif stage == "resource":
            for i in range(len(prc.get("resource_options") or [])):
                moves.append(_act(player_id, f"steal_resource {i + 1}"))
        return moves

    if action == "harvest_wild_gain_exchange":
        options = prc.get("options") or prc.get("gain_options") or []
        n = max(len(options), 3)
        for i in range(n):
            moves.append(_act(player_id, f"choose {i + 1}"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action in CHOOSE_N_PROMPTS or action.startswith("choose "):
        options = prc.get("options") or []
        for i in range(len(options)):
            moves.append(_act(player_id, f"choose {i + 1}"))
        if action == "choose_owned_card" or "skip" in (prc.get("kind") or ""):
            moves.append(_act(player_id, "skip"))
        return moves

    if action == "event_sequence":
        verb = (prc.get("verb") or "").strip()
        if verb == "pay_to_chosen":
            for p in state.get("player_list") or []:
                pid = p.get("player_id")
                if pid and pid != player_id:
                    for r in ("g", "s", "m"):
                        moves.append(_act(player_id, f"pay {r} {pid}"))
        elif verb == "banish_center_citizen":
            for i in range(len(state.get("citizen_grid") or [])):
                moves.append(_act(player_id, str(i)))
        elif verb == "banish_owned_citizen":
            me = _player_by_id(state, player_id)
            if me:
                for i in range(len(me.get("owned_citizens") or [])):
                    moves.append(_act(player_id, str(i)))
            moves.append(_act(player_id, "skip"))
        elif verb == "place_reserve_monster":
            for gi in range(len(state.get("monster_grid") or [])):
                moves.append(_act(player_id, f"place {gi} 0"))
        return moves

    options = prc.get("options") or []
    if options:
        for i, opt in enumerate(options):
            if isinstance(opt, dict):
                if opt.get("stack_index") is not None:
                    moves.append(_act(player_id, str(opt["stack_index"])))
                elif opt.get("index") is not None:
                    moves.append(_act(player_id, str(opt["index"])))
                else:
                    moves.append(_act(player_id, f"choose {i + 1}"))
            else:
                moves.append(_act(player_id, f"choose {i + 1}"))
        if prc.get("optional"):
            moves.append(_act(player_id, "skip"))
        return moves

    moves.append(_act(player_id, "skip"))
    return moves


def _enumerate_event_slay_cost(state, player_id):
    pesc = state.get("pending_event_slay_cost") or {}
    if pesc.get("player_id") and pesc.get("player_id") != player_id:
        return []
    req = state.get("action_required") or {}
    if req.get("id") != player_id:
        return []
    moves = []
    for top in _accessible_grid_tops(state.get("monster_grid")):
        body = {"player_id": player_id, "_route": "apply_event_slay_cost"}
        if top.get("event_id") is not None:
            body["event_id"] = top["event_id"]
        elif top.get("monster_id") is not None:
            body["monster_id"] = top["monster_id"]
        else:
            continue
        moves.append(body)
    return moves


def _simple_payment(player, gold=0, strength=0, magic=0):
    g = int(player.get("gold_score") or 0)
    s = int(player.get("strength_score") or 0)
    m = int(player.get("magic_score") or 0)
    if gold > g or strength > s or magic > m:
        return None
    return {"gold": gold, "strength": strength, "magic": magic}


def _enumerate_standard_actions(state, player_id):
    phase = (state.get("phase") or "").strip()
    req = state.get("action_required") or {}
    if phase != "action":
        return []
    if req.get("id") != player_id:
        return []
    if (req.get("action") or "").strip() != "standard_action":
        return []
    if int(state.get("actions_remaining") or 0) <= 0:
        return []

    moves = []
    for resource in RESOURCES:
        moves.append({
            "player_id": player_id,
            "action_type": "take_resource",
            "resource": resource,
        })

    me = _player_by_id(state, player_id)
    if not me:
        return moves

    for top in _accessible_grid_tops(state.get("citizen_grid")):
        cid = top.get("citizen_id")
        if cid is None:
            continue
        cost = int(top.get("gold_cost") or 0)
        pay = _simple_payment(me, gold=cost)
        if pay:
            moves.append({
                "player_id": player_id,
                "action_type": "hire_citizen",
                "citizen_id": cid,
                "payment": pay,
            })

    for top in _accessible_grid_tops(state.get("domain_grid")):
        if not top.get("is_visible"):
            continue
        did = top.get("domain_id")
        if did is None:
            continue
        cost = int(top.get("gold_cost") or 0)
        pay = _simple_payment(me, gold=cost)
        if pay:
            moves.append({
                "player_id": player_id,
                "action_type": "build_domain",
                "domain_id": did,
                "payment": pay,
            })

    for top in _accessible_grid_tops(state.get("monster_grid")):
        if top.get("event_id") is not None:
            eid = top.get("event_id")
            strength = int(top.get("strength_cost") or 0) + int(top.get("extra_strength_cost") or 0)
            magic = int(top.get("magic_cost") or 0) + int(top.get("extra_magic_cost") or 0)
            gold = int(top.get("extra_gold_cost") or 0)
            pay = _simple_payment(me, gold=gold, strength=strength, magic=magic)
            if pay:
                moves.append({
                    "player_id": player_id,
                    "action_type": "slay_monster",
                    "event_id": eid,
                    "payment": pay,
                })
        elif top.get("monster_id") is not None:
            mid = top.get("monster_id")
            strength = int(top.get("strength_cost") or 0) + int(top.get("extra_strength_cost") or 0)
            magic = int(top.get("magic_cost") or 0) + int(top.get("extra_magic_cost") or 0)
            gold = int(top.get("extra_gold_cost") or 0)
            pay = _simple_payment(me, gold=gold, strength=strength, magic=magic)
            if pay:
                moves.append({
                    "player_id": player_id,
                    "action_type": "slay_monster",
                    "monster_id": mid,
                    "payment": pay,
                })

    return moves


def enumerate_actions(state, player_id):
    """Return POST-ready move dicts in API decision-loop priority order."""
    if not state or not player_id:
        return []
    if (state.get("phase") or "").strip() == "game_over":
        return []

    ca = state.get("concurrent_action") or {}
    if player_id in (ca.get("pending") or []):
        return _enumerate_concurrent(state, player_id)

    moves = _enumerate_required_prompt(state, player_id)
    if moves:
        return moves

    pesc = state.get("pending_event_slay_cost") or {}
    if pesc and (not pesc.get("player_id") or pesc.get("player_id") == player_id):
        req = state.get("action_required") or {}
        if req.get("id") == player_id and req.get("action") == "event_slay_cost_choice":
            moves = _enumerate_event_slay_cost(state, player_id)
            if moves:
                return moves

    return _enumerate_standard_actions(state, player_id)
