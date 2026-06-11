// ── Seat assignment ───────────────────────────────────────────────────────
// Viewer is always at the bottom. Opponents follow clockwise turn order starting
// from the player to your right (next in `player_list` after you).
function idsMatch(a, b) {
  return String(a ?? '').trim() === String(b ?? '').trim();
}

// Crimson Seas adds a whole bundle of mechanics (the Sail/island board, maps,
// tomes, goods, nobles, …). All of that UI is gated on this single check so it
// stays hidden unless the game was dealt from the Crimson Seas preset. The
// engine performs the matching server-side gating; this just keeps the UI clean.
function crimsonSeasEnabled(state) {
  return String(state?.preset ?? '').trim().toLowerCase() === 'crimsonseas';
}

function playerIndexInList(state, player) {
  if (!player) return -1;
  const all = state.player_list || [];
  return all.findIndex(p => idsMatch(p.player_id, player.player_id));
}

/**
 * Opponents in clockwise order around the table from the viewer: first is to your right.
 */
function clockwiseOpponentsFromViewer(state) {
  const all = state.player_list || [];
  const n = all.length;
  const myIdx = all.findIndex(p => idsMatch(p.player_id, PLAYER_ID));
  const anchor = myIdx >= 0 ? myIdx : 0;
  const out = [];
  for (let i = 1; i < n; i++) {
    out.push(all[(anchor + i) % n]);
  }
  return out;
}

/**
 * Maps opponents to layout slots: top row (1–2), left, right.
 * layoutKey: p1–p5 by player count.
 */
function layoutSlotAssignment(state) {
  const all = state.player_list || [];
  const n = all.length;
  const myIdx = all.findIndex(p => idsMatch(p.player_id, PLAYER_ID));
  const me = myIdx >= 0 ? all[myIdx] : null;
  const opp = clockwiseOpponentsFromViewer(state);

  if (n <= 1) {
    return { n, layoutKey: 'p1', me, top: [], left: null, right: null };
  }
  if (n === 2) {
    return { n, layoutKey: 'p2', me, top: [opp[0]], left: null, right: null };
  }
  if (n === 3) {
    return { n, layoutKey: 'p3', me, top: [], left: opp[1], right: opp[0] };
  }
  if (n === 4) {
    return { n, layoutKey: 'p4', me, top: [opp[1]], left: opp[2], right: opp[0] };
  }
  return { n, layoutKey: 'p5', me, top: [opp[1], opp[2]], left: opp[3], right: opp[0] };
}

// ── Tableau sections (domains first … starters last) ─────────────────────
function tableauGroupsForPlayer(player) {
  const defs = [
    ['Domains', ['owned_domains']],
    ['Citizens', ['owned_citizens']],
    ['Monsters', ['owned_monsters']],
    ['Starters', ['owned_starters', 'owned_dukes']],
  ];
  const groups = defs
    .map(([label, keys]) => ({
      label,
      cards: keys.reduce((acc, k) => acc.concat(player[k] || []), []),
    }))
    .filter(g => g.cards.length > 0);
  // Tag Margrave cards with their owner so per-player artwork resolves
  // correctly here and (via dataset.card) in the inspect modal.
  const ownerId = player && player.player_id;
  groups.forEach(g => g.cards.forEach(c => {
    if (c && Number(c.starter_id) === MARGRAVE_STARTER_ID) c.__ownerId = ownerId;
  }));
  return groups;
}

// Crimson Seas tableau section: a single column split into 3 equal cells
// (Nobles top, Tomes middle, Goods bottom), each 1/3 of the 2-card strip height.
// Always rendered in Crimson Seas games so the layout is visible even when empty.
function makeCrimsonSeasTableauSection(player) {
  const grp = mk('card-group cs-group');
  const col = mk('cs-column');
  const cells = [
    ['Nobles', 'nobles', csNobleEntries(player.owned_nobles)],
    ['Tomes',  'tomes',  csTomeEntries(player.owned_tomes)],
    ['Goods',  'goods',  csGoodsEntries(player.owned_goods)],
  ];
  cells.forEach(([label, kind, entries]) => {
    const cell = mk(`cs-cell cs-cell-${kind}`);
    const lbl = mk('cs-cell-label');
    lbl.textContent = label;
    cell.appendChild(lbl);
    const row = mk('cs-cell-items');
    entries.forEach(({ item, count }) => row.appendChild(makeCrimsonSeasItem(kind, item, count)));
    cell.appendChild(row);
    col.appendChild(cell);
  });
  grp.appendChild(col);
  return grp;
}

// Nobles are unique rescued cards — each gets its own slot (never stacked), so
// the Nobles row grows with the number rescued.
function csNobleEntries(nobles) {
  return (Array.isArray(nobles) ? nobles : []).map(item => ({ item, count: 1 }));
}

// Goods collapse to one icon per type (there are only 4 types), so the Goods row
// caps at 4 icons no matter how many are owned.
function csGoodsEntries(goods) {
  return csGroupEntries(Array.isArray(goods) ? goods : [], g => String(g));
}

// Tomes collapse to one icon per type. Flipped (spent-this-turn) tomes look
// different from face-up ones, so they don't merge with them — mirroring how
// citizens key on is_flipped.
function csTomeEntries(tomes) {
  return csGroupEntries(Array.isArray(tomes) ? tomes : [], t => (
    (t && typeof t === 'object') ? `${t.tome_type}|${t.is_flipped ? 1 : 0}` : String(t)
  ));
}

// Collapse identical items into {item, count} entries, preserving first-seen order.
function csGroupEntries(items, keyOf) {
  const order = [];
  const byKey = new Map();
  items.forEach(item => {
    const key = keyOf(item);
    const existing = byKey.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      const entry = { item, count: 1 };
      byKey.set(key, entry);
      order.push(entry);
    }
  });
  return order;
}

function makeCrimsonSeasItem(kind, item, count) {
  const wrap = mk(`cs-item cs-item-${kind}`);
  if (kind === 'goods') {
    const img = document.createElement('img');
    img.className = 'cs-item-img';
    img.src = SAIL_GOODS_IMAGES[item] || '';
    img.alt = item;
    wrap.appendChild(img);
  } else if (kind === 'tomes') {
    // Tomes are Tome card objects ({tome_type, is_flipped}); tolerate a legacy
    // bare type string. A flipped (spent-this-turn) tome reuses the shared card
    // cross-fade flip stage: tome back rests, the face peeks through.
    const ttype = (item && typeof item === 'object') ? item.tome_type : item;
    const flipped = !!(item && typeof item === 'object' && item.is_flipped);
    const frontUrl = SAIL_TOME_IMAGES[ttype] || '';
    const frame = mk('cs-tome-frame');
    if (flipped) {
      wrap.classList.add('flipped');
      const stage = mk('card-flip-stage');
      const inner = mk('card-flip-inner');
      const back = mk('card-flip-face card-flip-back');
      const backImg = document.createElement('img');
      backImg.className = 'card-img';
      backImg.alt = '';
      backImg.src = SAIL_TOME_BACK_IMAGE;
      back.appendChild(backImg);
      const front = mk('card-flip-face card-flip-front');
      const frontImg = document.createElement('img');
      frontImg.className = 'card-img';
      frontImg.alt = '';
      frontImg.src = frontUrl;
      front.appendChild(frontImg);
      inner.appendChild(back);
      inner.appendChild(front);
      stage.appendChild(inner);
      frame.appendChild(stage);
    } else {
      const img = document.createElement('img');
      img.className = 'cs-item-img';
      img.src = frontUrl;
      img.alt = (item && item.name) || `${ttype} tome`;
      frame.appendChild(img);
    }
    wrap.appendChild(frame);
  } else {
    const img = document.createElement('img');
    img.className = 'cs-item-img';
    img.src = `/card-image/noble/${item.noble_id}`;
    img.alt = item.name || 'Noble';
    wrap.appendChild(img);
  }
  if (count > 1) {
    const badge = mk('stack-depth cs-item-count');
    badge.textContent = `\u00D7${count}`;
    wrap.appendChild(badge);
  }
  return wrap;
}

// ── Main render ───────────────────────────────────────────────────────────
function render(state) {
  // Drop out-of-order state pushes from older ticks. WebSocket messages can
  // arrive after a fresher HTTP-response render, and without this guard the
  // older payload would overwrite the newer prompt — making the new prompt
  // disappear until the next state arrives (or a manual refresh).
  const incomingGameId = (state && state.game_id) ? String(state.game_id) : '';
  const incomingTick = Number(state && state.tick_id);
  if (
    incomingGameId &&
    incomingGameId === lastRenderedGameId &&
    Number.isFinite(incomingTick) &&
    incomingTick < lastRenderedTickId
  ) {
    return;
  }
  if (incomingGameId) lastRenderedGameId = incomingGameId;
  if (Number.isFinite(incomingTick)) lastRenderedTickId = incomingTick;

  // Skip the heavy DOM rebuild when this state is byte-for-byte identical
  // to what we already rendered. The passive poll (5s) and concurrent poll
  // (1.5s while waiting on other players) both re-fetch the current state
  // to recover from dropped WS pushes; before this guard, those polls
  // rebuilt the entire tableau on every cycle and caused:
  //   • brief scrollbar flicker on the bottom carousel every 5s
  //   • prompt modal body/footer being destroyed every 1.5s during
  //     concurrent gates, interrupting scrollbar drags in the duke
  //     selection modal (Webkit cancels a drag when its scrolling
  //     element's children are replaced underneath it)
  // We compare full JSON rather than tick_id because tick_id is only
  // bumped at phase boundaries in engines/lifecycle.py; mid-flow
  // transitions (harvest steal stages, submit_concurrent_action
  // completions, etc.) mutate state without changing tick_id, so a
  // tick-only guard silently dropped real updates. The encoder in
  // game_serialization.py emits keys in deterministic order, so two
  // serializations of the same game state produce identical strings.
  let incomingJson;
  try {
    incomingJson = JSON.stringify(state);
  } catch (_) {
    incomingJson = '';
  }
  if (incomingJson && incomingJson === lastRenderedStateJson) {
    syncHurryUpDeadlineFromState(state);
    tickHurryUpTimerElements();
    return;
  }
  lastRenderedStateJson = incomingJson;

  latestGameState = state;
  ensureCardArtVariantsLoaded();
  syncHurryUpDeadlineFromState(state);
  if (typeof refreshOpenCardInspectModal === 'function') {
    refreshOpenCardInspectModal();
  }
  // During blocking concurrent prompts (e.g. choose duke), we poll frequently.
  // Rebuilding the entire board every poll causes narrow-layout tableau/carousel
  // scroll resets + scrollbar flicker. While the prompt overlay is open and the
  // concurrent gate is still pending, keep the existing board DOM and only
  // update the prompt + polling/timers.
  const ca = state?.concurrent_action;
  const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
  const hasBlockingConcurrent = pend.length > 0;
  const promptOverlayOpen = !!document.getElementById('game-prompt-overlay');
  if (hasBlockingConcurrent && promptOverlayOpen) {
    syncConcurrentPolling(state);
    renderPromptModal(state);
    tickHurryUpTimerElements();
    ensureHurryUpTicking();
    return;
  }

  const layout = layoutSlotAssignment(state);
  const board = document.getElementById('board');
  const me = (state.player_list || []).find(p => idsMatch(p && p.player_id, PLAYER_ID));
  const isMyTurn = !!(me && isActiveTurnForPlayer(me, state));
  if (board) {
    board.dataset.layout = layout.layoutKey;
    board.dataset.playerCount = String(layout.n);
    board.dataset.narrowLayout = '1';
    board.classList.toggle('is-my-active-turn', isMyTurn);
  }
  clearEl('gl-bottom');

  const bottomEl = document.getElementById('gl-bottom');
  renderTableauCarousel(state, bottomEl);

  renderCenter(state);
  renderGameOver(state);
  renderGameShutdown(state);
  syncBoardTabsObserver();
  syncConcurrentPolling(state);
  maybeAutoFinalizeRoll(state);
  renderPromptModal(state);
  tickHurryUpTimerElements();
  ensureHurryUpTicking();
}

function clearEl(id) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = '';
}

function isActiveTurnForPlayer(player, state) {
  const ap = state.active_player_id;
  if (ap == null || player == null) return false;
  return idsMatch(ap, player.player_id);
}

