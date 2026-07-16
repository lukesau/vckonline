"""Canonical legal-move enumeration.

Single source of truth for "what moves may this player make right now?".
It operates on a serialized game-state dict (the same wire shape the server
returns from `/api/game/{id}/state` and that `GameObjectEncoder` produces), so
it can be called three ways without divergence:

- server-side, to attach `legal_moves` onto the state payload (so no client has
  to reimplement this),
- by the headless simulator (`engines.headless`), which serializes a live
  `Game` and enumerates the acting player's moves,
- by any external bot that only has a state snapshot.

Each returned move is a POST-ready dict in the same shape the server's
`/action` route consumes; `engines.headless.apply_move` applies the identical
dicts directly to an in-process `Game`.
"""

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

    if action == "slay_monster_payment":
        # immediate_slay "may slay a Monster" pay stage: wants "slay_pay g s m".
        g = int(prc.get("gold_cost") or 0)
        s = int(prc.get("strength_cost") or 0)
        m = int(prc.get("magic_cost") or 0)
        moves.append(_act(player_id, f"slay_pay {g} {s} {m}"))
        moves.append(_act(player_id, "skip"))
        return moves

    if action == "build_domain_payment":
        # domain_build_opportunity pay stage (Ararmartin Ridge): wants "build_pay g m".
        g = int(prc.get("gold_cost") or 0)
        moves.append(_act(player_id, f"build_pay {g} 0"))
        moves.append(_act(player_id, "skip"))
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
        # Some handlers accept the generic "choose N"; others (e.g. the
        # steal_citizen legs of choose_player / choose_owned_card) require the
        # required-action verb as a prefix ("choose_player N"). Emit both forms
        # for named prompts so whichever the engine expects is available; the
        # headless progress guard skips the inert one.
        qualified = action if action in CHOOSE_N_PROMPTS else None
        for i in range(len(options)):
            moves.append(_act(player_id, f"choose {i + 1}"))
            if qualified:
                moves.append(_act(player_id, f"{qualified} {i + 1}"))
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


def _owned_same_name_count(player, name):
    """Count non-flipped owned citizens + starters sharing a name.

    Hiring a citizen you already own costs +1 gold per matching copy (the
    duplicate surcharge). This is engine rules (`player_actions.hire_citizen`);
    the enumerator must charge it so the emitted payment is actually legal.
    Effect-flag waivers (Emerald Stronghold, Defiant Ridge, New Shilina Tower)
    are not modeled here; `headless.apply_move` rolls back and the caller retries
    if a rare mismatch slips through.
    """
    if not name:
        return 0
    n = 0
    for c in player.get("owned_citizens") or []:
        if c.get("is_flipped"):
            continue
        if c.get("name") == name:
            n += 1
    for s in player.get("owned_starters") or []:
        if s.get("name") == name:
            n += 1
    return n


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
    # The engine only lets the true turn player act (consume_player_action gates
    # on current_player_id). action_required.id can lag behind between turns, so
    # trust active_player_id to avoid emitting standard actions the engine will
    # reject with "Not your turn".
    active = state.get("active_player_id")
    if active is not None and str(active) != str(player_id):
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
        if top.get("effective_hire_cost") is not None:
            cost = int(top["effective_hire_cost"])
        else:
            cost = int(top.get("gold_cost") or 0) + _owned_same_name_count(me, top.get("name"))
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
        if top.get("effective_build_cost") is not None:
            cost = int(top["effective_build_cost"])
        else:
            cost = int(top.get("gold_cost") or 0)
        pay = _simple_payment(me, gold=cost)
        if pay:
            moves.append({
                "player_id": player_id,
                "action_type": "build_domain",
                "domain_id": did,
                "payment": pay,
            })

    def _slay_costs(top):
        if top.get("effective_slay_strength") is not None:
            return (
                int(top.get("effective_slay_strength") or 0),
                int(top.get("effective_slay_magic") or 0),
                int(top.get("effective_slay_gold") or 0),
            )
        strength = int(top.get("strength_cost") or 0) + int(top.get("extra_strength_cost") or 0)
        magic = int(top.get("magic_cost") or 0) + int(top.get("extra_magic_cost") or 0)
        gold = int(top.get("extra_gold_cost") or 0)
        return strength, magic, gold

    for top in _accessible_grid_tops(state.get("monster_grid")):
        if top.get("event_id") is not None:
            eid = top.get("event_id")
            strength, magic, gold = _slay_costs(top)
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
            strength, magic, gold = _slay_costs(top)
            pay = _simple_payment(me, gold=gold, strength=strength, magic=magic)
            if pay:
                moves.append({
                    "player_id": player_id,
                    "action_type": "slay_monster",
                    "monster_id": mid,
                    "payment": pay,
                })

    return moves


