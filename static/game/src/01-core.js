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

// ── State delivery safety net ─────────────────────────────────────────────
// The server pushes state via WebSocket on every action. In practice WS
// messages get dropped (silent disconnects, mobile/tab suspend, proxy idle
// timeouts), which leaves the UI stuck on a stale view. The next prompt
// never appears for the player and they time out. To make this self-heal we:
//   1. Track the highest tick_id we've rendered so out-of-order pushes
//      (e.g. a late WS message arriving after a fresher HTTP response)
//      can be ignored.
//   2. Poll state every PASSIVE_GAME_POLL_MS, skipping when the user is
//      mid-edit (so we don't blow away typed slay-payment values) or when
//      concurrent polling is already running.
//   3. Refetch state whenever the tab becomes visible again.
const PASSIVE_GAME_POLL_MS = 5000;
let lastRenderedGameId = '';
let lastRenderedTickId = -1;
let passiveStatePollTimer = null;

/** Narrow layout: max-width breakpoint matches CSS tabbed / carousel mode */
function isViewportNarrow() {
  return true;
}

/** Which player's tableau slide is focused in the narrow carousel (persisted across re-renders) */
let tableauCarouselActiveId = null;

/** Center board tab carousel: last focused section key (BOARD_SECTIONS[].key) across re-renders */
let centerBoardActiveTabKey = null;

/** Narrow carousel: horizontal scrollLeft of each player's `.tableau-cards` strip */
const tableauStripScrollByPlayerId = {};

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

function escapeHtml(s) {
  return (s ?? '')
    .toString()
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

