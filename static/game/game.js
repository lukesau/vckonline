'use strict';

// ── URL params + cookie-backed ids (vck_client) ───────────────────────────
const params = new URLSearchParams(location.search);
const _vckStored =
  typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.read ? VCK_CLIENT_META.read() : {};
const _qGid = (params.get('game_id') || '').trim();
const _qPid = (params.get('player_id') || '').trim();
const GAME_ID = _qGid || String(_vckStored.game_id || '').trim();
const PLAYER_ID = _qPid || String(_vckStored.player_id || '').trim();
if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.patch) {
  if (_qGid || _qPid) {
    const pu = {};
    if (_qGid) pu.game_id = _qGid;
    if (_qPid) pu.player_id = _qPid;
    VCK_CLIENT_META.patch(pu);
  } else if (GAME_ID && PLAYER_ID) {
    VCK_CLIENT_META.patch({ game_id: GAME_ID, player_id: PLAYER_ID });
  }
}

function vckStoredPlayerId() {
  try {
    if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.read) {
      return String(VCK_CLIENT_META.read().player_id || '').trim();
    }
  } catch (_) {
    /* ignore */
  }
  try {
    return String(localStorage.getItem('playerId') || '').trim();
  } catch (_) {
    return '';
  }
}

function vckClientPatch(obj) {
  try {
    if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.patch) VCK_CLIENT_META.patch(obj);
  } catch (_) {
    /* ignore */
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────
let ws = null;
let reconnectTimer = null;
let concurrentPollTimer = null;
let finalizeRollInFlight = false;
/** Set each render — board card modal reads latest grids / phase */
let latestGameState = null;

/** Narrow layout: max-width breakpoint matches CSS tabbed / carousel mode */
function isViewportNarrow() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 800px)').matches;
}

/** Which player's tableau slide is focused in the narrow carousel (persisted across re-renders) */
let tableauCarouselActiveId = null;

/** Visual approx. of server 180s inactivity cleanup; refreshed on each state. */
const INACTIVITY_IDLE_MS = 180000;
let idleDeadlineMs = 0;
let idleTickHandle = null;

function isGameNotFoundText(s) {
  return String(s || '')
    .toLowerCase()
    .includes('game not found');
}

function clearStaleStoredGame() {
  vckClientPatch({ game_id: null });
  try {
    localStorage.removeItem('gameId');
  } catch (_) {
    /* ignore */
  }
}

function clientShouldDropStoredGame(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (payload.drop_stored_game) return true;
  if (isGameNotFoundText(payload.detail)) return true;
  return false;
}

function redirectToLobby() {
  clearStaleStoredGame();
  location.replace('/');
}

function vckStoredDisplayName() {
  try {
    if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.read) {
      return String(VCK_CLIENT_META.read().display_name || '').trim();
    }
  } catch (_) {
    /* ignore */
  }
  return '';
}

function bumpIdleDeadline() {
  idleDeadlineMs = Date.now() + INACTIVITY_IDLE_MS;
}

