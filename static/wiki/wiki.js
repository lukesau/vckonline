/*
 * Read-only browser for the vckonline card database.
 * Lives behind /wiki — talks to /api/wiki/cards on the FastAPI server.
 */

(() => {
  "use strict";

  const TYPE_ORDER = ["citizens", "monsters", "domains", "dukes", "starters"];
  const TYPE_LABELS = {
    citizens: "Citizens",
    monsters: "Monsters",
    domains:  "Domains",
    dukes:    "Dukes",
    starters: "Starters",
  };
  // The card-image endpoint expects the *singular* type name.
  const TYPE_TO_IMAGE_KIND = {
    citizens: "citizen",
    monsters: "monster",
    domains:  "domain",
    dukes:    "duke",
    starters: "starter",
  };
  const TYPE_TO_ID_FIELD = {
    citizens: "citizen_id",
    monsters: "monster_id",
    domains:  "domain_id",
    dukes:    "duke_id",
    starters: "starter_id",
  };

  const state = {
    raw: null,                  // full payload from /api/wiki/cards
    activeType: "citizens",
    search: "",
    filters: {},                // { citizens: { role: 'shadow' }, monsters: { area: 'Forest' }, ... }
  };

  const el = {
    tabs:    document.getElementById("wiki-tabs"),
    grid:    document.getElementById("wiki-grid"),
    empty:   document.getElementById("wiki-empty"),
    search:  document.getElementById("wiki-search"),
    filters: document.getElementById("wiki-filters"),
    filtersWrap: document.getElementById("wiki-filters-wrap"),
    filtersCount: document.getElementById("wiki-filters-count"),
    refresh: document.getElementById("wiki-refresh"),
    status:  document.getElementById("wiki-status"),
    modal:   document.getElementById("wiki-modal"),
    modalBody: document.getElementById("wiki-modal-body"),
    modalClose: document.getElementById("wiki-modal-close"),
  };

  // Default the filter panel open on wide viewports and closed on narrow ones.
  // The user can still toggle freely; we only set the initial state.
  const FILTER_BREAKPOINT_PX = 720;
  el.filtersWrap.open = window.innerWidth > FILTER_BREAKPOINT_PX;

  // ── tiny dom helpers ──────────────────────────────────────────────────
  const h = (tag, attrs = {}, ...children) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "html") node.innerHTML = v;
      else if (k === "onclick") node.addEventListener("click", v);
      else if (k === "dataset") Object.assign(node.dataset, v);
      else node.setAttribute(k, v);
    }
    for (const c of children) {
      if (c == null || c === false) continue;
      node.append(c.nodeType ? c : document.createTextNode(c));
    }
    return node;
  };

  const titleCase = (s) => (s || "").toString().replace(/\b\w/g, c => c.toUpperCase());

  // ── boot ──────────────────────────────────────────────────────────────
  loadData();
  el.refresh.addEventListener("click", () => loadData({ refresh: true }));
  el.search.addEventListener("input", (e) => {
    state.search = e.target.value.trim().toLowerCase();
    render();
  });
  el.modalClose.addEventListener("click", closeModal);
  el.modal.addEventListener("click", (e) => {
    if (e.target === el.modal) closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  async function loadData({ refresh = false } = {}) {
    el.status.classList.remove("error");
    el.status.textContent = "Loading card data...";
    try {
      const res = await fetch(`/api/wiki/cards${refresh ? "?refresh=1" : ""}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      state.raw = await res.json();
      renderTabs();
      renderFilters();
      render();
      const total = TYPE_ORDER.reduce((acc, t) => acc + (state.raw.counts[t] || 0), 0);
      el.status.textContent = `Loaded ${total} cards from the database.`;
    } catch (err) {
      el.status.classList.add("error");
      el.status.textContent = `Failed to load card data: ${err.message}. Is the DB tunnel up?`;
      el.grid.innerHTML = "";
    }
  }

  // ── tab bar ───────────────────────────────────────────────────────────
  function renderTabs() {
    el.tabs.innerHTML = "";
    for (const type of TYPE_ORDER) {
      const count = (state.raw.cards[type] || []).length;
      const tab = h("button", {
        class: "wiki-tab" + (type === state.activeType ? " active" : ""),
        dataset: { type },
      },
        TYPE_LABELS[type],
        h("span", { class: "wiki-tab-count" }, String(count))
      );
      tab.addEventListener("click", () => {
        state.activeType = type;
        renderTabs();
        renderFilters();
        render();
      });
      el.tabs.appendChild(tab);
    }
  }

  // ── per-type filter chips ─────────────────────────────────────────────
  function renderFilters() {
    el.filters.innerHTML = "";
    const type = state.activeType;
    const cards = state.raw.cards[type] || [];
    const groups = buildFilterGroupsFor(type, cards);
    el.filtersWrap.hidden = groups.length === 0;
    for (const group of groups) {
      const groupEl = h("div", { class: "wiki-filter-group" },
        h("span", { class: "wiki-filter-label" }, group.label));
      for (const opt of group.options) {
        const active = (state.filters[type]?.[group.key]) === opt.value;
        const chip = h("button", {
          class: "wiki-chip" + (active ? " active" : ""),
        }, opt.label);
        chip.addEventListener("click", () => {
          state.filters[type] = state.filters[type] || {};
          if (state.filters[type][group.key] === opt.value) {
            delete state.filters[type][group.key];
          } else {
            state.filters[type][group.key] = opt.value;
          }
          renderFilters();
          render();
        });
        groupEl.appendChild(chip);
      }
      el.filters.appendChild(groupEl);
    }
    updateActiveFilterCount();
  }

  function updateActiveFilterCount() {
    const type = state.activeType;
    const active = Object.keys(state.filters[type] || {}).length;
    if (active > 0) {
      el.filtersCount.textContent = String(active);
      el.filtersCount.classList.add("has-active");
    } else {
      el.filtersCount.textContent = "";
      el.filtersCount.classList.remove("has-active");
    }
  }

  function buildFilterGroupsFor(type, cards) {
    const groups = [];
    const expansions = unique(cards.map(c => c.expansion).filter(Boolean));
    if (expansions.length > 1) {
      groups.push({
        key: "expansion",
        label: "Expansion",
        options: expansions.sort().map(v => ({ value: v, label: titleCase(v) })),
      });
    }
    if (type === "citizens") {
      groups.push({
        key: "role",
        label: "Role",
        options: [
          { value: "shadow",  label: "Shadow" },
          { value: "holy",    label: "Holy" },
          { value: "soldier", label: "Soldier" },
          { value: "worker",  label: "Worker" },
        ],
      });
      groups.push({
        key: "has_special",
        label: "Has effect",
        options: [
          { value: "any", label: "Any" },
          { value: "on",  label: "On-turn" },
          { value: "off", label: "Off-turn" },
        ],
      });
    } else if (type === "monsters") {
      const areas = unique(cards.map(c => c.area).filter(Boolean)).sort();
      if (areas.length) {
        groups.push({
          key: "area",
          label: "Area",
          options: areas.map(a => ({ value: a, label: a })),
        });
      }
      const types = unique(cards.map(c => c.monster_type).filter(Boolean)).sort();
      if (types.length > 1) {
        groups.push({
          key: "monster_type",
          label: "Type",
          options: types.map(a => ({ value: a, label: titleCase(a) })),
        });
      }
      groups.push({
        key: "has_special_reward",
        label: "Reward",
        options: [{ value: "yes", label: "Has special" }],
      });
    } else if (type === "domains") {
      groups.push({
        key: "effect",
        label: "Has effect",
        options: [
          { value: "passive",    label: "Passive" },
          { value: "activation", label: "Activation" },
        ],
      });
      groups.push({
        key: "banned",
        label: "Status",
        options: [{ value: "yes", label: "Banned only" }],
      });
    } else if (type === "dukes") {
      groups.push({
        key: "banned",
        label: "Status",
        options: [{ value: "yes", label: "Banned only" }],
      });
    }
    return groups;
  }

  function unique(arr) {
    return Array.from(new Set(arr));
  }

  // ── filtering pipeline ────────────────────────────────────────────────
  function filteredCards() {
    const type = state.activeType;
    const cards = state.raw.cards[type] || [];
    const f = state.filters[type] || {};
    return cards.filter(c => {
      if (state.search) {
        const q = state.search;
        const hay = [
          c.name,
          c.expansion,
          c.area,
          c.monster_type,
          c.special_payout_on_turn,
          c.special_payout_off_turn,
          c.special_reward,
          c.special_cost,
          c.passive_effect,
          c.activation_effect,
          c.text,
        ].filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (f.expansion && c.expansion !== f.expansion) return false;
      if (type === "citizens") {
        if (f.role) {
          const count = c[`${f.role}_count`] || 0;
          if (count <= 0) return false;
        }
        if (f.has_special) {
          const on = !!c.has_special_payout_on_turn && !!String(c.special_payout_on_turn || "").trim();
          const off = !!c.has_special_payout_off_turn && !!String(c.special_payout_off_turn || "").trim();
          if (f.has_special === "any" && !(on || off)) return false;
          if (f.has_special === "on" && !on) return false;
          if (f.has_special === "off" && !off) return false;
        }
      }
      if (type === "monsters") {
        if (f.area && c.area !== f.area) return false;
        if (f.monster_type && c.monster_type !== f.monster_type) return false;
        if (f.has_special_reward === "yes" && !c.has_special_reward) return false;
      }
      if (type === "domains") {
        if (f.effect === "passive" && !c.has_passive_effect) return false;
        if (f.effect === "activation" && !c.has_activation_effect) return false;
        if (f.banned === "yes" && !c.is_banned) return false;
      }
      if (type === "dukes") {
        if (f.banned === "yes" && !c.is_banned) return false;
      }
      return true;
    });
  }

  // ── grid rendering ────────────────────────────────────────────────────
  function render() {
    if (!state.raw) return;
    const cards = filteredCards();
    el.grid.innerHTML = "";
    if (!cards.length) {
      el.empty.hidden = false;
      return;
    }
    el.empty.hidden = true;
    const frag = document.createDocumentFragment();
    for (const card of cards) {
      frag.appendChild(renderGridCard(card));
    }
    el.grid.appendChild(frag);
  }

  function renderGridCard(card) {
    const type = state.activeType;
    const kind = TYPE_TO_IMAGE_KIND[type];
    const id = card[TYPE_TO_ID_FIELD[type]];
    const imgUrl = `/card-image/${kind}/${id}`;
    const badges = [];
    if (card.is_banned) badges.push(h("span", { class: "wiki-badge banned" }, "Banned"));
    if (card.is_extra) badges.push(h("span", { class: "wiki-badge extra", title: "Only included in 5-player games" }, "5+"));
    if (card.expansion) badges.push(h("span", { class: "wiki-badge expansion" }, card.expansion));

    const img = h("img", {
      class: "wiki-card-image",
      src: imgUrl,
      alt: card.name,
      loading: "lazy",
    });
    img.addEventListener("error", () => {
      const placeholder = h("div", { class: "wiki-card-image missing" }, "no image");
      img.replaceWith(placeholder);
    });

    const idLine = `${kind} #${id}` + (type === "monsters" && card.order != null ? ` · order ${card.order}` : "");
    const node = h("div", { class: "wiki-card", "data-id": String(id), "data-type": type },
      img,
      h("div", { class: "wiki-card-meta" },
        h("div", { class: "wiki-card-name" }, card.name || "(unnamed)"),
        h("div", { class: "wiki-card-id" }, idLine),
      ),
      badges.length ? h("div", { class: "wiki-card-badges" }, ...badges) : null,
    );
    node.addEventListener("click", () => openModal(card));
    return node;
  }

  // ── detail modal ──────────────────────────────────────────────────────
  function openModal(card) {
    el.modalBody.innerHTML = "";
    el.modalBody.appendChild(renderDetail(card));
    el.modal.classList.add("open");
    el.modal.setAttribute("aria-hidden", "false");
  }
  function closeModal() {
    el.modal.classList.remove("open");
    el.modal.setAttribute("aria-hidden", "true");
  }

  function renderDetail(card) {
    const type = state.activeType;
    const kind = TYPE_TO_IMAGE_KIND[type];
    const id = card[TYPE_TO_ID_FIELD[type]];
    const imgUrl = `/card-image/${kind}/${id}`;

    const img = h("img", { class: "wiki-modal-image", src: imgUrl, alt: card.name });
    img.addEventListener("error", () => {
      img.replaceWith(h("div", { class: "wiki-modal-image" }, "no image"));
    });

    const left = h("div", { class: "wiki-modal-image-col" },
      img,
      card.is_banned ? h("span", { class: "wiki-badge banned" }, "Banned in game setup") : null,
    );

    const right = h("div", { class: "wiki-modal-detail" },
      h("div", { class: "wiki-modal-header-row" },
        h("h2", { id: "wiki-modal-title" }, card.name || "(unnamed)"),
        h("span", { class: "wiki-modal-type" }, kind),
        h("span", { class: "wiki-modal-dbid" }, `id ${id}`),
      ),
      renderStatsRow(type, card),
      renderRoles(card),
      renderTypeSpecific(type, card),
    );

    return h("div", { class: "wiki-modal-body-inner", style: "display: contents;" }, left, right);
  }

  function renderStatsRow(type, card) {
    const stats = [];
    if (card.gold_cost != null) stats.push(stat("gold", "Cost", `${card.gold_cost}g`));
    if (card.strength_cost != null) stats.push(stat("str", "Strength", `${card.strength_cost}`));
    if (card.magic_cost != null && card.magic_cost > 0) stats.push(stat("mag", "Magic", `${card.magic_cost}`));
    if (card.vp_reward != null) stats.push(stat("vp", "VP", `${card.vp_reward}`));
    if (card.gold_reward != null && type === "monsters") stats.push(stat("gold", "Gold reward", `${card.gold_reward}`));
    if (card.strength_reward != null && type === "monsters" && card.strength_reward) stats.push(stat("str", "Strength reward", `${card.strength_reward}`));
    if (card.magic_reward != null && type === "monsters" && card.magic_reward) stats.push(stat("mag", "Magic reward", `${card.magic_reward}`));
    if (card.roll_match1 != null && (type === "citizens" || type === "starters")) {
      const rolls = [card.roll_match1, card.roll_match2].filter(r => r && r > 0);
      if (rolls.length) stats.push(stat("", "Rolls", rolls.join(" / ")));
    }
    if (type === "monsters" && card.area) stats.push(stat("", "Area", card.area));
    if (type === "monsters" && card.monster_type) stats.push(stat("", "Type", titleCase(card.monster_type)));
    if (type === "monsters" && card.order != null) stats.push(stat("", "Order", String(card.order)));
    if (type === "monsters" && card.is_extra) stats.push(stat("", "Tier", "5p extra"));
    if (card.expansion) stats.push(stat("", "Expansion", card.expansion));
    return h("div", { class: "wiki-stats" }, ...stats);
  }

  function stat(cls, label, value) {
    return h("div", { class: "wiki-stat" + (cls ? " " + cls : "") },
      h("span", { class: "label" }, label),
      h("strong", {}, value));
  }

  function renderRoles(card) {
    const roles = [];
    if (card.shadow_count > 0)  roles.push(h("span", { class: "wiki-role shadow"  }, `Shadow × ${card.shadow_count}`));
    if (card.holy_count > 0)    roles.push(h("span", { class: "wiki-role holy"    }, `Holy × ${card.holy_count}`));
    if (card.soldier_count > 0) roles.push(h("span", { class: "wiki-role soldier" }, `Soldier × ${card.soldier_count}`));
    if (card.worker_count > 0)  roles.push(h("span", { class: "wiki-role worker"  }, `Worker × ${card.worker_count}`));
    if (!roles.length) return null;
    return h("div", { class: "wiki-roles" }, ...roles);
  }

  function renderTypeSpecific(type, card) {
    if (type === "citizens" || type === "starters") return renderPayoutCard(card);
    if (type === "monsters") return renderMonsterRewards(card);
    if (type === "domains") return renderDomain(card);
    if (type === "dukes") return renderDuke(card);
    return null;
  }

  function payoutRow(label, value, codeCls) {
    const isZero = !value || value === 0;
    return h("li", { class: isZero ? "zero" : "" },
      h("span", {}, label),
      h("span", { class: codeCls }, String(value || 0)));
  }

  function renderPayoutCard(card) {
    const sections = [];
    const onTurn = h("div", { class: "wiki-payout-block" },
      h("h4", {}, "On turn"),
      h("ul", { class: "wiki-payout-list" },
        payoutRow("Gold", card.gold_payout_on_turn, "v-g"),
        payoutRow("Strength", card.strength_payout_on_turn, "v-s"),
        payoutRow("Magic", card.magic_payout_on_turn, "v-m"),
      ),
    );
    const offTurn = h("div", { class: "wiki-payout-block" },
      h("h4", {}, "Off turn"),
      h("ul", { class: "wiki-payout-list" },
        payoutRow("Gold", card.gold_payout_off_turn, "v-g"),
        payoutRow("Strength", card.strength_payout_off_turn, "v-s"),
        payoutRow("Magic", card.magic_payout_off_turn, "v-m"),
      ),
    );
    sections.push(h("section", { class: "wiki-section" },
      h("h3", {}, "Payouts"),
      h("div", { class: "wiki-payouts" }, onTurn, offTurn)));

    const spOn = (card.special_payout_on_turn || "").toString().trim();
    const spOff = (card.special_payout_off_turn || "").toString().trim();
    if (spOn || spOff) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Special effects"),
        spOn ? h("div", { class: "wiki-effect" },
          h("span", { class: "wiki-effect-label" }, "ON TURN"), spOn) : null,
        spOff ? h("div", { class: "wiki-effect" },
          h("span", { class: "wiki-effect-label" }, "OFF TURN"), spOff) : null,
      ));
    }

    if (card.special_citizen != null && card.special_citizen !== 0 && card.special_citizen !== false) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Flags"),
        h("div", { class: "wiki-rules-text" }, `special_citizen = ${card.special_citizen}`),
      ));
    }

    return h("div", {}, ...sections);
  }

  function renderMonsterRewards(card) {
    const sections = [];
    if (card.has_special_cost && (card.special_cost || "").toString().trim()) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Special cost"),
        h("div", { class: "wiki-effect" }, String(card.special_cost).trim()),
      ));
    }
    if (card.has_special_reward && (card.special_reward || "").toString().trim()) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Special reward"),
        h("div", { class: "wiki-effect" }, String(card.special_reward).trim()),
      ));
    }
    return sections.length ? h("div", {}, ...sections) : null;
  }

  function renderDomain(card) {
    const sections = [];
    const passive = (card.passive_effect || "").toString().trim();
    const activation = (card.activation_effect || "").toString().trim();
    const text = (card.text || "").toString().trim();
    if (passive) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Passive effect"),
        h("div", { class: "wiki-effect" }, passive),
      ));
    }
    if (activation) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Activation effect"),
        h("div", { class: "wiki-effect" }, activation),
      ));
    }
    if (text) {
      sections.push(h("section", { class: "wiki-section" },
        h("h3", {}, "Rules text"),
        h("div", { class: "wiki-rules-text" }, text),
      ));
    }
    return sections.length ? h("div", {}, ...sections) : null;
  }

  function renderDuke(card) {
    const multFields = [
      ["gold_multiplier", "Gold"],
      ["strength_multiplier", "Strength"],
      ["magic_multiplier", "Magic"],
      ["shadow_multiplier", "Shadow"],
      ["holy_multiplier", "Holy"],
      ["soldier_multiplier", "Soldier"],
      ["worker_multiplier", "Worker"],
      ["monster_multiplier", "Monsters slain"],
      ["citizen_multiplier", "Citizens owned"],
      ["domain_multiplier", "Domains owned"],
      ["boss_multiplier", "Bosses slain"],
      ["minion_multiplier", "Minions slain"],
      ["beast_multiplier", "Beasts slain"],
      ["titan_multiplier", "Titans slain"],
    ];
    const mults = multFields.map(([key, label]) => {
      const v = Number(card[key] || 0);
      return h("div", { class: "wiki-mult" + (v === 0 ? " zero" : "") },
        h("span", { class: "wiki-mult-label" }, label),
        h("span", { class: "wiki-mult-value" }, v.toString()),
      );
    });
    return h("section", { class: "wiki-section" },
      h("h3", {}, "VP multipliers"),
      h("div", { class: "wiki-multipliers" }, ...mults),
    );
  }
})();
