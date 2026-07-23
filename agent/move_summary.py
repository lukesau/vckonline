"""Human-readable decision summaries for greedy and MCTS policies."""

import json

RES_LABELS = {"g": "gold", "s": "strength", "m": "magic", "v": "VP", "p": "maps"}


def move_key(move):
    return json.dumps(move, sort_keys=True, default=str)


def _find_top(grid, id_attr, card_id):
    for stack in grid or []:
        if stack and getattr(stack[-1], id_attr, None) == card_id:
            return stack[-1]
    return None


def _payment_suffix(move):
    pay = move.get("payment") or {}
    parts = []
    for key, label in (("gold", "g"), ("strength", "s"), ("magic", "m")):
        n = int(pay.get(key) or 0)
        if n:
            parts.append(f"{n}{label}")
    if not parts:
        return ""
    return " (" + " ".join(parts) + ")"


# ---- prompt-answer naming --------------------------------------------------
#
# Prompt moves are wire verbs like "choose 2" or a bare owned-citizen index;
# with the live game we can resolve what the number refers to and say
# "choose 2 gold" / "banish Peasant" instead. Every resolver degrades to the
# raw verb string when the game context is missing or doesn't match.

def _player_by_id(game, pid):
    for p in getattr(game, "player_list", None) or []:
        if str(getattr(p, "player_id", "")) == str(pid):
            return p
    return None


def _res_word(token):
    token = (token or "").strip().lower()
    if not token:
        return ""
    return RES_LABELS.get(token[0], token)


def _card_name(card, fallback):
    name = getattr(card, "name", None) if card is not None else None
    return str(name) if name else fallback


def _option_label(opt):
    if isinstance(opt, dict):
        for k in ("name", "victim_name", "player_name", "monster_name", "label", "text"):
            v = opt.get(k)
            if v:
                return str(v)
        if opt.get("resource"):
            amount = opt.get("amount")
            res = _res_word(str(opt["resource"]))
            return f"{amount} {res}" if amount else res
        return None
    if isinstance(opt, (list, tuple)) and len(opt) == 2:
        return f"{opt[1]} {_res_word(str(opt[0]))}"
    if opt is None:
        return None
    return str(opt)


def _pay_words(gold, strength, magic):
    parts = []
    if gold:
        parts.append(f"{gold} gold")
    if strength:
        parts.append(f"{strength} strength")
    if magic:
        parts.append(f"{magic} magic")
    return " + ".join(parts) if parts else "nothing"


_INDEXED_VERBS = {
    "choose": "choose",
    "build_domain_pick": "build",
    "grant_domain": "choose",
    "choose_monster": "choose",
    "choose_monster_slay": "slay",
    "choose_player": "choose",
    "choose_owned_card": "choose",
}