function formatIdleCountdownLabel(msLeft) {
  const s = Math.max(0, Math.ceil(msLeft / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

function tickIdleTimerElements() {
  const els = document.querySelectorAll('.tableau-inactive-timer');
  if (!els.length) return;
  const left = idleDeadlineMs - Date.now();
  const label = formatIdleCountdownLabel(left);
  els.forEach(el => {
    el.textContent = label;
  });
}

function ensureIdleTicking() {
  if (idleTickHandle != null) return;
  idleTickHandle = setInterval(() => {
    if (!document.querySelector('.tableau-inactive-timer')) {
      clearInterval(idleTickHandle);
      idleTickHandle = null;
      return;
    }
    tickIdleTimerElements();
  }, 1000);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/game/${GAME_ID}?player_id=${PLAYER_ID}`);

  ws.onopen = () => {
    setConnStatus('ok');
    clearTimeout(reconnectTimer);
  };

  ws.onmessage = evt => {
    const msg = JSON.parse(evt.data);
    if (msg.type === 'state') render(msg.state);
    if (msg.type === 'error') {
      if (msg.drop_stored_game || isGameNotFoundText(msg.message)) {
        redirectToLobby();
        return;
      }
      setConnStatus('error', msg.message);
      ws.close();
    }
  };

  ws.onclose = evt => {
    // Code 4004 = game not found; don't retry
    if (evt.code === 4004) {
      redirectToLobby();
      return;
    }
    setConnStatus('off');
    reconnectTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

function setConnStatus(s, detail) {
  const el = document.getElementById('conn-status');
  if (s === 'ok') {
    el.textContent = '● connected';
    el.className = 'conn-status';
  } else if (s === 'error') {
    el.textContent = `● ${detail || 'error'}`;
    el.className = 'conn-status disconnected';
  } else {
    el.textContent = '● disconnected';
    el.className = 'conn-status disconnected';
  }
}

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
  const narrow = isViewportNarrow();
  const board = document.getElementById('board');
  if (board) {
    board.dataset.layout = layout.layoutKey;
    board.dataset.playerCount = String(layout.n);
    board.dataset.narrowLayout = narrow ? '1' : '';
  }
  clearEl('gl-top');
  clearEl('gl-side-l');
  clearEl('gl-side-r');
  clearEl('gl-bottom');

  const bottomEl = document.getElementById('gl-bottom');
  if (narrow) {
    renderTableauCarousel(state, bottomEl);
  } else {
    layout.top.forEach(p => {
      const wrap = mk('gl-top-slot');
      wrap.appendChild(renderSeatEl(p, state, layout.n === 5 ? 'top-mini' : 'top'));
      document.getElementById('gl-top').appendChild(wrap);
    });

    if (layout.right) {
      document.getElementById('gl-side-r').appendChild(renderSeatEl(layout.right, state, 'side'));
    }
    if (layout.left) {
      document.getElementById('gl-side-l').appendChild(renderSeatEl(layout.left, state, 'side'));
    }

    if (bottomEl) {
      bottomEl.appendChild(renderSeatEl(layout.me, state, 'me'));
    }
  }

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
    const grouped = groupCardsForTableau(g.cards);
    if (grouped) {
      grouped.forEach(({ card, count }) => grp.appendChild(makeTableauStack(card, count, cardMode)));
    } else {
      g.cards.forEach(c => grp.appendChild(makeTableauStack(c, 1, cardMode)));
    }
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

function wireTableauCarouselViewport(viewport) {
  viewport.addEventListener(
    'wheel',
    e => {
      if (viewport.scrollWidth <= viewport.clientWidth + 1) return;
      e.preventDefault();
      viewport.scrollLeft += e.deltaY;
    },
    { passive: false },
  );

  let dragPtr = null;
  viewport.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    if (e.target.closest && e.target.closest('.card')) return;
    dragPtr = e.pointerId;
    try {
      viewport.setPointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
    viewport.classList.add('is-pointer-dragging');
  });
  viewport.addEventListener('pointermove', e => {
    if (e.pointerId !== dragPtr) return;
    viewport.scrollLeft -= e.movementX;
  });
  const endDrag = e => {
    if (e.pointerId !== dragPtr) return;
    dragPtr = null;
    viewport.classList.remove('is-pointer-dragging');
    try {
      viewport.releasePointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
  };
  viewport.addEventListener('pointerup', endDrag);
  viewport.addEventListener('pointercancel', endDrag);
}

function renderTableauCarousel(state, bottomEl) {
  if (!bottomEl) return;
  const players = state.player_list || [];
  const root = mk('tableau-carousel');
  root.setAttribute('role', 'region');
  root.setAttribute('aria-label', 'Player tableaus');

  // In narrow mode, ring the whole carousel on your turn (avoids clipped outer box-shadows).
  const me = players.find(p => idsMatch(p && p.player_id, PLAYER_ID));
  if (me && isActiveTurnForPlayer(me, state)) {
    root.classList.add('is-my-active-turn');
  }

  const viewport = mk('tableau-carousel-viewport');
  players.forEach(p => {
    const slide = mk('tableau-carousel-slide');
    slide.appendChild(renderSeatEl(p, state, 'carousel'));
    viewport.appendChild(slide);
  });

  wireTableauCarouselViewport(viewport);

  root.appendChild(viewport);
  bottomEl.appendChild(root);

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
  };

  let scrollEndTimer = null;
  viewport.addEventListener('scroll', () => {
    clearTimeout(scrollEndTimer);
    scrollEndTimer = setTimeout(syncActiveFromScroll, 120);
  }, { passive: true });

  requestAnimationFrame(() => {
    const slide = viewport.children[targetIdx];
    if (!slide) return;
    viewport.scrollTo({ left: slide.offsetLeft, behavior: 'auto' });
    const pl = players[targetIdx];
    if (pl && pl.player_id != null) tableauCarouselActiveId = pl.player_id;
  });
}

// ── Center board ──────────────────────────────────────────────────────────
function renderCenter(state) {
  const el = document.getElementById('zone-center');
  if (!el) return;
  const narrow = isViewportNarrow();
  const n = (state.player_list || []).length;
  const logBesideGrid = n === 2 && !narrow;
  el.innerHTML = '';
  el.classList.toggle('center-board--log-side', logBesideGrid);

  const scrollArea = mk('center-board-scroll');
  const tabsBar = mk('board-tabs-bar');
  tabsBar.setAttribute('role', 'tablist');
  scrollArea.appendChild(tabsBar);

  const secMon = makeGridSection('Monsters', state.monster_grid || [], 'monster', 5, 'board-monsters');
  secMon.dataset.boardSection = 'monsters';
  const secCit = makeCitizenSection(state.citizen_grid || []);
  secCit.dataset.boardSection = 'citizens';
  const secDom = makeGridSection('Domains', state.domain_grid || [], 'domain', 5, 'board-domains');
  secDom.dataset.boardSection = 'domains';

  scrollArea.appendChild(secMon);
  scrollArea.appendChild(secCit);
  scrollArea.appendChild(secDom);

  const body = mk('center-board-body');
  body.appendChild(makeInfoBar(state));
  body.appendChild(scrollArea);

  if (logBesideGrid) {
    const log = makeGameLog(state);
    log.classList.add('game-log--side');
    const split = mk('center-board-split');
    split.appendChild(body);
    split.appendChild(log);
    el.appendChild(split);
  } else {
    el.appendChild(body);
    if (!narrow) {
      el.appendChild(makeGameLog(state));
    }
  }

  setupBoardTabs(el, tabsBar);
}

/** Vertical wheel turns into horizontal scroll on top-strip opponent tableaus only. */
function initOpponentTableauWheelScroll() {
  const board = document.getElementById('board');
  if (!board || board.dataset.tableauWheelBound) return;
  board.dataset.tableauWheelBound = '1';
  board.addEventListener(
    'wheel',
    e => {
      const row = e.target.closest('.tableau-cards');
      if (!row) return;
      const seat = row.closest('.seat');
      if (!seat || seat.classList.contains('seat-empty')) return;
      if (!seat.classList.contains('seat-top') && !seat.classList.contains('seat-top-mini')) return;
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

function setupBoardTabs(zoneCenter, tabsBar) {
  const sections = () => Array.from(zoneCenter.querySelectorAll('.center-board-scroll > .center-section'));
  const labels = { monsters: 'Monsters', citizens: 'Citizens', domains: 'Domains' };
  const keys = ['monsters', 'citizens', 'domains'];
  tabsBar.innerHTML = '';
  keys.forEach((key, i) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'board-tab' + (i === 0 ? ' is-active' : '');
    btn.textContent = labels[key];
    btn.dataset.boardTab = key;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', i === 0 ? 'true' : 'false');
    btn.addEventListener('click', () => {
      keys.forEach(k => {
        sections().forEach(sec => {
          if (sec.dataset.boardSection === k) {
            sec.classList.toggle('board-tab-visible', k === key);
          }
        });
      });
      tabsBar.querySelectorAll('.board-tab').forEach(b => {
        const on = b.dataset.boardTab === key;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
    });
    tabsBar.appendChild(btn);
  });

  keys.forEach((key, i) => {
    sections().forEach(sec => {
      if (sec.dataset.boardSection === key) {
        sec.classList.toggle('board-tab-visible', i === 0);
      }
    });
  });
  syncBoardTabState(zoneCenter);
}

function syncBoardTabState(zoneCenter) {
  const scroll = zoneCenter.querySelector('.center-board-scroll');
  if (!scroll) return;
  const useTabs = isViewportNarrow();
  zoneCenter.classList.toggle('board-use-tabs', useTabs);
  if (!useTabs) {
    zoneCenter.querySelectorAll('.center-section').forEach(sec => sec.classList.add('board-tab-visible'));
  } else {
    const active = zoneCenter.querySelector('.board-tab.is-active');
    const key = active ? active.dataset.boardTab : 'monsters';
    zoneCenter.querySelectorAll('.center-section').forEach(sec => {
      sec.classList.toggle('board-tab-visible', sec.dataset.boardSection === key);
    });
  }
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

function makeInfoBar(state) {
  const bar = mk('info-bar');
  const narrow = isViewportNarrow();
  if (narrow) bar.classList.add('info-bar--stacked');

  const meta = mk('info-bar-meta');

  const phase = mk('phase-label');
  phase.textContent = fmtPhase(state.phase);
  meta.appendChild(phase);

  const tn = mk('turn-label');
  tn.textContent = `Turn ${state.turn_number || 1}`;
  meta.appendChild(tn);

  const active = (state.player_list || []).find(p => p.player_id === state.active_player_id);
  if (active && active.player_id !== PLAYER_ID) {
    const who = mk('turn-label');
    who.textContent = `— ${active.name}'s turn`;
    meta.appendChild(who);
  }

  if (state.end_game_triggered) {
    const eg = mk('turn-label');
    eg.textContent = '⚑ Final round';
    eg.style.color = 'var(--gold)';
    meta.appendChild(eg);
  }

  bar.appendChild(meta);

  if (canOfferTakeResourceAction(state)) {
    const takeWrap = mk('info-bar-take-resource');
    const takeLbl = mk('info-bar-take-label');
    const nAct = Number(state.actions_remaining || 0);
    takeLbl.textContent = `Spend action (${nAct} left)`;
    takeWrap.appendChild(takeLbl);
    const takeBtns = mk('info-bar-take-buttons');
    ['gold', 'strength', 'magic'].forEach(r => {
      const lab = r === 'gold' ? 'G' : r === 'strength' ? 'S' : 'M';
      takeBtns.appendChild(promptButton(`+1 ${lab}`, () => postGameAction({
        player_id: PLAYER_ID,
        action_type: 'take_resource',
        resource: r,
      })));
    });
    takeWrap.appendChild(takeBtns);
    bar.appendChild(takeWrap);
  }

  const diceRow = mk('info-bar-dice-row');
  const dice = mk('dice-display');
  if (state.die_one != null) {
    dice.appendChild(makeDie(state.die_one));
    dice.appendChild(makeDie(state.die_two));
    const sum = mk('die-sum');
    sum.textContent = `= ${state.die_sum}`;
    dice.appendChild(sum);
  }
  diceRow.appendChild(dice);

  if (!narrow) {
    const lobby = document.createElement('a');
    lobby.href = '/';
    lobby.className = 'info-bar-lobby-btn';
    lobby.textContent = 'Lobby';
    lobby.addEventListener('click', ev => {
      ev.preventDefault();
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
    diceRow.appendChild(lobby);
  }

  bar.appendChild(diceRow);

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

  const ord = playerIndexInList(state, player);
  const listLen = (state.player_list || []).length;
  if (ord >= 0 && listLen > 0) {
    const seatLbl = mk('player-seat-order');
    seatLbl.textContent = `Seat ${ord + 1}/${listLen}`;
    seatLbl.title = 'Player order in this game (clockwise from Seat 1)';
    h.appendChild(seatLbl);
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
  h.appendChild(name);

  h.appendChild(makeResourceScorePill('gold', player.gold_score, 'Gold', TABLEAU_RESOURCE_ICONS.gold));
  h.appendChild(makeResourceScorePill('strength', player.strength_score, 'Strength', TABLEAU_RESOURCE_ICONS.strength));
  h.appendChild(makeResourceScorePill('magic', player.magic_score, 'Magic', TABLEAU_RESOURCE_ICONS.magic));
  h.appendChild(makeVpScorePill(player.victory_score));

  if (isActiveTurnForPlayer(player, state)) {
    const tim = mk('tableau-inactive-timer');
    tim.title =
      'Approximate idle time before this table may close if nobody acts (resets on activity).';
    tim.setAttribute(
      'aria-label',
      'Approximate idle time before this table may close if nobody acts',
    );
    h.appendChild(tim);
  }

  return h;
}

// ── Player detail modal (tableau drill-down) ────────────────────────────
function escapeHtml(s) {
  return (s ?? '')
    .toString()
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function detailPill(label, value) {
  return `<span class="player-detail-pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
}

function citizenRoleCounts(card) {
  const r = card && card.roles;
  if (r && typeof r === 'object') {
    return {
      sn: Number(r.shadow) || 0,
      hn: Number(r.holy) || 0,
      son: Number(r.soldier) || 0,
      wn: Number(r.worker) || 0,
    };
  }
  return {
    sn: Number(card.shadow_count) || 0,
    hn: Number(card.holy_count) || 0,
    son: Number(card.soldier_count) || 0,
    wn: Number(card.worker_count) || 0,
  };
}

function formatHarvestGSM(card, onTurn) {
  const g = onTurn ? 'gold_payout_on_turn' : 'gold_payout_off_turn';
  const s = onTurn ? 'strength_payout_on_turn' : 'strength_payout_off_turn';
  const m = onTurn ? 'magic_payout_on_turn' : 'magic_payout_off_turn';
  const gv = Number(card[g]) || 0;
  const sv = Number(card[s]) || 0;
  const mv = Number(card[m]) || 0;
  return `G ${gv}, S ${sv}, M ${mv}`;
}

function pushHarvestHints(hints, card) {
  const hasOn =
    card.gold_payout_on_turn !== undefined ||
    card.strength_payout_on_turn !== undefined ||
    card.magic_payout_on_turn !== undefined;
  const hasOff =
    card.gold_payout_off_turn !== undefined ||
    card.strength_payout_off_turn !== undefined ||
    card.magic_payout_off_turn !== undefined;
  if (!hasOn && !hasOff) return;
  const onStr = formatHarvestGSM(card, true);
  const offStr = formatHarvestGSM(card, false);
  if (onStr === offStr) {
    hints.push(`Harvest: ${onStr} (on & off turn)`);
  } else {
    hints.push(`Harvest (on turn): ${onStr}`);
    hints.push(`Harvest (off turn): ${offStr}`);
  }
}

function tableauCardFullText(card) {
  if (!card || typeof card !== 'object') return '';
  const rawText = (card.text ?? '').toString().trim();
  if (rawText) return rawText;

  const parts = [];
  pushHarvestHints(parts, card);
  if (card.monster_id !== undefined && card.monster_id !== null) {
    const vp = Number(card.vp_reward || 0);
    const gr = Number(card.gold_reward || 0);
    const sr = Number(card.strength_reward || 0);
    const mr = Number(card.magic_reward || 0);
    parts.push(`Reward: VP ${vp} · G ${gr} · S ${sr} · M ${mr}`);
  }
  const passive = (card.passive_effect ?? '').toString().trim();
  const activation = (card.activation_effect ?? '').toString().trim();
  if (passive) parts.push(`Passive: ${passive}`);
  if (activation) parts.push(`Activation: ${activation}`);
  const spOn = (card.special_payout_on_turn ?? '').toString().trim();
  const spOff = (card.special_payout_off_turn ?? '').toString().trim();
  if (spOn) parts.push(`Special (on turn): ${spOn}`);
  if (spOff) parts.push(`Special (off turn): ${spOff}`);
  const specialReward = (card.special_reward ?? '').toString().trim();
  const specialCost = (card.special_cost ?? '').toString().trim();
  if (specialReward) parts.push(`Special reward: ${specialReward}`);
  if (specialCost) parts.push(`Special cost: ${specialCost}`);

  if (card.duke_id !== undefined) {
    const mults = [];
    const add = (label, val) => {
      if (val === undefined || val === null) return;
      const n = Number(val);
      if (!Number.isFinite(n) || n === 0) return;
      mults.push(`${label}×${n}`);
    };
    const addResource = (label, val) => {
      if (val === undefined || val === null) return;
      const n = Number(val);
      if (!Number.isFinite(n) || n === 0) return;
      mults.push(`${label}×1/${n}`);
    };
    addResource('Gold', card.gold_multiplier);
    addResource('Strength', card.strength_multiplier);
    addResource('Magic', card.magic_multiplier);
    add('Shadow', card.shadow_multiplier);
    add('Holy', card.holy_multiplier);
    add('Soldier', card.soldier_multiplier);
    add('Worker', card.worker_multiplier);
    add('Monster', card.monster_multiplier);
    add('Citizen', card.citizen_multiplier);
    add('Domain', card.domain_multiplier);
    add('Boss', card.boss_multiplier);
    add('Minion', card.minion_multiplier);
    add('Beast', card.beast_multiplier);
    add('Titan', card.titan_multiplier);
    if (mults.length) parts.unshift(mults.join(' · '));
  }
  return parts.join('\n').trim();
}

function renderDetailCardItem(card, count = 1) {
  if (!card || typeof card !== 'object') {
    return `<div class="player-detail-item"><div class="player-detail-item-title">${escapeHtml(String(card))}</div></div>`;
  }
  const name = card.name || card.title || '(unnamed)';
  const id = card.starter_id || card.citizen_id || card.monster_id || card.domain_id || card.duke_id || card.id || '';
  const isCitizen = card.citizen_id !== undefined && card.citizen_id !== null;

  const hints = [];
  if (card.roll_match1 !== undefined || card.roll_match2 !== undefined) {
    const rm1 = card.roll_match1 ?? '';
    const rm2 = card.roll_match2 ?? '';
    hints.push(`Roll: ${rm1}${rm2 !== '' ? '/' + rm2 : ''}`);
  }
  if (card.gold_cost !== undefined) hints.push(`Gold cost: ${card.gold_cost}`);
  if (card.strength_cost !== undefined) hints.push(`Strength cost: ${card.strength_cost}`);
  if (card.magic_cost !== undefined) hints.push(`Magic cost: ${card.magic_cost}`);
  pushHarvestHints(hints, card);
  if (isCitizen && card.is_flipped) hints.push('Flipped — no harvest payout / roll spend counts');

  const { sn, hn, son, wn } = citizenRoleCounts(card);
  const roleParts = [];
  if (sn > 0) roleParts.push(`Shadow +${sn}`);
  if (hn > 0) roleParts.push(`Holy +${hn}`);
  if (son > 0) roleParts.push(`Soldier +${son}`);
  if (wn > 0) roleParts.push(`Worker +${wn}`);
  const isDomain = card.domain_id !== undefined && card.domain_id !== null;
  const showRoleRow = (isCitizen || isDomain) && roleParts.length;
  const roleBlock = showRoleRow
    ? `<div class="player-detail-item-sub"><strong>Roles:</strong> ${escapeHtml(roleParts.join(' · '))}</div>`
    : '';

  const subtitle = hints.length ? `<div class="player-detail-item-sub">${escapeHtml(hints.join(' · '))}</div>` : '';
  const fullText = tableauCardFullText(card);
  const rulesText = fullText
    ? `<div class="player-detail-item-sub" style="margin-top:6px;">${escapeHtml(fullText)}</div>`
    : '';
  const idText = id !== '' ? ` <span class="player-detail-mini">(#${escapeHtml(id)})</span>` : '';
  const qty = Number(count) || 1;
  const qtyText = qty > 1 ? ` <span class="player-detail-mini">×${qty}</span>` : '';
  return `<div class="player-detail-item"><div class="player-detail-item-title">${escapeHtml(name)}${qtyText}${idText}</div>${subtitle}${roleBlock}${rulesText}</div>`;
}

function renderDetailCardList(title, cards) {
  const arr = Array.isArray(cards) ? cards : [];
  if (!arr.length) {
    return `<div class="player-detail-card-block"><h3>${escapeHtml(title)}</h3><div class="player-detail-mini">none</div></div>`;
  }
  const grouped = groupCardsForTableau(arr);
  if (!grouped) {
    return `<div class="player-detail-card-block"><h3>${escapeHtml(title)} <span class="player-detail-mini">(${arr.length})</span></h3>${arr.map(c => renderDetailCardItem(c)).join('')}</div>`;
  }
  return `<div class="player-detail-card-block"><h3>${escapeHtml(title)} <span class="player-detail-mini">(${arr.length} cards, ${grouped.length} types)</span></h3>${grouped.map(x => renderDetailCardItem(x.card, x.count)).join('')}</div>`;
}

function renderPlayerDetailInner(state, playerId) {
  const players = state.player_list || [];
  const subject = players.find(p => idsMatch(p.player_id, playerId));
  if (!subject) {
    return `<p class="player-detail-mini">Player not found in this game.</p>`;
  }
  const ord = playerIndexInList(state, subject);

  const dukes = Array.isArray(subject.owned_dukes) ? subject.owned_dukes : [];
  const duke = dukes.length ? dukes[0] : null;
  const dukeName = duke ? duke.name || 'Duke' : 'Hidden';
  const dukeText = duke ? tableauCardFullText(duke) : '';
  const dukeLine = `<div class="player-detail-mini" style="margin-bottom:12px;"><strong>Duke:</strong> ${escapeHtml(duke ? dukeName : '(hidden from opponents)')}${dukeText ? `<div style="margin-top:6px;white-space:pre-wrap;">${escapeHtml(dukeText)}</div>` : ''}</div>`;

  const kv = `
    <div class="player-detail-kv">
      ${detailPill('Seat', ord >= 0 ? `${ord + 1} / ${players.length}` : '?')}
      ${detailPill('Gold', subject.gold_score ?? 0)}
      ${detailPill('Strength', subject.strength_score ?? 0)}
      ${detailPill('Magic', subject.magic_score ?? 0)}
      ${detailPill('Victory', subject.victory_score ?? 0)}
      ${detailPill('Shadow', subject.shadow_count ?? 0)}
      ${detailPill('Holy', subject.holy_count ?? 0)}
      ${detailPill('Soldier', subject.soldier_count ?? 0)}
      ${detailPill('Worker', subject.worker_count ?? 0)}
    </div>
  `;

  return `
    ${kv}
    ${dukeLine}
    <div class="player-detail-grid">
      ${renderDetailCardList('Starters', subject.owned_starters)}
      ${renderDetailCardList('Citizens', subject.owned_citizens)}
      ${renderDetailCardList('Monsters', subject.owned_monsters)}
      ${renderDetailCardList('Domains', subject.owned_domains)}
    </div>
  `;
}

function openPlayerDetailModal(playerId) {
  const state = latestGameState;
  const body = document.getElementById('player-detail-body');
  const panel = document.getElementById('player-detail-modal');
  const titleEl = document.getElementById('player-detail-title');
  if (!body || !panel) return;
  if (!state) return;
  const players = state.player_list || [];
  const subject = players.find(p => idsMatch(p.player_id, playerId));
  if (titleEl) {
    if (!subject) {
      titleEl.textContent = 'Player';
    } else {
      const displayName = (subject.name || '').toString().trim() || subject.player_id || 'Player';
      const poss = n => {
        const s = (n ?? '').toString().trim();
        if (!s) return 'Player';
        return s.toLowerCase().endsWith('s') ? `${s}'` : `${s}'s`;
      };
      titleEl.textContent = idsMatch(playerId, PLAYER_ID) ? 'Your tableau (detail)' : `${poss(displayName)} tableau`;
    }
  }
  body.innerHTML = renderPlayerDetailInner(state, playerId);
  panel.classList.add('is-open');
  panel.setAttribute('aria-hidden', 'false');
}

function closePlayerDetailModal() {
  const panel = document.getElementById('player-detail-modal');
  if (!panel) return;
  panel.classList.remove('is-open');
  panel.setAttribute('aria-hidden', 'true');
}

function initPlayerDetailModal() {
  const panel = document.getElementById('player-detail-modal');
  const closeBtn = document.getElementById('player-detail-close');
  if (panel) {
    panel.addEventListener('click', e => {
      if (e.target === panel) closePlayerDetailModal();
    });
  }
  if (closeBtn) closeBtn.addEventListener('click', () => closePlayerDetailModal());
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePlayerDetailModal();
  });
}

// ── Card factory ──────────────────────────────────────────────────────────
function cardImageUrl(card) {
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
    el.setAttribute('aria-label', card.name || 'Card');

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

// ── Game over overlay ─────────────────────────────────────────────────────
function renderGameOver(state) {
  const existing = document.getElementById('game-over-overlay');
  if (state.phase !== 'game_over' || !state.final_scores) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return;

  const overlay = mk('game-over-overlay');
  overlay.id = 'game-over-overlay';

  const panel = mk('game-over-panel');
  const title = mk('game-over-title');
  title.textContent = 'Game Over';
  panel.appendChild(title);

  const winner = (state.final_scores || []).find(s => Number(s.rank) === 1) || (state.final_scores || [])[0];
  if (winner) {
    const win = mk('game-over-winner');
    win.textContent = `${winner.name} wins!`;
    panel.appendChild(win);
  }

  (state.final_scores || []).forEach(s => {
    const row = mk('score-row');

    const rank = mk('rank');
    rank.textContent = `#${s.rank}`;
    row.appendChild(rank);

    const mid = mk('score-row-mid');

    const name = mk('sname');
    name.textContent = s.name;
    mid.appendChild(name);

    const dukeInfo = s.duke;
    if (dukeInfo && dukeInfo.duke_id != null) {
      const dukeStrip = mk('score-duke-strip');
      const img = document.createElement('img');
      img.className = 'score-duke-thumb';
      img.alt = '';
      img.loading = 'lazy';
      img.src = `/card-image/duke/${dukeInfo.duke_id}`;
      dukeStrip.appendChild(img);
      const dn = mk('score-duke-name');
      dn.textContent = dukeInfo.name || 'Duke';
      dukeStrip.appendChild(dn);
      mid.appendChild(dukeStrip);
    } else if (Number(s.duke_vp) > 0) {
      const legacy = mk('score-duke-none');
      legacy.textContent = 'Duke (card not in snapshot)';
      mid.appendChild(legacy);
    } else {
      const noDuke = mk('score-duke-none');
      noDuke.textContent = 'No Duke';
      mid.appendChild(noDuke);
    }

    const lines = Array.isArray(s.duke_vp_breakdown) ? s.duke_vp_breakdown : [];
    if (lines.length) {
      const list = mk('duke-vp-breakdown');
      lines.forEach(line => {
        const li = mk('duke-vp-line');
        const top = mk('duke-vp-line-top');
        const lbl = mk('duke-vp-line-label');
        lbl.textContent = line.label || '';
        const val = mk('duke-vp-line-vp');
        val.textContent = `+${line.vp} VP`;
        top.appendChild(lbl);
        top.appendChild(val);
        li.appendChild(top);
        if (line.detail) {
          const det = mk('duke-vp-line-detail');
          det.textContent = line.detail;
          li.appendChild(det);
        }
        list.appendChild(li);
      });
      mid.appendChild(list);
    }

    const summary = mk('score-vp-summary');
    summary.textContent = `${s.base_vp} base + ${s.duke_vp} Duke`;
    mid.appendChild(summary);

    row.appendChild(mid);

    const total = mk('total');
    total.textContent = `${s.total_vp} VP`;
    row.appendChild(total);

    panel.appendChild(row);
  });

  const shutdown = state.shutdown || null;
  const countdown = mk('game-shutdown-countdown');
  countdown.id = 'game-shutdown-countdown';
  countdown.textContent = shutdown?.redirect_at
    ? `Returning to lobby in ${fmtSecondsRemaining(shutdown.redirect_at)}s…`
    : 'Returning to lobby soon…';
  panel.appendChild(countdown);

  const actions = mk('game-shutdown-actions');
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'game-shutdown-btn';
  btn.textContent = 'Go to lobby now';
  btn.addEventListener('click', () => goToLobbyNow());
  actions.appendChild(btn);
  panel.appendChild(actions);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);
}

// ── Game shutdown / abandon overlay ────────────────────────────────────────
let _shutdownUiTimer = null;

function fmtSecondsRemaining(redirectAtEpochSeconds) {
  const msLeft = Math.max(0, Number(redirectAtEpochSeconds || 0) * 1000 - Date.now());
  return Math.ceil(msLeft / 1000);
}

function goToLobbyNow() {
  redirectToLobby();
}

async function abandonGame() {
  try {
    await fetch(`/api/game/${encodeURIComponent(GAME_ID)}/abandon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ player_id: PLAYER_ID }),
    });
  } catch (_) {
    // Even if the request fails, don't auto-navigate; player can try again.
  }
}

function renderGameShutdown(state) {
  const shutdown = state?.shutdown || null;
  const existing = document.getElementById('game-shutdown-overlay');

  if (!shutdown) {
    if (existing) existing.remove();
    if (_shutdownUiTimer) {
      clearInterval(_shutdownUiTimer);
      _shutdownUiTimer = null;
    }
    return;
  }

  const redirectAt = shutdown.redirect_at;
  const reason = String(shutdown.reason || '');
  const initiatorName = shutdown?.initiated_by?.name ? String(shutdown.initiated_by.name) : '';

  if (redirectAt && fmtSecondsRemaining(redirectAt) <= 0) {
    goToLobbyNow();
    return;
  }

  // If game over overlay exists, we reuse it and just keep countdown updated there.
  if (state.phase === 'game_over' && state.final_scores) {
    const c = document.getElementById('game-shutdown-countdown');
    if (c && redirectAt) c.textContent = `Returning to lobby in ${fmtSecondsRemaining(redirectAt)}s…`;
    return;
  }

  if (!existing) {
    const overlay = mk('game-over-overlay');
    overlay.id = 'game-shutdown-overlay';
    const panel = mk('game-over-panel');
    const title = mk('game-over-title');
    title.textContent = 'Game Ending';
    panel.appendChild(title);

    const msg = mk('game-shutdown-msg');
    if (reason === 'abandoned') {
      msg.textContent = initiatorName
        ? `${initiatorName} abandoned the game.`
        : 'A player abandoned the game.';
    } else {
      msg.textContent = 'This game is ending.';
    }
    panel.appendChild(msg);

    const countdown = mk('game-shutdown-countdown');
    countdown.id = 'game-shutdown-countdown';
    countdown.textContent = redirectAt
      ? `Returning to lobby in ${fmtSecondsRemaining(redirectAt)}s…`
      : 'Returning to lobby soon…';
    panel.appendChild(countdown);

    const actions = mk('game-shutdown-actions');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'game-shutdown-btn';
    btn.textContent = 'Go to lobby now';
    btn.addEventListener('click', () => goToLobbyNow());
    actions.appendChild(btn);
    panel.appendChild(actions);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
  }

  const countdown = document.getElementById('game-shutdown-countdown');
  if (countdown && redirectAt) {
    countdown.textContent = `Returning to lobby in ${fmtSecondsRemaining(redirectAt)}s…`;
  }

  if (!_shutdownUiTimer) {
    _shutdownUiTimer = setInterval(() => {
      if (!latestGameState?.shutdown) return;
      const ra = latestGameState.shutdown.redirect_at;
      if (ra && fmtSecondsRemaining(ra) <= 0) goToLobbyNow();
      const c = document.getElementById('game-shutdown-countdown');
      if (c && ra) c.textContent = `Returning to lobby in ${fmtSecondsRemaining(ra)}s…`;
    }, 250);
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────
function mk(classes) {
  const el = document.createElement('div');
  el.className = classes || '';
  return el;
}

function fmtPhase(phase) {
  return {
    roll:      'Roll Phase',
    harvest:   'Harvest Phase',
    action:    'Action Phase',
    cleanup:   'Cleanup',
    game_over: 'Game Over',
    setup:     'Setup',
  }[phase] || (phase || '');
}

// ── Card hover preview ────────────────────────────────────────────────────
const _previewEl = document.createElement('img');
_previewEl.className = 'card-preview';
document.body.appendChild(_previewEl);

let _hoverCard         = null;
let _hoverTimer        = null;
let _pendingRect       = null;
let _previewPlacement  = 'auto';

function previewPlacementForCard(cardEl) {
  if (!cardEl.closest('.center-board')) return 'auto';
  if (cardEl.closest('.citizen-row-second')) return 'above';
  if (cardEl.closest('.board-domains')) return 'above';
  if (cardEl.closest('.board-monsters')) return 'below';
  if (cardEl.closest('.citizen-row-first')) return 'below';
  return 'auto';
}

_previewEl.onload = () => {
  if (_pendingRect) {
    positionPreview(_pendingRect, _previewEl.naturalWidth, _previewEl.naturalHeight, _previewPlacement);
  }
};

function positionPreview(rect, w, h, placement) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const mode = placement != null ? placement : _previewPlacement;
  let top;
  if (mode === 'below') {
    top = rect.bottom + 8;
    if (top + h > vh - 8) top = rect.top - h - 8;
  } else if (mode === 'above') {
    top = rect.top - h - 8;
    if (top < 8) top = rect.bottom + 8;
  } else {
    top = rect.top - h - 8;
    if (top < 8) top = rect.bottom + 8;
  }
  let left = rect.left + rect.width / 2 - w / 2;
  left = Math.max(8, Math.min(left, vw - w - 8));
  _previewEl.style.top  = top  + 'px';
  _previewEl.style.left = left + 'px';
}

document.addEventListener('mouseover', e => {
  const cardEl = e.target.closest('.card[data-card]');
  if (cardEl === _hoverCard) return;
  clearTimeout(_hoverTimer);
  _hoverCard = cardEl;
  if (!cardEl) { _previewEl.style.display = 'none'; return; }

  const card = JSON.parse(cardEl.dataset.card);
  const url  = cardImageUrl(card);
  if (!url) return;

  _previewPlacement = previewPlacementForCard(cardEl);

  _hoverTimer = setTimeout(() => {
    const rect = cardEl.getBoundingClientRect();
    _pendingRect = rect;
    _previewEl.style.display = 'block';
    if (_previewEl.src.endsWith(url) && _previewEl.complete && _previewEl.naturalWidth) {
      positionPreview(rect, _previewEl.naturalWidth, _previewEl.naturalHeight, _previewPlacement);
    } else {
      _previewEl.src = url;
    }
  }, 120);
});

document.addEventListener('mouseout', e => {
  const cardEl = e.target.closest('.card[data-card]');
  if (!cardEl || cardEl.contains(e.relatedTarget)) return;
  clearTimeout(_hoverTimer);
  _hoverCard = null;
  _previewEl.style.display = 'none';
});

// ── Board market actions (hire / build / slay) ─────────────────────────────
function topOfStack(stack) {
  if (!Array.isArray(stack) || stack.length === 0) return null;
  return stack[stack.length - 1];
}

function canAffordCost(player, cost) {
  const G = Number(player?.gold_score || 0);
  const S = Number(player?.strength_score || 0);
  const M = Number(player?.magic_score || 0);
  const goldCost = Number(cost?.gold || 0);
  const strengthCost = Number(cost?.strength || 0);
  const magicMin = Number(cost?.magicMin || 0);

  const remainingMagic = M - magicMin;
  if (remainingMagic < 0) return { ok: false };

  const deficitGold = Math.max(0, goldCost - G);
  const deficitStrength = Math.max(0, strengthCost - S);

  if (goldCost > 0 && deficitGold > 0 && G <= 0) return { ok: false };
  if (strengthCost > 0 && deficitStrength > 0 && S <= 0) return { ok: false };

  const ok = (deficitGold + deficitStrength) <= remainingMagic;

  const payGold = Math.min(G, goldCost);
  const payStrength = Math.min(S, strengthCost);
  const payMagic = magicMin + deficitGold + deficitStrength;
  return { ok, payGold, payStrength, payMagic, deficitGold, deficitStrength, remainingMagic };
}

function ownedNameCount(player, name) {
  const target = (name ?? '').toString();
  if (!target) return 0;
  const starters = Array.isArray(player?.owned_starters) ? player.owned_starters : [];
  const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
  let n = 0;
  starters.forEach(c => { if ((c?.name ?? '').toString() === target) n += 1; });
  citizens.forEach(c => { if ((c?.name ?? '').toString() === target) n += 1; });
  return n;
}

function citizenRoleCounts(card) {
  const r = card && card.roles;
  if (r && typeof r === 'object') {
    return {
      sn: Number(r.shadow) || 0,
      hn: Number(r.holy) || 0,
      son: Number(r.soldier) || 0,
      wn: Number(r.worker) || 0,
    };
  }
  return {
    sn: Number(card.shadow_count) || 0,
    hn: Number(card.holy_count) || 0,
    son: Number(card.soldier_count) || 0,
    wn: Number(card.worker_count) || 0,
  };
}

function formatHarvestGSM(card, onTurn) {
  const g = onTurn ? 'gold_payout_on_turn' : 'gold_payout_off_turn';
  const s = onTurn ? 'strength_payout_on_turn' : 'strength_payout_off_turn';
  const m = onTurn ? 'magic_payout_on_turn' : 'magic_payout_off_turn';
  const gv = Number(card[g]) || 0;
  const sv = Number(card[s]) || 0;
  const mv = Number(card[m]) || 0;
  return `G ${gv}, S ${sv}, M ${mv}`;
}

function pushHarvestHints(hints, card) {
  const hasOn = card.gold_payout_on_turn !== undefined || card.strength_payout_on_turn !== undefined || card.magic_payout_on_turn !== undefined;
  const hasOff = card.gold_payout_off_turn !== undefined || card.strength_payout_off_turn !== undefined || card.magic_payout_off_turn !== undefined;
  if (!hasOn && !hasOff) return;
  const onStr = formatHarvestGSM(card, true);
  const offStr = formatHarvestGSM(card, false);
  if (onStr === offStr) {
    hints.push(`Harvest: ${onStr} (on & off turn)`);
  } else {
    hints.push(`Harvest (on turn): ${onStr}`);
    hints.push(`Harvest (off turn): ${offStr}`);
  }
}

function cardDetailedRules(card) {
  if (!card || typeof card !== 'object') return '';
  const rawText = (card.text ?? '').toString().trim();
  if (rawText) return rawText;

  const parts = [];
  pushHarvestHints(parts, card);
  if (card.monster_id !== undefined && card.monster_id !== null) {
    const vp = Number(card.vp_reward || 0);
    const gr = Number(card.gold_reward || 0);
    const sr = Number(card.strength_reward || 0);
    const mr = Number(card.magic_reward || 0);
    parts.push(`Reward: VP ${vp} · G ${gr} · S ${sr} · M ${mr}`);
  }

  const passive = (card.passive_effect ?? '').toString().trim();
  const activation = (card.activation_effect ?? '').toString().trim();
  if (passive) parts.push(`Passive: ${passive}`);
  if (activation) parts.push(`Activation: ${activation}`);

  const spOn = (card.special_payout_on_turn ?? '').toString().trim();
  const spOff = (card.special_payout_off_turn ?? '').toString().trim();
  if (spOn) parts.push(`Special (on turn): ${spOn}`);
  if (spOff) parts.push(`Special (off turn): ${spOff}`);

  const specialReward = (card.special_reward ?? '').toString().trim();
  const specialCost = (card.special_cost ?? '').toString().trim();
  if (specialReward) parts.push(`Special reward: ${specialReward}`);
  if (specialCost) parts.push(`Special cost: ${specialCost}`);

  return parts.join('\n').trim();
}

function normalizedPassiveEffects(player, turnNumber) {
  const out = [];
  const domains = Array.isArray(player?.owned_domains) ? player.owned_domains : [];
  domains.forEach(d => {
    if (domainPassiveOnBuildTurnCooldown(d, turnNumber)) return;
    const name = (d?.name ?? '').toString().trim().toLowerCase();
    const text = (d?.text ?? '').toString().trim().toLowerCase();
    const raw = (d?.passive_effect ?? '').toString().trim().toLowerCase();
    if (raw) {
      out.push(raw);
      const nrm = raw.replace(/effect:add/g, 'effect.add').replace(/action:/g, 'action.');
      if (nrm.startsWith('effect.add ')) {
        out.push(nrm.slice('effect.add '.length).trim());
      }
    }
    if (name.includes('emerald stronghold') || (text.includes("ignore '+'") && text.includes('buying citizens'))) {
      out.push('action.emeraldstronghold');
    }
    if (name.includes('pratchett') || (text.includes('1gp less') && text.includes('domain'))) {
      out.push('action.pratchettsplateau');
    }
  });
  return out;
}

function hasActionEffectFlag(player, flag, turnNumber) {
  const target = (flag ?? '').toString().trim().toLowerCase();
  if (!target) return false;
  const effects = normalizedPassiveEffects(player, turnNumber);
  return effects.includes(target);
}

function findMarketStack(card, state) {
  let grid = null;
  let idKey = null;
  if (card.monster_id != null) { grid = state?.monster_grid; idKey = 'monster_id'; }
  else if (card.citizen_id != null) { grid = state?.citizen_grid; idKey = 'citizen_id'; }
  else if (card.domain_id != null) { grid = state?.domain_grid; idKey = 'domain_id'; }
  else return null;
  const stacks = Array.isArray(grid) ? grid : [];
  const cid = card[idKey];
  for (let i = 0; i < stacks.length; i++) {
    const top = topOfStack(stacks[i]);
    if (!top || top[idKey] !== cid) continue;
    return { stack: stacks[i], stackIndex: i, top };
  }
  return null;
}

function evaluateMarketCardContext(card, state) {
  const phase = (state?.phase || '').toString();
  const req = state?.action_required || {};
  const reqAction = (req?.action || '').toString();
  const reqId = req?.id || '';
  const standardActionPhase =
    phase === 'action' && reqAction === 'standard_action' && reqId && reqId !== state?.game_id;
  const isYourTurn = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const actionsRemaining = Number(state?.actions_remaining || 0);

  const players = state?.player_list || [];
  const actingPlayer = players.find(p => idsMatch(p.player_id, reqId)) || null;

  const tn = Number(state?.turn_number);
  const emeraldActive = actingPlayer ? hasActionEffectFlag(actingPlayer, 'action.emeraldstronghold', tn) : false;
  const pratchettActive = actingPlayer ? hasActionEffectFlag(actingPlayer, 'action.pratchettsplateau', tn) : false;

  const loc = state ? findMarketStack(card, state) : null;
  let blockReason = '';
  let top = loc ? loc.top : null;
  let stackSize = loc ? loc.stack.length : 0;

  if (!state) {
    blockReason = 'Game state not loaded.';
  } else if (!loc) {
    blockReason = 'This card is not on the market (stacks may have changed).';
  } else if (card.monster_id != null && !top.is_accessible) {
    blockReason = 'This monster stack is blocked.';
  } else if (card.citizen_id != null && !top.is_accessible) {
    blockReason = 'This citizen stack is blocked.';
  } else if (card.domain_id != null && (!top.is_visible || !top.is_accessible)) {
    blockReason = 'This domain cannot be built right now.';
  }

  let evalRes = { ok: false, payGold: 0, payStrength: 0, payMagic: 0 };
  let scaledCost = 0;
  let baseCost = 0;
  let surcharge = 0;
  let effectiveGold = 0;
  let pratchettHint = '';
  let dupHint = '';
  let emeraldHint = '';

  if (actingPlayer && loc && top && !blockReason) {
    if (card.citizen_id != null) {
      baseCost = Number(top.gold_cost || 0);
      surcharge = emeraldActive ? 0 : ownedNameCount(actingPlayer, top.name);
      scaledCost = baseCost + surcharge;
      evalRes = canAffordCost(actingPlayer, { gold: scaledCost, strength: 0, magicMin: 0 });
      dupHint = surcharge ? `base ${baseCost}g + ${surcharge} duplicate(s)` : '';
      emeraldHint = (!surcharge && emeraldActive) ? 'Emerald Stronghold: no duplicate surcharge.' : '';
    } else if (card.domain_id != null) {
      baseCost = Number(top.gold_cost || 0);
      effectiveGold = Math.max(0, baseCost - (pratchettActive ? 1 : 0));
      evalRes = canAffordCost(actingPlayer, { gold: effectiveGold, strength: 0, magicMin: 0 });
      pratchettHint = pratchettActive && baseCost !== effectiveGold ? `base ${baseCost}g − 1 (Pratchett's Plateau)` : '';
    } else if (card.monster_id != null) {
      evalRes = canAffordCost(actingPlayer, {
        gold: 0,
        strength: Number(top.strength_cost || 0),
        magicMin: Number(top.magic_cost || 0),
      });
    }
  }

  const canActThisCard =
    standardActionPhase &&
    isYourTurn &&
    actionsRemaining > 0 &&
    loc &&
    !blockReason;

  return {
    phase,
    standardActionPhase,
    isYourTurn,
    actionsRemaining,
    actingPlayer,
    reqId,
    emeraldActive,
    pratchettActive,
    loc,
    top,
    stackSize,
    blockReason,
    evalRes,
    scaledCost,
    baseCost,
    surcharge,
    effectiveGold,
    pratchettHint,
    dupHint,
    emeraldHint,
    canActThisCard,
  };
}

function clampPayInt(value, minV, maxV) {
  let n = Math.floor(Number(value));
  if (!Number.isFinite(n)) n = 0;
  const lo = Math.floor(Number(minV) || 0);
  const hiRaw = maxV === '' || maxV === undefined || maxV === null ? null : Number(maxV);
  const hi = hiRaw === null || !Number.isFinite(hiRaw) ? null : Math.floor(hiRaw);
  n = Math.max(lo, n);
  if (hi !== null) n = Math.min(hi, n);
  return n;
}

function readMarketPayRow(row) {
  const gEl = row.querySelector('.pay-g');
  const sEl = row.querySelector('.pay-s');
  const mEl = row.querySelector('.pay-m');
  const g = (!gEl || gEl.disabled) ? 0 : clampPayInt(gEl.value, gEl.min, gEl.max);
  const s = (!sEl || sEl.disabled) ? 0 : clampPayInt(sEl.value, sEl.min, sEl.max);
  const m = (!mEl || mEl.disabled) ? 0 : clampPayInt(mEl.value, mEl.min, mEl.max);
  return { gold: g, strength: s, magic: m };
}

function mkPayField(label, cls, minV, maxV, value, disabled, title, resourceIconKey) {
  const lab = document.createElement('label');
  lab.className = 'market-pay-field';
  if (title) lab.title = title;
  const span = document.createElement('span');
  span.className = 'market-pay-field-label';
  if (resourceIconKey && TABLEAU_RESOURCE_ICONS[resourceIconKey]) {
    span.classList.add(`market-pay-field-label--${resourceIconKey}`);
    const img = document.createElement('img');
    img.className = 'market-pay-label-icon';
    img.src = TABLEAU_RESOURCE_ICONS[resourceIconKey];
    img.alt = '';
    span.appendChild(img);
    if (label) span.appendChild(document.createTextNode(` ${label}`));
  } else {
    span.textContent = label;
  }
  lab.appendChild(span);
  const inp = document.createElement('input');
  inp.type = 'number';
  inp.className = `market-pay-input ${cls}`;
  inp.min = String(minV);
  inp.max = maxV === null || maxV === undefined ? '' : String(maxV);
  inp.value = String(value);
  inp.disabled = !!disabled;
  lab.appendChild(inp);
  return lab;
}

function fillMarketCostSummary(costEl, card, ctx, pay) {
  const stackTail = ` · stack ×${ctx.stackSize}`;
  if (card.citizen_id != null) {
    costEl.appendChild(document.createTextNode('Cost: '));
    costEl.appendChild(makeModalResourceInline('gold', ctx.scaledCost, 'modal-gold', false));
    if (ctx.dupHint) costEl.appendChild(document.createTextNode(` (${ctx.dupHint})`));
    if (ctx.emeraldHint) costEl.appendChild(document.createTextNode(` · ${ctx.emeraldHint}`));
    costEl.appendChild(document.createTextNode(' · suggested pay '));
    costEl.appendChild(makeModalResourceInline('gold', pay.payGold ?? 0, 'modal-gold', false));
    if (pay.payMagic) {
      costEl.appendChild(document.createTextNode(', '));
      costEl.appendChild(makeModalResourceInline('magic', pay.payMagic ?? 0, 'modal-mag', false));
    }
    costEl.appendChild(document.createTextNode(stackTail));
    return;
  }
  if (card.domain_id != null) {
    costEl.appendChild(document.createTextNode('Cost: '));
    costEl.appendChild(makeModalResourceInline('gold', ctx.effectiveGold, 'modal-gold', false));
    if (ctx.pratchettHint) costEl.appendChild(document.createTextNode(` (${ctx.pratchettHint})`));
    costEl.appendChild(document.createTextNode(' · suggested pay '));
    costEl.appendChild(makeModalResourceInline('gold', pay.payGold ?? 0, 'modal-gold', false));
    if (pay.payMagic) {
      costEl.appendChild(document.createTextNode(', '));
      costEl.appendChild(makeModalResourceInline('magic', pay.payMagic ?? 0, 'modal-mag', false));
    }
    costEl.appendChild(document.createTextNode(stackTail));
    return;
  }
  if (card.monster_id != null) {
    const sc = Number(ctx.top?.strength_cost || 0);
    const mm = Number(ctx.top?.magic_cost || 0);
    costEl.appendChild(document.createTextNode('Cost: '));
    costEl.appendChild(makeModalResourceInline('strength', sc, 'modal-str', false));
    costEl.appendChild(document.createTextNode(' + '));
    costEl.appendChild(makeModalResourceInline('magic', mm, 'modal-mag', false));
    costEl.appendChild(document.createTextNode(' minimum · suggested pay '));
    costEl.appendChild(makeModalResourceInline('strength', pay.payStrength ?? 0, 'modal-str', false));
    costEl.appendChild(document.createTextNode(', '));
    costEl.appendChild(makeModalResourceInline('magic', pay.payMagic ?? 0, 'modal-mag', false));
    costEl.appendChild(document.createTextNode(stackTail));
  }
}

function appendMarketActionUI(infoEl, card, ctx) {
  const panel = mk('market-action-panel');
  const actName = ctx.actingPlayer?.name || ctx.reqId || 'Active player';

  const hdr = mk('market-action-heading');
  if (ctx.standardActionPhase) {
    hdr.textContent = ctx.isYourTurn
      ? `Your action (${ctx.actionsRemaining} remaining)`
      : `${actName}'s turn — ${ctx.actionsRemaining} action(s) remaining`;
  } else {
    hdr.textContent = `Phase: ${fmtPhase(ctx.phase)}`;
  }
  panel.appendChild(hdr);

  if (ctx.actingPlayer) {
    const p = ctx.actingPlayer;
    const resRow = mk('market-resources-row market-resources-row--strip');
    const intro = document.createElement('span');
    intro.className = 'market-resources-intro';
    intro.textContent = `Resources (${actName}):`;
    resRow.appendChild(intro);
    resRow.appendChild(makeResourceScorePill('gold', p.gold_score, 'Gold', TABLEAU_RESOURCE_ICONS.gold));
    resRow.appendChild(makeResourceScorePill('strength', p.strength_score, 'Strength', TABLEAU_RESOURCE_ICONS.strength));
    resRow.appendChild(makeResourceScorePill('magic', p.magic_score, 'Magic', TABLEAU_RESOURCE_ICONS.magic));
    resRow.appendChild(makeVpScorePill(p.victory_score));
    panel.appendChild(resRow);
  }

  const fx = [];
  if (ctx.emeraldActive) fx.push('Emerald Stronghold: ignore citizen duplicate surcharge');
  if (ctx.pratchettActive) fx.push("Pratchett's Plateau: domains cost 1 less gold");
  if (fx.length) {
    const fb = mk('market-effects-banner');
    fb.textContent = `Active: ${fx.join(' · ')}`;
    panel.appendChild(fb);
  }

  if (ctx.blockReason) {
    const br = mk('market-block-note');
    br.textContent = ctx.blockReason;
    panel.appendChild(br);
  }

  const payWrap = mk('market-pay-row');
  const Gmax = Number(ctx.actingPlayer?.gold_score || 0);
  const Smax = Number(ctx.actingPlayer?.strength_score || 0);
  const Mmax = Number(ctx.actingPlayer?.magic_score || 0);
  const pay = ctx.evalRes;
  const inputsDisabled = !ctx.standardActionPhase;

  let primaryLabel = '';

  if (card.citizen_id != null) {
    primaryLabel = 'Hire citizen';
    payWrap.dataset.citizenId = String(card.citizen_id);
    payWrap.appendChild(mkPayField('', 'pay-g', 0, Gmax, pay.payGold ?? 0, inputsDisabled, 'Gold payment', 'gold'));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, 0, 0, true, 'Citizens use gold and magic', 'strength'));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic'));
  } else if (card.domain_id != null) {
    primaryLabel = 'Build domain';
    payWrap.dataset.domainId = String(card.domain_id);
    payWrap.appendChild(mkPayField('', 'pay-g', 0, Gmax, pay.payGold ?? 0, inputsDisabled, 'Gold payment', 'gold'));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, 0, 0, true, 'Domains use gold and magic', 'strength'));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic'));
  } else if (card.monster_id != null) {
    primaryLabel = 'Slay monster';
    payWrap.dataset.monsterId = String(card.monster_id);
    payWrap.appendChild(mkPayField('', 'pay-g', 0, 0, 0, true, 'Monsters use strength and magic', 'gold'));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, Smax, pay.payStrength ?? 0, inputsDisabled, 'Strength payment', 'strength'));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic'));
  }

  const costEl = mk('market-cost-summary');
  fillMarketCostSummary(costEl, card, ctx, pay);
  panel.appendChild(costEl);

  const affordEl = mk(ctx.evalRes.ok ? 'market-afford-ok' : 'market-afford-bad');
  affordEl.textContent = ctx.evalRes.ok
    ? 'Suggested payment fits current resources.'
    : 'Suggested payment exceeds resources — adjust G/S/M or magic coverage.';
  panel.appendChild(affordEl);

  const fieldsRow = mk('market-pay-fields');
  fieldsRow.appendChild(payWrap);
  panel.appendChild(fieldsRow);

  const btnRow = mk('market-primary-actions');

  function attachPrimary(btnEl, disabled) {
    if (disabled) btnEl.disabled = true;
    btnRow.appendChild(btnEl);
  }

  const hireDisabled = !(card.citizen_id != null && ctx.canActThisCard);
  const buildDisabled = !(card.domain_id != null && ctx.canActThisCard);
  const slayDisabled = !(card.monster_id != null && ctx.canActThisCard);

  if (card.citizen_id != null) {
    attachPrimary(promptButton('Hire', () => {
      const p = readMarketPayRow(payWrap);
      postGameAction({
        player_id: PLAYER_ID,
        action_type: 'hire_citizen',
        citizen_id: Number(card.citizen_id),
        payment: { gold: p.gold, strength: p.strength, magic: p.magic },
      });
      document.getElementById('card-modal-overlay')?.remove();
    }), hireDisabled);
  } else if (card.domain_id != null) {
    attachPrimary(promptButton('Build', () => {
      const p = readMarketPayRow(payWrap);
      postGameAction({
        player_id: PLAYER_ID,
        action_type: 'build_domain',
        domain_id: Number(card.domain_id),
        payment: { gold: p.gold, strength: p.strength, magic: p.magic },
      });
      document.getElementById('card-modal-overlay')?.remove();
    }), buildDisabled);
  } else if (card.monster_id != null) {
    attachPrimary(promptButton('Slay', () => {
      const p = readMarketPayRow(payWrap);
      postGameAction({
        player_id: PLAYER_ID,
        action_type: 'slay_monster',
        monster_id: Number(card.monster_id),
        payment: { gold: p.gold, strength: p.strength, magic: p.magic },
      });
      document.getElementById('card-modal-overlay')?.remove();
    }), slayDisabled);
  }

  panel.appendChild(btnRow);

  const help = mk('market-action-help');
  help.textContent =
    primaryLabel
      ? `${primaryLabel}: adjust gold, strength, and magic payment (magic covers shortages after you spend required minimum magic on monsters).`
      : '';
  if (help.textContent) panel.appendChild(help);

  infoEl.appendChild(panel);
}