// ── Seat renderer ─────────────────────────────────────────────────────────
function renderSeatEl(player, state, variant) {
  const el = mk(`seat seat-${variant}`);
  if (player && player.player_id) {
    el.dataset.playerId = String(player.player_id);
  }
  if (player && (variant === 'me' || variant === 'carousel') && isActiveTurnForPlayer(player, state)) {
    el.classList.add('seat-my-active-turn');
  }
  if (!player) {
    el.classList.add('seat-empty');
    const ghost = mk('seat-ghost-label');
    ghost.textContent = 'Empty';
    el.appendChild(ghost);
    return el;
  }

  const inner = mk('seat-inner');
  inner.appendChild(makeHeader(player, state));
  const cardMode = variant === 'me' || variant === 'carousel' ? 'full' : 'mini';
  const tableau = mk('tableau-cards');
  const groups = tableauGroupsForPlayer(player);
  groups.forEach(g => {
    const grp = mk('card-group');
    const lbl = mk('card-group-label');
    lbl.textContent = g.label;
    grp.appendChild(lbl);
    const stacksWrap = mk('card-group-stacks');
    if (g.label === 'Citizens') {
      const grouped = groupCardsForTableau(g.cards);
      (grouped || g.cards.map(c => ({ card: c, count: 1 }))).forEach(
        ({ card, count }) => stacksWrap.appendChild(makeTableauStack(card, count, cardMode))
      );
    } else if (g.label === 'Monsters') {
      const monsters = Array.isArray(g.cards) ? g.cards : [];
      stacksWrap.appendChild(makeTableauMonsterFan(monsters, cardMode));
    } else {
      g.cards.forEach(c => stacksWrap.appendChild(makeTableauStack(c, 1, cardMode)));
    }
    grp.appendChild(stacksWrap);
    tableau.appendChild(grp);
  });
  // Crimson Seas pieces live in a dedicated section to the left of Domains, laid
  // out top→bottom (Nobles / Tomes / Goods) instead of side by side.
  if (crimsonSeasEnabled(state)) {
    tableau.insertBefore(makeCrimsonSeasTableauSection(player), tableau.firstChild);
  }
  inner.appendChild(tableau);
  el.appendChild(inner);
  wireSeatTableauOpen(el, player);
  return el;
}

function wireSeatTableauOpen(seatEl, player) {
  if (!player || !player.player_id) return;
  seatEl.classList.add('seat-detail-hit');
  seatEl.addEventListener('click', e => {
    if (e.target.closest('.card')) return;
    openPlayerDetailModal(player.player_id);
  });
}

/**
 * Scroll a padded horizontal carousel so a slide lines up with the viewport's inner (padding) edge.
 * Using slide.offsetLeft alone is wrong here: offsetLeft can include padding while scrollLeft does not,
 * which shifts every slide slightly right and peeks the next slide past the right edge.
 */
function scrollTableauCarouselToSlide(viewport, slide, behavior) {
  if (!viewport || !slide) return;
  const st = getComputedStyle(viewport);
  const insetL = (parseFloat(st.borderLeftWidth) || 0) + (parseFloat(st.paddingLeft) || 0);
  const vRect = viewport.getBoundingClientRect();
  const sRect = slide.getBoundingClientRect();
  const contentEdge = vRect.left + insetL;
  const delta = sRect.left - contentEdge;
  let left = viewport.scrollLeft + delta;
  const max = Math.max(0, viewport.scrollWidth - viewport.clientWidth);
  if (left < 0) left = 0;
  else if (left > max) left = max;
  viewport.scrollTo({ left, behavior });
}

function wireTableauCarouselViewport(viewport) {
  // Wheel: vertical scroll maps to horizontal carousel scroll, except over tableau (handled there).
  viewport.addEventListener('wheel', e => {
    if (e.target.closest('.tableau-cards')) return;
    if (viewport.scrollWidth <= viewport.clientWidth + 1) return;
    e.preventDefault();
    viewport.scrollLeft += e.deltaY;
  }, { passive: false });

  // Touch: tableau that cannot scroll horizontally must not pass swipes through to this viewport.
  viewport.addEventListener(
    'touchmove',
    e => {
      const inner = e.target.closest && e.target.closest('.card-group-stacks');
      if (inner && viewport.contains(inner)) {
        const canY = inner.scrollHeight > inner.clientHeight + 1;
        const canX = inner.scrollWidth > inner.clientWidth + 1;
        if (canY || canX) return;
      }
      const tc = e.target.closest && e.target.closest('.tableau-cards');
      if (!tc || !viewport.contains(tc)) return;
      if (tc.scrollWidth > tc.clientWidth + 1) return;
      e.preventDefault();
    },
    { passive: false, capture: true },
  );

  // Pointer drag on the header → scroll the carousel
  let dragPtr = null;
  let dragLastX = 0;
  viewport.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    if (!e.target.closest('.player-header')) return;
    dragPtr = e.pointerId;
    dragLastX = e.clientX;
    try { viewport.setPointerCapture(e.pointerId); } catch (_) {}
    viewport.classList.add('is-pointer-dragging');
  });
  viewport.addEventListener('pointermove', e => {
    if (e.pointerId !== dragPtr) return;
    const dx = e.clientX - dragLastX;
    dragLastX = e.clientX;
    viewport.scrollLeft -= dx;
  });
  const endDrag = e => {
    if (e.pointerId !== dragPtr) return;
    dragPtr = null;
    viewport.classList.remove('is-pointer-dragging');
    try { viewport.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  viewport.addEventListener('pointerup', endDrag);
  viewport.addEventListener('pointercancel', endDrag);
}

function wireCarouselTableauInteractions(tableauCards) {
  const syncTouchAction = () => {
    const can = tableauCards.scrollWidth > tableauCards.clientWidth + 1;
    tableauCards.style.touchAction = can ? 'pan-x' : 'none';
  };
  syncTouchAction();
  let ro = null;
  try {
    ro = new ResizeObserver(syncTouchAction);
    ro.observe(tableauCards);
  } catch (_) {
    /* older engines */
  }
  tableauCards.addEventListener('scroll', syncTouchAction, { passive: true });

  try {
    const mo = new MutationObserver(() => {
      requestAnimationFrame(syncTouchAction);
    });
    mo.observe(tableauCards, { childList: true, subtree: true, attributes: true });
  } catch (_) {
    /* older engines */
  }

  tableauCards.addEventListener(
    'wheel',
    e => {
      const inner = e.target.closest && e.target.closest('.card-group-stacks');
      if (inner && tableauCards.contains(inner)) {
        const canY = inner.scrollHeight > inner.clientHeight + 1;
        const canX = inner.scrollWidth > inner.clientWidth + 1;
        if (canY && Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
          e.preventDefault();
          e.stopPropagation();
          inner.scrollTop += e.deltaY;
          return;
        }
        if (canX) {
          e.preventDefault();
          e.stopPropagation();
          inner.scrollLeft += e.deltaY + e.deltaX;
          return;
        }
      }
      e.preventDefault();
      e.stopPropagation();
      if (tableauCards.scrollWidth > tableauCards.clientWidth + 1) {
        tableauCards.scrollLeft += e.deltaY + e.deltaX;
      }
    },
    { passive: false },
  );
}

function trackTableauStripScrollForPlayer(tableauCards, playerId) {
  if (!tableauCards || playerId == null) return;
  const sid = String(playerId);
  tableauCards.addEventListener(
    'scroll',
    () => {
      tableauStripScrollByPlayerId[sid] = tableauCards.scrollLeft;
    },
    { passive: true },
  );
}

function restoreTableauStripScroll(tableauCards, playerId) {
  if (!tableauCards || playerId == null) return;
  const sid = String(playerId);
  const saved = tableauStripScrollByPlayerId[sid];
  if (saved == null || !Number.isFinite(Number(saved))) return;
  const want = Number(saved);
  const apply = () => {
    const max = Math.max(0, tableauCards.scrollWidth - tableauCards.clientWidth);
    tableauCards.scrollLeft = Math.min(Math.max(0, want), max);
  };
  requestAnimationFrame(() => {
    apply();
    requestAnimationFrame(apply);
  });
}

function renderTableauCarousel(state, bottomEl) {
  if (!bottomEl) return;
  const players = state.player_list || [];
  const root = mk('tableau-carousel');
  root.setAttribute('role', 'region');
  root.setAttribute('aria-label', 'Player tableaus');

  const viewport = mk('tableau-carousel-viewport');
  players.forEach(p => {
    const slide = mk('tableau-carousel-slide');
    slide.appendChild(renderSeatEl(p, state, 'carousel'));
    const tc = slide.querySelector('.tableau-cards');
    if (tc) {
      wireCarouselTableauInteractions(tc);
      trackTableauStripScrollForPlayer(tc, p.player_id);
      restoreTableauStripScroll(tc, p.player_id);
    }
    viewport.appendChild(slide);
  });

  wireTableauCarouselViewport(viewport);

  const navDotsEl = document.createElement('div');
  navDotsEl.className = 'board-tabs-bar carousel-nav-dots';
  const dots = players.map((p, i) => {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'board-tab';
    const labelEl = document.createElement('span');
    labelEl.className = 'board-tab-label';
    labelEl.textContent = p.name || `Player ${i + 1}`;
    dot.appendChild(labelEl);
    if (PLAYER_ID && idsMatch(p.player_id, PLAYER_ID)) {
      const youTag = document.createElement('span');
      youTag.className = 'board-tab-you-tag';
      youTag.textContent = 'You';
      dot.appendChild(youTag);
    }
    dot.addEventListener('click', () => {
      const slide = viewport.children[i];
      const pl = players[i];
      if (pl && pl.player_id != null) tableauCarouselActiveId = pl.player_id;
      if (slide) scrollTableauCarouselToSlide(viewport, slide, 'smooth');
    });
    navDotsEl.appendChild(dot);
    return dot;
  });

  const syncDots = activeIdx => {
    dots.forEach((d, i) => d.classList.toggle('is-active', i === activeIdx));
  };

  root.appendChild(viewport);
  bottomEl.appendChild(root);
  bottomEl.appendChild(navDotsEl);

  let targetIdx = players.findIndex(p => idsMatch(p.player_id, tableauCarouselActiveId));
  if (targetIdx < 0) {
    targetIdx = players.findIndex(p => idsMatch(p.player_id, PLAYER_ID));
  }
  if (targetIdx < 0) targetIdx = 0;

  const syncActiveFromScroll = () => {
    const slides = viewport.children;
    if (!slides.length) return;
    const vr = viewport.getBoundingClientRect();
    const mid = vr.left + vr.width / 2;
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < slides.length; i++) {
      const r = slides[i].getBoundingClientRect();
      const c = r.left + r.width / 2;
      const d = Math.abs(c - mid);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    }
    const pl = players[best];
    if (pl && pl.player_id != null) tableauCarouselActiveId = pl.player_id;
    syncDots(best);
  };

  let carouselScrollRaf = null;
  const scheduleSyncActiveFromScroll = () => {
    if (carouselScrollRaf != null) return;
    carouselScrollRaf = requestAnimationFrame(() => {
      carouselScrollRaf = null;
      syncActiveFromScroll();
    });
  };

  let scrollEndTimer = null;
  viewport.addEventListener('scroll', () => {
    scheduleSyncActiveFromScroll();
    clearTimeout(scrollEndTimer);
    scrollEndTimer = setTimeout(scheduleSyncActiveFromScroll, 120);
  }, { passive: true });

  const runCarouselLayoutMeasure = () => {
    const slide = viewport.children[targetIdx];
    if (!slide) return;
    // 'instant' (not 'auto') so a refresh / game state update never animates the
    // carousel back to the previously-viewed slide. Only user-driven scrolls
    // (dot click) should animate.
    scrollTableauCarouselToSlide(viewport, slide, 'instant');
    const pl = players[targetIdx];
    if (pl && pl.player_id != null) tableauCarouselActiveId = pl.player_id;
    syncDots(targetIdx);
  };

  requestAnimationFrame(() => {
    runCarouselLayoutMeasure();
    requestAnimationFrame(runCarouselLayoutMeasure);
  });
}

// ── Center board ──────────────────────────────────────────────────────────
const BOARD_SECTIONS = [
  { key: 'monsters',   label: 'Monsters' },
  { key: 'citizens-1', label: 'Citizens 1–5' },
  { key: 'citizens-2', label: 'Citizens 6–12' },
  { key: 'domains',    label: 'Domains' },
];

function boardSectionsForState(state) {
  return crimsonSeasEnabled(state)
    ? [{ key: 'sail', label: 'Sail' }, ...BOARD_SECTIONS]
    : BOARD_SECTIONS;
}

function renderCenter(state) {
  const el = document.getElementById('zone-center');
  if (!el) return;
  el.innerHTML = '';
  el.classList.add('board-use-tabs');

  const tabsBar = mk('board-tabs-bar');
  tabsBar.setAttribute('role', 'tablist');

  const viewport = mk('center-board-viewport');

  const citizenGrid = state.citizen_grid || [];
  const boardSections = boardSectionsForState(state);
  const sections = [
    makeGridSection('Monsters',      state.monster_grid || [], 'monster', 5, 'board-monsters'),
    makeGridSection('Citizens 1–5',  citizenGrid.slice(0, 5),  'citizen', 5, 'board-citizens-1'),
    makeGridSection('Citizens 6–12', citizenGrid.slice(5),     'citizen', 5, 'board-citizens-2'),
    makeGridSection('Domains',       state.domain_grid  || [], 'domain',  5, 'board-domains'),
  ];
  if (crimsonSeasEnabled(state)) sections.unshift(makeSailSection(state));
  boardSections.forEach(({ key }, i) => {
    sections[i].dataset.boardSection = key;
    const slide = mk('center-board-slide');
    slide.appendChild(sections[i]);
    viewport.appendChild(slide);
  });

  const body = mk('center-board-body');
  body.appendChild(makeInfoBar(state));
  body.appendChild(makeResourceActionBar(state));
  body.appendChild(viewport);
  body.appendChild(tabsBar);
  el.appendChild(body);

  setupBoardTabs(el, tabsBar, viewport, boardSections);
}