def annotate_effective_costs(game, state, player_id):
    """Stamp per-player effective action costs onto a serialized `state`.

    Writes new `effective_*` fields onto each accessible grid top by calling the
    engine's own cost helpers (`player_actions.hire_cost/build_cost/slay_cost`),
    so `enumerate_actions` emits payments that exactly match what the engine will
    charge — including the duplicate-hire surcharge, Blessed Lands / Dark Lord
    Rising, monster special-cost scaling, etc.

    Existing cost fields (`gold_cost`, `strength_cost`, ...) are left untouched so
    the web client's display logic is unaffected; only additive `effective_*`
    fields are added. Costs are computed from the live `game`, so they do not
    depend on any prior in-dict cost baking.
    """
    player = None
    for p in getattr(game, "player_list", []) or []:
        if str(getattr(p, "player_id", None)) == str(player_id):
            player = p
            break
    if player is None:
        return state

    pa = game.player_actions

    def _live_tops(grid):
        tops = []
        for stack in grid or []:
            if stack:
                tops.append(stack[-1])
            else:
                tops.append(None)
        return tops

    def _bake(grid_key, live_grid, fn):
        state_grid = state.get(grid_key) or []
        live_tops = _live_tops(live_grid)
        for i, stack in enumerate(state_grid):
            if not isinstance(stack, list) or not stack:
                continue
            top = stack[-1]
            if not isinstance(top, dict) or not top.get("is_accessible"):
                continue
            if i >= len(live_tops) or live_tops[i] is None:
                continue
            fn(top, live_tops[i])

    def _bake_citizen(top, live):
        if getattr(live, "citizen_id", None) is None:
            return
        cost, allow_strength = pa.hire_cost(player, live)
        top["effective_hire_cost"] = int(cost)
        top["effective_hire_allow_strength"] = bool(allow_strength)

    def _bake_domain(top, live):
        if getattr(live, "domain_id", None) is None:
            return
        top["effective_build_cost"] = int(pa.build_cost(player, live))

    def _bake_monster(top, live):
        if getattr(live, "monster_id", None) is None and getattr(live, "event_id", None) is None:
            return
        s, m, g = pa.slay_cost(player, live)
        top["effective_slay_strength"] = int(s)
        top["effective_slay_magic"] = int(m)
        top["effective_slay_gold"] = int(g)

    _bake("citizen_grid", getattr(game, "citizen_grid", None), _bake_citizen)
    _bake("domain_grid", getattr(game, "domain_grid", None), _bake_domain)
    _bake("monster_grid", getattr(game, "monster_grid", None), _bake_monster)
    # Citizens (King's Guard) and monsters (Undead Samurai) can appear on other
    # grids; bake those surfaces too so their costs are correct if hirable/slayable.
    _bake("monster_grid", getattr(game, "monster_grid", None), _bake_citizen)
    _bake("citizen_grid", getattr(game, "citizen_grid", None), _bake_monster)
    return state


def enumerate_actions(state, player_id):
    """Return POST-ready move dicts in API decision-loop priority order.

    Costs come from `effective_*` fields when present (stamped by
    `annotate_effective_costs`); otherwise it falls back to the raw card cost
    fields plus a best-effort duplicate-hire surcharge estimate.
    """
    if not state or not player_id:
        return []
    if (state.get("phase") or "").strip() == "game_over":
        return []

    ca = state.get("concurrent_action") or {}
    ca_pending = ca.get("pending") or []
    if ca_pending:
        # While a concurrent (non-ordered) gate is open the engine blocks every
        # other action for everyone (is_blocked_on_concurrent_action). Only the
        # participants can act; anyone else must wait.
        if player_id in ca_pending:
            return _enumerate_concurrent(state, player_id)
        return []

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