function openMarketCardModal(card) {
  if (document.getElementById('game-prompt-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;

  const state = latestGameState;
  const ctx = evaluateMarketCardContext(card, state);

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';

  const modal = mk('card-modal card-modal--market');
  modal.addEventListener('click', e => e.stopPropagation());

  const url = cardImageUrl(card);
  if (url) {
    const img = document.createElement('img');
    img.className = 'card-modal-img';
    img.src = url;
    modal.appendChild(img);
  }

  const info = mk('card-modal-info');

  const heading = document.createElement('h2');
  heading.className = 'modal-card-name';
  heading.textContent = card.name || '?';
  info.appendChild(heading);

  appendCardModalStatRows(info, card);

  const rc = citizenRoleCounts(card);
  const rp = [];
  if (rc.sn > 0) rp.push(`Shadow +${rc.sn}`);
  if (rc.hn > 0) rp.push(`Holy +${rc.hn}`);
  if (rc.son > 0) rp.push(`Soldier +${rc.son}`);
  if (rc.wn > 0) rp.push(`Worker +${rc.wn}`);
  if (rp.length && (card.citizen_id != null || card.domain_id != null)) {
    const row = mk('modal-stat-row');
    const l = document.createElement('span');
    l.className = 'modal-stat-label';
    l.textContent = 'Roles';
    const v = document.createElement('span');
    v.className = 'modal-stat-value';
    v.textContent = rp.join(' · ');
    row.appendChild(l);
    row.appendChild(v);
    info.appendChild(row);
  }

  if (card.text) {
    const t = document.createElement('p');
    t.className = 'modal-card-text';
    t.textContent = card.text;
    info.appendChild(t);
  }

  const rules = cardDetailedRules(card);
  if (rules && rules !== (card.text || '').toString().trim()) {
    const t2 = document.createElement('p');
    t2.className = 'modal-card-text market-rules-extra';
    t2.textContent = rules;
    info.appendChild(t2);
  }

  appendMarketActionUI(info, card, ctx);

  modal.appendChild(info);
  overlay.appendChild(modal);
  overlay.addEventListener('click', () => overlay.remove());
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); }
  });
  document.body.appendChild(overlay);
}

