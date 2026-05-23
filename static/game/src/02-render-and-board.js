// ── Seat assignment ───────────────────────────────────────────────────────
// Viewer is always at the bottom. Opponents follow clockwise turn order starting
// from the player to your right (next in `player_list` after you).
function idsMatch(a, b) {
  return String(a ?? '').trim() === String(b ?? '').trim();
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

// ── Tableau sections (domains first … dukes last) ─────────────────────────
function tableauGroupsForPlayer(player) {
  const defs = [
    ['Domains', 'owned_domains'],
    ['Citizens', 'owned_citizens'],
    ['Monsters', 'owned_monsters'],
    ['Starters', 'owned_starters'],
    ['Dukes', 'owned_dukes'],
  ];
  return defs
    .map(([label, key]) => ({ label, cards: player[key] || [] }))
    .filter(g => g.cards.length > 0);
}

// ── Main render ───────────────────────────────────────────────────────────
function render(state) {
  latestGameState = state;
  bumpIdleDeadline();
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
    tickIdleTimerElements();
    ensureIdleTicking();
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
  tickIdleTimerElements();
  ensureIdleTicking();
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
      if (monsters.length > 1) {
        stacksWrap.appendChild(makeTableauOrderedStack(monsters, cardMode));
      } else {
        monsters.forEach(c => stacksWrap.appendChild(makeTableauStack(c, 1, cardMode)));
      }
    } else {
      g.cards.forEach(c => stacksWrap.appendChild(makeTableauStack(c, 1, cardMode)));
    }
    grp.appendChild(stacksWrap);
    tableau.appendChild(grp);
  });
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
    dot.textContent = p.name || `Player ${i + 1}`;
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
    scrollTableauCarouselToSlide(viewport, slide, 'auto');
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