/** Vertical wheel → horizontal scroll on opponent top strips and narrow-layout carousel tableaus. */
function initOpponentTableauWheelScroll() {
  const board = document.getElementById('board');
  if (!board || board.dataset.tableauWheelBound) return;
  board.dataset.tableauWheelBound = '1';
  board.addEventListener(
    'wheel',
    e => {
      const inner = e.target.closest && e.target.closest('.card-group-stacks');
      if (inner) {
        const seat = inner.closest('.seat');
        if (!seat || seat.classList.contains('seat-empty')) return;
        if (!seat.classList.contains('seat-carousel')) return;
        const canY = inner.scrollHeight > inner.clientHeight + 1;
        const canX = inner.scrollWidth > inner.clientWidth + 1;
        if (canY && Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
          e.preventDefault();
          inner.scrollTop += e.deltaY;
          return;
        }
        if (canX) {
          e.preventDefault();
          inner.scrollLeft += e.deltaY;
          return;
        }
        return;
      }
      const row = e.target.closest('.tableau-cards');
      if (!row) return;
      const seat = row.closest('.seat');
      if (!seat || seat.classList.contains('seat-empty')) return;
      if (
        !seat.classList.contains('seat-top') &&
        !seat.classList.contains('seat-top-mini') &&
        !seat.classList.contains('seat-carousel')
      )
        return;
      if (row.scrollWidth <= row.clientWidth + 1) return;
      e.preventDefault();
      row.scrollLeft += e.deltaY;
    },
    { passive: false },
  );
}

function syncBoardTabsObserver() {
  const zone = document.getElementById('zone-center');
  if (zone) syncBoardTabState(zone);
}

function setupBoardTabs(zoneCenter, tabsBar, viewport, boardSections) {
  const slides = Array.from(viewport.children);
  tabsBar.innerHTML = '';
  let initialIdx = 0;
  if (centerBoardActiveTabKey != null) {
    const j = boardSections.findIndex(s => s.key === centerBoardActiveTabKey);
    if (j >= 0) initialIdx = j;
  }
  const tabs = boardSections.map(({ key, label }, i) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'board-tab' + (i === initialIdx ? ' is-active' : '');
    btn.textContent = label;
    btn.dataset.boardTab = key;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', i === initialIdx ? 'true' : 'false');
    btn.addEventListener('click', () => {
      const slide = slides[i];
      centerBoardActiveTabKey = key;
      if (slide) viewport.scrollTo({ left: slide.offsetLeft, behavior: 'smooth' });
      syncTabActive(i);
    });
    tabsBar.appendChild(btn);
    return btn;
  });

  const syncTabActive = idx => {
    tabs.forEach((b, i) => {
      const on = i === idx;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  };

  let scrollEndTimer = null;
  viewport.addEventListener('scroll', () => {
    clearTimeout(scrollEndTimer);
    scrollEndTimer = setTimeout(() => {
      const vr = viewport.getBoundingClientRect();
      const mid = vr.left + vr.width / 2;
      let best = 0, bestDist = Infinity;
      slides.forEach((s, i) => {
        const r = s.getBoundingClientRect();
        const d = Math.abs(r.left + r.width / 2 - mid);
        if (d < bestDist) { bestDist = d; best = i; }
      });
      const sec = boardSections[best];
      if (sec) centerBoardActiveTabKey = sec.key;
      syncTabActive(best);
    }, 80);
  }, { passive: true });

  const applyInitialBoardScroll = () => {
    const slide = slides[initialIdx];
    if (slide) viewport.scrollTo({ left: slide.offsetLeft, behavior: 'auto' });
  };
  requestAnimationFrame(() => {
    applyInitialBoardScroll();
    requestAnimationFrame(applyInitialBoardScroll);
  });
}

function syncBoardTabState(zoneCenter) {
  // No-op — carousel handles its own state via scroll sync
}

const RULEBOOK_PDF_URL = '/static/game/b0-valeria-card-kingdoms-rulebook.pdf';


function makeResourceActionBar(state) {
  const canTake = canOfferTakeResourceAction(state);
  const resourceBar = document.createElement('div');
  resourceBar.className = 'resource-action-bar' + (canTake ? '' : ' resource-action-bar--inactive');
  const resources = crimsonSeasEnabled(state) ? ['gold', 'strength', 'magic', 'map'] : ['gold', 'strength', 'magic'];
  resources.forEach(r => {
    const lab = r.charAt(0).toUpperCase() + r.slice(1);
    const btn = promptButton('', () => {
      if (!canOfferTakeResourceAction(latestGameState)) return;
      confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'take_resource', resource: r },
        {
          title: 'Take resource?',
          message: `Take +1 ${lab} from the bank as your standard action.`,
        },
      );
    });
    btn.classList.add('resource-action-btn', `resource-action-btn--${r}`);
    btn.appendChild(document.createTextNode(`+1 ${lab}`));
    const icon = document.createElement('img');
    icon.className = 'resource-action-btn-icon';
    icon.alt = '';
    icon.src = TABLEAU_RESOURCE_ICONS[r];
    btn.appendChild(icon);
    if (!canTake) btn.disabled = true;
    resourceBar.appendChild(btn);
  });
  return resourceBar;
}

function canOfferTakeResourceAction(state) {
  if (!PLAYER_ID || !state) return false;
  if ((state.phase || '').toString() !== 'action') return false;
  const req = state.action_required || {};
  if ((req.action || '').toString() !== 'standard_action') return false;
  const reqId = req.id || '';
  if (!reqId || idsMatch(reqId, state.game_id)) return false;
  if (!idsMatch(reqId, PLAYER_ID)) return false;
  return Number(state.actions_remaining || 0) > 0;
}

// Crimson Seas "you may Sail" bonus (Dampiar's Workshop): one free Sail is
// available while the may_sail prompt is open for this player, even with 0
// regular actions remaining. Sail modals enable on this in addition to the
// normal action-phase check.
function canOfferBonusSail(state) {
  if (!PLAYER_ID || !state) return false;
  if ((state.phase || '').toString() !== 'action') return false;
  const req = state.action_required || {};
  if ((req.action || '').toString() !== 'may_sail') return false;
  const reqId = req.id || '';
  if (!reqId || idsMatch(reqId, state.game_id)) return false;
  return idsMatch(reqId, PLAYER_ID);
}

function activeTurnNamePart(state) {
  const active = (state.player_list || []).find(p => p.player_id === state.active_player_id);
  if (!active) return { hasActive: false, isMe: false, displayName: '' };
  const raw = (active.name || '').toString().trim();
  const displayName = raw || 'Player';
  const isMe = idsMatch(active.player_id, PLAYER_ID);
  return { hasActive: true, isMe, displayName };
}

/** Keep info bar compact: short name + ellipsis before "'s turn". */
function ellipsizeForTurnLabel(name, maxChars) {
  const t = String(name || '').trim();
  const m = Number(maxChars);
  const cap = Number.isFinite(m) && m > 0 ? Math.floor(m) : 8;
  if (t.length <= cap) return t;
  if (cap <= 1) return '\u2026';
  return `${t.slice(0, cap - 1)}\u2026`;
}

const INFO_BAR_TURN_NAME_MAX_CHARS = 8;

/** Full line for tooltips: "Your turn" / "Name's turn" (untruncated). */
function boardActiveTurnFullLine(state) {
  const t = activeTurnNamePart(state);
  if (!t.hasActive) return '';
  if (t.isMe) return 'Your turn';
  return `${t.displayName}'s turn`;
}

/** Short line for the main board (no turn number): "Your turn" / "Name's turn" (name truncated). */
function boardActiveTurnLine(state) {
  const t = activeTurnNamePart(state);
  if (!t.hasActive) return '';
  if (t.isMe) return 'Your turn';
  const short = ellipsizeForTurnLabel(t.displayName, INFO_BAR_TURN_NAME_MAX_CHARS);
  return `${short}'s turn`;
}

function openDiceInfoModal(state) {
  const existing = document.getElementById('dice-info-modal-overlay');
  if (existing) { existing.remove(); return; }

  const overlay = document.createElement('div');
  overlay.id = 'dice-info-modal-overlay';
  overlay.className = 'dice-info-modal-overlay';
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });

  const panel = document.createElement('div');
  panel.className = 'dice-info-modal';

  const closeBtn = document.createElement('button');
  closeBtn.className = 'card-modal-close';
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', () => overlay.remove());
  panel.appendChild(closeBtn);

  // Hosts whose contents depend on live state. We replace their innerHTML on
  // every refresh so the modal stays accurate as phase/turn change while open.
  const phase = mk('phase-label');
  panel.appendChild(phase);

  const tn = mk('turn-label');
  panel.appendChild(tn);

  const endgameHost = document.createElement('div');
  panel.appendChild(endgameHost);

  const lobby = document.createElement('a');
  lobby.href = '/';
  lobby.className = 'info-bar-lobby-btn';
  lobby.textContent = 'Lobby';
  lobby.addEventListener('click', ev => {
    ev.preventDefault();
    overlay.remove();
    if (latestGameState?.shutdown) {
      goToLobbyNow();
      return;
    }
    const ok = window.confirm(
      'Leave to the lobby and abandon this game for everyone?\n\nThe game will end for all players and redirect to the lobby after 30 seconds.'
    );
    if (!ok) return;
    abandonGame();
  });
  panel.appendChild(lobby);

  const rulebook = document.createElement('a');
  rulebook.href = RULEBOOK_PDF_URL;
  rulebook.className = 'info-bar-rulebook-btn';
  rulebook.textContent = 'Rulebook';
  rulebook.target = '_blank';
  rulebook.rel = 'noopener noreferrer';
  panel.appendChild(rulebook);

  const logHost = document.createElement('div');
  panel.appendChild(logHost);

  // Cache of the last rendered log fingerprint. Used so we can skip the
  // DOM swap when nothing changed — that's what was losing the user's scroll
  // position on every state poll while the modal was open.
  let lastLogFingerprint = null;

  function logFingerprint(arr) {
    if (!Array.isArray(arr) || !arr.length) return '0||';
    const entryText = e => ((e && typeof e === 'object' ? e.msg : e) ?? '').toString();
    const head = entryText(arr[0]);
    const tail = entryText(arr[arr.length - 1]);
    return `${arr.length}|${head}|${tail}`;
  }

  function renderFromState() {
    const s = latestGameState || state;
    if (!s) return;
    phase.textContent = fmtPhase(s.phase);
    const t = activeTurnNamePart(s);
    const turnWho = t.hasActive ? ` — ${t.isMe ? 'your' : `${t.displayName}'s`} turn` : '';
    tn.textContent = `Turn ${s.turn_number || 1}${turnWho}`;
    tn.title = tn.textContent;

    endgameHost.innerHTML = '';
    if (s.end_game_triggered) {
      const eg = mk('turn-label');
      eg.textContent = '⚑ Final round';
      eg.style.color = 'var(--gold)';
      endgameHost.appendChild(eg);
    }

    // Only rebuild the log if it actually changed, and preserve the user's
    // scroll position across the swap so polling doesn't yank them off
    // whatever entry they were reading.
    const fp = logFingerprint(s.game_log);
    if (fp !== lastLogFingerprint) {
      const existing = logHost.querySelector('.game-log');
      const prevScrollTop = existing ? existing.scrollTop : 0;
      logHost.innerHTML = '';
      const rebuilt = makeGameLog(s);
      logHost.appendChild(rebuilt);
      rebuilt.scrollTop = prevScrollTop;
      lastLogFingerprint = fp;
    }
  }

  renderFromState();
  overlay._refreshFromLiveState = renderFromState;

  overlay.appendChild(panel);
  document.body.appendChild(overlay);
}

function makeInfoBar(state) {
  const bar = mk('info-bar');

  const row = mk('info-bar-dice-row');
  const diceBtn = document.createElement('button');
  diceBtn.className = 'info-bar-dice-btn';
  const dice = mk('dice-display');
  if (state.die_one != null) {
    dice.appendChild(makeDie(state.die_one));
    dice.appendChild(makeDie(state.die_two));
    const sum = mk('die-sum');
    sum.textContent = `= ${state.die_sum}`;
    dice.appendChild(sum);
  }
  diceBtn.appendChild(dice);
  diceBtn.addEventListener('click', () => openDiceInfoModal(state));
  row.appendChild(diceBtn);

  const turnCluster = mk('info-bar-turn-cluster');
  const turnLine = mk('info-bar-turn-label');
  const turnText = boardActiveTurnLine(state);
  const turnFull = boardActiveTurnFullLine(state);
  turnLine.textContent = turnText;
  if (turnFull) turnLine.title = turnFull;
  turnCluster.appendChild(turnLine);
  if (state.end_game_triggered) {
    const fr = mk('info-bar-final-round');
    fr.textContent = '\u2691 Final round';
    fr.title = 'Final round';
    turnCluster.appendChild(fr);
  }
  row.appendChild(turnCluster);

  bar.appendChild(row);

  return bar;
}