function isBoardMarketCard(card, cardEl) {
  if (!cardEl || !cardEl.closest('.center-board')) return false;
  return card.monster_id != null || card.citizen_id != null || card.domain_id != null;
}

// ── Card click modal ──────────────────────────────────────────────────────
document.addEventListener('click', e => {
  const cardEl = e.target.closest('.card[data-card]');
  if (!cardEl) return;
  _previewEl.style.display = 'none';
  const card = JSON.parse(cardEl.dataset.card);
  if (isBoardMarketCard(card, cardEl)) {
    openMarketCardModal(card);
    return;
  }
  openCardModal(card);
});

function openCardModal(card) {
  if (document.getElementById('game-prompt-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';

  const modal = mk('card-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const url = cardImageUrl(card);
  if (url) {
    const img = document.createElement('img');
    img.className = 'card-modal-img';
    img.src = url;
    modal.appendChild(img);
  }

  const info = mk('card-modal-info');

  const heading = document.createElement('h2');
  heading.className = 'modal-card-name';
  heading.textContent = card.name || '?';
  info.appendChild(heading);

  appendCardModalStatRows(info, card);

  if (card.text) {
    const t = document.createElement('p');
    t.className = 'modal-card-text';
    t.textContent = card.text;
    info.appendChild(t);
  }

  modal.appendChild(info);
  overlay.appendChild(modal);
  overlay.addEventListener('click', () => overlay.remove());
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); }
  });
  document.body.appendChild(overlay);
}

