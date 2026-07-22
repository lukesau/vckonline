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
        if len(action) > 48:
            action = action[:45] + "..."
        return f"prompt: {action or '(empty)'}"

    if at == "submit_concurrent_action":
        kind = move.get("kind") or "concurrent"
        body = (move.get("action") or move.get("response") or "").strip()
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