// ── Crimson Seas island board (Sail tab) ───────────────────────────────────
// The mat artwork is scaled client-side (fit-to-height, horizontally scrollable).
// Overlaid assets stay locked to the artwork by using NORMALIZED coordinates
// (fractions 0–1 of the mat's natural size) inside a wrapper that shrink-wraps
// the rendered image, so percentages resolve against the exact image box at any
// scale. Coordinates are measured against the native-size mat image.
const SAIL_MAT_NATURAL = { w: 5173, h: 1137 };

// Asset positions measured against the native-size mat image (5173×1137). Each
// box is { left, top, w, h } in source pixels of the asset's top-left corner and
// bounding-box size; placeSailAsset() normalizes them to % of the mat so they
// stay locked to the artwork at any client-side scale.
const SAIL_LAYOUT = {
  // Araby: octagonal Goods tokens (square 224×224 art with transparency).
  goods: {
    w: 224, h: 224,
    slots: [
      { left: 218, top: 195 },
      { left: 218, top: 505 },
      { left: 218, top: 815 },
    ],
  },
  // Nae Aerie: square Tome tokens (224×224).
  tomes: {
    w: 224, h: 224,
    slots: [
      { left: 1116, top: 190 },
      { left: 1116, top: 502 },
      { left: 1116, top: 812 },
    ],
  },
  // Amarynth: rectangular Noble cards (520×814).
  nobles: {
    w: 520, h: 814,
    slots: [
      { left: 3456, top: 204 },
      { left: 4030, top: 204 },
      { left: 4604, top: 204 },
    ],
  },
  // Exekratys: oval resource pool. Box is the oval's bounding rect (corners lie
  // outside the oval); we render a centered resource readout inside it.
  exekratys: { left: 2372, top: 770, w: 720, h: 318 },
};

const SAIL_EXEKRATYS_RESOURCES = ['gold', 'strength', 'magic'];

// Goods token artwork (square PNGs with transparent octagon backgrounds).
const SAIL_GOODS_IMAGES = {
  artifacts: '/images/goods_artifacts.png',
  jewels: '/images/goods_jewels.png',
  fabrics: '/images/goods_fabrics.png',
  spices: '/images/goods_spices.png',
};

// Gold cost per Araby goods slot, top→bottom. Must match game_setup.GOODS_SLOT_COSTS.
const SAIL_GOODS_SLOT_COSTS = [6, 4, 2];

// Tome token artwork (square tiles, one per resource type).
const SAIL_TOME_IMAGES = {
  gold: '/images/tome_gold.jpg',
  magic: '/images/tome_magic.jpg',
  strength: '/images/tome_strength.jpg',
};

// Tome back, shown for a flipped (spent-this-turn) tome in the tableau.
const SAIL_TOME_BACK_IMAGE = '/images/tome_back.jpg';

// Gold cost per Nae Aerie tome slot, top→bottom. Must match game_setup.TOME_SLOT_COSTS.
const SAIL_TOME_SLOT_COSTS = [7, 5, 3];

/** Place an overlay node at a pixel box { left, top, w, h }, normalized to % of the mat. */
function placeSailAsset(overlay, box, node) {
  node.classList.add('sail-asset');
  node.style.left = `${(box.left / SAIL_MAT_NATURAL.w) * 100}%`;
  node.style.top = `${(box.top / SAIL_MAT_NATURAL.h) * 100}%`;
  node.style.width = `${(box.w / SAIL_MAT_NATURAL.w) * 100}%`;
  node.style.height = `${(box.h / SAIL_MAT_NATURAL.h) * 100}%`;
  overlay.appendChild(node);
  return node;
}

function sailBoxOf(group, slot) {
  return { left: slot.left, top: slot.top, w: group.w, h: group.h };
}

function makeSailSection(state) {
  const sec = mk('center-section board-sail');
  const lbl = mk('section-label');
  lbl.textContent = 'Sail';
  sec.appendChild(lbl);

  const wrap = mk('sail-board');
  // .sail-mat shrink-wraps the image so the overlay box matches the artwork exactly.
  const mat = mk('sail-mat');
  mat.style.aspectRatio = `${SAIL_MAT_NATURAL.w} / ${SAIL_MAT_NATURAL.h}`;
  const img = document.createElement('img');
  img.className = 'sail-board-img';
  img.src = '/images/crimson_seas_mat.jpg';
  img.alt = 'Crimson Seas island board';
  mat.appendChild(img);

  const overlay = mk('sail-overlay');
  mat.appendChild(overlay);
  renderSailAssets(overlay, state);

  wrap.appendChild(mat);
  // Vertical wheel scrolls the wide mat horizontally (same feel as the tableaus).
  wrap.addEventListener('wheel', e => {
    if (wrap.scrollWidth <= wrap.clientWidth + 1) return;
    const delta = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
    if (!delta) return;
    e.preventDefault();
    wrap.scrollLeft += delta;
  }, { passive: false });
  // Persist scroll across the periodic state-poll re-renders.
  wrap.addEventListener('scroll', () => { sailBoardScrollLeft = wrap.scrollLeft; }, { passive: true });
  const restoreSailScroll = () => {
    const max = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    wrap.scrollLeft = Math.min(sailBoardScrollLeft, max);
  };
  if (img.complete) requestAnimationFrame(restoreSailScroll);
  else img.addEventListener('load', () => requestAnimationFrame(restoreSailScroll), { once: true });
  sec.appendChild(wrap);
  return sec;
}

// Render the overlay assets. Goods/Tomes are dealt from live state; Nobles and
// the Exekratys readout are still placeholders pending their own state wiring.
function renderSailAssets(overlay, state) {
  overlay.innerHTML = '';
  const L = SAIL_LAYOUT;
  const goods = (state && state.goods_slots) || [];
  L.goods.slots.forEach((s, i) => {
    let node;
    if (goods[i]) {
      node = makeSailToken(SAIL_GOODS_IMAGES[goods[i]], goods[i], 'sail-good-token');
      // Any goods click opens the single Araby shop modal (one Sail buys any
      // number of the face-up goods together for 1 map).
      node.classList.add('sail-clickable');
      node.addEventListener('click', e => { e.stopPropagation(); openArabyGoodsModal(); });
    } else {
      node = makeSailEmptySlot();
    }
    placeSailAsset(overlay, sailBoxOf(L.goods, s), node);
  });
  const tomes = (state && state.tome_slots) || [];
  L.tomes.slots.forEach((s, i) => {
    let node;
    if (tomes[i]) {
      node = makeSailToken(SAIL_TOME_IMAGES[tomes[i]], `${tomes[i]} tome`, 'sail-tome-token');
      node.classList.add('sail-clickable');
      node.addEventListener('click', e => { e.stopPropagation(); openNaeAerieTomesModal(); });
    } else {
      node = makeSailEmptySlot();
    }
    placeSailAsset(overlay, sailBoxOf(L.tomes, s), node);
  });
  const nobles = (state && state.noble_slots) || [];
  L.nobles.slots.forEach((s, i) => {
    let node;
    if (nobles[i]) {
      node = makeSailNobleCard(nobles[i]);
      node.classList.add('sail-clickable');
      node.addEventListener('click', e => { e.stopPropagation(); openAmarynthNobleModal(i); });
    } else {
      node = makeSailEmptySlot();
    }
    placeSailAsset(overlay, sailBoxOf(L.nobles, s), node);
  });
  const exe = makeSailExekratysReadout(state);
  exe.classList.add('sail-clickable');
  exe.addEventListener('click', e => { e.stopPropagation(); openExekratysSailModal(); });
  placeSailAsset(overlay, L.exekratys, exe);
}

// An image token (Goods/Tomes) filling its slot box.
function makeSailToken(src, alt, extraClass) {
  const wrap = mk(`sail-token ${extraClass || ''}`);
  const img = document.createElement('img');
  img.className = 'sail-token-img';
  img.src = src || '';
  img.alt = alt || '';
  wrap.appendChild(img);
  return wrap;
}

// Faint outline for an empty slot (e.g. supply exhausted near end-game).
function makeSailEmptySlot() {
  return mk('sail-slot-empty');
}

// Click any face-up Araby goods to open the shop. One Sail (1 map) buys any
// subset of the 3 face-up goods, each at its slot's gold price.
function openArabyGoodsModal() {
  openSailShopModal({
    title: 'Sail to Araby',
    noun: 'Goods',
    actionType: 'buy_goods',
    slotsKey: 'goods_slots',
    costs: SAIL_GOODS_SLOT_COSTS,
    costsForPlayer: (player, state) => {
      const tn = Number(state?.turn_number ?? 0);
      const discounted = player && hasActionEffectFlag(player, 'action.portofdrake', tn);
      return discounted ? SAIL_GOODS_SLOT_COSTS.map(c => Math.max(0, c - 1)) : SAIL_GOODS_SLOT_COSTS;
    },
    images: SAIL_GOODS_IMAGES,
    label: t => t.charAt(0).toUpperCase() + t.slice(1),
  });
}

// Click any face-up Nae Aerie tome to open the shop. Identical to Araby but for
// tomes (slot costs 7/5/3).
function openNaeAerieTomesModal() {
  openSailShopModal({
    title: 'Sail to Nae Aerie',
    noun: 'Tomes',
    actionType: 'buy_tomes',
    slotsKey: 'tome_slots',
    costs: SAIL_TOME_SLOT_COSTS,
    costsForPlayer: (player, state) => {
      const tn = Number(state?.turn_number ?? 0);
      const discounted = player && hasActionEffectFlag(player, 'action.browncoatssanctum', tn);
      return discounted ? SAIL_TOME_SLOT_COSTS.map(c => Math.max(0, c - 1)) : SAIL_TOME_SLOT_COSTS;
    },
    images: SAIL_TOME_IMAGES,
    label: t => `${t.charAt(0).toUpperCase() + t.slice(1)} Tome`,
  });
}