function buildCardStats(card) {
  const rows = [];
  const push = (label, value, cls, resource, leadingPlus) => {
    if (value != null && value !== 0 && value !== '') {
      rows.push({
        label,
        value,
        cls: cls || '',
        resource: resource || null,
        leadingPlus: !!leadingPlus,
      });
    }
  };

  if      (card.monster_id  != null) push('Type', 'Monster', null, null, false);
  else if (card.citizen_id  != null) push('Type', 'Citizen', null, null, false);
  else if (card.domain_id   != null) push('Type', 'Domain', null, null, false);
  else if (card.duke_id     != null) push('Type', 'Duke', null, null, false);
  else if (card.starter_id  != null) push('Type', 'Starter', null, null, false);

  if (card.gold_cost)       push('Gold cost',    card.gold_cost,       'modal-gold', 'gold', false);
  if (card.strength_cost)   push('Str cost',     card.strength_cost,   'modal-str',  'strength', false);
  if (card.magic_cost)      push('Mag cost',     card.magic_cost,      'modal-mag',  'magic', false);
  if (card.vp_reward)      push('VP reward',    card.vp_reward,       'modal-vp',   'vp', false);
  if (card.gold_reward)     push('Gold reward',  card.gold_reward,     'modal-gold', 'gold', true);
  if (card.strength_reward) push('Str reward',   card.strength_reward, 'modal-str',  'strength', true);
  if (card.magic_reward)    push('Mag reward',   card.magic_reward,    'modal-mag',  'magic', true);

  if (card.domain_id != null) {
    const req = [];
    if (card.shadow_count)  req.push(`${card.shadow_count} Shadow`);
    if (card.holy_count)    req.push(`${card.holy_count} Holy`);
    if (card.soldier_count) req.push(`${card.soldier_count} Soldier`);
    if (card.worker_count)  req.push(`${card.worker_count} Worker`);
    if (req.length) push('Requires', req.join(', '));
  }

  if (card.starter_id != null) {
    const m1 = card.roll_match1, m2 = card.roll_match2;
    if (m1 && m2 && m1 !== m2) push('Rolls', `${m1}, ${m2}`);
    else if (m1) push('Roll', String(m1));
  }

  if (card.is_flipped) push('Status', 'Flipped');

  return rows;
}

// ── Prompt modal (required choices, concurrent setup) ─────────────────────
function clampDie(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) return 1;
  return Math.max(1, Math.min(6, Math.trunc(x)));
}

function syncConcurrentPolling(state) {
  const ca = state?.concurrent_action;
  const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
  const should = pend.length > 0;
  if (should && !concurrentPollTimer) {
    concurrentPollTimer = setInterval(() => {
      fetchGameStateFromApi();
    }, 1500);
  } else if (!should && concurrentPollTimer) {
    clearInterval(concurrentPollTimer);
    concurrentPollTimer = null;
  }
}

async function fetchGameStateFromApi() {
  if (!GAME_ID || !PLAYER_ID) return;
  try {
    const res = await fetch(`/api/game/${encodeURIComponent(GAME_ID)}/state?player_id=${encodeURIComponent(PLAYER_ID)}`);
    if (!res.ok) {
      if (res.status === 404) {
        const payload = await res.json().catch(() => ({}));
        if (clientShouldDropStoredGame(payload)) {
          redirectToLobby();
          return;
        }
      }
      return;
    }
    const data = await res.json();
    render(data);
  } catch (e) {
    console.error(e);
  }
}

async function postGameAction(body) {
  const res = await fetch(`/api/game/${encodeURIComponent(GAME_ID)}/action`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload?.detail || res.statusText || 'Request failed';
    if (res.status === 404 && clientShouldDropStoredGame(payload)) {
      redirectToLobby();
      return false;
    }
    window.alert(detail);
    return false;
  }
  if (payload?.game_state) render(payload.game_state);
  else fetchGameStateFromApi();
  return true;
}

function removePromptOverlay() {
  const el = document.getElementById('game-prompt-overlay');
  if (el && el._promptClickHandler) {
    el.removeEventListener('click', el._promptClickHandler);
    el._promptClickHandler = null;
  }
  if (el && el._promptEscHandler) {
    document.removeEventListener('keydown', el._promptEscHandler);
    el._promptEscHandler = null;
  }
  if (el && el._prevBodyOverflow !== undefined) {
    document.body.style.overflow = el._prevBodyOverflow;
    el._prevBodyOverflow = undefined;
  }
  el?.remove();
}

function openPromptOverlayShell(opts) {
  const { title, subtitle, dismissible, bodyEl, footerEl } = opts;
  const newTitle = (title || '').toString();

  function configureDismissBehavior(overlay) {
    // Clear prior handlers first.
    if (overlay._promptClickHandler) {
      overlay.removeEventListener('click', overlay._promptClickHandler);
      overlay._promptClickHandler = null;
    }
    if (overlay._promptEscHandler) {
      document.removeEventListener('keydown', overlay._promptEscHandler);
      overlay._promptEscHandler = null;
    }

    if (!dismissible) return;

    const dismiss = () => removePromptOverlay();
    const onKey = e => {
      if (e.key === 'Escape') dismiss();
    };
    overlay._promptClickHandler = dismiss;
    overlay._promptEscHandler = onKey;
    overlay.addEventListener('click', dismiss);
    document.addEventListener('keydown', onKey);
  }

  // If a prompt overlay already exists, update it in-place.
  const overlay = document.getElementById('game-prompt-overlay');
  if (overlay) {
    const modal = overlay.querySelector('.card-modal');
    if (!modal) {
      removePromptOverlay();
      return openPromptOverlayShell(opts);
    }

    // Lock background scroll while overlay is present.
    if (overlay._prevBodyOverflow === undefined) {
      overlay._prevBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    }

    const head = modal.querySelector('.prompt-modal-head');
    const titleEl = modal.querySelector('.prompt-modal-title');
    if (titleEl) titleEl.textContent = newTitle;
    if (head) {
      let subEl = head.querySelector('.prompt-modal-subtitle');
      if (subtitle) {
        if (!subEl) {
          subEl = mk('prompt-modal-subtitle');
          head.appendChild(subEl);
        }
        subEl.textContent = subtitle;
      } else if (subEl) {
        subEl.remove();
      }
    }

    // Preserve current scroll positions while we swap content.
    const preservedModalScroll = modal.scrollTop;
    const preservedList = modal.querySelector('.prompt-choice-list');
    const preservedChoiceListScroll = preservedList ? preservedList.scrollTop : 0;

    // Remove existing body/footer (keep head).
    Array.from(modal.children).forEach(ch => {
      if (ch.classList?.contains('prompt-modal-head')) return;
      ch.remove();
    });

    if (bodyEl) modal.appendChild(bodyEl);
    if (footerEl) {
      const ft = mk('prompt-modal-footer');
      ft.appendChild(footerEl);
      modal.appendChild(ft);
    }

    configureDismissBehavior(overlay);

    // Restore scroll without any overlay teardown/recreate flicker.
    modal.scrollTop = preservedModalScroll;
    const list = modal.querySelector('.prompt-choice-list');
    if (list) list.scrollTop = preservedChoiceListScroll;
    return;
  }

  // Otherwise create it fresh.
  const newOverlay = document.createElement('div');
  newOverlay.id = 'game-prompt-overlay';
  newOverlay.className = 'card-modal-overlay game-prompt-overlay';
  newOverlay._prevBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = 'hidden';

  const modal = mk('card-modal card-modal--prompt');
  modal.addEventListener('click', e => e.stopPropagation());

  const head = mk('prompt-modal-head');
  const h = document.createElement('h2');
  h.className = 'modal-card-name prompt-modal-title';
  h.textContent = newTitle;
  head.appendChild(h);
  if (subtitle) {
    const sub = mk('prompt-modal-subtitle');
    sub.textContent = subtitle;
    head.appendChild(sub);
  }
  modal.appendChild(head);

  if (bodyEl) modal.appendChild(bodyEl);
  if (footerEl) {
    const ft = mk('prompt-modal-footer');
    ft.appendChild(footerEl);
    modal.appendChild(ft);
  }

  newOverlay.appendChild(modal);
  configureDismissBehavior(newOverlay);
  document.body.appendChild(newOverlay);
}

