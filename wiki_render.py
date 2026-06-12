"""
Server-side HTML renderer for the read-only card wiki.

Produces crawlable markup (tab bar, card grids, detail panels) that mirrors
the class structure previously built client-side in static/wiki/wiki.js.
JavaScript only enhances: search, filters, modal navigation, alt-art controls.
"""

import html
import re
from pathlib import Path

TYPE_ORDER = [
    "citizens", "monsters", "domains", "dukes", "starters",
    "events", "nobles", "agents", "relics",
]
TYPE_LABELS = {
    "citizens": "Citizens",
    "monsters": "Monsters",
    "domains": "Domains",
    "dukes": "Dukes",
    "starters": "Starters",
    "events": "Events",
    "nobles": "Nobles",
    "agents": "Agents",
    "relics": "Relics",
}
TYPE_TO_IMAGE_KIND = {
    "citizens": "citizen",
    "monsters": "monster",
    "domains": "domain",
    "dukes": "duke",
    "starters": "starter",
    "events": "event",
    "nobles": "noble",
    "agents": "agent",
    "relics": "relic",
}
TYPE_TO_IMAGE_FOLDER = {
    "citizen": "citizens",
    "monster": "monsters",
    "domain": "domains",
    "duke": "dukes",
    "starter": "starters",
    "event": "exhausted",
    "noble": "nobles",
    "agent": "agents",
    "relic": "relics",
}
TYPE_TO_ID_FIELD = {
    "citizens": "citizen_id",
    "monsters": "monster_id",
    "domains": "domain_id",
    "dukes": "duke_id",
    "starters": "starter_id",
    "events": "id_events",
    "nobles": "noble_id",
    "agents": "id_agents",
    "relics": "id_relics",
}
RULEBOOKS_TAB = "rulebooks"

ROLE_ICONS = {
    "shadow": "/images/shadow.png",
    "holy": "/images/holy.png",
    "soldier": "/images/soldier.png",
    "worker": "/images/worker.png",
}

# Per-tab rendered grid HTML cache keyed by (cache_version, tab).
_rendered_grid_cache = {}
_image_url_cache = {}
_repo_root = Path(__file__).resolve().parent


def esc(value):
    return html.escape(str(value) if value is not None else "", quote=True)


def title_case(s):
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), str(s or ""))


def role_icon(role):
    src = ROLE_ICONS.get(role)
    if not src:
        return ""
    return f'<img class="wiki-role-icon" src="{esc(src)}" alt="" aria-hidden="true">'


def roll_signature(card):
    rolls = []
    for key in ("roll_match1", "roll_match2"):
        v = card.get(key)
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            rolls.append(n)
    if not rolls:
        return ""
    rolls.sort()
    return "/".join(str(r) for r in rolls)


def card_image_url(kind, card_id, variant=""):
    if not variant:
        canonical = canonical_card_image_url(kind, card_id)
        if canonical:
            return canonical
    base = f"/card-image/{kind}/{card_id}"
    if variant:
        return f"{base}?variant={html.escape(variant, quote=True)}"
    return base


def canonical_card_image_url(kind, card_id):
    """Prefer the descriptive static filename for SSR/wiki image markup.

    The app endpoint `/card-image/{kind}/{id}` remains useful for runtime lookups,
    but search engines get more context from `/images/agents/agent_15_treasurer.jpg`.
    """
    cache_key = (kind, str(card_id))
    if cache_key in _image_url_cache:
        return _image_url_cache[cache_key]

    folder = TYPE_TO_IMAGE_FOLDER.get(kind)
    if not folder:
        _image_url_cache[cache_key] = ""
        return ""
    dir_path = _repo_root / "images" / folder
    if not dir_path.is_dir():
        _image_url_cache[cache_key] = ""
        return ""
    prefix = f"{kind}_{int(card_id):02d}_"
    for f in sorted(dir_path.iterdir()):
        if f.name.startswith(prefix) and f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            url = f"/images/{folder}/{f.name}"
            _image_url_cache[cache_key] = url
            return url
    _image_url_cache[cache_key] = ""
    return ""