def _describe_action_string(action, game, mover_id, prc=None):
    """Human phrasing for a prompt verb string, or None to keep the raw form."""
    if game is None or not action:
        return None
    if prc is None:
        prc = getattr(game, "pending_required_choice", None)
    prc = prc if isinstance(prc, dict) else {}
    req = getattr(game, "action_required", None) or {}
    ctx = str(req.get("action") or "").strip() if isinstance(req, dict) else ""
    toks = action.split()
    verb = toks[0]

    if action in ("accept", "skip") and ctx and ctx != "standard_action":
        return f"{action} ({ctx.replace('_', ' ')})"
    if verb == "skip_harvest_exchange":
        return "skip exchange"
    if verb == "confirm_harvest_exchange":
        return "confirm exchange"
    if verb in ("wild_cost_resource", "relic_pay") and len(toks) == 2:
        return f"pay 1 {_res_word(toks[1])}"
    if verb in ("wild_gain_resource", "relic_gain") and len(toks) == 2:
        return f"gain 1 {_res_word(toks[1])}"
    if verb == "exekratys_offering" and len(toks) == 2:
        return f"offer {_res_word(toks[1])}"
    if verb == "pay" and len(toks) == 3:
        target = _player_by_id(game, toks[2])
        target_name = getattr(target, "name", None) or f"player {toks[2]}"
        return f"pay 1 {_res_word(toks[1])} to {target_name}"
    if verb == "slay_pay" and len(toks) >= 4:
        try:
            return f"slay: pay {_pay_words(int(toks[1]), int(toks[2]), int(toks[3]))}"
        except ValueError:
            return None
    if verb == "build_pay" and len(toks) >= 3:
        try:
            return f"build: pay {_pay_words(int(toks[1]), 0, int(toks[2]))}"
        except ValueError:
            return None
    if verb == "steal_victim" and len(toks) == 2 and toks[1].isdigit():
        opts = prc.get("victim_options") or []
        idx = int(toks[1]) - 1
        label = _option_label(opts[idx]) if 0 <= idx < len(opts) else None
        return f"steal from {label}" if label else None
    if verb == "steal_resource" and len(toks) == 2 and toks[1].isdigit():
        opts = prc.get("resource_options") or []
        idx = int(toks[1]) - 1
        label = _option_label(opts[idx]) if 0 <= idx < len(opts) else None
        return f"steal {label}" if label else None
    if verb in _INDEXED_VERBS and len(toks) == 2 and toks[1].isdigit():
        idx = int(toks[1]) - 1
        pool = prc.get("options")
        if not pool and prc.get("choices"):
            pool = prc.get("choices")
        if isinstance(pool, list) and 0 <= idx < len(pool):
            label = _option_label(pool[idx])
            if label:
                return f"{_INDEXED_VERBS[verb]} {label}"
        return None
    if verb == "place" and len(toks) == 3:
        return f"place monster on {toks[1]} stack {toks[2]}"
    if action.isdigit():
        n = int(action)
        prompt_verb = str(prc.get("verb") or "")
        if prompt_verb == "banish_center_citizen":
            grid = getattr(game, "citizen_grid", None) or []
            card = grid[n][-1] if 0 <= n < len(grid) and grid[n] else None
            return f"banish {_card_name(card, f'center stack {n}')}"
        if prompt_verb == "banish_owned_citizen":
            mover = _player_by_id(game, mover_id)
            owned = getattr(mover, "owned_citizens", None) or []
            card = owned[n] if 0 <= n < len(owned) else None
            return f"banish {_card_name(card, f'citizen #{n}')}"
        for opt in prc.get("options") or []:
            if isinstance(opt, dict) and (opt.get("stack_index") == n or opt.get("index") == n):
                label = _option_label(opt)
                if label:
                    return f"choose {label}"
        return None
    return None


def _harvest_prompt_prc(game, mover_id, prompt_id):
    ca = getattr(game, "concurrent_action", None) or {}
    prompts = ((ca.get("data") or {}).get("prompts") or {})
    mine = prompts.get(mover_id) or prompts.get(str(mover_id)) or []
    if not isinstance(mine, list):
        mine = [mine]
    for prompt in mine:
        if isinstance(prompt, dict) and str(prompt.get("id")) == str(prompt_id):
            return prompt.get("pending_required_choice") or {}
    return {}


def _describe_concurrent(kind, body, game, mover_id):
    """Human phrasing for a concurrent-action response, or None."""
    if game is None or not body:
        return None
    mover = _player_by_id(game, mover_id)
    if kind == "choose_duke":
        for d in getattr(mover, "owned_dukes", None) or []:
            if str(getattr(d, "duke_id", "")) == body:
                return f"choose duke {_card_name(d, body)}"
        return None
    if kind == "choose_relic":
        for r in getattr(mover, "owned_relics", None) or []:
            if str(getattr(r, "relic_id", "")) == body:
                return f"choose relic {_card_name(r, body)}"
        return None
    if kind in ("flip_one_citizen", "event_banish_citizen_for_reward") and body.isdigit():
        owned = getattr(mover, "owned_citizens", None) or []
        i = int(body)
        card = owned[i] if 0 <= i < len(owned) else None
        word = "flip" if kind == "flip_one_citizen" else "banish"
        return f"{word} {_card_name(card, f'citizen #{i}')}"
    if kind == "harvest_choices" and "|" in body:
        prompt_id, sub = body.split("|", 1)
        sub = sub.strip()
        if sub in ("gold", "strength", "magic"):
            return f"take {sub}"
        prc = _harvest_prompt_prc(game, mover_id, prompt_id)
        described = _describe_action_string(sub, game, mover_id, prc=prc)
        return described or sub.replace("_", " ")
    if kind == "event_self_convert" and body in ("g", "s", "m"):
        return f"pay 1 {_res_word(body)}"
    return None