function promptButton(label, onClick, secondary) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = secondary ? 'prompt-btn prompt-btn-secondary' : 'prompt-btn';
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

function promptActionsRow(buttons) {
  const row = mk('prompt-modal-actions');
  buttons.forEach(b => row.appendChild(b));
  return row;
}

function harvestTurnChip(state, forPlayerId) {
  const pid = (forPlayerId || '').toString();
  const ap = state?.active_player_id;
  if (!pid || ap == null) return null;
  const onTurn = idsMatch(pid, ap);
  const el = mk('prompt-turn-chip');
  el.textContent = onTurn ? 'On-turn harvest' : 'Off-turn harvest';
  if (onTurn) el.classList.add('is-on-turn');
  return el;
}

function playerById(state, pid) {
  const list = state?.player_list || [];
  return list.find(p => idsMatch(p.player_id, pid)) || null;
}

function playerDisplayName(state, pid) {
  const p = playerById(state, pid);
  const nm = (p?.name ?? '').toString().trim();
  const id = (pid ?? '').toString();
  return nm || id || 'Player';
}

function pendingPlayerLabels(state, pending) {
  return (pending || []).map(pid => playerDisplayName(state, pid));
}

function ownedCitizenRoleSelectorCount(player, roleSelector) {
  const role = (roleSelector || '').toString().trim().toLowerCase();
  if (!role) return 0;
  const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
  const keyByRole = {
    holy_citizen: 'holy_count',
    shadow_citizen: 'shadow_count',
    soldier_citizen: 'soldier_count',
    worker_citizen: 'worker_count',
  };
  const key = keyByRole[role];
  if (!key) return 0;
  let n = 0;
  citizens.forEach(c => {
    if (Number(c?.[key] || 0) > 0) n += 1;
  });
  return n;
}

function domainPassiveOnBuildTurnCooldown(domain, turnNumber) {
  const acq = domain?.acquired_turn_number;
  if (acq === undefined || acq === null) return false;
  const t = Number(turnNumber);
  if (!Number.isFinite(t)) return false;
  return Number(acq) === t;
}

function parseRollSetOneDieEffects(player, turnNumber) {
  const out = [];
  const domains = Array.isArray(player?.owned_domains) ? player.owned_domains : [];
  domains.forEach(d => {
    if (domainPassiveOnBuildTurnCooldown(d, turnNumber)) return;
    const raw = (d?.passive_effect ?? '').toString().trim();
    if (!raw) return;
    const parts = raw.split(/\s+/);
    const head0 = (parts[0] || '').toLowerCase().replace(/:/g, '.');
    if (!parts.length || head0 !== 'roll.set_one_die') return;
    const kv = {};
    for (let i = 1; i < parts.length; i += 1) {
      const p = parts[i];
      const eq = p.indexOf('=');
      if (eq < 0) continue;
      const k = p.slice(0, eq).trim().toLowerCase();
      const v = p.slice(eq + 1).trim();
      kv[k] = v;
    }
    const target = Number(kv.target);
    const costSpec = (kv.cost || '').toString().trim().toLowerCase();
    if (!Number.isFinite(target) || target < 1 || target > 6 || !costSpec) return;
    out.push({ domainName: (d?.name || 'Domain').toString(), target, costSpec });
  });
  return out;
}

function rollEffectCostGold(player, costSpec) {
  const spec = (costSpec || '').toString().trim().toLowerCase();
  if (spec.startsWith('g:')) {
    const n = Number(spec.slice(2));
    if (!Number.isFinite(n) || n < 0) return null;
    return Math.floor(n);
  }
  if (spec.startsWith('g_per_owned_role:')) {
    const role = spec.slice('g_per_owned_role:'.length);
    return ownedCitizenRoleSelectorCount(player, role);
  }
  if (spec === 'g:per_owned_holy_citizen' || spec === 'per_owned_holy_citizen') {
    return ownedCitizenRoleSelectorCount(player, 'holy_citizen');
  }
  return null;
}

function listRollSetOneDieOptions(player, rolled1, rolled2, turnNumber) {
  const effects = parseRollSetOneDieEffects(player, turnNumber);
  const gold = Number(player?.gold_score || 0);
  const options = [];
  effects.forEach(e => {
    const costGold = rollEffectCostGold(player, e.costSpec);
    if (costGold === null || gold < costGold) return;
    if (Number(rolled1) !== Number(e.target)) {
      options.push({ die: 1, target: Number(e.target), costGold, domainName: e.domainName });
    }
    if (Number(rolled2) !== Number(e.target)) {
      options.push({ die: 2, target: Number(e.target), costGold, domainName: e.domainName });
    }
  });
  return options;
}

async function sendFinalizeRollChoice(d1, d2) {
  if (!GAME_ID || !PLAYER_ID || finalizeRollInFlight) return;
  finalizeRollInFlight = true;
  try {
    await postGameAction({
      player_id: PLAYER_ID,
      action_type: 'finalize_roll',
      die_one: clampDie(d1),
      die_two: clampDie(d2),
    });
  } finally {
    finalizeRollInFlight = false;
  }
}

/** Affordable roll.set_one_die choices for the player who must finalize (may be empty). */
function finalizeRollModifierOptions(state) {
  const req = state?.action_required || {};
  if ((req.action || '').toString() !== 'finalize_roll') return [];
  const reqId = (req.id || '').toString();
  const actingPlayer = playerById(state, reqId);
  if (!actingPlayer) return [];
  const rolled1 = clampDie(state?.rolled_die_one ?? state?.die_one ?? 1);
  const rolled2 = clampDie(state?.rolled_die_two ?? state?.die_two ?? 1);
  return listRollSetOneDieOptions(actingPlayer, rolled1, rolled2, state.turn_number);
}

/** No prompt when there are zero modifiers — finalize immediately (matches dev-client behavior). */
function maybeAutoFinalizeRoll(state) {
  if (!GAME_ID || !PLAYER_ID || finalizeRollInFlight) return;
  if ((state?.phase || '').toString() !== 'roll_pending') return;
  const req = state?.action_required || {};
  if ((req.action || '').toString() !== 'finalize_roll') return;
  if (!idsMatch(req.id, PLAYER_ID)) return;
  if (finalizeRollModifierOptions(state).length > 0) return;
  const rolled1 = clampDie(state?.rolled_die_one ?? state?.die_one ?? 1);
  const rolled2 = clampDie(state?.rolled_die_two ?? state?.die_two ?? 1);
  sendFinalizeRollChoice(rolled1, rolled2);
}

function labelForChoiceToken(tok) {
  const t = (tok || '').toString().trim().toLowerCase();
  if (t === 'g') return 'Gold';
  if (t === 's') return 'Strength';
  if (t === 'm') return 'Magic';
  if (t === 'v') return 'Victory';
  if (t.startsWith('citizens.')) {
    const name = t.split('.', 2)[1] || '';
    return name ? `${name} citizen` : 'Citizen';
  }
  return tok;
}

function parseChooseCommand(cmd) {
  const parts = (cmd || '').toString().trim().split(/\s+/);
  if (!parts.length || parts[0] !== 'choose') return [];
  const options = [];
  for (let i = 1; i + 1 < parts.length; i += 2) {
    const token = parts[i];
    const amount = parts[i + 1];
    const tl = (token || '').toString().trim().toLowerCase();
    if (!(tl === 'g' || tl === 's' || tl === 'm' || tl === 'v' || tl.startsWith('citizens.'))) continue;
    options.push({ token, amount });
    if (options.length >= 3) break;
  }
  return options;
}

function resourceSpecLabel(spec) {
  const raw = (spec || '').toString().trim().toLowerCase();
  const m = /^(g|s|m|v|vp)\s*:\s*(\d+)$/.exec(raw);
  if (!m) return raw || '';
  const n = Number(m[2]);
  const k = m[1] === 'vp' ? 'v' : m[1];
  const word = k === 'g' ? 'gold' : k === 's' ? 'strength' : k === 'm' ? 'magic' : 'VP';
  const unit = k === 'v' ? '' : ' ';
  return k === 'v' ? `${n} VP` : `${n}${unit}${word}`;
}

function domainEffectGainIsVp(kv) {
  const g = (kv?.gain ?? '').toString().trim().toLowerCase();
  return g.startsWith('v:') || g.startsWith('vp:');
}

function domainManipulateExplain(prc) {
  const item = prc?.item || {};
  const mode = (item.mode || '').toString().trim().toLowerCase();
  const kv = item.kv || {};
  if (mode === 'pay_to_player') {
    const pay = resourceSpecLabel(kv.pay);
    const gain = resourceSpecLabel(kv.gain);
    const gainLine = gain ? ` Gain ${gain} from the bank (not from that player).` : '';
    let decline = '';
    if (prc?.allow_skip && domainEffectGainIsVp(kv)) {
      decline = ' You may decline: no payment and no VP.';
    } else if (prc?.allow_skip) {
      decline = ' You may skip this optional effect.';
    }
    return `Pay ${pay || '(see rules)'} to the player you choose.${gainLine}${decline}`;
  }
  if (mode === 'take_from_player') {
    const take = resourceSpecLabel(kv.take);
    return `Take ${take || '(see rules)'} from the player you choose.`;
  }
  return 'Choose another player.';
}

function selfConvertExplain(kv) {
  const pay = resourceSpecLabel(kv?.pay);
  const gain = resourceSpecLabel(kv?.gain);
  return `Trade ${pay || '?'} from your supply for ${gain || '?'} (bank).`;
}

function dukePromptBlurb(card) {
  if (!card || typeof card !== 'object') return '';
  const rawText = (card.text ?? '').toString().trim();
  if (rawText) return rawText;
  const passive = (card.passive_effect ?? '').toString().trim();
  const activation = (card.activation_effect ?? '').toString().trim();
  const bits = [];
  if (passive) bits.push(`Passive: ${passive}`);
  if (activation) bits.push(`Activation: ${activation}`);
  return bits.join('\n');
}

/** Matches dev-client cardFullText duke multiplier display (resources use ×1/N). */
function dukeScalingLine(card) {
  if (!card || typeof card !== 'object') return '';
  if (card.duke_id == null) return '';
  const mults = [];
  const add = (label, val) => {
    if (val === undefined || val === null) return;
    const n = Number(val);
    if (!Number.isFinite(n) || n === 0) return;
    mults.push(`${label}×${n}`);
  };
  const addResource = (label, val) => {
    if (val === undefined || val === null) return;
    const n = Number(val);
    if (!Number.isFinite(n) || n === 0) return;
    mults.push(`${label}×1/${n}`);
  };
  addResource('Gold', card.gold_multiplier);
  addResource('Strength', card.strength_multiplier);
  addResource('Magic', card.magic_multiplier);
  add('Shadow', card.shadow_multiplier);
  add('Holy', card.holy_multiplier);
  add('Soldier', card.soldier_multiplier);
  add('Worker', card.worker_multiplier);
  add('Monster', card.monster_multiplier);
  add('Citizen', card.citizen_multiplier);
  add('Domain', card.domain_multiplier);
  add('Boss', card.boss_multiplier);
  add('Minion', card.minion_multiplier);
  add('Beast', card.beast_multiplier);
  add('Titan', card.titan_multiplier);
  return mults.join(' · ');
}