def _search_haystack(card):
    parts = [
        card.get("name"),
        card.get("expansion"),
        card.get("area"),
        card.get("monster_type"),
        card.get("special_payout_on_turn"),
        card.get("special_payout_off_turn"),
        card.get("special_reward"),
        card.get("special_cost"),
        card.get("passive_effect"),
        card.get("activation_effect"),
        card.get("passive_effect_text"),
        card.get("activation_effect_text"),
        card.get("roll_effect"),
        card.get("effect_text"),
        card.get("text"),
        card.get("special_duke_payout"),
        card.get("roll_effect_text"),
        card.get("special_reward_text"),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _citizen_special_flag(card):
    on = bool(card.get("has_special_payout_on_turn")) and bool(str(card.get("special_payout_on_turn") or "").strip())
    off = bool(card.get("has_special_payout_off_turn")) and bool(str(card.get("special_payout_off_turn") or "").strip())
    if on and off:
        return "any"
    if on:
        return "on"
    if off:
        return "off"
    return ""


def _card_data_attrs(tab, card):
    impl = "unimplemented" if card.get("is_unimplemented") else "implemented"
    attrs = {
        "data-type": tab,
        "data-search": _search_haystack(card),
        "data-expansion": card.get("expansion") or "",
        "data-implementation": impl,
    }
    if tab == "citizens":
        attrs["data-shadow"] = str(card.get("shadow_count") or 0)
        attrs["data-holy"] = str(card.get("holy_count") or 0)
        attrs["data-soldier"] = str(card.get("soldier_count") or 0)
        attrs["data-worker"] = str(card.get("worker_count") or 0)
        attrs["data-rolls"] = roll_signature(card)
        attrs["data-special"] = _citizen_special_flag(card)
    elif tab == "monsters":
        attrs["data-area"] = card.get("area") or ""
        attrs["data-monster-type"] = card.get("monster_type") or ""
        attrs["data-has-special-reward"] = "yes" if card.get("has_special_reward") else ""
    elif tab == "domains":
        attrs["data-shadow"] = str(card.get("shadow_count") or 0)
        attrs["data-holy"] = str(card.get("holy_count") or 0)
        attrs["data-soldier"] = str(card.get("soldier_count") or 0)
        attrs["data-worker"] = str(card.get("worker_count") or 0)
        attrs["data-passive"] = "yes" if card.get("has_passive_effect") else ""
        attrs["data-activation"] = "yes" if card.get("has_activation_effect") else ""
        attrs["data-banned"] = "yes" if card.get("is_banned") else ""
    elif tab == "dukes":
        attrs["data-banned"] = "yes" if card.get("is_banned") else ""
    elif tab == "events":
        attrs["data-roll"] = "yes" if card.get("has_roll_effect") else ""
        attrs["data-activation"] = "yes" if card.get("has_activation_effect") else ""
        attrs["data-passive"] = "yes" if card.get("has_passive_effect") else ""
        attrs["data-reward"] = "yes" if card.get("has_special_reward") else ""
        attrs["data-is-monster"] = "yes" if card.get("is_monster") else ""
    elif tab == "nobles":
        attrs["data-shadow"] = str(card.get("shadow_count") or 0)
        attrs["data-holy"] = str(card.get("holy_count") or 0)
        attrs["data-soldier"] = str(card.get("soldier_count") or 0)
        attrs["data-worker"] = str(card.get("worker_count") or 0)
        attrs["data-special"] = "yes" if card.get("has_special_duke_payout") else ""
    return attrs


def _attrs_string(attrs):
    return " ".join(f'{k}="{esc(v)}"' for k, v in attrs.items() if v is not None)


def _render_badges(card):
    parts = []
    if card.get("expansion"):
        parts.append(f'<span class="wiki-badge expansion">{esc(card["expansion"])}</span>')
    if card.get("is_banned"):
        parts.append('<span class="wiki-badge banned">Banned</span>')
    if card.get("is_unimplemented"):
        parts.append(
            '<span class="wiki-badge unimplemented" '
            'title="Has a flagged special effect with no text — not yet implemented">'
            'Unimplemented</span>'
        )
    if card.get("is_extra"):
        parts.append(
            '<span class="wiki-badge extra" title="Only dealt in 5-player games">5P</span>'
        )
    if not parts:
        return ""
    return f'<div class="wiki-card-badges">{"".join(parts)}</div>'


def _render_grid_artwork(tab, card_id, kind, card_name, variants, is_noble=False):
    noble_cls = " is-noble" if is_noble else ""
    variants = variants or []
    variant_attr = esc(",".join(variants)) if variants else ""
    canonical_url = card_image_url(kind, card_id)
    alt_btn = ""
    if variants:
        alt_btn = (
            f'<button type="button" class="wiki-alt-toggle" '
            f'data-card-type="{esc(tab)}" data-card-id="{esc(card_id)}" '
            f'data-variants="{variant_attr}" aria-pressed="false">Alt</button>'
        )
    return (
        f'<div class="wiki-art-wrap{noble_cls}" data-card-type="{esc(tab)}" '
        f'data-card-id="{esc(card_id)}" data-image-kind="{esc(kind)}" '
        f'data-canonical-src="{esc(canonical_url)}" '
        f'data-variants="{variant_attr}">'
        f'<img class="wiki-card-image{noble_cls}" '
        f'src="{esc(canonical_url)}" '
        f'alt="{esc(card_name)}" loading="lazy">'
        f'{alt_btn}'
        f'</div>'
    )


def render_tab_bar(active_tab, counts):
    parts = []
    for tab in TYPE_ORDER:
        count = counts.get(tab, 0)
        active = " active" if tab == active_tab else ""
        parts.append(
            f'<a class="wiki-tab{active}" href="/wiki/{esc(tab)}" data-type="{esc(tab)}">'
            f'{esc(TYPE_LABELS[tab])}'
            f'<span class="wiki-tab-count">{count}</span>'
            f'</a>'
        )
    rb_active = " active" if active_tab == RULEBOOKS_TAB else ""
    parts.append(
        f'<a class="wiki-tab{rb_active}" href="/wiki/{RULEBOOKS_TAB}" '
        f'data-type="{RULEBOOKS_TAB}">Rulebooks</a>'
    )
    return "".join(parts)


def render_card_grid(tab, cards):
    if not cards:
        return ""
    id_field = TYPE_TO_ID_FIELD[tab]
    kind = TYPE_TO_IMAGE_KIND[tab]
    parts = []
    for card in cards:
        card_id = card[id_field]
        card_name = card.get("name") or "(unnamed)"
        variants = card.get("alt_variants") or []
        is_noble = tab == "nobles"
        attrs = _card_data_attrs(tab, card)
        attrs["class"] = "wiki-card"
        attrs["href"] = f"/wiki/{tab}/{card_id}"
        attrs["data-id"] = str(card_id)

        id_line = f"{kind} #{card_id}"
        if tab == "monsters":
            if card.get("area"):
                id_line += f" · {card['area']}"
            if card.get("order") is not None:
                id_line += f" · order {card['order']}"

        attr_str = _attrs_string(attrs)
        parts.append(
            f'<a {attr_str}>'
            f'{_render_grid_artwork(tab, card_id, kind, card_name, variants, is_noble)}'
            f'<div class="wiki-card-meta">'
            f'<div class="wiki-card-name">{esc(card_name)}</div>'
            f'<div class="wiki-card-id">{esc(id_line)}</div>'
            f'</div>'
            f'{_render_badges(card)}'
            f'</a>'
        )
    return "".join(parts)


def _stat(cls, label, value):
    cls_attr = f" {cls}" if cls else ""
    return (
        f'<div class="wiki-stat{cls_attr}">'
        f'<span class="label">{esc(label)}</span>'
        f'<strong>{esc(value)}</strong>'
        f'</div>'
    )


def _render_stats_row(tab, card):
    stats = []
    if card.get("gold_cost") is not None:
        stats.append(_stat("gold", "Cost", f"{card['gold_cost']}g"))
    if card.get("strength_cost") is not None:
        stats.append(_stat("str", "Strength", str(card["strength_cost"])))
    magic_cost = card.get("magic_cost")
    if magic_cost is not None and magic_cost > 0:
        stats.append(_stat("mag", "Magic", str(magic_cost)))
    if card.get("vp_reward") is not None:
        stats.append(_stat("vp", "VP", str(card["vp_reward"])))
    if tab == "monsters":
        if card.get("gold_reward") is not None:
            stats.append(_stat("gold", "Gold reward", str(card["gold_reward"])))
        if card.get("strength_reward"):
            stats.append(_stat("str", "Strength reward", str(card["strength_reward"])))
        if card.get("magic_reward"):
            stats.append(_stat("mag", "Magic reward", str(card["magic_reward"])))
    if tab in ("citizens", "starters", "events") and card.get("roll_match1") is not None:
        rolls = [r for r in (card.get("roll_match1"), card.get("roll_match2")) if r and r > 0]
        if rolls:
            stats.append(_stat("", "Rolls", " / ".join(str(r) for r in rolls)))
    if tab == "events":
        if card.get("gold_reward"):
            stats.append(_stat("gold", "Gold reward", str(card["gold_reward"])))
        if card.get("strength_reward"):
            stats.append(_stat("str", "Strength reward", str(card["strength_reward"])))
        if card.get("magic_reward"):
            stats.append(_stat("mag", "Magic reward", str(card["magic_reward"])))
        if card.get("monster_type"):
            stats.append(_stat("", "Monster type", title_case(card["monster_type"])))
    if tab == "monsters":
        if card.get("area"):
            stats.append(_stat("", "Area", card["area"]))
        if card.get("monster_type"):
            stats.append(_stat("", "Type", title_case(card["monster_type"])))
        if card.get("order") is not None:
            stats.append(_stat("", "Order", str(card["order"])))
        if card.get("is_extra"):
            stats.append(_stat("", "Tier", "5p extra"))
    if card.get("expansion"):
        stats.append(_stat("", "Expansion", card["expansion"]))
    if not stats:
        return ""
    return f'<div class="wiki-stats">{"".join(stats)}</div>'


def _render_roles(card):
    roles = []
    for role in ("shadow", "holy", "soldier", "worker"):
        count = card.get(f"{role}_count") or 0
        if count > 0:
            roles.append(
                f'<span class="wiki-role {role}">'
                f'{role_icon(role)} {title_case(role)} × {count}'
                f'</span>'
            )
    if not roles:
        return ""
    return f'<div class="wiki-roles">{"".join(roles)}</div>'


def _payout_row(label, value, code_cls):
    if not value or value == 0:
        return ""
    return (
        f'<li>'
        f'<span>{esc(label)}</span>'
        f'<span class="{esc(code_cls)}">{esc(value)}</span>'
        f'</li>'
    )


def _payout_block(title, gold, strength, magic, special, special_text=None):
    rows = (
        _payout_row("Gold", gold, "v-g")
        + _payout_row("Strength", strength, "v-s")
        + _payout_row("Magic", magic, "v-m")
    )
    body = ""
    if rows:
        body += f'<ul class="wiki-payout-list">{rows}</ul>'
    sp = str(special or "").strip()
    sp_text = str(special_text or "").strip()
    if sp_text:
        body += f'<div class="wiki-payout-special">{esc(sp_text)}</div>'
    if sp:
        # Always surface the raw effect string; muted when human text exists.
        code_cls = "wiki-payout-special-code" + (" sub" if sp_text else "")
        body += f'<div class="{code_cls}">{esc(sp)}</div>'
    if not body:
        body = '<div class="wiki-payout-empty">—</div>'
    return f'<div class="wiki-payout-block"><h4>{esc(title)}</h4>{body}</div>'


def _render_payout_card(card):
    sections = []
    on_turn = _payout_block(
        "On turn",
        card.get("gold_payout_on_turn"),
        card.get("strength_payout_on_turn"),
        card.get("magic_payout_on_turn"),
        card.get("special_payout_on_turn"),
        card.get("special_payout_on_turn_text"),
    )
    off_turn = _payout_block(
        "Off turn",
        card.get("gold_payout_off_turn"),
        card.get("strength_payout_off_turn"),
        card.get("magic_payout_off_turn"),
        card.get("special_payout_off_turn"),
        card.get("special_payout_off_turn_text"),
    )
    sections.append(
        f'<section class="wiki-section"><h3>Payouts</h3>'
        f'<div class="wiki-payouts">{on_turn}{off_turn}</div></section>'
    )
    sc = card.get("special_citizen")
    if sc is not None and sc != 0 and sc is not False:
        sections.append(
            f'<section class="wiki-section"><h3>Flags</h3>'
            f'<div class="wiki-rules-text">special_citizen = {esc(sc)}</div>'
            f'</section>'
        )
    return f'<div>{"".join(sections)}</div>'


def _render_monster_rewards(card):
    sections = []
    sc = str(card.get("special_cost") or "").strip()
    if card.get("has_special_cost") and sc:
        sections.append(
            f'<section class="wiki-section"><h3>Special cost</h3>'
            f'<div class="wiki-effect">{esc(sc)}</div></section>'
        )
    sr = str(card.get("special_reward") or "").strip()
    if card.get("has_special_reward") and sr:
        sections.append(
            f'<section class="wiki-section"><h3>Special reward</h3>'
            f'<div class="wiki-effect">{esc(sr)}</div></section>'
        )
    if not sections:
        return ""
    return f'<div>{"".join(sections)}</div>'


def _render_domain(card):
    sections = []
    passive = str(card.get("passive_effect") or "").strip()
    activation = str(card.get("activation_effect") or "").strip()
    text = str(card.get("effect_text") or card.get("text") or "").strip()
    if passive:
        sections.append(
            f'<section class="wiki-section"><h3>Passive effect</h3>'
            f'<div class="wiki-effect">{esc(passive)}</div></section>'
        )
    if activation:
        sections.append(
            f'<section class="wiki-section"><h3>Activation effect</h3>'
            f'<div class="wiki-effect">{esc(activation)}</div></section>'
        )
    if text:
        sections.append(
            f'<section class="wiki-section"><h3>Rules text</h3>'
            f'<div class="wiki-rules-text">{esc(text)}</div></section>'
        )
    if not sections:
        return ""
    return f'<div>{"".join(sections)}</div>'


def _render_event(card):
    sections = []
    for key, title in (
        ("roll_effect", "Roll effect"),
        ("activation_effect", "Activation effect"),
        ("passive_effect", "Passive effect"),
        ("special_reward", "Special reward"),
    ):
        val = str(card.get(key) or "").strip()
        if val:
            sections.append(
                f'<section class="wiki-section"><h3>{esc(title)}</h3>'
                f'<div class="wiki-effect">{esc(val)}</div></section>'
            )
    if not sections:
        return ""
    return f'<div>{"".join(sections)}</div>'


def _render_multipliers(card, fields):
    mults = []
    for key, label in fields:
        v = int(card.get(key) or 0)
        role = key.replace("_multiplier", "")
        zero = " zero" if v == 0 else ""
        mults.append(
            f'<div class="wiki-mult{zero}">'
            f'<span class="wiki-mult-label">{role_icon(role)} {esc(label)}</span>'
            f'<span class="wiki-mult-value">{v}</span>'
            f'</div>'
        )
    return (
        f'<section class="wiki-section"><h3>VP multipliers</h3>'
        f'<div class="wiki-multipliers">{"".join(mults)}</div>'
        f'</section>'
    )


def _render_duke(card):
    fields = [
        ("gold_multiplier", "Gold"),
        ("strength_multiplier", "Strength"),
        ("magic_multiplier", "Magic"),
        ("shadow_multiplier", "Shadow"),
        ("holy_multiplier", "Holy"),
        ("soldier_multiplier", "Soldier"),
        ("worker_multiplier", "Worker"),
        ("monster_multiplier", "Monsters slain"),
        ("citizen_multiplier", "Citizens owned"),
        ("domain_multiplier", "Domains owned"),
        ("boss_multiplier", "Bosses slain"),
        ("minion_multiplier", "Minions slain"),
        ("beast_multiplier", "Beasts slain"),
        ("titan_multiplier", "Titans slain"),
    ]
    return _render_multipliers(card, fields)


def _render_noble(card):
    fields = [
        ("shadow_multiplier", "Shadow"),
        ("holy_multiplier", "Holy"),
        ("soldier_multiplier", "Soldier"),
        ("worker_multiplier", "Worker"),
        ("monster_multiplier", "Monsters slain"),
        ("citizen_multiplier", "Citizens owned"),
        ("domain_multiplier", "Domains owned"),
        ("boss_multiplier", "Bosses slain"),
        ("minion_multiplier", "Minions slain"),
        ("beast_multiplier", "Beasts slain"),
        ("titan_multiplier", "Titans slain"),
        ("goods_multiplier", "Goods"),
    ]
    sections = [_render_multipliers(card, fields)]
    special = str(card.get("special_duke_payout") or "").strip()
    if card.get("has_special_duke_payout") and special:
        sections.append(
            f'<section class="wiki-section"><h3>Special payout</h3>'
            f'<div class="wiki-effect">{esc(special)}</div></section>'
        )
    return f'<div>{"".join(sections)}</div>'


def _render_agent(card):
    text = str(card.get("activation_effect_text") or "").strip()
    if not text:
        return ""
    return (
        f'<section class="wiki-section"><h3>Activation effect</h3>'
        f'<div class="wiki-effect">{esc(text)}</div></section>'
    )


def _render_relic(card):
    text = str(card.get("passive_effect_text") or "").strip()
    if not text:
        return ""
    return (
        f'<section class="wiki-section"><h3>Passive effect</h3>'
        f'<div class="wiki-effect">{esc(text)}</div></section>'
    )


def _render_type_specific(tab, card):
    if tab in ("citizens", "starters"):
        return _render_payout_card(card)
    if tab == "monsters":
        return _render_monster_rewards(card)
    if tab == "domains":
        return _render_domain(card)
    if tab == "dukes":
        return _render_duke(card)
    if tab == "events":
        return _render_event(card)
    if tab == "nobles":
        return _render_noble(card)
    if tab == "agents":
        return _render_agent(card)
    if tab == "relics":
        return _render_relic(card)
    return ""


def _render_modal_artwork(tab, card_id, kind, card_name, variants, is_noble=False):
    noble_cls = " is-noble" if is_noble else ""
    variants = variants or []
    variant_attr = esc(",".join(variants)) if variants else ""
    canonical_url = card_image_url(kind, card_id)
    alt_btn = ""
    if variants:
        alt_btn = (
            f'<button type="button" class="wiki-alt-toggle modal" '
            f'data-card-type="{esc(tab)}" data-card-id="{esc(card_id)}" '
            f'data-variants="{variant_attr}" aria-pressed="false">'
            f'Show alternate artwork</button>'
        )
    return (
        f'<div class="wiki-art-wrap{noble_cls}" data-card-type="{esc(tab)}" '
        f'data-card-id="{esc(card_id)}" data-image-kind="{esc(kind)}" '
        f'data-canonical-src="{esc(canonical_url)}" '
        f'data-variants="{variant_attr}">'
        f'<img class="wiki-modal-image{noble_cls}" '
        f'src="{esc(canonical_url)}" '
        f'alt="{esc(card_name)}">'
        f'</div>'
        f'{alt_btn}'
    )


def render_card_detail(tab, card):
    id_field = TYPE_TO_ID_FIELD[tab]
    kind = TYPE_TO_IMAGE_KIND[tab]
    card_id = card[id_field]
    card_name = card.get("name") or "(unnamed)"
    variants = card.get("alt_variants") or []
    is_noble = tab == "nobles"

    left_badges = ""
    if card.get("is_banned"):
        left_badges += '<span class="wiki-badge banned">Banned in game setup</span>'
    if card.get("is_unimplemented"):
        left_badges += (
            '<span class="wiki-badge unimplemented" '
            'title="Has a flagged special effect with no text — not yet implemented">'
            'Unimplemented</span>'
        )

    left = (
        f'<div class="wiki-modal-image-col">'
        f'{_render_modal_artwork(tab, card_id, kind, card_name, variants, is_noble)}'
        f'{left_badges}'
        f'</div>'
    )
    right = (
        f'<div class="wiki-modal-detail">'
        f'<div class="wiki-modal-header-row">'
        f'<h2 id="wiki-modal-title">{esc(card_name)}</h2>'
        f'<span class="wiki-modal-type">{esc(kind)}</span>'
        f'<span class="wiki-modal-dbid">id {esc(card_id)}</span>'
        f'</div>'
        f'{_render_stats_row(tab, card)}'
        f'{_render_roles(card)}'
        f'{_render_type_specific(tab, card)}'
        f'</div>'
    )
    return (
        f'<div class="wiki-modal-body-inner" style="display: contents;">'
        f'{left}{right}'
        f'</div>'
    )


def _render_rule_card_grid(card):
    front = card.get("front_url") or ""
    back = card.get("back_url") or ""
    has_both = bool(front and back)
    side = "front"
    url = front or back
    flip_btn = ""
    if has_both:
        flip_btn = (
            f'<button type="button" class="wiki-alt-toggle" '
            f'data-rule-card-slug="{esc(card.get("slug"))}" '
            f'data-front-url="{esc(front)}" data-back-url="{esc(back)}">Flip</button>'
        )
    return (
        f'<div class="wiki-card wiki-rule-card" data-rule-card-slug="{esc(card.get("slug"))}" '
        f'data-front-url="{esc(front)}" data-back-url="{esc(back)}">'
        f'<div class="wiki-art-wrap">'
        f'<img class="wiki-card-image rule-card-img" src="{esc(url)}" '
        f'alt="{esc(card.get("name") or "")}" loading="lazy">'
        f'{flip_btn}'
        f'</div>'
        f'<div class="wiki-card-meta">'
        f'<div class="wiki-rule-card-name-row">'
        f'<span class="wiki-card-name">{esc(card.get("name") or "(unnamed)")}</span>'
        f'{"<span class=\"wiki-rule-card-side\">Front</span>" if has_both else ""}'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def render_rulebooks(rulebooks_data):
    books = rulebooks_data.get("rulebooks") or []
    cards = rulebooks_data.get("rule_cards") or []
    if not books and not cards:
        return '<p class="wiki-rulebooks-status">No rulebooks available.</p>'

    parts = ['<div class="wiki-grid wiki-grid--plain">']
    if books:
        items = "".join(
            f'<li class="wiki-rulebook-item">'
            f'<a class="wiki-rulebook-link" href="{esc(b["url"])}" '
            f'target="_blank" rel="noopener noreferrer">{esc(b["name"])}</a>'
            f'</li>'
            for b in books
        )
        parts.append(
            f'<section class="wiki-rb-section">'
            f'<h2 class="wiki-rb-heading">Rulebooks</h2>'
            f'<ul class="wiki-rulebooks">{items}</ul>'
            f'</section>'
        )
    if cards:
        card_grid = "".join(_render_rule_card_grid(c) for c in cards)
        parts.append(
            f'<section class="wiki-rb-section">'
            f'<h2 class="wiki-rb-heading">Rule Cards</h2>'
            f'<div class="wiki-grid">{card_grid}</div>'
            f'</section>'
        )
    parts.append("</div>")
    return "".join(parts)


def find_card(cards_data, tab, card_id):
    id_field = TYPE_TO_ID_FIELD.get(tab)
    if not id_field:
        return None
    target = str(card_id)
    for card in cards_data.get("cards", {}).get(tab, []):
        if str(card.get(id_field)) == target:
            return card
    return None


def render_grid_for_tab(tab, cards_data, cache_version=None):
    if tab == RULEBOOKS_TAB:
        return ""
    cache_key = (cache_version, tab)
    if cache_key in _rendered_grid_cache:
        return _rendered_grid_cache[cache_key]
    html_out = render_card_grid(tab, cards_data.get("cards", {}).get(tab, []))
    if cache_version is not None:
        _rendered_grid_cache[cache_key] = html_out
    return html_out


def clear_render_cache():
    _rendered_grid_cache.clear()


def render_wiki_page(
    template,
    *,
    active_tab,
    cards_data=None,
    rulebooks_data=None,
    card_id=None,
    error_message=None,
    page_title=None,
):
    """Fill wiki index.html placeholders and return complete HTML string."""
    counts = (cards_data or {}).get("counts") or {}
    tabs_html = render_tab_bar(active_tab, counts)

    if error_message:
        status_html = f'<div class="wiki-status error">{esc(error_message)}</div>'
        grid_html = ""
        modal_open = False
        modal_body = ""
        filters_hidden = True
    elif active_tab == RULEBOOKS_TAB:
        status_html = '<div class="wiki-status" id="wiki-status" hidden></div>'
        grid_html = render_rulebooks(rulebooks_data or {})
        modal_open = False
        modal_body = ""
        filters_hidden = True
    else:
        status_html = '<div class="wiki-status" id="wiki-status" hidden></div>'
        cache_version = id(cards_data) if cards_data else None
        grid_html = render_grid_for_tab(active_tab, cards_data or {}, cache_version)
        modal_open = False
        modal_body = ""
        if card_id is not None and cards_data:
            card = find_card(cards_data, active_tab, card_id)
            if card:
                modal_open = True
                modal_body = render_card_detail(active_tab, card)
        filters_hidden = False

    modal_cls = "wiki-modal-backdrop open" if modal_open else "wiki-modal-backdrop"
    modal_aria = "false" if modal_open else "true"
    filters_attr = " hidden" if filters_hidden else ""

    body_attrs = f' data-active-tab="{esc(active_tab)}"'
    if card_id is not None:
        body_attrs += f' data-active-card-id="{esc(card_id)}"'

    modal_attrs = f'class="{modal_cls}" aria-hidden="{modal_aria}"'

    out = template
    if page_title:
        out = out.replace("<title>Valeria Card Kingdoms Wiki</title>", f"<title>{esc(page_title)}</title>", 1)
    out = out.replace("<!--WIKI_BODY_ATTRS-->", body_attrs)
    out = out.replace("<!--WIKI_TABS-->", tabs_html)
    out = out.replace("<!--WIKI_STATUS-->", status_html)
    out = out.replace('id="wiki-filters-wrap"', f'id="wiki-filters-wrap"{filters_attr}', 1)
    out = out.replace("<!--WIKI_GRID-->", grid_html)
    out = out.replace("<!--WIKI_MODAL_ATTRS-->", modal_attrs)
    out = out.replace("<!--WIKI_MODAL_BODY-->", modal_body)
    return out