function renderCenter(state) {
  const el = document.getElementById('zone-center');
  if (!el) return;
  el.innerHTML = '';
  el.classList.add('board-use-tabs');

  const tabsBar = mk('board-tabs-bar');
  tabsBar.setAttribute('role', 'tablist');

  const viewport = mk('center-board-viewport');

  const citizenGrid = state.citizen_grid || [];
  const sections = [
    makeGridSection('Monsters',      state.monster_grid || [], 'monster', 5, 'board-monsters'),
    makeGridSection('Citizens 1–5',  citizenGrid.slice(0, 5),  'citizen', 5, 'board-citizens-1'),
    makeGridSection('Citizens 6–12', citizenGrid.slice(5),     'citizen', 5, 'board-citizens-2'),
    makeGridSection('Domains',       state.domain_grid  || [], 'domain',  5, 'board-domains'),
  ];
  BOARD_SECTIONS.forEach(({ key }, i) => {
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

  setupBoardTabs(el, tabsBar, viewport);
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

function setupBoardTabs(zoneCenter, tabsBar, viewport) {
  const slides = Array.from(viewport.children);
  tabsBar.innerHTML = '';
  let initialIdx = 0;
  if (centerBoardActiveTabKey != null) {
    const j = BOARD_SECTIONS.findIndex(s => s.key === centerBoardActiveTabKey);
    if (j >= 0) initialIdx = j;
  }
  const tabs = BOARD_SECTIONS.map(({ key, label }, i) => {
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
      const sec = BOARD_SECTIONS[best];
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
  ['gold', 'strength', 'magic'].forEach(r => {
    const lab = r.charAt(0).toUpperCase() + r.slice(1);
    const btn = promptButton(`+1 ${lab}`, () => {
      if (!canOfferTakeResourceAction(latestGameState)) return;
      confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'take_resource', resource: r },
        {
          title: 'Take resource?',
          message: `Take +1 ${lab} from the bank as your standard action.`,
        },
      );
    });
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

  const phase = mk('phase-label');
  phase.textContent = fmtPhase(state.phase);
  panel.appendChild(phase);

  const tn = mk('turn-label');
  const t = activeTurnNamePart(state);
  const turnWho = t.hasActive ? ` — ${t.isMe ? 'your' : `${t.displayName}'s`} turn` : '';
  tn.textContent = `Turn ${state.turn_number || 1}${turnWho}`;
  tn.title = tn.textContent;
  panel.appendChild(tn);

  if (state.end_game_triggered) {
    const eg = mk('turn-label');
    eg.textContent = '⚑ Final round';
    eg.style.color = 'var(--gold)';
    panel.appendChild(eg);
  }

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
  panel.appendChild(makeGameLog(state));

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
function groupCardsForTableau(cards) {
  const arr = Array.isArray(cards) ? cards : [];
  const map = new Map();
  arr.forEach(c => {
    if (!c || typeof c !== 'object') return;
    const name = (c.name || c.title || '').toString().trim();
    const id = c.starter_id || c.citizen_id || c.monster_id || c.domain_id || c.duke_id || c.id || '';
    const isCitizenKey = c.citizen_id !== undefined && c.citizen_id !== null;
    const flipSeg = isCitizenKey ? `||flip:${c.is_flipped ? 1 : 0}` : '';
    const key = `${name}||${id}${flipSeg}`;
    const cur = map.get(key);
    if (cur) cur.count += 1;
    else map.set(key, { card: c, count: 1, sortName: name.toLowerCase(), sortId: String(id) });
  });
  if (map.size === 0 && arr.length) return null;
  return Array.from(map.values()).sort((a, b) => {
    if (a.sortName < b.sortName) return -1;
    if (a.sortName > b.sortName) return 1;
    if (a.sortId < b.sortId) return -1;
    if (a.sortId > b.sortId) return 1;
    return 0;
  });
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
 * Ordered tableau stack: index 0 is oldest, last index is newest (top).
 * Reusable for any ordered pile where the viewer taps the stack and pages through in a modal.
 */
function makeTableauOrderedStack(cards, mode) {
  const arr = Array.isArray(cards) ? cards.filter(Boolean) : [];
  if (arr.length === 0) return mk('grid-stack');
  if (arr.length === 1) return makeTableauStack(arr[0], 1, mode);

  const wrap = mk('grid-stack tableau-card-stack');
  wrap.dataset.stack = JSON.stringify(arr);

  const foundation = mk('tableau-stack-foundation');
  const maxSlivers = 8;
  const under = Math.min(arr.length - 1, maxSlivers);
  for (let i = 0; i < under; i++) {
    foundation.appendChild(mk('tableau-stack-sliver'));
  }
  wrap.appendChild(foundation);

  const topWrap = mk('tableau-stack-top');
  topWrap.appendChild(makeCard(arr[arr.length - 1], mode));
  wrap.appendChild(topWrap);

  if (arr.length > maxSlivers + 1) {
    const badge = mk('stack-depth');
    badge.textContent = `×${arr.length}`;
    wrap.appendChild(badge);
  }
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
  const names = { gold: 'Gold', strength: 'Strength', magic: 'Magic' };
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
  v.textContent = row.value;
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

  const ord = playerIndexInList(state, player);
  const listLen = (state.player_list || []).length;
  if (ord >= 0 && listLen > 0) {
    const seatLbl = mk('player-seat-order');
    seatLbl.textContent = `Seat ${ord + 1}/${listLen}`;
    seatLbl.title = 'Player order in this game (clockwise from Seat 1)';
    nameRow.appendChild(seatLbl);
  }

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

  if (isActiveTurnForPlayer(player, state)) {
    const tim = mk('tableau-inactive-timer');
    tim.title =
      'Approximate idle time before this table may close if nobody acts (resets on activity).';
    tim.setAttribute(
      'aria-label',
      'Approximate idle time before this table may close if nobody acts',
    );
    nameRow.appendChild(tim);
  }

  h.appendChild(nameRow);

  const resRow = mk('player-header-res-row');
  resRow.appendChild(makeResourceScorePill('gold', player.gold_score, 'Gold', TABLEAU_RESOURCE_ICONS.gold));
  resRow.appendChild(makeResourceScorePill('strength', player.strength_score, 'Strength', TABLEAU_RESOURCE_ICONS.strength));
  resRow.appendChild(makeResourceScorePill('magic', player.magic_score, 'Magic', TABLEAU_RESOURCE_ICONS.magic));
  resRow.appendChild(makeVpScorePill(player.victory_score));
  h.appendChild(resRow);

  return h;
}
// ── Card factory ──────────────────────────────────────────────────────────
/** Viewer cannot see the card face (face-down domain pile, future hidden stacks, etc.). */
function cardObscuredFromViewer(card) {
  return !!(card && typeof card === 'object' && card.is_visible === false);
}

function isDomainStackFaceDown(card) {
  return card?.domain_id != null && cardObscuredFromViewer(card);
}

function obscuredTypeBackUrl(card) {
  if (!card || typeof card !== 'object') return '/images/domains/domain_back.jpg';
  if (card.monster_id !== undefined && card.monster_id !== null) {
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

function cardImageUrl(card) {
  if (cardObscuredFromViewer(card)) return obscuredTypeBackUrl(card);
  if (card.monster_id !== undefined) return `/card-image/monster/${card.monster_id}`;
  if (card.citizen_id !== undefined) return `/card-image/citizen/${card.citizen_id}`;
  if (card.domain_id  !== undefined) return `/card-image/domain/${card.domain_id}`;
  if (card.duke_id    !== undefined) return `/card-image/duke/${card.duke_id}`;
  if (card.starter_id !== undefined) return `/card-image/starter/${card.starter_id}`;
  if (card.exhausted_id !== undefined) return `/card-image/exhausted/${card.exhausted_id}`;
  return null;
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

  const imgUrl = mode !== 'compact' ? cardImageUrl(card) : null;

  if (imgUrl) {
    el.classList.add('card-has-image');
    el.setAttribute('role', 'img');
    const aria = cardObscuredFromViewer(card)
      ? (isDomainStackFaceDown(card) ? 'Face-down domain' : 'Hidden card')
      : (card.name || 'Card');
    el.setAttribute('aria-label', aria);

    const img = document.createElement('img');
    img.className = 'card-img';
    img.alt = '';
    img.onerror = () => {
      el.classList.remove('card-has-image');
      el.removeAttribute('role');
      el.removeAttribute('aria-label');
      el.innerHTML = '';
      _appendCardText(el, card, mode);
    };
    img.src = imgUrl;  // set src after onerror so handler is registered first
    el.appendChild(img);
  } else {
    _appendCardText(el, card, mode);
  }

  return el;
}

function cardClass(card) {
  if (card.exhausted_id !== undefined) return 'card-exhausted';
  if (card.monster_id   !== undefined) return 'card-monster';
  if (card.citizen_id   !== undefined) return 'card-citizen';
  if (card.domain_id    !== undefined) return 'card-domain';
  if (card.duke_id      !== undefined) return 'card-duke';
  return 'card-starter';
}

function cardSub(card) {
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