function renderConcurrentChooseDuke(state, concurrent) {
  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
  const isPending = !!(PLAYER_ID && pending.some(pid => idsMatch(pid, PLAYER_ID)));
  const totalParticipants = pending.length + completed.length;

  const players = state?.player_list || [];
  const you = players.find(p => idsMatch(p.player_id, PLAYER_ID)) || null;
  const waitingLabels = pendingPlayerLabels(state, pending);

  const body = mk('prompt-modal-body');

  const status = mk('prompt-modal-note');
  status.textContent =
    `Starting setup: ${completed.length}/${totalParticipants} duke choice(s) submitted.` +
    (pending.length ? ` Waiting on: ${waitingLabels.join(', ')}.` : '');
  body.appendChild(status);

  if (!isPending) {
    const youDone = !!(PLAYER_ID && completed.some(pid => idsMatch(pid, PLAYER_ID)));
    const line = mk('prompt-modal-note');
    line.textContent = youDone
      ? 'You have already chosen your duke. Waiting on the other player(s).'
      : 'Starting setup is in progress.';
    body.appendChild(line);
    openPromptOverlayShell({
      title: 'Choose your Duke',
      subtitle: null,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const dukes = Array.isArray(you?.owned_dukes) ? you.owned_dukes : [];
  if (!dukes.length) {
    body.appendChild(document.createTextNode('No dukes found to choose from.'));
    openPromptOverlayShell({
      title: 'Choose your Duke',
      dismissible: false,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const list = mk('prompt-choice-list');
  dukes.forEach(d => {
    const id = d?.duke_id;
    const name = d?.name || `Duke #${id}`;
    const cardEl = mk('prompt-choice-card');

    const inner = mk('prompt-choice-card-inner');
    const url = cardImageUrl(d);
    if (url) {
      const wrap = mk('prompt-choice-card-img-wrap');
      const img = document.createElement('img');
      img.className = 'prompt-choice-card-img';
      img.alt = '';
      img.loading = 'eager';
      img.src = url;
      img.onerror = () => wrap.remove();
      wrap.appendChild(img);
      inner.appendChild(wrap);
    }

    const main = mk('prompt-choice-card-main');
    const nm = mk('prompt-choice-card-title');
    nm.textContent = `${name} (#${id})`;
    main.appendChild(nm);
    const scalingLine = dukeScalingLine(d);
    if (scalingLine) {
      const sc = mk('prompt-choice-card-scaling');
      sc.textContent = scalingLine;
      main.appendChild(sc);
    }
    const blurb = dukePromptBlurb(d);
    if (blurb) {
      const tx = mk('prompt-choice-card-text');
      tx.textContent = blurb;
      main.appendChild(tx);
    }
    const row = mk('prompt-choice-card-actions');
    row.appendChild(promptButton('Keep this duke', () => {
      postGameAction({
        player_id: PLAYER_ID,
        action_type: 'submit_concurrent_action',
        kind: 'choose_duke',
        response: String(id),
      });
    }));
    main.appendChild(row);
    inner.appendChild(main);
    cardEl.appendChild(inner);
    list.appendChild(cardEl);
  });
  body.appendChild(list);

  openPromptOverlayShell({
    title: 'Choose 1 Duke to keep',
    subtitle: null,
    dismissible: false,
    bodyEl: body,
    footerEl: null,
  });
}

function renderConcurrentFlipCitizen(state, concurrent) {
  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
  const isPending = !!(PLAYER_ID && pending.some(pid => idsMatch(pid, PLAYER_ID)));
  const totalParticipants = pending.length + completed.length;
  const data = concurrent.data || {};
  const buyerId = (data.buyer_id || '').toString();

  const buyer = playerById(state, buyerId);
  const buyerTag = buyer?.name || buyerId || '';
  const waitingLabels = pendingPlayerLabels(state, pending);

  const body = mk('prompt-modal-body');

  const status = mk('prompt-modal-note');
  status.textContent =
    `Cursed Cavern — flip one citizen face-down: ${completed.length}/${totalParticipants} player choice(s) submitted.` +
    (pending.length ? ` Waiting on: ${waitingLabels.join(', ')}.` : '') +
    (buyerTag ? ` Triggered by ${buyerTag}.` : '');
  body.appendChild(status);

  if (!isPending) {
    const youDone = !!(PLAYER_ID && completed.some(pid => idsMatch(pid, PLAYER_ID)));
    const line = mk('prompt-modal-note');
    line.textContent = youDone
      ? 'You already chose a citizen to flip. Waiting on other players.'
      : 'You have no pending flip choice (no eligible citizens, or not in this prompt).';
    body.appendChild(line);
    openPromptOverlayShell({
      title: 'Flip a citizen',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const you = playerById(state, PLAYER_ID);
  const citizens = Array.isArray(you?.owned_citizens) ? you.owned_citizens : [];
  const choices = [];
  citizens.forEach((c, idx) => {
    if (!c || c.is_flipped) return;
    choices.push({ idx, card: c, nm: (c.name || `Citizen #${idx}`).toString() });
  });

  if (!choices.length) {
    body.appendChild(document.createTextNode('No face-up citizens on your tableau — contact host if this seems wrong.'));
    openPromptOverlayShell({
      title: 'Flip a citizen',
      dismissible: false,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const list = mk('prompt-choice-list');
  choices.forEach(({ idx, card, nm }) => {
    const cardEl = mk('prompt-choice-card');
    const titleEl = mk('prompt-choice-card-title');
    titleEl.textContent = `${nm} (slot #${idx})`;
    cardEl.appendChild(titleEl);
    const metaParts = [];
    if (card.roll_match1 !== undefined || card.roll_match2 !== undefined) {
      metaParts.push(`Roll ${card.roll_match1 ?? ''}/${card.roll_match2 ?? ''}`);
    }
    if (card.gold_cost !== undefined) metaParts.push(`${card.gold_cost}g`);
    if (metaParts.length) {
      const meta = mk('prompt-choice-card-meta');
      meta.textContent = metaParts.join(' · ');
      cardEl.appendChild(meta);
    }
    const row = mk('prompt-choice-card-actions');
    row.appendChild(promptButton('Flip this citizen face-down', () => {
      postGameAction({
        player_id: PLAYER_ID,
        action_type: 'submit_concurrent_action',
        kind: 'flip_one_citizen',
        response: String(idx),
      });
    }));
    cardEl.appendChild(row);
    list.appendChild(cardEl);
  });
  body.appendChild(list);

  openPromptOverlayShell({
    title: 'Choose 1 citizen to flip face-down',
    dismissible: false,
    bodyEl: body,
    footerEl: null,
  });
}

function renderConcurrentPanel(state, concurrent) {
  const kind = concurrent?.kind || '';
  if (kind === 'choose_duke') return renderConcurrentChooseDuke(state, concurrent);
  if (kind === 'flip_one_citizen') return renderConcurrentFlipCitizen(state, concurrent);

  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const body = mk('prompt-modal-body');
  const note = mk('prompt-modal-note');
  const who = pending.length ? ` Waiting on: ${pendingPlayerLabels(state, pending).join(', ')}.` : '';
  note.textContent =
    `Waiting on concurrent action "${kind}" (${pending.length} player(s) still need to respond).${who}`;
  body.appendChild(note);
  openPromptOverlayShell({
    title: 'Waiting',
    dismissible: true,
    bodyEl: body,
    footerEl: null,
  });
}

function renderFinalizeRollPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const rolled1 = clampDie(state?.rolled_die_one ?? state?.die_one ?? 1);
  const rolled2 = clampDie(state?.rolled_die_two ?? state?.die_two ?? 1);

  const body = mk('prompt-modal-body');

  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} to finalize the roll.`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: 'Finalize roll',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const you = playerById(state, PLAYER_ID);
  const options = listRollSetOneDieOptions(you, rolled1, rolled2, state.turn_number);

  const diceLine = mk('prompt-modal-dice-line');
  diceLine.appendChild(makeDie(rolled1));
  diceLine.appendChild(document.createTextNode(' + '));
  diceLine.appendChild(makeDie(rolled2));
  diceLine.appendChild(document.createTextNode(` = ${rolled1 + rolled2}`));
  body.appendChild(diceLine);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  foot.appendChild(promptButton(`Keep ${rolled1} + ${rolled2}`, () => sendFinalizeRollChoice(rolled1, rolled2)));
  options.forEach(o => {
    const fromVal = o.die === 1 ? rolled1 : rolled2;
    const d1 = o.die === 1 ? o.target : rolled1;
    const d2 = o.die === 2 ? o.target : rolled2;
    foot.appendChild(promptButton(
      `Die ${o.die}: ${fromVal} → ${o.target} (${o.costGold}g · ${o.domainName})`,
      () => sendFinalizeRollChoice(d1, d2),
    ));
  });

  const hint = mk('prompt-modal-note');
  hint.textContent = 'Choose a roll modifier or keep the rolled dice.';
  body.appendChild(hint);

  openPromptOverlayShell({
    title: 'Finalize roll',
    subtitle: null,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderDomainSelfConvertPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const dn = (prc?.domain_name || 'Domain').toString();
  const kv = prc?.kv || {};
  const explain = selfConvertExplain(kv);

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${dn} optional trade.`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: `${dn}: trade`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = explain;
  body.appendChild(sub);

  const foot = promptActionsRow([
    promptButton('Confirm trade', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'confirm_self_convert',
    })),
    promptButton('Decline', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    }), true),
  ]);

  openPromptOverlayShell({
    title: `${dn}: optional trade`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function harvestExchangeExplain(command) {
  const parts = (command || '').trim().split(/\s+/);
  if (parts.length < 5 || parts[0].toLowerCase() !== 'exchange') return (command || '').trim() || 'Optional harvest exchange.';
  const pay = parts[1].toLowerCase();
  const payN = parts[2];
  const gain = parts[3].toLowerCase();
  const gainN = parts[4];
  const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
  return `Pay ${payN} ${labels[pay] || pay}, gain ${gainN} ${labels[gain] || gain}.`;
}

function renderHarvestOptionalExchangePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const cmd = (prc?.command || '').toString();
  const explain = harvestExchangeExplain(cmd);

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — optional citizen harvest exchange.`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: 'Harvest exchange',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = explain;
  body.appendChild(sub);

  const foot = promptActionsRow([
    promptButton('Take exchange', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'confirm_harvest_exchange',
    })),
    promptButton('Skip (keep resources)', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip_harvest_exchange',
    }), true),
  ]);

  openPromptOverlayShell({
    title: 'Harvest: optional exchange',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderDomainChoosePlayer(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];
  const dn = (prc?.item?.domain_name || 'Domain').toString();
  const explain = prc?.kind === 'domain_manipulate_player'
    ? domainManipulateExplain(prc)
    : 'Choose another player.';

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} to choose a player for ${dn}.`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: `${dn}`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = explain;
  body.appendChild(sub);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || o?.player_id || '?').toString();
    foot.appendChild(promptButton(nm, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `choose_player ${idx + 1}`,
    })));
  });

  const kv = prc?.item?.kv || {};
  const skipLabel = prc?.allow_skip && domainEffectGainIsVp(kv)
    ? 'Decline (no pay, no VP)'
    : 'Skip (optional)';
  if (prc?.allow_skip) {
    foot.appendChild(promptButton(skipLabel, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    }), true));
  }

  openPromptOverlayShell({
    title: `${dn}: choose another player`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderDomainChooseMonster(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];
  const dn = (prc?.domain_name || 'Domain').toString();
  const delta = Number(prc?.delta) || 0;

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${dn} (monster +${delta} strength cost).`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: dn,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || '?').toString();
    foot.appendChild(promptButton(nm, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `choose_monster ${idx + 1}`,
    })));
  });

  openPromptOverlayShell({
    title: `${dn}: strengthen a center monster`,
    subtitle: `Add +${delta} to strength cost`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function chooseOptionButtonLabel(opt, idx) {
  const token = (opt?.token || '').toString();
  const label = labelForChoiceToken(token);
  const amt = Number(opt.amount);
  const prettyAmt = Number.isFinite(amt) ? amt : opt.amount;
  const tl = token.trim().toLowerCase();
  if (tl === 'count_area') {
    const area = (opt?.area ?? '').toString();
    const res = (opt?.resource ?? '').toString().toLowerCase();
    const mult = Number(opt?.mult);
    const rLabel = labelForChoiceToken(res);
    const mText = Number.isFinite(mult) ? mult : opt?.mult;
    return `+(${mText} × ${area}) ${rLabel}`;
  }
  if (tl.startsWith('citizens.')) {
    const name = (opt?.name ?? '').toString().trim();
    const extras = Array.isArray(opt?.extras) ? opt.extras : [];
    const extraText = extras.map(e => {
      const et = (e?.token ?? '').toString().toLowerCase();
      const ea = Number(e?.amount);
      const el = labelForChoiceToken(et);
      const an = Number.isFinite(ea) ? ea : e?.amount;
      return `+${an} ${el}`;
    }).join(' + ');
    const extraSuffix = extraText ? ` + ${extraText}` : '';
    const who = name ? `${name} citizen` : label;
    return `Gain ${prettyAmt} ${who}${extraSuffix}`;
  }
  return `+${prettyAmt} ${label}`;
}

function renderChoosePrompt(state, chooseCmd) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const pendingChoice = state?.pending_required_choice || null;

  let options = parseChooseCommand(chooseCmd);
  if (
    pendingChoice &&
    pendingChoice.kind === 'special_payout_choose' &&
    Array.isArray(pendingChoice.options) &&
    pendingChoice.options.length
  ) {
    options = pendingChoice.options;
  }

  const body = mk('prompt-modal-body');
  if (!options.length || !isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = !options.length
      ? `Waiting on required choice: ${chooseCmd}`
      : `Waiting on ${playerDisplayName(state, reqId)} — ${chooseCmd}`;
    body.appendChild(note);
    openPromptOverlayShell({
      title: 'Choose one',
      dismissible: !isYou || !options.length,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  options.forEach((opt, idx) => {
    foot.appendChild(promptButton(chooseOptionButtonLabel(opt, idx), () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `choose ${idx + 1}`,
    })));
  });

  openPromptOverlayShell({
    title: 'Choose one',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderManualHarvestPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const slots = Array.isArray(state?.harvest_prompt_slots) ? state.harvest_prompt_slots : [];
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));

  const chip = harvestTurnChip(state, reqId);

  const body = mk('prompt-modal-body');
  const headRow = mk('prompt-modal-inline');
  const ht = mk('prompt-modal-note');
  ht.textContent = isYou ? 'Harvest — choose order' : `Harvest in progress for ${playerDisplayName(state, reqId)}`;
  headRow.appendChild(ht);
  if (chip) headRow.appendChild(chip);
  body.appendChild(headRow);

  if (!isYou || !slots.length) {
    const note = mk('prompt-modal-note');
    note.textContent = !isYou
      ? `${slots.length} card(s) remaining for this harvest.`
      : !slots.length
        ? 'No harvest slots (try reconnecting).'
        : '';
    if (note.textContent) body.appendChild(note);
    openPromptOverlayShell({
      title: 'Harvest',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  if (slots.some(s => s.kind === 'citizen' && s.is_thief)) {
    const thief = mk('prompt-modal-note');
    thief.textContent = 'If you have the Thief, harvest that citizen before other citizens.';
    body.appendChild(thief);
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  slots.forEach(s => {
    const ai = Number(s.activation_index);
    const dup = Number.isFinite(ai) && ai > 0 ? ` · #${ai + 1}` : '';
    const ci = Number(s.card_idx);
    const copy = Number.isFinite(ci) ? ` · copy ${ci + 1}` : '';
    const label = `${s.name || ''} (${s.kind} #${s.card_id}${copy}${dup})`;
    const sk = (s.slot_key || '').toString();
    foot.appendChild(promptButton(`Harvest: ${label}`, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'harvest_card',
      harvest_slot_key: sk,
    })));
  });

  openPromptOverlayShell({
    title: 'Harvest',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderBonusResourcePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));

  const chip = harvestTurnChip(state, reqId);

  const body = mk('prompt-modal-body');
  const headRow = mk('prompt-modal-inline');
  const ht = mk('prompt-modal-note');
  ht.textContent = isYou ? 'Harvest bonus — choose +1 resource' : `Harvest bonus pending for ${playerDisplayName(state, reqId)}`;
  headRow.appendChild(ht);
  if (chip) headRow.appendChild(chip);
  body.appendChild(headRow);

  if (!isYou) {
    openPromptOverlayShell({
      title: 'Harvest bonus',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const foot = promptActionsRow([
    promptButton('+1 Gold', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'gold',
    })),
    promptButton('+1 Strength', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'strength',
    })),
    promptButton('+1 Magic', () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'magic',
    })),
  ]);

  openPromptOverlayShell({
    title: 'Harvest bonus',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderUnknownRequired(state, reqAction, reqId) {
  const body = mk('prompt-modal-body');
  const note = mk('prompt-modal-note');
  note.textContent = `Waiting on ${playerDisplayName(state, reqId)}: ${reqAction}`;
  body.appendChild(note);
  openPromptOverlayShell({
    title: 'Waiting',
    dismissible: true,
    bodyEl: body,
    footerEl: null,
  });
}

function renderPromptModal(state) {
  if (!GAME_ID || !PLAYER_ID) return;

  const concurrent = state?.concurrent_action || null;
  const concurrentPending = concurrent && Array.isArray(concurrent.pending) ? concurrent.pending : [];
  if (concurrentPending.length > 0) {
    renderConcurrentPanel(state, concurrent);
    return;
  }

  const req = state?.action_required || {};
  const reqId = req?.id || '';
  const reqAction = (req?.action || '').toString();

  if (!reqId || reqId === state?.game_id) {
    removePromptOverlay();
    return;
  }

  if (reqAction === 'standard_action') {
    removePromptOverlay();
    return;
  }

  if (reqAction === 'finalize_roll') {
    if (finalizeRollModifierOptions(state).length === 0) {
      removePromptOverlay();
      return;
    }
    renderFinalizeRollPrompt(state);
    return;
  }

  if (reqAction === 'domain_self_convert') {
    renderDomainSelfConvertPrompt(state);
    return;
  }

  if (reqAction === 'choose_player') {
    renderDomainChoosePlayer(state);
    return;
  }

  if (reqAction === 'choose_monster_strength') {
    renderDomainChooseMonster(state);
    return;
  }

  if (typeof reqAction === 'string' && reqAction.trim().startsWith('choose ')) {
    renderChoosePrompt(state, reqAction);
    return;
  }

  if (reqAction === 'harvest_optional_exchange') {
    renderHarvestOptionalExchangePrompt(state);
    return;
  }

  if (reqAction === 'manual_harvest') {
    renderManualHarvestPrompt(state);
    return;
  }

  if (reqAction !== 'bonus_resource_choice') {
    renderUnknownRequired(state, reqAction, reqId);
    return;
  }

  renderBonusResourcePrompt(state);
}

// ── Lobby modal when visiting without game_id / player_id ────────────────
function initLobbyModal() {
  const overlay = document.getElementById('lobby-overlay');
  const connEl = document.getElementById('conn-status');
  const errEl = document.getElementById('lobby-error');
  const stepJoin = document.getElementById('lobby-step-join');
  const stepWait = document.getElementById('lobby-step-wait');
  const nameInput = document.getElementById('lobby-display-name');
  const joinBtn = document.getElementById('lobby-join-btn');
  const readyBtn = document.getElementById('lobby-ready-btn');
  const leaveBtn = document.getElementById('lobby-leave-btn');
  const playerList = document.getElementById('lobby-player-list');
  const metaEl = document.getElementById('lobby-meta');

  if (!overlay || !stepJoin || !stepWait || !joinBtn || !readyBtn || !leaveBtn || !playerList || !nameInput) {
    if (connEl) connEl.textContent = 'Missing game_id or player_id in URL';
    return;
  }

  const savedDisplay = vckStoredDisplayName();
  if (savedDisplay && !String(nameInput.value || '').trim()) {
    nameInput.value = savedDisplay;
  }

  let lobbyPlayerId = '';
  let lobbyWs = null;
  let lobbyWsReconnectTimer = null;
  let lastLobbySnapshot = null;

  function shutdownLobbySocket() {
    if (lobbyWs) {
      lobbyWs.onopen = null;
      lobbyWs.onmessage = null;
      lobbyWs.onclose = null;
      lobbyWs.onerror = null;
      try {
        lobbyWs.close();
      } catch (_) {
        /* ignore */
      }
      lobbyWs = null;
    }
  }

  function tearDownLobbyConnection() {
    if (lobbyWsReconnectTimer) {
      clearTimeout(lobbyWsReconnectTimer);
      lobbyWsReconnectTimer = null;
    }
    shutdownLobbySocket();
  }

  function setLobbyLiveStatus(mode) {
    const liveEl = document.getElementById('lobby-live');
    if (!liveEl) return;
    liveEl.classList.remove('lobby-live--ok', 'lobby-live--warn', 'lobby-live--off');
    if (mode === 'ok') {
      liveEl.textContent = 'Live';
      liveEl.classList.add('lobby-live--ok');
    } else if (mode === 'warn') {
      liveEl.textContent = 'Connecting…';
      liveEl.classList.add('lobby-live--warn');
    } else {
      liveEl.textContent = 'Offline';
      liveEl.classList.add('lobby-live--off');
    }
  }

  function lobbyWsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws/lobby`;
  }

  function sendLobbyIdentify() {
    if (!lobbyWs || lobbyWs.readyState !== WebSocket.OPEN) return;
    const pid = lobbyPlayerId || vckStoredPlayerId() || '';
    lobbyWs.send(JSON.stringify({ type: 'identify', player_id: pid || null }));
  }

  function connectLobbyWs() {
    if (lobbyWsReconnectTimer) {
      clearTimeout(lobbyWsReconnectTimer);
      lobbyWsReconnectTimer = null;
    }
    shutdownLobbySocket();
    setLobbyLiveStatus('warn');
    lobbyWs = new WebSocket(lobbyWsUrl());
    lobbyWs.onopen = () => {
      setLobbyLiveStatus('ok');
      sendLobbyIdentify();
    };
    lobbyWs.onmessage = evt => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch (_) {
        return;
      }
      if (msg.type === 'lobby_status') applyLobbyStatusPayload(msg);
      else if (msg.type === 'game_started') handleGameStarted(msg);
    };
    lobbyWs.onclose = () => {
      lobbyWs = null;
      setLobbyLiveStatus('warn');
      lobbyWsReconnectTimer = setTimeout(connectLobbyWs, 2200);
    };
    lobbyWs.onerror = () => {
      try {
        lobbyWs.close();
      } catch (_) {
        /* ignore */
      }
    };
  }

  function openOverlay() {
    overlay.classList.add('lobby-overlay--open');
    overlay.setAttribute('aria-hidden', 'false');
    if (connEl) connEl.textContent = '● lobby';
  }

  function showLobbyError(msg) {
    if (!errEl) return;
    if (!msg) {
      errEl.textContent = '';
      errEl.classList.add('lobby-hidden');
      return;
    }
    errEl.textContent = msg;
    errEl.classList.remove('lobby-hidden');
  }

  function enterGameFromLobby(gameId, playerId) {
    tearDownLobbyConnection();
    vckClientPatch({ player_id: playerId, game_id: gameId });
    const q = new URLSearchParams({ game_id: gameId, player_id: playerId });
    location.replace(`${location.pathname}?${q}`);
  }

  function handleGameStarted(msg) {
    const pid = lobbyPlayerId || vckStoredPlayerId();
    const gid = msg.game_id;
    const ids = msg.player_ids || [];
    if (!pid || !gid) return;
    if (!ids.some(x => idsMatch(x, pid))) return;
    enterGameFromLobby(gid, pid);
  }

  function applyLobbyStatusPayload(data) {
    lastLobbySnapshot = data;
    if (data.in_game && data.game_id) {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (pid) enterGameFromLobby(data.game_id, pid);
      return;
    }
    const selfId = lobbyPlayerId || vckStoredPlayerId() || '';
    const inList = selfId && (data.lobby || []).some(x => idsMatch(x.player_id, selfId));
    if (selfId && stepWait && !stepWait.classList.contains('lobby-hidden') && !inList) {
      showLobbyError('You are no longer in this lobby. Join again.');
      lobbyPlayerId = '';
      vckClientPatch({ player_id: null });
      tearDownLobbyConnection();
      connectLobbyWs();
      stepWait.classList.add('lobby-hidden');
      stepJoin.classList.remove('lobby-hidden');
      return;
    }
    if (metaEl) {
      metaEl.textContent =
        typeof data.game_count === 'number'
          ? `${data.game_count} active game${data.game_count === 1 ? '' : 's'} on this server`
          : '';
    }
    renderLobbyRows(data.lobby || [], selfId);
    const self = (data.lobby || []).find(x => idsMatch(x.player_id, selfId));
    if (self) {
      const ready = !!self.is_ready;
      readyBtn.textContent = ready ? 'Cancel ready' : 'Ready';
      readyBtn.classList.toggle('is-cancel', ready);
    }
  }

  async function fetchLobbyPayload() {
    const pid = lobbyPlayerId || vckStoredPlayerId() || '';
    const url = pid
      ? `/api/lobby/status?player_id=${encodeURIComponent(pid)}`
      : '/api/lobby/status';
    const res = await fetch(url);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail != null ? String(data.detail) : res.statusText;
      throw new Error(detail || 'Lobby request failed');
    }
    return data;
  }

  function renderLobbyRows(lobby, selfId) {
    playerList.innerHTML = '';
    lobby.forEach(p => {
      const li = document.createElement('li');
      li.className = 'lobby-player-row' + (idsMatch(p.player_id, selfId) ? ' is-self' : '');
      const nameSpan = document.createElement('span');
      nameSpan.className = 'lobby-p-name';
      nameSpan.textContent = p.name || 'Player';
      const stSpan = document.createElement('span');
      stSpan.className = 'lobby-p-status' + (p.is_ready ? ' is-ready' : '');
      stSpan.textContent = p.is_ready ? 'Ready' : 'Waiting';
      li.appendChild(nameSpan);
      li.appendChild(stSpan);
      playerList.appendChild(li);
    });
  }

  function showWaitUi() {
    stepJoin.classList.add('lobby-hidden');
    stepWait.classList.remove('lobby-hidden');
    openOverlay();
    sendLobbyIdentify();
  }

  async function tryResumeStoredPlayer() {
    const saved = vckStoredPlayerId();
    if (!saved) return;
    try {
      const res = await fetch(`/api/lobby/status?player_id=${encodeURIComponent(saved)}`);
      const data = await res.json();
      if (!res.ok) return;
      if (data.in_game && data.game_id) {
        enterGameFromLobby(data.game_id, saved);
        return;
      }
      const stillThere = (data.lobby || []).some(p => idsMatch(p.player_id, saved));
      if (stillThere) {
        lobbyPlayerId = saved;
        showWaitUi();
      }
    } catch (_) {
      /* ignore */
    }
  }

  joinBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    if (!name) {
      showLobbyError('Enter a display name.');
      return;
    }
    showLobbyError('');
    joinBtn.disabled = true;
    try {
      const res = await fetch('/api/lobby/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Join failed');
      }
      lobbyPlayerId = data.player_id || '';
      vckClientPatch({ player_id: lobbyPlayerId, display_name: name });
      showWaitUi();
    } catch (e) {
      showLobbyError(e.message || 'Could not join lobby.');
    } finally {
      joinBtn.disabled = false;
    }
  });

  nameInput.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') joinBtn.click();
  });

  readyBtn.addEventListener('click', async () => {
    const pid = lobbyPlayerId || vckStoredPlayerId();
    if (!pid) return;
    readyBtn.disabled = true;
    try {
      let st = lastLobbySnapshot;
      if (!st) {
        try {
          st = await fetchLobbyPayload();
        } catch (e) {
          showLobbyError(e.message || 'Could not reach lobby.');
          return;
        }
      }
      const self = (st.lobby || []).find(x => idsMatch(x.player_id, pid));
      const endpoint = self && self.is_ready ? '/api/lobby/unready' : '/api/lobby/ready';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: pid, debug_starting_resources: false }),
      });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(out.detail != null ? String(out.detail) : res.statusText || 'Ready failed');
      }
      if (out.game_id) {
        enterGameFromLobby(out.game_id, pid);
        return;
      }
    } catch (e) {
      showLobbyError(e.message || 'Ready toggle failed.');
    } finally {
      readyBtn.disabled = false;
    }
  });

  leaveBtn.addEventListener('click', async () => {
    const pid = lobbyPlayerId || vckStoredPlayerId();
    if (!pid) return;
    leaveBtn.disabled = true;
    try {
      await fetch(`/api/lobby/leave?player_id=${encodeURIComponent(pid)}`, { method: 'POST' });
    } catch (_) {
      /* still reset UI */
    }
    lobbyPlayerId = '';
    vckClientPatch({ player_id: null });
    showLobbyError('');
    sendLobbyIdentify();
    stepWait.classList.add('lobby-hidden');
    stepJoin.classList.remove('lobby-hidden');
    leaveBtn.disabled = false;
  });

  openOverlay();
  connectLobbyWs();
  tryResumeStoredPlayer();
}

// ── Boot ──────────────────────────────────────────────────────────────────
if (!GAME_ID || !PLAYER_ID) {
  initLobbyModal();
} else {
  connect();
  initOpponentTableauWheelScroll();
  initPlayerDetailModal();
  let prevNarrowForLayout = isViewportNarrow();
  const onViewportLayoutChange = () => {
    const narrow = isViewportNarrow();
    if (narrow !== prevNarrowForLayout && latestGameState) {
      render(latestGameState);
    }
    prevNarrowForLayout = narrow;
    const zone = document.getElementById('zone-center');
    if (zone) syncBoardTabState(zone);
  };
  window.addEventListener('resize', onViewportLayoutChange);
  const mmNarrow = window.matchMedia('(max-width: 800px)');
  if (mmNarrow.addEventListener) mmNarrow.addEventListener('change', onViewportLayoutChange);
  else if (mmNarrow.addListener) mmNarrow.addListener(onViewportLayoutChange);
}