def move_label(move, game=None):
    """Short label for logs: action + target card or prompt text."""
    if not move:
        return "(none)"
    at = move.get("action_type") or "?"
    if at == "take_resource":
        res = RES_LABELS.get((move.get("resource") or "g")[0], move.get("resource"))
        return f"take {res}"

    if at == "hire_citizen":
        cid = move.get("citizen_id")
        name = f"citizen #{cid}"
        if game is not None:
            card = _find_top(getattr(game, "citizen_grid", None), "citizen_id", cid)
            if card is not None:
                name = getattr(card, "name", name)
        return f"hire {name}{_payment_suffix(move)}"

    if at == "build_domain":
        did = move.get("domain_id")
        name = f"domain #{did}"
        if game is not None:
            card = _find_top(getattr(game, "domain_grid", None), "domain_id", did)
            if card is not None:
                name = getattr(card, "name", name)
        return f"build {name}{_payment_suffix(move)}"

    if at == "slay_monster":
        mid = move.get("monster_id")
        name = f"monster #{mid}" if mid is not None else "event"
        if game is not None and mid is not None:
            card = _find_top(getattr(game, "monster_grid", None), "monster_id", mid)
            if card is not None:
                name = getattr(card, "name", name)
        return f"slay {name}{_payment_suffix(move)}"

    if at == "act_on_required_action":
        action = (move.get("action") or "").strip()
        described = _describe_action_string(action, game, move.get("player_id"))
        if described:
            return described
        if len(action) > 48:
            action = action[:45] + "..."
        return f"prompt: {action or '(empty)'}"

    if at == "submit_concurrent_action":
        kind = move.get("kind") or "concurrent"
        body = (move.get("action") or move.get("response") or "").strip()
        described = _describe_concurrent(kind, body, game, move.get("player_id"))
        if described:
            return described
        if len(body) > 40:
            body = body[:37] + "..."
        return f"{kind}: {body or '(empty)'}"

    if at == "finalize_roll":
        d1 = move.get("die_one")
        d2 = move.get("die_two")
        if d1 is not None and d2 is not None:
            return f"finalize roll → {d1}+{d2}"
        return "finalize roll"

    if at == "harvest_card":
        return "harvest card"

    slim = {k: v for k, v in move.items() if k not in ("player_id",) and not k.startswith("_")}
    return f"{at} {slim}".strip()


def _candidate_key(entry):
    move = entry.get("move")
    return entry.get("key") or (move_key(move) if move else None)


def format_greedy_decision(decision, game=None, top_n=5):
    """Lines summarizing a greedy VP-equivalent ranking."""
    if not decision:
        return []
    lines = ["greedy:"]
    if decision.get("unscored"):
        lines.append("  (could not score moves — picked at random)")
        return lines
    if decision.get("trivial"):
        lines.append(f"  only legal move → {move_label(decision.get('chosen'), game)}")
        return lines
    chosen = decision.get("chosen")
    lines.append(f"  pick → {move_label(chosen, game)}")
    best = decision.get("best_vp_equiv")
    if best is not None:
        lines.append(f"  best VP-equiv ≈ {best:.2f}")
    for entry in (decision.get("candidates") or [])[:top_n]:
        marker = "*" if entry.get("move") is chosen else " "
        vp = entry.get("vp_equiv", 0.0)
        delta = entry.get("delta_from_best", 0.0)
        delta_s = "" if abs(delta) < 1e-9 else f", Δ{delta:+.2f}"
        lines.append(f"  {marker} {vp:6.2f} VP-equiv{delta_s}  {move_label(entry.get('move'), game)}")
    return lines


