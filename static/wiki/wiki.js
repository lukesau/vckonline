/*
 * Progressive enhancement for the server-rendered card wiki.
 * Card grids and detail HTML come from the server; this script adds
 * search, filters, modal navigation, and alt-artwork controls.
 */

(() => {
  "use strict";

  const TYPE_ORDER = [
    "citizens", "monsters", "domains", "dukes", "starters",
    "events", "nobles", "agents", "relics",
  ];
  const TYPE_TO_IMAGE_KIND = {
    citizens: "citizen",
    monsters: "monster",
    domains: "domain",
    dukes: "duke",
    starters: "starter",
    events: "event",
    nobles: "noble",
    agents: "agent",
    relics: "relic",
  };
  const RULEBOOKS_TAB = "rulebooks";

  const state = {
    activeType: document.body.dataset.activeTab || "citizens",
    search: "",
    filters: {},
    altSelections: new Map(),
    ruleCardSides: new Map(),
  };

  const el = {
    grid: document.getElementById("wiki-grid"),
    empty: document.getElementById("wiki-empty"),
    search: document.getElementById("wiki-search"),
    filters: document.getElementById("wiki-filters"),
    filtersWrap: document.getElementById("wiki-filters-wrap"),
    filtersCount: document.getElementById("wiki-filters-count"),
    modal: document.getElementById("wiki-modal"),
    modalBody: document.getElementById("wiki-modal-body"),
    modalClose: document.getElementById("wiki-modal-close"),
  };

  const FILTER_BREAKPOINT_PX = 720;
  if (el.filtersWrap) {
    el.filtersWrap.open = window.innerWidth > FILTER_BREAKPOINT_PX;
  }

  const wikiUrlForType = (type) => `/wiki/${type}`;
  const wikiUrlForCard = (type, id) => `/wiki/${type}/${id}`;
  const normalizePath = (p) => p.replace(/\/+$/, "");

  function currentRoute() {
    const parts = normalizePath(location.pathname).split("/").filter(Boolean);
    let type = parts[1] ? decodeURIComponent(parts[1]) : null;
    let id = parts[2] != null ? decodeURIComponent(parts[2]) : null;
    if (type && type !== RULEBOOKS_TAB && !TYPE_ORDER.includes(type)) {
      type = null;
      id = null;
    }
    return { type, id };
  }

  function cardImageUrl(kind, id, variant, canonicalSrc) {
    if (!variant && canonicalSrc) return canonicalSrc;
    const base = `/card-image/${kind}/${id}`;
    return variant ? `${base}?variant=${encodeURIComponent(variant)}` : base;
  }

  function altKey(type, id) {
    return `${type}_${id}`;
  }

  function getAltVariant(type, id) {
    return state.altSelections.get(altKey(type, id)) || "";
  }

  function setAltVariant(type, id, token) {
    const k = altKey(type, id);
    if (token) state.altSelections.set(k, token);
    else state.altSelections.delete(k);
  }

  function altLabel(token) {
    const m = /^alt_0*(\d+)$/.exec(token);
    if (m) return `Alt ${parseInt(m[1], 10)}`;
    if (token === "alt") return "Alt";
    return token;
  }

  function parseVariants(raw) {
    if (!raw) return [];
    return raw.split(",").map((s) => s.trim()).filter(Boolean);
  }

  function wireArtworkControls(root) {
    const wraps = root.querySelectorAll(".wiki-art-wrap[data-card-type]");
    wraps.forEach((wrap) => {
      const tab = wrap.dataset.cardType;
      const id = wrap.dataset.cardId;
      const kind = wrap.dataset.imageKind;
      const canonicalSrc = wrap.dataset.canonicalSrc || "";
      const variants = parseVariants(wrap.dataset.variants);
      const img = wrap.querySelector("img");
      const btn = wrap.querySelector(".wiki-alt-toggle:not(.modal)")
        || root.querySelector(`.wiki-alt-toggle.modal[data-card-type="${tab}"][data-card-id="${id}"]`);
      if (!img || !variants.length) return;

      let current = getAltVariant(tab, id);
      if (current && !variants.includes(current)) current = "";

      const syncBtn = () => {
        if (!btn) return;
        const on = !!current;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        if (btn.classList.contains("modal")) {
          btn.textContent = on ? `Showing ${altLabel(current)}` : "Show alternate artwork";
        }
      };

      const setVariant = (token) => {
        current = token;
        setAltVariant(tab, id, token);
        img.src = cardImageUrl(kind, id, current, canonicalSrc);
        syncBtn();
        // Keep grid thumbnail in sync when modal alt changes.
        document.querySelectorAll(
          `.wiki-art-wrap[data-card-type="${tab}"][data-card-id="${id}"] img`
        ).forEach((other) => {
          const otherWrap = other.closest(".wiki-art-wrap");
          const otherCanonical = otherWrap ? (otherWrap.dataset.canonicalSrc || "") : canonicalSrc;
          if (other !== img) other.src = cardImageUrl(kind, id, current, otherCanonical);
        });
      };

      img.addEventListener("error", () => {
        const src = img.getAttribute("src") || "";
        const q = src.indexOf("?variant=");
        if (q !== -1) {
          img.src = src.slice(0, q);
          return;
        }
        const cls = img.className;
        const missing = document.createElement("div");
        missing.className = cls + " missing";
        missing.textContent = "no image";
        img.replaceWith(missing);
      });

      if (btn) {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (variants.length === 1) {
            setVariant(current ? "" : variants[0]);
            return;
          }
          openAltChooser(wrap, tab, id, kind, variants, current, setVariant);
        });
        syncBtn();
      }
    });
  }

  function openAltChooser(wrap, tab, id, kind, variants, current, setVariant) {
    const existing = wrap.querySelector(".wiki-alt-chooser");
    if (existing) { existing.remove(); return; }

    const chooser = document.createElement("div");
    chooser.className = "wiki-alt-chooser";
    chooser.addEventListener("click", (e) => e.stopPropagation());

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "wiki-alt-chooser-close";
    closeBtn.setAttribute("aria-label", "Close chooser");
    closeBtn.textContent = "\u00d7";
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); chooser.remove(); });

    const grid = document.createElement("div");
    grid.className = "wiki-alt-chooser-grid";

    const makeOpt = (token, label) => {
      const opt = document.createElement("button");
      opt.type = "button";
      opt.className = "wiki-alt-option" + (current === token ? " active" : "");
      const thumb = document.createElement("img");
      thumb.className = "wiki-alt-option-thumb";
      thumb.src = cardImageUrl(kind, id, token, token ? "" : (wrap.dataset.canonicalSrc || ""));
      thumb.alt = "";
      thumb.loading = "lazy";
      const lbl = document.createElement("span");
      lbl.className = "wiki-alt-option-label";
      lbl.textContent = label;
      opt.append(thumb, lbl);
      opt.addEventListener("click", (e) => {
        e.stopPropagation();
        setVariant(token);
        chooser.remove();
      });
      return opt;
    };

    grid.appendChild(makeOpt("", "Original"));
    variants.forEach((v) => grid.appendChild(makeOpt(v, altLabel(v))));
    chooser.append(closeBtn, grid);
    wrap.appendChild(chooser);
  }

  function wireRuleCardControls(root) {
    root.querySelectorAll(".wiki-alt-toggle[data-rule-card-slug]").forEach((btn) => {
      if (btn.dataset.wiredRuleFlip) return;
      btn.dataset.wiredRuleFlip = "1";
      const slug = btn.dataset.ruleCardSlug;
      const front = btn.dataset.frontUrl || "";
      const back = btn.dataset.backUrl || "";
      if (!slug || !front || !back) return;

      const container = btn.closest(".wiki-modal-image-col") || btn.closest(".wiki-rule-card");
      const img = container ? container.querySelector("img") : null;
      const caption = container ? container.querySelector(".wiki-rule-card-side") : null;
      if (!img) return;

      let side = state.ruleCardSides.get(slug) || "front";
      const urlFor = (s) => (s === "back" ? (back || front) : (front || back));
      const sideLabel = (s) => (s === "back" ? "Back" : "Front");

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        side = side === "back" ? "front" : "back";
        state.ruleCardSides.set(slug, side);
        img.src = urlFor(side);
        if (caption) caption.textContent = sideLabel(side);
      });
    });
  }

  // ── filters (derived from SSR data-* on cards) ───────────────────────
  function gridCards() {
    if (!el.grid) return [];
    return Array.from(el.grid.querySelectorAll("a.wiki-card"));
  }

  function unique(arr) {
    return Array.from(new Set(arr.filter(Boolean)));
  }

  function titleCase(s) {
    return (s || "").toString().replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function buildFilterGroups() {
    const type = state.activeType;
    const cards = gridCards();
    const groups = [];

    const expansions = unique(cards.map((c) => c.dataset.expansion));
    if (expansions.length > 1) {
      groups.push({
        key: "expansion",
        label: "Expansion",
        options: expansions.sort().map((v) => ({ value: v, label: titleCase(v) })),
      });
    }

    const implementationGroup = {
      key: "implementation",
      label: "Status",
      options: [
        { value: "implemented", label: "Implemented" },
        { value: "unimplemented", label: "Unimplemented" },
      ],
    };

    const roleGroup = {
      key: "role",
      label: "Role",
      multi: true,
      options: [
        { value: "shadow", label: "Shadow" },
        { value: "holy", label: "Holy" },
        { value: "soldier", label: "Soldier" },
        { value: "worker", label: "Worker" },
      ],
    };

    if (type === "citizens") {
      groups.push(roleGroup);
      const rolls = unique(cards.map((c) => c.dataset.rolls)).sort();
      if (rolls.length) {
        groups.push({ key: "roll_match", label: "Rolls", options: rolls.map((v) => ({ value: v, label: v })) });
      }
      groups.push({
        key: "has_special",
        label: "Has effect",
        options: [
          { value: "any", label: "Any" },
          { value: "on", label: "On-turn" },
          { value: "off", label: "Off-turn" },
        ],
      });
      groups.push(implementationGroup);
    } else if (type === "monsters") {
      const areas = unique(cards.map((c) => c.dataset.area)).sort();
      if (areas.length) {
        groups.push({ key: "area", label: "Area", options: areas.map((a) => ({ value: a, label: a })) });
      }
      const mtypes = unique(cards.map((c) => c.dataset.monsterType)).sort();
      if (mtypes.length > 1) {
        groups.push({ key: "monster_type", label: "Type", options: mtypes.map((a) => ({ value: a, label: titleCase(a) })) });
      }
      groups.push({ key: "has_special_reward", label: "Reward", options: [{ value: "yes", label: "Has special" }] });
      groups.push(implementationGroup);
    } else if (type === "domains") {
      groups.push(roleGroup);
      groups.push({
        key: "effect",
        label: "Has effect",
        options: [
          { value: "passive", label: "Passive" },
          { value: "activation", label: "Activation" },
        ],
      });
      groups.push(implementationGroup);
      groups.push({ key: "banned", label: "Banned", options: [{ value: "yes", label: "Banned only" }] });
    } else if (type === "dukes") {
      groups.push({ key: "banned", label: "Banned", options: [{ value: "yes", label: "Banned only" }] });
    } else if (type === "events") {
      groups.push({
        key: "effect",
        label: "Has effect",
        options: [
          { value: "roll", label: "Roll" },
          { value: "activation", label: "Activation" },
          { value: "passive", label: "Passive" },
          { value: "reward", label: "Special reward" },
        ],
      });
      groups.push({ key: "is_monster", label: "Monster", options: [{ value: "yes", label: "Is monster" }] });
      groups.push(implementationGroup);
    } else if (type === "nobles") {
      groups.push(roleGroup);
      groups.push({ key: "special", label: "Payout", options: [{ value: "yes", label: "Has special payout" }] });
    }
    return groups;
  }

  function passesRoleFilter(card, roles) {
    if (!Array.isArray(roles) || !roles.length) return true;
    return roles.every((role) => Number(card.dataset[role] || 0) > 0);
  }

  function cardPassesFilters(card) {
    const type = state.activeType;
    const f = state.filters[type] || {};

    if (state.search) {
      const hay = (card.dataset.search || "").toLowerCase();
      if (!hay.includes(state.search)) return false;
    }
    if (f.expansion && card.dataset.expansion !== f.expansion) return false;
    if (f.implementation === "implemented" && card.dataset.implementation === "unimplemented") return false;
    if (f.implementation === "unimplemented" && card.dataset.implementation !== "unimplemented") return false;

    if (type === "citizens") {
      if (!passesRoleFilter(card, f.role)) return false;
      if (f.roll_match && card.dataset.rolls !== f.roll_match) return false;
      if (f.has_special) {
        const sp = card.dataset.special || "";
        if (f.has_special === "any" && !sp) return false;
        if (f.has_special === "on" && sp !== "on" && sp !== "any") return false;
        if (f.has_special === "off" && sp !== "off" && sp !== "any") return false;
      }
    }
    if (type === "monsters") {
      if (f.area && card.dataset.area !== f.area) return false;
      if (f.monster_type && card.dataset.monsterType !== f.monster_type) return false;
      if (f.has_special_reward === "yes" && card.dataset.hasSpecialReward !== "yes") return false;
    }
    if (type === "domains") {
      if (!passesRoleFilter(card, f.role)) return false;
      if (f.effect === "passive" && card.dataset.passive !== "yes") return false;
      if (f.effect === "activation" && card.dataset.activation !== "yes") return false;
      if (f.banned === "yes" && card.dataset.banned !== "yes") return false;
    }
    if (type === "dukes") {
      if (f.banned === "yes" && card.dataset.banned !== "yes") return false;
    }
    if (type === "events") {
      if (f.effect === "roll" && card.dataset.roll !== "yes") return false;
      if (f.effect === "activation" && card.dataset.activation !== "yes") return false;
      if (f.effect === "passive" && card.dataset.passive !== "yes") return false;
      if (f.effect === "reward" && card.dataset.reward !== "yes") return false;
      if (f.is_monster === "yes" && card.dataset.isMonster !== "yes") return false;
    }
    if (type === "nobles") {
      if (!passesRoleFilter(card, f.role)) return false;
      if (f.special === "yes" && card.dataset.special !== "yes") return false;
    }
    return true;
  }

  function applyFilters() {
    const cards = gridCards();
    let visible = 0;
    cards.forEach((card) => {
      const show = cardPassesFilters(card);
      card.hidden = !show;
      if (show) visible += 1;
    });
    if (el.empty) el.empty.hidden = visible > 0 || cards.length === 0;
  }

  function renderFilters() {
    if (!el.filters || state.activeType === RULEBOOKS_TAB) return;
    el.filters.innerHTML = "";
    const groups = buildFilterGroups();
    el.filters.hidden = groups.length === 0;

    for (const group of groups) {
      const groupEl = document.createElement("div");
      groupEl.className = "wiki-filter-group";
      const label = document.createElement("span");
      label.className = "wiki-filter-label";
      label.textContent = group.label;
      groupEl.appendChild(label);

      for (const opt of group.options) {
        const selected = state.filters[state.activeType]?.[group.key];
        const active = group.multi
          ? Array.isArray(selected) && selected.includes(opt.value)
          : selected === opt.value;
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "wiki-chip" + (active ? " active" : "");
        chip.textContent = opt.label;
        chip.addEventListener("click", () => {
          state.filters[state.activeType] = state.filters[state.activeType] || {};
          if (group.multi) {
            const current = Array.isArray(state.filters[state.activeType][group.key])
              ? state.filters[state.activeType][group.key]
              : [];
            if (current.includes(opt.value)) {
              const next = current.filter((v) => v !== opt.value);
              if (next.length) state.filters[state.activeType][group.key] = next;
              else delete state.filters[state.activeType][group.key];
            } else {
              state.filters[state.activeType][group.key] = [...current, opt.value];
            }
          } else if (state.filters[state.activeType][group.key] === opt.value) {
            delete state.filters[state.activeType][group.key];
          } else {
            state.filters[state.activeType][group.key] = opt.value;
          }
          renderFilters();
          applyFilters();
        });
        groupEl.appendChild(chip);
      }
      el.filters.appendChild(groupEl);
    }

    const active = Object.keys(state.filters[state.activeType] || {}).length;
    if (el.filtersCount) {
      el.filtersCount.textContent = active > 0 ? String(active) : "";
      el.filtersCount.classList.toggle("has-active", active > 0);
    }
  }

  // ── modal ─────────────────────────────────────────────────────────────
  function showModal() {
    el.modal.classList.add("open");
    el.modal.setAttribute("aria-hidden", "false");
  }

  function hideModal() {
    el.modal.classList.remove("open");
    el.modal.setAttribute("aria-hidden", "true");
    el.modalBody.classList.remove("rule-card");
  }

  function closeModal() {
    if (history.state && history.state.modal) {
      history.back();
      return;
    }
    history.replaceState({ type: state.activeType }, "", wikiUrlForType(state.activeType));
    hideModal();
  }

  async function openCardModal(type, id, push = true) {
    if (push) {
      history.pushState({ type, id, modal: true }, "", wikiUrlForCard(type, id));
    }
    try {
      const res = await fetch(`/api/wiki/card-detail/${type}/${id}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      el.modalBody.innerHTML = await res.text();
      el.modalBody.classList.remove("rule-card");
      wireArtworkControls(el.modalBody);
      showModal();
    } catch (_) {
      location.href = wikiUrlForCard(type, id);
    }
  }

  function wireGridClicks() {
    if (!el.grid) return;
    el.grid.addEventListener("click", (e) => {
      const link = e.target.closest("a.wiki-card");
      if (!link) return;
      e.preventDefault();
      const type = link.dataset.type || state.activeType;
      const id = link.dataset.id;
      if (type && id) openCardModal(type, id);
    });
  }

  function applyRoute() {
    const route = currentRoute();
    if (route.id != null && route.type && route.type !== RULEBOOKS_TAB) {
      openCardModal(route.type, route.id, false);
      return;
    }
    hideModal();
  }

  // ── boot ──────────────────────────────────────────────────────────────
  function openRuleCardModal(cardEl) {
    const slug = cardEl.dataset.ruleCardSlug;
    const front = cardEl.dataset.frontUrl || "";
    const back = cardEl.dataset.backUrl || "";
    const side = state.ruleCardSides.get(slug) || "front";
    const url = side === "back" ? (back || front) : (front || back);
    el.modalBody.innerHTML = "";
    el.modalBody.classList.add("rule-card");
    const wrap = document.createElement("div");
    wrap.className = "wiki-modal-image-col";
    const art = document.createElement("div");
    art.className = "wiki-art-wrap";
    art.dataset.ruleCardSlug = slug;
    art.dataset.frontUrl = front;
    art.dataset.backUrl = back;
    const img = document.createElement("img");
    img.className = "wiki-modal-image rule-card-img";
    img.src = url;
    img.alt = cardEl.querySelector(".wiki-card-name")?.textContent || "";
    art.appendChild(img);
    if (front && back) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wiki-alt-toggle modal";
      btn.textContent = "Flip";
      btn.dataset.ruleCardSlug = slug;
      btn.dataset.frontUrl = front;
      btn.dataset.backUrl = back;
      wrap.append(art, btn);
    } else {
      wrap.appendChild(art);
    }
    el.modalBody.appendChild(wrap);
    wireRuleCardControls(el.modalBody);
    showModal();
  }

  function wireRuleCardGridClicks() {
    document.querySelectorAll(".wiki-rule-card").forEach((cardEl) => {
      cardEl.addEventListener("click", (e) => {
        if (e.target.closest(".wiki-alt-toggle")) return;
        openRuleCardModal(cardEl);
      });
    });
  }

  if (state.activeType !== RULEBOOKS_TAB) {
    renderFilters();
    applyFilters();
    wireGridClicks();
    wireArtworkControls(document);
  } else {
    wireRuleCardControls(document);
    wireRuleCardGridClicks();
  }

  if (el.modalBody && el.modalBody.innerHTML.trim()) {
    wireArtworkControls(el.modalBody);
    if (el.modal.classList.contains("open")) {
      // Deep-linked card page: modal already rendered server-side.
    }
  }

  el.search.addEventListener("input", (e) => {
    state.search = e.target.value.trim().toLowerCase();
    applyFilters();
  });
  el.modalClose.addEventListener("click", closeModal);
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });
  window.addEventListener("popstate", applyRoute);
})();