// Sail-to-Amarynth: rescue 1 Noble from a face-up slot. Costs 1 map plus
// (9 + nobles already in your tableau) of one chosen resource type.
function openAmarynthNobleModal(slotIndex) {
  if (getVisiblePromptOverlay()) return;
  if (document.getElementById('card-modal-overlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';
  const modal = mk('card-modal sail-shop-modal sail-noble-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const labels = { gold: 'Gold', strength: 'Strength', magic: 'Magic' };
  const scoreKey = { gold: 'gold_score', strength: 'strength_score', magic: 'magic_score' };
  // Saved (toggled-off) tome indices per type; default is "used" (tome-first).
  const savedTomes = { gold: new Set(), strength: new Set(), magic: new Set() };

  function render() {
    modal.innerHTML = '';
    const state = latestGameState || {};
    const noble = (state.noble_slots || [])[slotIndex] || null;
    const player = (state.player_list || []).find(p => idsMatch(p.player_id, PLAYER_ID)) || null;
    const ownedNobles = (player && Array.isArray(player.owned_nobles)) ? player.owned_nobles.length : 0;
    const playerMap = Number(player && player.map_score || 0);
    const canAct = canOfferTakeResourceAction(state) || canOfferBonusSail(state);
    // Murat Reis (Domain 73) waives the "+Wild" surcharge (+1 per owned Noble),
    // leaving a flat 9 of one resource type.
    const tn = Number(state?.turn_number ?? 0);
    const muratReis = player && hasActionEffectFlag(player, 'action.muratreis', tn);
    const surcharge = muratReis ? 0 : ownedNobles;
    const cost = 9 + surcharge;
    const tomeAvail = faceUpTomeCountsForPlayer(player);
    const tomeUsed = {
      gold: Math.max(0, tomeAvail.gold - savedTomes.gold.size),
      strength: Math.max(0, tomeAvail.strength - savedTomes.strength.size),
      magic: Math.max(0, tomeAvail.magic - savedTomes.magic.size),
    };

    const heading = document.createElement('h2');
    heading.className = 'modal-card-name';
    heading.textContent = 'Sail to Amarynth';
    modal.appendChild(heading);

    if (!noble) {
      const empty = mk('sail-shop-sub');
      empty.textContent = 'That noble slot is empty.';
      modal.appendChild(empty);
    } else {
      const img = document.createElement('img');
      img.className = 'sail-noble-modal-img';
      img.src = `/card-image/noble/${noble.noble_id}`;
      img.alt = noble.name || 'Noble';
      modal.appendChild(img);

      const sub = mk('sail-shop-sub');
      sub.textContent = `Rescue costs ${cost} of one resource type + 1 map`
        + (muratReis && ownedNobles
          ? ` (Murat Reis: flat 9, +Wild surcharge waived).`
          : (ownedNobles ? ` (9 + ${ownedNobles} noble${ownedNobles === 1 ? '' : 's'} in your tableau).` : '.'));
      modal.appendChild(sub);

      const list = mk('sail-shop-list');
      SAIL_EXEKRATYS_RESOURCES.forEach(res => {
        const have = Number(player && player[scoreKey[res]] || 0);
        const tomeApplied = Math.min(tomeUsed[res] || 0, cost);
        const bankNeeded = Math.max(0, cost - tomeApplied);
        const item = mk('sail-shop-item sail-exe-item');
        const icon = document.createElement('img');
        icon.className = 'sail-shop-item-img';
        icon.src = TABLEAU_RESOURCE_ICONS[res] || '';
        icon.alt = res;
        const meta = mk('sail-shop-item-meta');
        const nm = mk('sail-shop-item-name');
        nm.textContent = `Pay with ${labels[res]}`;
        const cst = mk('sail-shop-item-cost');
        cst.textContent = tomeApplied
          ? `${cost} ${labels[res]} (${tomeApplied} from tomes, ${bankNeeded} treasury; have ${have}) + 1 map`
          : `${cost} ${labels[res]} (have ${have}) + 1 map`;
        meta.appendChild(nm);
        meta.appendChild(cst);
        item.appendChild(icon);
        item.appendChild(meta);
        const enabled = canAct && have >= bankNeeded && playerMap >= 1;
        if (enabled) {
          item.classList.add('sail-clickable');
          item.addEventListener('click', () => {
            const action = { player_id: PLAYER_ID, action_type: 'rescue_noble', slot_index: slotIndex, resource: res };
            if (tomeApplied > 0) action.tome_payment = { gold: 0, strength: 0, magic: 0, [res]: tomeApplied };
            postGameAction(action);
            dismissCardInspectModal();
          });
        } else {
          item.classList.add('is-disabled');
        }
        list.appendChild(item);
      });
      modal.appendChild(list);

      // Tome chips (one per face-up tome, grouped by type). A tome is spent
      // only if you pay the matching resource type; default is "used".
      if ((tomeAvail.gold + tomeAvail.strength + tomeAvail.magic) > 0) {
        const trow = mk('market-tome-row');
        const tlbl = mk('market-tome-label');
        tlbl.textContent = 'Tomes';
        trow.appendChild(tlbl);
        const tchips = mk('market-tome-chips');
        ['gold', 'strength', 'magic'].forEach(type => {
          for (let i = 0; i < (tomeAvail[type] || 0); i++) {
            const used = !savedTomes[type].has(i);
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = `market-tome-chip market-tome-chip--${type} ${used ? 'is-used' : 'is-saved'}`;
            chip.disabled = !canAct;
            const cimg = document.createElement('img');
            cimg.src = SAIL_TOME_IMAGES[type] || '';
            cimg.alt = `${type} tome`;
            chip.appendChild(cimg);
            chip.title = used ? `${type} tome — used if you pay ${labels[type]} (click to save)` : `${type} tome — saved (click to use)`;
            chip.addEventListener('click', e => {
              e.stopPropagation();
              if (savedTomes[type].has(i)) savedTomes[type].delete(i); else savedTomes[type].add(i);
              render();
            });
            tchips.appendChild(chip);
          }
        });
        trow.appendChild(tchips);
        modal.appendChild(trow);
      }
    }

    const footer = mk('sail-shop-footer');
    const actions = mk('sail-shop-actions');
    actions.appendChild(promptButton('Cancel', () => dismissCardInspectModal(), true));
    footer.appendChild(actions);
    modal.appendChild(footer);

    if (!canAct) {
      const note = mk('sail-shop-note');
      note.textContent = 'You can rescue a noble on your turn during the action phase.';
      modal.appendChild(note);
    } else if (playerMap < 1) {
      const note = mk('sail-shop-note');
      note.textContent = 'You need 1 map to sail.';
      modal.appendChild(note);
    }
  }

  overlay._refreshFromLiveState = render;
  render();
  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

// Sail-to-Exekratys: drain ALL of one chosen resource type from the pool for
// 1 map. One button per resource shows how much would be received.
function openExekratysSailModal() {
  if (getVisiblePromptOverlay()) return;
  if (document.getElementById('card-modal-overlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';
  const modal = mk('card-modal sail-shop-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const labels = { gold: 'Gold', strength: 'Strength', magic: 'Magic' };

  function render() {
    modal.innerHTML = '';
    const state = latestGameState || {};
    const pool = state.exekratys_resources || {};
    const player = (state.player_list || []).find(p => idsMatch(p.player_id, PLAYER_ID)) || null;
    const playerMap = Number(player && player.map_score || 0);
    const canAct = canOfferTakeResourceAction(state) || canOfferBonusSail(state);

    const heading = document.createElement('h2');
    heading.className = 'modal-card-name';
    heading.textContent = 'Sail to Exekratys';
    modal.appendChild(heading);

    const sub = mk('sail-shop-sub');
    sub.textContent = 'Take all of one resource type from the island (costs 1 map).';
    modal.appendChild(sub);

    const list = mk('sail-shop-list');
    SAIL_EXEKRATYS_RESOURCES.forEach(res => {
      const amount = Number(pool[res] || 0);
      const item = mk('sail-shop-item sail-exe-item');
      const img = document.createElement('img');
      img.className = 'sail-shop-item-img';
      img.src = TABLEAU_RESOURCE_ICONS[res] || '';
      img.alt = res;
      const meta = mk('sail-shop-item-meta');
      const nm = mk('sail-shop-item-name');
      nm.textContent = labels[res] || res;
      const cst = mk('sail-shop-item-cost');
      cst.textContent = `Take ${amount} (1 map)`;
      meta.appendChild(nm);
      meta.appendChild(cst);
      item.appendChild(img);
      item.appendChild(meta);
      const enabled = canAct && playerMap >= 1;
      if (enabled) {
        item.classList.add('sail-clickable');
        item.addEventListener('click', () => {
          postGameAction({ player_id: PLAYER_ID, action_type: 'sail_exekratys', resource: res });
          dismissCardInspectModal();
        });
      } else {
        item.classList.add('is-disabled');
      }
      list.appendChild(item);
    });
    modal.appendChild(list);

    const footer = mk('sail-shop-footer');
    const actions = mk('sail-shop-actions');
    actions.appendChild(promptButton('Cancel', () => dismissCardInspectModal(), true));
    footer.appendChild(actions);
    modal.appendChild(footer);

    if (!canAct) {
      const note = mk('sail-shop-note');
      note.textContent = 'You can sail on your turn during the action phase.';
      modal.appendChild(note);
    } else if (playerMap < 1) {
      const note = mk('sail-shop-note');
      note.textContent = 'You need 1 map to sail.';
      modal.appendChild(note);
    }
  }

  overlay._refreshFromLiveState = render;
  render();
  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

// Generic Sail shop: pick any subset of the 3 face-up tokens to buy in one Sail
// action (gold per slot + 1 map total). Re-renders live from state.
function openSailShopModal(cfg) {
  if (getVisiblePromptOverlay()) return;
  if (document.getElementById('card-modal-overlay')) return;

  const selected = new Set();
  // Saved (toggled-off) tome indices. Goods/Tomes cost gold; Gold tomes pay it
  // directly and Magic tomes pay it as wild (magic is wild for gold). Default is
  // "used" (tome-first); the player clicks a chip to save it for later.
  const savedGoldTomes = new Set();
  const savedMagicTomes = new Set();
  // Manual gold/magic payment overrides (null => use the suggested gold-first
  // split). Cleared whenever the selection or tome toggles change so the
  // suggestion re-computes against the new cost / usable tomes.
  const payOverride = { gold: null, magic: null };
  function resetPayOverride() { payOverride.gold = null; payOverride.magic = null; }

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';
  const modal = mk('card-modal sail-shop-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const nounLower = cfg.noun.toLowerCase();

  function render() {
    modal.innerHTML = '';
    const state = latestGameState || {};
    const slots = state[cfg.slotsKey] || [];
    const player = (state.player_list || []).find(p => idsMatch(p.player_id, PLAYER_ID)) || null;
    const playerGold = Number(player && player.gold_score || 0);
    const playerMap = Number(player && player.map_score || 0);
    const canAct = canOfferTakeResourceAction(state) || canOfferBonusSail(state);
    const costs = typeof cfg.costsForPlayer === 'function'
      ? cfg.costsForPlayer(player, state)
      : cfg.costs;

    const heading = document.createElement('h2');
    heading.className = 'modal-card-name';
    heading.textContent = cfg.title;
    modal.appendChild(heading);

    const sub = mk('sail-shop-sub');
    sub.textContent = `Buy any number of ${cfg.noun} in one Sail (costs 1 map total).`;
    modal.appendChild(sub);

    const list = mk('sail-shop-list');
    let anyAvail = false;
    slots.forEach((type, i) => {
      if (!type) return;
      anyAvail = true;
      const cost = costs[i] != null ? costs[i] : 0;
      const isSel = selected.has(i);
      const item = mk('sail-shop-item' + (isSel ? ' is-selected' : ''));
      const img = document.createElement('img');
      img.className = 'sail-shop-item-img';
      img.src = cfg.images[type] || '';
      img.alt = type;
      const meta = mk('sail-shop-item-meta');
      const nm = mk('sail-shop-item-name');
      nm.textContent = cfg.label(type);
      const cst = mk('sail-shop-item-cost');
      cst.textContent = `${cost} gold`;
      meta.appendChild(nm);
      meta.appendChild(cst);
      const check = mk('sail-shop-item-check');
      check.textContent = isSel ? '✓' : '';
      item.appendChild(img);
      item.appendChild(meta);
      item.appendChild(check);
      item.addEventListener('click', () => {
        if (selected.has(i)) selected.delete(i); else selected.add(i);
        resetPayOverride();
        render();
      });
      list.appendChild(item);
    });
    if (!anyAvail) {
      const empty = mk('sail-shop-sub');
      empty.textContent = `No ${nounLower} are currently available.`;
      list.appendChild(empty);
    }
    modal.appendChild(list);

    const totalGold = [...selected].reduce(
      (sum, i) => sum + (costs[i] != null ? costs[i] : 0), 0);
    const playerMagic = Number(player && player.magic_score || 0);

    // Tomes the player can spend toward the gold cost (tome-first). Gold tomes
    // pay gold directly; Magic tomes pay as wild. A "used" tome raises the
    // matching pay field's max (treasury + usable tomes) and is attributed from
    // that field on submit, exactly like the hire/build market panel.
    const tomeCounts = faceUpTomeCountsForPlayer(player);
    const availGoldTomes = tomeCounts.gold;
    const availMagicTomes = tomeCounts.magic;
    const usedGoldTomes = Math.max(0, availGoldTomes - savedGoldTomes.size);
    const usedMagicTomes = Math.max(0, availMagicTomes - savedMagicTomes.size);
    const effGold = playerGold + usedGoldTomes;
    const effMagic = playerMagic + usedMagicTomes;

    function renderTomeRow(label, count, savedSet, imgSrc, alt) {
      if (count <= 0) return;
      const trow = mk('market-tome-row');
      const tlbl = mk('market-tome-label');
      tlbl.textContent = label;
      trow.appendChild(tlbl);
      const tchips = mk('market-tome-chips');
      const cls = alt === 'magic tome' ? 'market-tome-chip--magic' : 'market-tome-chip--gold';
      for (let i = 0; i < count; i++) {
        const used = !savedSet.has(i);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = `market-tome-chip ${cls} ${used ? 'is-used' : 'is-saved'}`;
        chip.disabled = !canAct;
        const cimg = document.createElement('img');
        cimg.src = imgSrc;
        cimg.alt = alt;
        chip.appendChild(cimg);
        chip.title = used ? `${label} — used to pay (click to save)` : `${label} — saved (click to use)`;
        chip.addEventListener('click', e => {
          e.stopPropagation();
          if (savedSet.has(i)) savedSet.delete(i); else savedSet.add(i);
          resetPayOverride();
          render();
        });
        tchips.appendChild(chip);
      }
      trow.appendChild(tchips);
      modal.appendChild(trow);
    }

    renderTomeRow('Gold tomes', availGoldTomes, savedGoldTomes, SAIL_TOME_IMAGES.gold, 'gold tome');
    renderTomeRow('Magic tomes', availMagicTomes, savedMagicTomes, SAIL_TOME_IMAGES.magic, 'magic tome');

    // Suggested gold-first split (used until the player edits a field).
    const suggGold = Math.min(effGold, totalGold);
    const suggMagic = totalGold - suggGold;
    const goldVal = payOverride.gold != null
      ? clampPayInt(payOverride.gold, 0, effGold) : suggGold;
    const magicVal = payOverride.magic != null
      ? clampPayInt(payOverride.magic, 0, effMagic) : suggMagic;

    const payRow = mk('market-pay-row sail-shop-pay-row');
    payRow.appendChild(
      mkPayField('Gold', 'pay-g', 0, effGold, goldVal, !canAct, 'Gold to spend (includes used Gold tomes)', 'gold', playerGold));
    payRow.appendChild(
      mkPayField('Magic', 'pay-m', 0, effMagic, magicVal, !canAct, 'Magic to spend as wild (includes used Magic tomes)', 'magic', playerMagic));
    modal.appendChild(payRow);

    const footer = mk('sail-shop-footer');
    const total = mk('sail-shop-total');
    footer.appendChild(total);

    const buyBtn = promptButton('Buy', () => {
      if (buyBtn.disabled) return;
      const { gp, mp, tGold, tMagic } = readPay();
      const action = { player_id: PLAYER_ID, action_type: cfg.actionType, slot_indices: [...selected],
        payment: { gold: gp, strength: 0, magic: mp } };
      if (tGold > 0 || tMagic > 0) {
        action.tome_payment = { gold: tGold, strength: 0, magic: tMagic };
      }
      postGameAction(action);
      dismissCardInspectModal();
    });
    const cancelBtn = promptButton('Cancel', () => dismissCardInspectModal(), true);
    const actions = mk('sail-shop-actions');
    actions.appendChild(cancelBtn);
    actions.appendChild(buyBtn);
    footer.appendChild(actions);
    modal.appendChild(footer);

    const note = mk('sail-shop-note');
    modal.appendChild(note);

    const goldInput = payRow.querySelector('.pay-g');
    const magicInput = payRow.querySelector('.pay-m');

    function readPay() {
      const gp = goldInput ? clampPayInt(goldInput.value, 0, effGold) : 0;
      const mp = magicInput ? clampPayInt(magicInput.value, 0, effMagic) : 0;
      const tGold = Math.min(usedGoldTomes, gp);
      const tMagic = Math.min(usedMagicTomes, mp);
      return { gp, mp, tGold, tMagic };
    }

    // Live update of the total line / note / Buy button as the player types,
    // without rebuilding the modal (which would steal input focus).
    function syncPay() {
      const { gp, mp, tGold, tMagic } = readPay();
      const sum = gp + mp;
      const needsMinGold = mp > 0 && gp < 1;
      const covered = selected.size > 0 && sum === totalGold && !needsMinGold;

      if (selected.size) {
        const parts = [];
        if (tGold) parts.push(`${tGold} gold tome${tGold > 1 ? 's' : ''}`);
        if (gp - tGold) parts.push(`${gp - tGold} treasury gold`);
        if (tMagic) parts.push(`${tMagic} magic tome${tMagic > 1 ? 's' : ''}`);
        if (mp - tMagic) parts.push(`${mp - tMagic} treasury magic`);
        total.textContent = parts.length
          ? `Paying: ${parts.join(', ')} (need ${totalGold} gold) + 1 map`
          : `Total: ${totalGold} gold + 1 map`;
      } else {
        total.textContent = `Select ${nounLower} to buy`;
      }

      let noteText = '';
      if (!canAct) noteText = `You can buy ${nounLower} on your turn during the action phase.`;
      else if (selected.size && needsMinGold) noteText = 'You must pay at least 1 gold to use magic as wild.';
      else if (selected.size && sum !== totalGold) noteText = `Gold + magic must total ${totalGold}.`;
      else if (selected.size && playerMap < 1) noteText = 'You need 1 map to sail.';
      note.textContent = noteText;
      note.style.display = noteText ? '' : 'none';

      buyBtn.disabled = !(canAct && covered && playerMap >= 1);
    }

    function onPayInput(e) {
      const el = e.target;
      const val = clampPayInt(el.value, 0, el === goldInput ? effGold : effMagic);
      if (el === goldInput) payOverride.gold = val;
      else payOverride.magic = val;
      syncPay();
    }
    if (goldInput) goldInput.addEventListener('input', onPayInput);
    if (magicInput) magicInput.addEventListener('input', onPayInput);

    syncPay();
  }

  overlay._refreshFromLiveState = render;
  render();
  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

// A dealt Noble card shown face-up in its Amarynth slot.
function makeSailNobleCard(noble) {
  const card = mk('sail-card sail-noble');
  const img = document.createElement('img');
  img.className = 'sail-noble-img';
  img.src = `/card-image/noble/${noble.noble_id}`;
  img.alt = noble.name || 'Noble';
  card.appendChild(img);
  return card;
}

// A no-image placeholder card sized to fill its slot box.
function makeSailPlaceholderCard(label, extraClass, idx) {
  const card = mk(`sail-card ${extraClass}`);
  const name = mk('sail-card-label');
  name.textContent = idx != null ? `${label} ${idx + 1}` : label;
  card.appendChild(name);
  return card;
}

// Exekratys resource pool: a centered row of resource icons + counts, inset from
// the oval's bounding box so the readout sits comfortably inside the oval.
function makeSailExekratysReadout(state) {
  const counts = (state && state.exekratys_resources) || {};
  const wrap = mk('sail-exekratys');
  SAIL_EXEKRATYS_RESOURCES.forEach(res => {
    const chip = mk('sail-exekratys-chip');
    const icon = document.createElement('img');
    icon.className = 'sail-exekratys-icon';
    icon.src = TABLEAU_RESOURCE_ICONS[res];
    icon.alt = res;
    const count = mk('sail-exekratys-count');
    count.textContent = String(counts[res] || 0);
    chip.appendChild(icon);
    chip.appendChild(count);
    wrap.appendChild(chip);
  });
  return wrap;
}

function makeGridSection(label, grid, _type, _cols, extraClass) {
  const sec = mk('center-section' + (extraClass ? ` ${extraClass}` : ''));
  const lbl = mk('section-label');
  lbl.textContent = label;
  sec.appendChild(lbl);
  const row = mk('grid-row');
  grid.forEach(stack => row.appendChild(makeStack(stack)));
  sec.appendChild(row);
  return sec;
}

function makeCitizenSection(grid) {
  const sec = mk('center-section board-citizens');
  const lbl = mk('section-label');
  lbl.textContent = 'Citizens';
  sec.appendChild(lbl);

  const row1 = mk('grid-row citizen-row-first');
  const row2 = mk('grid-row citizen-row-second');
  grid.slice(0, 5).forEach(s => row1.appendChild(makeStack(s)));
  grid.slice(5).forEach(s  => row2.appendChild(makeStack(s)));
  sec.appendChild(row1);
  if (grid.length > 5) sec.appendChild(row2);
  return sec;
}

function makeStack(stack) {
  if (!stack || stack.length === 0) {
    return mk('card-slot-empty');
  }
  const wrap = mk('grid-stack');
  wrap.appendChild(makeCard(stack[stack.length - 1], 'grid'));
  if (stack.length > 1) {
    const badge = mk('stack-depth');
    badge.textContent = `×${stack.length}`;
    wrap.appendChild(badge);
  }
  return wrap;
}

// Group identical owned cards (same logic as dev-client tableau); citizens also key on is_flipped.
// Citizens get a roll-based primary sort key (ascending by trigger value, highest
// positive roll_match per card) so the tableau lays them out in dice-roll order.
// For non-citizens the roll key ties out and behavior falls back to name/id.
function groupCardsForTableau(cards) {
  const arr = Array.isArray(cards) ? cards : [];
  const map = new Map();
  arr.forEach(c => {
    if (!c || typeof c !== 'object') return;
    const name = (c.name || c.title || '').toString().trim();
    const id = c.starter_id || c.citizen_id || c.monster_id || c.event_id || c.domain_id || c.duke_id || c.id || '';
    const isCitizenKey = c.citizen_id !== undefined && c.citizen_id !== null;
    const flipSeg = isCitizenKey ? `||flip:${c.is_flipped ? 1 : 0}` : '';
    const key = `${name}||${id}${flipSeg}`;
    const cur = map.get(key);
    if (cur) cur.count += 1;
    else map.set(key, {
      card: c,
      count: 1,
      sortName: name.toLowerCase(),
      sortId: String(id),
      sortRoll: isCitizenKey ? bestCitizenRollSortValue(c) : Number.POSITIVE_INFINITY,
    });
  });
  if (map.size === 0 && arr.length) return null;
  return Array.from(map.values()).sort((a, b) => {
    if (a.sortRoll !== b.sortRoll) return a.sortRoll - b.sortRoll;
    if (a.sortName < b.sortName) return -1;
    if (a.sortName > b.sortName) return 1;
    if (a.sortId < b.sortId) return -1;
    if (a.sortId > b.sortId) return 1;
    return 0;
  });
}

// Highest positive dice-roll trigger value for a citizen. Citizens may trigger
// on roll_match1 and/or roll_match2; pick the largest positive value so cards
// with multiple triggers sort by their best (highest) trigger. Citizens with
// no positive roll match fall to the end of the citizen group.
function bestCitizenRollSortValue(card) {
  let best = Number.NEGATIVE_INFINITY;
  for (const v of [card && card.roll_match1, card && card.roll_match2]) {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0 && n > best) best = n;
  }
  return best === Number.NEGATIVE_INFINITY ? Number.POSITIVE_INFINITY : best;
}

// One card image with optional ×N badge (matches center-board stacks).
function makeTableauStack(card, count, mode) {
  const wrap = mk('grid-stack');
  wrap.appendChild(makeCard(card, mode));
  if (count > 1) {
    const badge = mk('stack-depth');
    badge.textContent = `×${count}`;
    wrap.appendChild(badge);
  }
  return wrap;
}

/**
 * Vertical fan of cards used for slain-monster piles in the tableau.
 *
 * Cards are appended in input order, so index 0 sits at the top of the slot
 * and the highest index sits at the bottom. Per-card z-index makes later
 * (newer) cards paint on top of earlier (older) ones in their overlap region,
 * so the newest slain monster is fully visible at the bottom and older
 * monsters show only their top edges above it.
 *
 *   N == 1   → render a single normal-height card (one row, like a citizen).
 *   N == 2   → two full cards stacked top-to-bottom with no overlap, filling
 *              the 1×2 slot.
 *   N >= 3   → cards begin to overlap vertically. The whole fan still fits in
 *              the 1×2 (100cqh) slot, so as more cards are added each older
 *              card shows a smaller sliver above the one below it.
 *
 * Stays compatible with the shared stack-inspect click handler via the
 * `tableau-card-stack[data-stack]` selector; each child card carries its
 * index on `data-stack-index` so clicking a partially-visible card opens the
 * inspect modal on that card.
 */
function makeTableauMonsterFan(cards, mode) {
  const arr = Array.isArray(cards) ? cards.filter(Boolean) : [];
  if (arr.length === 0) return mk('grid-stack');
  if (arr.length === 1) return makeTableauStack(arr[0], 1, mode);

  const wrap = mk('grid-stack tableau-card-stack tableau-card-fan');
  wrap.dataset.stack = JSON.stringify(arr);

  // Step between consecutive card top edges, expressed in cqh of the carousel
  // tableau container. Card height is 50cqh; the slot height is 100cqh. To fit
  // every card we need (N-1)*step + 50cqh = 100cqh → step = 50/(N-1) cqh.
  // The negative top margin each non-first card uses is then `cardHeight - step`,
  // i.e. how much the next card overlaps the previous one.
  const stepCqh = 50 / (arr.length - 1);
  const overlapCqh = 50 - stepCqh;
  wrap.style.setProperty('--fan-overlap', `${overlapCqh}cqh`);

  arr.forEach((card, i) => {
    const cardEl = makeCard(card, mode);
    cardEl.classList.add('tableau-fan-card');
    cardEl.dataset.stackIndex = String(i);
    cardEl.style.zIndex = String(i + 1);
    wrap.appendChild(cardEl);
  });
  return wrap;
}

function makeGameLog(state) {
  const log = mk('game-log');
  (state.game_log || []).slice().reverse().forEach(entry => {
    const line = mk('log-entry');
    line.textContent = entry.msg ?? entry;
    log.appendChild(line);
  });
  return log;
}

function makeDie(val) {
  const d = mk('die');
  d.textContent = val;
  return d;
}

// ── Player header / tableau score strip ──────────────────────────────────
const TABLEAU_RESOURCE_ICONS = {
  gold: '/images/gold_icon.jpg',
  magic: '/images/magic_icon.png',
  strength: '/images/strength_icon.png',
  victory: '/images/vp_icon.png',
  map: '/images/map.png',
};

function makeResourceScorePill(cls, val, fullName, iconSrc) {
  const pill = mk('score-pill ' + cls);
  const n = Number(val ?? 0);
  const tip = `${n} times ${fullName}`;
  pill.title = tip;
  pill.setAttribute('aria-label', tip);
  pill.appendChild(document.createTextNode(String(n)));
  pill.appendChild(document.createTextNode(' \u00D7 '));
  const img = document.createElement('img');
  img.className = 'score-pill-resource-icon';
  img.alt = '';
  img.src = iconSrc;
  pill.appendChild(img);
  return pill;
}

function makeVpScorePill(val) {
  const pill = mk('score-pill victory');
  const n = Number(val ?? 0);
  const tip = `${n} times Victory Points`;
  pill.title = tip;
  pill.setAttribute('aria-label', tip);
  pill.appendChild(document.createTextNode(String(n)));
  pill.appendChild(document.createTextNode(' \u00D7 '));
  const img = document.createElement('img');
  img.className = 'score-pill-resource-icon';
  img.alt = '';
  img.src = TABLEAU_RESOURCE_ICONS.victory;
  pill.appendChild(img);
  return pill;
}

/** Inline resource display for card modals (matches tableau icons × coloring). */
function makeModalResourceInline(kind, num, cls, leadingPlus) {
  const wrap = document.createElement('span');
  wrap.className = cls ? `modal-stat-value ${cls} modal-resource-inline` : 'modal-stat-value modal-resource-inline';
  if (leadingPlus) wrap.appendChild(document.createTextNode('+'));
  wrap.appendChild(document.createTextNode(String(num)));
  wrap.appendChild(document.createTextNode(' \u00D7 '));
  const img = document.createElement('img');
  img.className = 'modal-resource-icon';
  img.alt = '';
  img.src = TABLEAU_RESOURCE_ICONS[kind];
  const names = { gold: 'Gold', strength: 'Strength', magic: 'Magic', map: 'Map' };
  const n = Number(num);
  const tip = `${n} times ${names[kind]}`;
  wrap.title = tip;
  wrap.setAttribute('aria-label', tip);
  wrap.appendChild(img);
  return wrap;
}

function makeModalVpValue(num, cls, leadingPlus) {
  const wrap = document.createElement('span');
  wrap.className = cls
    ? `modal-stat-value ${cls} modal-resource-inline`
    : 'modal-stat-value modal-resource-inline';
  if (leadingPlus) wrap.appendChild(document.createTextNode('+'));
  const n = Number(num);
  wrap.appendChild(document.createTextNode(String(n)));
  wrap.appendChild(document.createTextNode(' \u00D7 '));
  const img = document.createElement('img');
  img.className = 'modal-resource-icon';
  img.alt = '';
  img.src = TABLEAU_RESOURCE_ICONS.victory;
  const tip = `${n} times Victory Points`;
  wrap.title = tip;
  wrap.setAttribute('aria-label', tip);
  wrap.appendChild(img);
  return wrap;
}

function createModalStatValueEl(row) {
  if (row.resource === 'gold' || row.resource === 'strength' || row.resource === 'magic') {
    return makeModalResourceInline(row.resource, row.value, row.cls, row.leadingPlus);
  }
  if (row.resource === 'vp') {
    return makeModalVpValue(row.value, row.cls, row.leadingPlus);
  }
  const v = document.createElement('span');
  v.className = row.cls ? `modal-stat-value ${row.cls}` : 'modal-stat-value';
  if (row.html != null) v.innerHTML = row.html;
  else v.textContent = row.value;
  return v;
}

function appendCardModalStatRows(infoEl, card) {
  buildCardStats(card).forEach(row => {
    const r = mk('modal-stat-row');
    const l = document.createElement('span');
    l.className = 'modal-stat-label';
    l.textContent = row.label;
    r.appendChild(l);
    r.appendChild(createModalStatValueEl(row));
    infoEl.appendChild(r);
  });
}

function makeHeader(player, state) {
  const h = mk('player-header');

  const nameRow = mk('player-header-name-row');

  const name = mk('player-name');
  if (player.is_first) {
    name.classList.add('is-first');
    const star = mk('player-first-star');
    star.textContent = '★';
    star.title = 'This player went first';
    star.setAttribute('aria-label', 'This player went first');
    name.appendChild(star);
  }
  name.appendChild(document.createTextNode(player.name));
  nameRow.appendChild(name);

  if (PLAYER_ID && idsMatch(player.player_id, PLAYER_ID)) {
    const youTag = mk('player-you-tag');
    youTag.textContent = 'You';
    youTag.title = 'This is your tableau';
    youTag.setAttribute('aria-label', 'This is your tableau');
    nameRow.appendChild(youTag);
  }

  if (isActiveTurnForPlayer(player, state)) {
    const actions = Math.max(0, Number(state?.actions_remaining || 0));
    const actionsBadge = mk('tableau-actions-remaining');
    actionsBadge.textContent = `${actions} action${actions === 1 ? '' : 's'} remaining`;
    actionsBadge.title = 'Standard actions remaining in this turn (turn ends when this hits 0).';
    actionsBadge.setAttribute(
      'aria-label',
      `${actions} standard action${actions === 1 ? '' : 's'} remaining this turn`,
    );
    nameRow.appendChild(actionsBadge);

    const tim = mk('tableau-inactive-timer');
    tim.title =
      'Hurry-up timer for this action. If it hits 0:00 the server auto-takes +1 of the active player\'s lowest resource.';
    tim.setAttribute(
      'aria-label',
      'Hurry-up timer for this action. If it hits zero the active player auto-takes their lowest resource.',
    );
    nameRow.appendChild(tim);
  }

  if (state && state.resting_player_id != null && idsMatch(state.resting_player_id, player.player_id)) {
    const restBadge = mk('player-resting-badge');
    restBadge.textContent = 'Resting';
    restBadge.title =
      '5-player rule: the seat immediately before the active player skips harvest this turn.';
    restBadge.setAttribute(
      'aria-label',
      'Resting (5-player rule: skips harvest this turn)',
    );
    nameRow.appendChild(restBadge);
  }

  h.appendChild(nameRow);

  const resRow = mk('player-header-res-row');
  resRow.appendChild(makeResourceScorePill('gold', player.gold_score, 'Gold', TABLEAU_RESOURCE_ICONS.gold));
  resRow.appendChild(makeResourceScorePill('strength', player.strength_score, 'Strength', TABLEAU_RESOURCE_ICONS.strength));
  resRow.appendChild(makeResourceScorePill('magic', player.magic_score, 'Magic', TABLEAU_RESOURCE_ICONS.magic));
  if (crimsonSeasEnabled(state)) {
    resRow.appendChild(makeResourceScorePill('map', player.map_score, 'Map', TABLEAU_RESOURCE_ICONS.map));
  }
  resRow.appendChild(makeVpScorePill(player.victory_score));
  h.appendChild(resRow);

  return h;
}
// ── Card factory ──────────────────────────────────────────────────────────
/** Viewer cannot see the card face (face-down domain pile, future hidden stacks, etc.).
 *  Flipped tableau citizens are deliberately excluded: they are physically face-down
 *  but the viewer knows exactly which card it is (it stays on the same tableau slot). */
function cardObscuredFromViewer(card) {
  if (!card || typeof card !== 'object') return false;
  if (card.is_flipped) return false;
  return card.is_visible === false;
}

function isDomainStackFaceDown(card) {
  return card?.domain_id != null && cardObscuredFromViewer(card);
}

function obscuredTypeBackUrl(card) {
  if (!card || typeof card !== 'object') return '/images/domains/domain_back.jpg';
  if ((card.monster_id !== undefined && card.monster_id !== null) ||
      (card.event_id   !== undefined && card.event_id   !== null)) {
    return '/images/monsters/monster_back.jpg';
  }
  if (card.citizen_id !== undefined && card.citizen_id !== null) {
    return '/images/citizens/citizen_back.jpg';
  }
  if (card.domain_id !== undefined && card.domain_id !== null) {
    return '/images/domains/domain_back.jpg';
  }
  if (card.duke_id !== undefined && card.duke_id !== null) {
    return '/images/dukes/duke_back.jpg';
  }
  if (card.starter_id !== undefined && card.starter_id !== null) {
    return '/images/starters/starter_back.jpg';
  }
  return '/images/domains/domain_back.jpg';
}

// ── Alternate artwork preferences (per-viewer, cosmetic) ─────────────────
// Any card with alternate artwork on disk can have a per-viewer art choice.
// Choices are stored locally as a { "<type>_<id>": "<variant token>" } map and
// applied through `cardImageUrl`. `_cardArtVariants` caches which cards support
// alternates (fetched once from /card-image-variants) so we know where to show
// the "Alt" control.
const MARGRAVE_STARTER_ID = 4;
const CARD_ART_LS_KEY = 'vck_card_art_variants';
let _cardArtVariants = null;        // { type: { id: [tokens] } } or null until loaded
let _cardArtVariantsLoading = false;

function _readCardArtStore() {
  try {
    const obj = JSON.parse(localStorage.getItem(CARD_ART_LS_KEY) || '{}');
    return (obj && typeof obj === 'object') ? obj : {};
  } catch (_) {
    return {};
  }
}

function getCardArtVariant(type, id) {
  if (!type || id == null) return '';
  return _readCardArtStore()[`${type}_${id}`] || '';
}

function setCardArtVariant(type, id, token) {
  if (!type || id == null) return;
  const store = _readCardArtStore();
  const key = `${type}_${id}`;
  if (token) store[key] = token;
  else delete store[key];
  try {
    localStorage.setItem(CARD_ART_LS_KEY, JSON.stringify(store));
  } catch (_) {}
}

function cardTypeAndId(card) {
  if (!card || typeof card !== 'object') return null;
  if (card.monster_id != null) return { type: 'monster', id: card.monster_id };
  if (card.citizen_id != null) return { type: 'citizen', id: card.citizen_id };
  if (card.domain_id  != null) return { type: 'domain',  id: card.domain_id };
  if (card.duke_id    != null) return { type: 'duke',    id: card.duke_id };
  if (card.starter_id != null) return { type: 'starter', id: card.starter_id };
  if (card.event_id   != null) return { type: 'event',   id: card.event_id };
  return null;
}

function cardArtVariantsFor(type, id) {
  if (!_cardArtVariants || !type || id == null) return [];
  const byId = _cardArtVariants[type];
  if (!byId) return [];
  const list = byId[id] != null ? byId[id] : byId[String(id)];
  return Array.isArray(list) ? list : [];
}

// ── Margrave per-owner artwork (each player's Margrave shows a unique art) ──
// Unlike other cards, the Margrave starter is keyed by *owning player* rather
// than a single global preference, so two players' Margraves never share art on
// this client. Choices are "pins" the viewer makes; everyone else's Margrave is
// auto-filled with the remaining variants. Pins persist per game in
// localStorage and are never sent to the server (purely cosmetic, per-viewer).
const MARGRAVE_PINS_LS_KEY = 'vck_margrave_pins';

// Sentinel pin meaning "this owner explicitly uses the default (canonical) art".
// Distinct from "no pin at all": an unpinned owner is eligible for random
// auto-fill once any real alt is picked, whereas a NO_ALT-pinned owner is held
// at the canonical art and excluded from the fill.
const MARGRAVE_NO_ALT = '__none__';

function _readMargravePinsAll() {
  try {
    const o = JSON.parse(localStorage.getItem(MARGRAVE_PINS_LS_KEY) || '{}');
    return (o && typeof o === 'object') ? o : {};
  } catch (_) {
    return {};
  }
}

function getMargravePins(gid) {
  const g = _readMargravePinsAll()[gid];
  return (g && typeof g === 'object') ? g : {};
}

function setMargravePin(gid, playerId, token) {
  if (!gid || playerId == null) return;
  const all = _readMargravePinsAll();
  const g = (all[gid] && typeof all[gid] === 'object') ? all[gid] : {};
  const pid = String(playerId);
  if (token === MARGRAVE_NO_ALT) {
    g[pid] = MARGRAVE_NO_ALT;  // explicit default — kept out of the random fill
  } else if (token) {
    // Keep arts unique: drop this token from any other owner's pin so the
    // newly-picked art is exclusive to this player.
    for (const k of Object.keys(g)) {
      if (k !== pid && g[k] === token) delete g[k];
    }
    g[pid] = token;
  } else {
    delete g[pid];
  }
  all[gid] = g;
  try {
    localStorage.setItem(MARGRAVE_PINS_LS_KEY, JSON.stringify(all));
  } catch (_) {}
}

function margraveOwnerIds(state) {
  const ids = [];
  for (const p of (state && state.player_list) || []) {
    if (p && (p.owned_starters || []).some(s => s && Number(s.starter_id) === MARGRAVE_STARTER_ID)) {
      ids.push(String(p.player_id));
    }
  }
  return ids;
}

// Resolve every Margrave-owning player to a distinct variant: honor the
// viewer's pins first (a real variant, or MARGRAVE_NO_ALT to force canonical),
// then randomly deal the remaining variants to the still-unpinned owners so no
// two Margraves display the same art. Until the viewer picks at least one real
// alt, everyone keeps the canonical art (returns {}).
//
// The random fill is cached by (game, owners, pool, pins) so it stays stable
// across the many renders/lookups within a single pin state, and only
// re-randomizes when one of those inputs actually changes.
let _margraveAssignCache = { key: null, out: {} };

function computeMargraveAssignment(state) {
  if (!state) return {};
  const pool = cardArtVariantsFor('starter', MARGRAVE_STARTER_ID);
  const owners = margraveOwnerIds(state);
  if (!pool.length || !owners.length) return {};
  const gid = state.game_id ? String(state.game_id) : '';
  const pins = getMargravePins(gid);

  const key = JSON.stringify([gid, owners, pool, pins]);
  if (_margraveAssignCache.key === key) return _margraveAssignCache.out;

  const out = {};
  const used = new Set();
  owners.forEach(oid => {
    const t = pins[oid];
    if (t === MARGRAVE_NO_ALT) { out[oid] = ''; }            // explicit default
    else if (t && pool.includes(t) && !used.has(t)) { out[oid] = t; used.add(t); }
  });
  if (!used.size) {  // no real alt picked yet → canonical art for every Margrave
    _margraveAssignCache = { key, out: {} };
    return {};
  }

  // Fisher-Yates shuffle of the leftover variants, then deal to unpinned owners.
  const remaining = pool.filter(t => !used.has(t));
  for (let i = remaining.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [remaining[i], remaining[j]] = [remaining[j], remaining[i]];
  }
  let i = 0;
  owners.forEach(oid => {
    if (out[oid] != null) return;  // already pinned (real variant or default)
    out[oid] = i < remaining.length ? remaining[i++] : '';  // run out → canonical
  });

  _margraveAssignCache = { key, out };
  return out;
}

function margraveVariantForOwner(ownerId) {
  if (ownerId == null || typeof latestGameState === 'undefined' || !latestGameState) return '';
  return computeMargraveAssignment(latestGameState)[String(ownerId)] || '';
}

// Fetch the catalog of which cards have alternate art (once per page load).
// On success, re-render so any "Alt" controls appear.
function ensureCardArtVariantsLoaded() {
  if (_cardArtVariants || _cardArtVariantsLoading) return;
  _cardArtVariantsLoading = true;
  fetch('/card-image-variants')
    .then(r => (r.ok ? r.json() : null))
    .then(data => {
      _cardArtVariants = (data && typeof data === 'object') ? data : {};
      if (latestGameState) {
        lastRenderedStateJson = '';
        render(latestGameState);
      }
    })
    .catch(() => { _cardArtVariants = {}; });
}

// Re-render the board (and any open inspect modal) after an art-variant change.
function rerenderForArtChange() {
  if (typeof latestGameState !== 'undefined' && latestGameState) {
    lastRenderedStateJson = '';
    render(latestGameState);
  }
}

function cardImageUrlBase(card) {
  if (cardObscuredFromViewer(card)) return obscuredTypeBackUrl(card);
  if (card.monster_id !== undefined) return `/card-image/monster/${card.monster_id}`;
  if (card.citizen_id !== undefined) return `/card-image/citizen/${card.citizen_id}`;
  if (card.domain_id  !== undefined) return `/card-image/domain/${card.domain_id}`;
  if (card.duke_id    !== undefined) return `/card-image/duke/${card.duke_id}`;
  if (card.starter_id !== undefined) return `/card-image/starter/${card.starter_id}`;
  if (card.exhausted_id !== undefined) return `/card-image/exhausted/${card.exhausted_id}`;
  if (card.event_id     !== undefined) return `/card-image/event/${card.event_id}`;
  return null;
}

// Resolve the artwork URL for a card, honoring any per-viewer artwork variant
// preference. The variant is purely cosmetic; `installImgVariantFallback`
// strips it back to the canonical image if the alternate file fails to load.
function cardImageUrl(card) {
  const base = cardImageUrlBase(card);
  if (!base) return base;
  if (cardObscuredFromViewer(card)) return base;  // card backs never get variants
  const ti = cardTypeAndId(card);
  if (ti) {
    // Margrave is resolved per owning player (see computeMargraveAssignment) so
    // each player's Margrave shows a different art; every other card uses the
    // single global per-type/id preference.
    const variant = (ti.type === 'starter' && Number(ti.id) === MARGRAVE_STARTER_ID)
      ? margraveVariantForOwner(card.__ownerId)
      : getCardArtVariant(ti.type, ti.id);
    if (variant) return `${base}?variant=${encodeURIComponent(variant)}`;
  }
  return base;
}

// On image load error, if the src carries a `?variant=` token, retry once with
// the canonical (variant-less) URL before giving up to `finalFallback`. This
// guarantees any broken alternate artwork degrades to the original image.
function installImgVariantFallback(img, finalFallback) {
  img.onerror = () => {
    const src = img.getAttribute('src') || '';
    const qIdx = src.indexOf('?variant=');
    if (qIdx !== -1) {
      img.onerror = () => {
        img.onerror = null;
        if (typeof finalFallback === 'function') finalFallback();
      };
      img.src = src.slice(0, qIdx);
      return;
    }
    img.onerror = null;
    if (typeof finalFallback === 'function') finalFallback();
  };
}

function _appendCardText(el, card, mode) {
  const name = mk('card-name');
  name.textContent = card.name || '?';
  el.appendChild(name);
  if (mode !== 'compact') {
    const sub = cardSub(card);
    if (sub) { const s = mk('card-sub'); s.textContent = sub; el.appendChild(s); }
    const extra = cardExtra(card);
    if (extra) { const e = mk('card-extra'); e.textContent = extra; el.appendChild(e); }
  }
}

function makeCard(card, mode) {
  const el = mk('card ' + cardClass(card));
  el.dataset.card = JSON.stringify(card);
  if (card.is_flipped) el.classList.add('flipped');

  // The viewer's OWN duke is technically face-down: show the duke back on the
  // tableau and only reveal the face in the inspect modal (which uses
  // `cardImageUrl` directly). Opponent dukes are obscured and already resolve
  // to the back via `cardImageUrl`.
  const isOwnDuke = card.duke_id !== undefined && !cardObscuredFromViewer(card);
  const imgUrl = mode !== 'compact'
    ? (isOwnDuke ? obscuredTypeBackUrl(card) : cardImageUrl(card))
    : null;

  if (imgUrl) {
    el.classList.add('card-has-image');
    el.setAttribute('role', 'img');
    let aria;
    if (cardObscuredFromViewer(card)) {
      aria = isDomainStackFaceDown(card) ? 'Face-down domain' : 'Hidden card';
    } else if (isOwnDuke) {
      aria = card.name ? `${card.name} (your duke, face-down)` : 'Your duke (face-down)';
    } else if (card.is_flipped) {
      aria = card.name ? `${card.name} (flipped face-down)` : 'Flipped citizen';
    } else {
      aria = card.name || 'Card';
    }
    el.setAttribute('aria-label', aria);

    const fallbackToText = () => {
      el.classList.remove('card-has-image');
      el.removeAttribute('role');
      el.removeAttribute('aria-label');
      el.innerHTML = '';
      _appendCardText(el, card, mode);
    };

    // Flipped tableau citizens (`is_flipped`) are physically face-down but the
    // viewer still knows the identity, so they use a shared cross-fade flip
    // stage: the back rests as the steady state and the front periodically
    // peeks through. The wrapping `.card[data-card]` element still receives
    // clicks (the flip-stage uses `pointer-events: none`), so the delegated
    // handler in 03-modals.js continues to open the full card modal as usual.
    const useFlipStage = card.is_flipped;

    if (useFlipStage) {
      const stage = mk('card-flip-stage');
      const inner = mk('card-flip-inner');

      const back = mk('card-flip-face card-flip-back');
      const backImg = document.createElement('img');
      backImg.className = 'card-img';
      backImg.alt = '';
      backImg.src = obscuredTypeBackUrl(card);
      back.appendChild(backImg);

      const front = mk('card-flip-face card-flip-front');
      const frontImg = document.createElement('img');
      frontImg.className = 'card-img';
      frontImg.alt = '';
      installImgVariantFallback(frontImg, fallbackToText);
      frontImg.src = imgUrl;
      front.appendChild(frontImg);

      inner.appendChild(back);
      inner.appendChild(front);
      stage.appendChild(inner);
      el.appendChild(stage);
    } else {
      const img = document.createElement('img');
      img.className = 'card-img';
      img.alt = '';
      installImgVariantFallback(img, fallbackToText);  // wire handler before src
      img.src = imgUrl;
      el.appendChild(img);
    }

    // "Alt" control for cards whose face is shown to this viewer and that have
    // alternate artwork on disk. Obscured/own-duke cards render a back, so they
    // get no control here (the duke's face is reachable via the inspect modal).
    if (!cardObscuredFromViewer(card) && !isOwnDuke) {
      const ti = cardTypeAndId(card);
      const variants = ti ? cardArtVariantsFor(ti.type, ti.id) : [];
      if (ti && variants.length) {
        el.appendChild(makeCardAltButton(ti.type, ti.id, variants, card.name, card.__ownerId));
      }
    }
  } else {
    _appendCardText(el, card, mode);
  }

  // Ghost Ship: gold accumulated on the card is just a bank sitting on the
  // monster (claimed by the slayer), not a slay-cost change like Leviathan's
  // strength tokens — so it gets its own coin badge rather than folding into
  // the cost line. Shown for any face-up card carrying a pool.
  if (!cardObscuredFromViewer(card)) {
    const goldBadge = makeGoldPoolBadge(card);
    if (goldBadge) el.appendChild(goldBadge);
  }

  return el;
}

// Coin badge for a card's accumulated gold pool (Ghost Ship). Returns null when
// the card carries no pool. Positioned top-left so it clears the "Alt" control
// (top-right) and the stack-depth badge (bottom-right).
function makeGoldPoolBadge(card) {
  const pool = Number(card && card.gold_pool) || 0;
  if (pool <= 0) return null;
  const badge = mk('card-gold-pool');
  const img = document.createElement('img');
  img.className = 'card-gold-pool-icon';
  img.alt = '';
  img.src = TABLEAU_RESOURCE_ICONS.gold;
  const num = mk('card-gold-pool-count');
  num.textContent = String(pool);
  badge.appendChild(img);
  badge.appendChild(num);
  badge.title = `${pool} gold on this card`;
  badge.setAttribute('aria-label', `${pool} gold on this card`);
  return badge;
}

// Small top-right "Alt" button mirroring the wiki: a single alternate toggles
// in place, multiple alternates open the artwork chooser. Selection persists in
// localStorage and applies via `cardImageUrl`. Margrave is special-cased to a
// per-owner assignment so each player's Margrave shows a distinct art.
function makeCardAltButton(type, id, variants, name, ownerId) {
  const isMargrave = type === 'starter' && Number(id) === MARGRAVE_STARTER_ID;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'card-alt-toggle';
  btn.textContent = 'Alt';
  const refresh = () => {
    const on = isMargrave ? !!margraveVariantForOwner(ownerId) : !!getCardArtVariant(type, id);
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    btn.title = on ? 'Change alternate artwork' : 'Show alternate artwork';
  };
  refresh();
  btn.setAttribute('aria-label', 'Choose alternate artwork');
  btn.addEventListener('click', e => {
    e.stopPropagation();
    e.preventDefault();
    if (!isMargrave && variants.length === 1) {
      setCardArtVariant(type, id, getCardArtVariant(type, id) ? '' : variants[0]);
      rerenderForArtChange();
    } else {
      openCardArtChooser({
        type,
        id,
        variants,
        ownerId,
        title: name ? `${name} — artwork` : 'Choose artwork',
      });
    }
  });
  return btn;
}

function cardClass(card) {
  if (card.exhausted_id !== undefined) return 'card-exhausted';
  if (card.event_id     !== undefined) return 'card-event';
  if (card.monster_id   !== undefined) return 'card-monster';
  if (card.citizen_id   !== undefined) return 'card-citizen';
  if (card.domain_id    !== undefined) return 'card-domain';
  if (card.duke_id      !== undefined) return 'card-duke';
  return 'card-starter';
}

function cardSub(card) {
  if (card.event_id !== undefined) {
    const parts = [];
    const sc = (card.strength_cost || 0) + (card.extra_strength_cost || 0);
    const mc = (card.magic_cost    || 0) + (card.extra_magic_cost    || 0);
    const gc =  card.extra_gold_cost || 0;
    if (sc) parts.push(`${sc} str`);
    if (mc) parts.push(`${mc} mag`);
    if (gc) parts.push(`${gc} gold`);
    return parts.length ? `Cost: ${parts.join(' + ')}` : '';
  }
  if (card.monster_id !== undefined) {
    const parts = [];
    if (card.strength_cost) parts.push(`${card.strength_cost} str`);
    if (card.magic_cost)    parts.push(`${card.magic_cost} mag`);
    return parts.length ? `Cost: ${parts.join(' + ')}` : '';
  }
  if (card.citizen_id !== undefined || card.domain_id !== undefined) {
    return card.gold_cost ? `Cost: ${card.gold_cost}g` : '';
  }
  if (card.starter_id !== undefined) {
    const m1 = card.roll_match1, m2 = card.roll_match2;
    if (m1 && m2 && m1 !== m2) return `Rolls: ${m1}, ${m2}`;
    if (m1) return `Roll: ${m1}`;
  }
  return '';
}

function cardExtra(card) {
  const parts = [];
  if (card.vp_reward)        parts.push(`${card.vp_reward} VP`);
  if (card.gold_reward)      parts.push(`+${card.gold_reward}g`);
  if (card.strength_reward)  parts.push(`+${card.strength_reward} str`);
  if (card.magic_reward)     parts.push(`+${card.magic_reward} mag`);
  // Domain text (short)
  if (!parts.length && card.text) {
    const t = card.text.slice(0, 40);
    return t.length < card.text.length ? t + '…' : t;
  }
  return parts.join(' ');
}