def format_mcts_decision(decision, game=None, top_n=5):
    """Lines summarizing MCTS root visit counts and mean win rate (Q)."""
    if not decision:
        return []
    lines = ["mcts:"]
    if decision.get("trivial"):
        lines.append(f"  only legal move → {move_label(decision.get('chosen'), game)}")
        return lines
    chosen = decision.get("chosen")
    iters = decision.get("iterations")
    workers = decision.get("workers") or 1
    budget = f"{iters} iter"
    if workers > 1:
        budget += f" × {workers} workers"
    lines.append(f"  pick → {move_label(chosen, game)}  ({budget})")
    for entry in (decision.get("candidates") or [])[:top_n]:
        marker = "*" if entry.get("move") is chosen else " "
        visits = entry.get("visits", 0)
        pct = entry.get("visit_pct", 0.0)
        q = entry.get("q", 0.0)
        prior = entry.get("prior")
        prior_s = f", prior {prior:.0%}" if prior is not None else ""
        lines.append(
            f"  {marker} {visits:4d} visits ({pct:4.0f}%), Q≈{q:.2f}{prior_s}  "
            f"{move_label(entry.get('move'), game)}"
        )
    return lines


def format_decision(decision, game=None, top_n=5):
    if not decision:
        return []
    policy = decision.get("policy")
    if policy == "greedy":
        return format_greedy_decision(decision, game, top_n=top_n)
    if policy == "mcts":
        return format_mcts_decision(decision, game, top_n=top_n)
    return []


def compare_decisions(greedy_decision, mcts_decision, top_n=3):
    """Overlap / divergence metadata for side-by-side policy comparison."""
    g_chosen = greedy_decision.get("chosen") if greedy_decision else None
    m_chosen = mcts_decision.get("chosen") if mcts_decision else None
    g_key = move_key(g_chosen) if g_chosen else None
    m_key = move_key(m_chosen) if m_chosen else None
    same_move = g_key is not None and g_key == m_key

    g_rank = {}
    for i, entry in enumerate(greedy_decision.get("candidates") or []):
        k = _candidate_key(entry)
        if k:
            g_rank[k] = i + 1
    m_rank = {}
    for i, entry in enumerate(mcts_decision.get("candidates") or []):
        k = _candidate_key(entry)
        if k:
            m_rank[k] = i + 1

    g_top_keys = [_candidate_key(e) for e in (greedy_decision.get("candidates") or [])[:top_n]]
    m_top_keys = [_candidate_key(e) for e in (mcts_decision.get("candidates") or [])[:top_n]]
    g_top_keys = [k for k in g_top_keys if k]
    m_top_keys = [k for k in m_top_keys if k]
    overlap = len(set(g_top_keys) & set(m_top_keys))

    same_action_type = (
        g_chosen is not None
        and m_chosen is not None
        and g_chosen.get("action_type") == m_chosen.get("action_type")
    )

    notes = []
    if same_move:
        notes.append("top pick matches")
    else:
        notes.append("top pick differs")
        if same_action_type:
            notes.append(f"same action type ({g_chosen.get('action_type')})")
        else:
            g_at = (g_chosen or {}).get("action_type", "?")
            m_at = (m_chosen or {}).get("action_type", "?")
            notes.append(f"action types: greedy={g_at}, mcts={m_at}")
        if m_key in g_rank:
            notes.append(f"MCTS pick ranked #{g_rank[m_key]} by greedy VP")
        else:
            notes.append("MCTS pick outside greedy top candidates")
        if g_key in m_rank:
            notes.append(f"greedy pick ranked #{m_rank[g_key]} by MCTS visits")
        else:
            notes.append("greedy pick outside MCTS search tree")

    if overlap >= 2:
        notes.append(f"{overlap}/{top_n} top candidates overlap")
    elif overlap == 1:
        notes.append(f"only 1/{top_n} top candidates overlap")
    else:
        notes.append(f"no overlap in top-{top_n} candidates")

    return {
        "same_move": same_move,
        "same_action_type": same_action_type,
        "top3_overlap": overlap,
        "notes": notes,
    }


