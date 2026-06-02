def _n(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _validate_hire_or_domain_gold_payment(player, scaled_gold_cost, gp, sp, mp, allow_strength=False):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    if gp < 0 or sp < 0 or mp < 0:
        raise ValueError("Invalid payment (negative amounts).")
    if sp != 0 and not allow_strength:
        raise ValueError("Strength cannot be spent on hiring citizens or building domains.")
    scaled_gold_cost = int(scaled_gold_cost or 0)
    if allow_strength:
        total = gp + sp + mp
        if total < scaled_gold_cost:
            raise ValueError("Payment does not cover the gold cost.")
        if total != scaled_gold_cost:
            raise ValueError("Payment must exactly match the gold cost.")
        if int(getattr(player, "gold_score", 0)) < gp or int(getattr(player, "magic_score", 0)) < mp \
                or int(getattr(player, "strength_score", 0)) < sp:
            raise ValueError("Insufficient resources.")
    else:
        if scaled_gold_cost > 0 and mp > 0 and gp < 1:
            raise ValueError("Must pay at least 1 gold to use magic as wild.")
        total = gp + mp
        if total < scaled_gold_cost:
            raise ValueError("Payment does not cover the gold cost.")
        if total != scaled_gold_cost:
            raise ValueError("Payment must exactly match the gold cost.")
        if int(getattr(player, "gold_score", 0)) < gp or int(getattr(player, "magic_score", 0)) < mp:
            raise ValueError("Insufficient resources.")


def _citizen_has_steal(citizen, on_turn):
    """Return True if this citizen's relevant payout (on- or off-turn) is a steal effect.

    Honors the `has_special_payout_*` flag the same way the harvest engine
    does: if the flag is 0, a stale (non-empty) `special_payout_*` string
    is ignored entirely — the flag wins.
    """
    if not citizen:
        return False
    flag = "has_special_payout_on_turn" if on_turn else "has_special_payout_off_turn"
    if not getattr(citizen, flag, False):
        return False
    field = "special_payout_on_turn" if on_turn else "special_payout_off_turn"
    val = (getattr(citizen, field, None) or "").strip().lower()
    return val.startswith("steal")


def _parse_domain_effect_kv(effect):
    out = {}
    for p in (effect or "").split():
        if "=" in p:
            k, v = p.split("=", 1)
            out[(k or "").strip().lower()] = (v or "").strip()
    return out


def _parse_resource_kv(spec):
    """
    'g:3' / 'vp:1' / 'm:1' -> (letter, amount) with vp mapped to 'v'.
    """
    if not spec or ":" not in spec:
        return None, 0
    kind, rest = spec.split(":", 1)
    kind = (kind or "").strip().lower()
    try:
        n = int((rest or "").strip())
    except (TypeError, ValueError):
        return None, 0
    if kind == "vp":
        kind = "v"
    if kind not in ("g", "s", "m", "v"):
        return None, 0
    return kind, n


def _validate_monster_slay_payment(player, strength_cost, magic_min, gold_cost, gp, sp, mp):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    gold_cost = int(gold_cost or 0)
    if gold_cost > 0:
        if gp != gold_cost:
            raise ValueError(f"Must pay exactly {gold_cost} gold (no substitution allowed).")
        if int(getattr(player, "gold_score", 0)) < gp:
            raise ValueError("Insufficient gold.")
    elif gp != 0:
        raise ValueError("Gold cannot be spent on slaying monsters.")
    strength_cost = int(strength_cost or 0)
    magic_min = int(magic_min or 0)
    if sp < 0 or mp < 0 or mp < magic_min:
        raise ValueError("Invalid monster payment.")
    wild_magic = mp - magic_min
    if sp + wild_magic < strength_cost:
        raise ValueError("Payment does not cover strength cost.")
    if strength_cost > 0 and wild_magic > 0 and sp < 1:
        raise ValueError("Must pay at least 1 strength to use magic as wild for slaying.")
    if int(getattr(player, "strength_score", 0)) < sp or int(getattr(player, "magic_score", 0)) < mp:
        raise ValueError("Insufficient resources.")


def _player_resource_balances(player):
    if not player:
        return None
    return {
        "g": int(getattr(player, "gold_score", 0)),
        "s": int(getattr(player, "strength_score", 0)),
        "m": int(getattr(player, "magic_score", 0)),
        "v": int(getattr(player, "victory_score", 0)),
    }


def _balances_allow_payout(balances, payout_vec):
    """balances: dict g,s,m,v; payout_vec: [dg, ds, dm, dv]."""
    if not balances:
        return False
    keys = ("g", "s", "m", "v")
    for i, k in enumerate(keys):
        if int(balances.get(k, 0)) + int(payout_vec[i]) < 0:
            return False
    return True


# Append-only server log included in serialized game state (same for every client).
_GAME_LOG_MAX = 400