def format_compare_block(greedy_decision, mcts_decision, game=None, top_n=5):
    """Full compare output: both rankings, divergence, playing MCTS."""
    lines = ["decision compare (playing MCTS):"]
    cmp = compare_decisions(greedy_decision, mcts_decision, top_n=min(3, top_n))
    verdict = "AGREE" if cmp["same_move"] else "DIVERGE"
    lines.append(f"  {verdict}: " + "; ".join(cmp["notes"]))
    lines.append("")
    lines.extend(format_greedy_decision(greedy_decision, game, top_n=top_n))
    lines.append("")
    lines.extend(format_mcts_decision(mcts_decision, game, top_n=top_n))
    return lines


def format_greedy_rankings(decision, game=None, top_n=5):
    """Ranked top-N greedy lines for advisor mode (no pick/play wording)."""
    if not decision:
        return []
    lines = ["greedy (VP-equiv):"]
    if decision.get("unscored"):
        lines.append("  (could not score moves)")
        return lines
    if decision.get("trivial"):
        lines.append(f"  #1  {move_label(decision.get('chosen'), game)}")
        return lines
    best = decision.get("best_vp_equiv")
    if best is not None:
        lines.append(f"  best ≈ {best:.2f} VP-equiv")
    for rank, entry in enumerate((decision.get("candidates") or [])[:top_n], 1):
        vp = entry.get("vp_equiv", 0.0)
        delta = entry.get("delta_from_best", 0.0)
        delta_s = "" if abs(delta) < 1e-9 else f", Δ{delta:+.2f}"
        lines.append(f"  #{rank} {vp:6.2f} VP-equiv{delta_s}  {move_label(entry.get('move'), game)}")
    return lines


def format_mcts_rankings(decision, game=None, top_n=5):
    """Ranked top-N MCTS lines for advisor mode (no pick/play wording)."""
    if not decision:
        return []
    lines = ["mcts (search):"]
    if decision.get("trivial"):
        lines.append(f"  #1  {move_label(decision.get('chosen'), game)}")
        return lines
    iters = decision.get("iterations")
    workers = decision.get("workers") or 1
    budget = f"{iters} iter"
    if workers > 1:
        budget += f" × {workers} workers"
    lines.append(f"  budget: {budget}")
    for rank, entry in enumerate((decision.get("candidates") or [])[:top_n], 1):
        visits = entry.get("visits", 0)
        pct = entry.get("visit_pct", 0.0)
        q = entry.get("q", 0.0)
        prior = entry.get("prior")
        prior_s = f", prior {prior:.0%}" if prior is not None else ""
        lines.append(
            f"  #{rank} {visits:4d} visits ({pct:4.0f}%), Q≈{q:.2f}{prior_s}  "
            f"{move_label(entry.get('move'), game)}"
        )
    return lines


def format_recommendation_block(greedy_decision, mcts_decision, game=None, top_n=5):
    """Read-only advisor output: top-N greedy + MCTS rankings and overlap notes."""
    lines = ["move recommendations (read-only — not playing):"]
    cmp = compare_decisions(greedy_decision, mcts_decision, top_n=top_n)
    verdict = "AGREE" if cmp["same_move"] else "DIVERGE"
    lines.append(f"  {verdict} on #1: " + "; ".join(cmp["notes"]))
    lines.append("")
    lines.extend(format_greedy_rankings(greedy_decision, game, top_n=top_n))
    lines.append("")
    lines.extend(format_mcts_rankings(mcts_decision, game, top_n=top_n))
    return lines


def analyze_compare(game, player_id, moves, mcts_policy):
    """Run greedy + MCTS analysis on the same move list."""
    from agent.policies import GreedyPolicy

    greedy = GreedyPolicy()
    return greedy.analyze(game, player_id, moves), mcts_policy.analyze(game, player_id, moves)
