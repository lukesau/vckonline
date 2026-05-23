// ── Lobby background ───────────────────────────────────────────────────────
// `'collage'` = static overlapping card grid (original). `'bounce'` = one card, constant speed, specular wall bounces, new random card each bounce.
const LOBBY_BACKGROUND_MODE = 'collage';

async function paintLobbyBackgroundCollage(canvas) {
  const t0 = performance.now();
  const overlay = canvas.closest('.lobby-overlay');
  if (!overlay) return;
  canvas.classList.remove('lobby-bg-canvas--fill');
  const vw = Math.max(window.innerWidth || 0, 1024);
  const vh = Math.max(window.innerHeight || 0, 640);
  // One large bitmap, centered; window resizes clip it (no stretch).
  const bw = Math.min(4096, Math.max(2880, Math.ceil(vw * 1.42)));
  const bh = Math.min(2560, Math.max(1800, Math.ceil(vh * 1.42)));

  let urls = [];
  try {
    const res = await fetch('/api/lobby/background-card-urls');
    if (!res.ok) return;
    const data = await res.json();
    urls = Array.isArray(data.urls) ? data.urls : [];
  } catch (_) {
    return;
  }
  if (!urls.length) return;

  const tAfterList = performance.now();

  // Staggered grid; wider spacing + less overlap than before (fewer tiles, less duplicate clutter).
  const cellW = 218;
  const cellH = 302;
  const overlap = 1.2;
  const tileCols = Math.ceil(bw / cellW) + 2;
  const tileRows = Math.ceil(bh / cellH) + 2;
  const tileCount = tileCols * tileRows;
  const srcDeck = [];
  while (srcDeck.length < tileCount) {
    const pass = urls.slice();
    for (let i = pass.length - 1; i > 0; i--) {
      const j = (Math.random() * (i + 1)) | 0;
      const t = pass[i];
      pass[i] = pass[j];
      pass[j] = t;
    }
    srcDeck.push(...pass);
  }
  const positions = [];
  for (let row = 0; row < tileRows; row++) {
    const brick = (row % 2) * (cellW * 0.5);
    for (let col = 0; col < tileCols; col++) {
      const cx =
        brick +
        (col + 0.5) * cellW +
        (Math.random() - 0.5) * cellW * 0.2;
      const cy = (row + 0.5) * cellH + (Math.random() - 0.5) * cellH * 0.18;
      const scale = 0.96 + Math.random() * 0.12;
      positions.push({
        cx,
        cy,
        pw: cellW * scale * overlap,
        ph: cellH * scale * overlap,
        rot: (Math.random() - 0.5) * 0.42,
        src: srcDeck[positions.length],
      });
    }
  }

  const imgPromiseBySrc = new Map();
  function loadOneCached(src) {
    let p = imgPromiseBySrc.get(src);
    if (!p) {
      p = new Promise(resolve => {
        const img = new Image();
        img.onload = () => resolve({ ok: true, img });
        img.onerror = () => resolve({ ok: false });
        img.src = src;
      });
      imgPromiseBySrc.set(src, p);
    }
    return p;
  }

  const loads = positions.map(p => loadOneCached(p.src).then(r => ({ ...p, ...r })));
  const results = await Promise.all(loads);
  const tAfterLoad = performance.now();

  for (let i = results.length - 1; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    const t = results[i];
    results[i] = results[j];
    results[j] = t;
  }

  canvas.width = bw;
  canvas.height = bh;
  canvas.style.width = `${bw}px`;
  canvas.style.height = `${bh}px`;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  ctx.fillStyle = '#0a1610';
  ctx.fillRect(0, 0, bw, bh);

  let drawn = 0;
  for (const r of results) {
    if (!r.ok || !r.img) continue;
    drawn += 1;
    const img = r.img;
    const ar = img.naturalWidth / img.naturalHeight;
    let dw = r.pw;
    let dh = dw / ar;
    if (dh > r.ph) {
      dh = r.ph;
      dw = dh * ar;
    }
    ctx.save();
    ctx.translate(r.cx, r.cy);
    ctx.rotate(r.rot);
    ctx.drawImage(img, -dw * 0.5, -dh * 0.5, dw, dh);
    ctx.restore();
  }

  ctx.fillStyle = 'rgba(4, 10, 7, 0.4)';
  ctx.fillRect(0, 0, bw, bh);

  const tDone = performance.now();
  console.info(
    '[lobby-bg] list %sms  load+decode %sms  draw %sms  total %sms (%d tiles, %d drawn)',
    (tAfterList - t0).toFixed(0),
    (tAfterLoad - tAfterList).toFixed(0),
    (tDone - tAfterLoad).toFixed(0),
    (tDone - t0).toFixed(0),
    positions.length,
    drawn
  );
}

function startLobbyBackgroundBounce(canvas) {
  const overlay = canvas.closest('.lobby-overlay');
  if (!overlay) return Promise.resolve();

  const existingStop = canvas._lobbyBounceStop;
  if (typeof existingStop === 'function') existingStop();

  const DARKEN = 'rgba(4, 10, 7, 0.4)';
  const SPEED_PX = 220;
  const POOL_TARGET = 22;
  const CARD_MAX_H_FRAC = 0.28;

  let urls = [];
  let ctx = null;
  let rafId = 0;
  let lastTs = 0;
  let cssW = 1;
  let cssH = 1;
  let dpr = 1;
  let x = 0;
  let y = 0;
  let vx = 0;
  let vy = 0;
  let currentUrl = '';
  let currentImg = null;
  let halfW = 60;
  let halfH = 84;
  const pool = new Map();

  function syncSize() {
    const rect = overlay.getBoundingClientRect();
    cssW = Math.max(1, Math.floor(rect.width || window.innerWidth || 1));
    cssH = Math.max(1, Math.floor(rect.height || window.innerHeight || 1));
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;
    ctx = canvas.getContext('2d');
    return !!ctx;
  }

  function measureCard(img) {
    if (!img || !img.naturalWidth) return { dw: halfW * 2, dh: halfH * 2 };
    const ar = img.naturalWidth / img.naturalHeight;
    let dh = Math.min(cssH * CARD_MAX_H_FRAC, 240);
    let dw = dh * ar;
    const maxW = cssW * 0.42;
    if (dw > maxW) {
      dw = maxW;
      dh = dw / ar;
    }
    return { dw, dh };
  }

  function clampPos() {
    halfW = Math.min(halfW, cssW * 0.5 - 0.5);
    halfH = Math.min(halfH, cssH * 0.5 - 0.5);
    x = Math.max(halfW, Math.min(cssW - halfW, x));
    y = Math.max(halfH, Math.min(cssH - halfH, y));
  }

  function pickRandomUrl(exclude) {
    if (!urls.length) return '';
    const filtered = urls.filter(u => u !== exclude);
    const list = filtered.length ? filtered : urls;
    return list[(Math.random() * list.length) | 0];
  }

  function pickNextFromPool(exclude) {
    const keys = [...pool.keys()].filter(k => k !== exclude);
    const pickFrom = keys.length ? keys : [...pool.keys()];
    if (!pickFrom.length) return '';
    return pickFrom[(Math.random() * pickFrom.length) | 0];
  }

  function swapCardOnBounce() {
    const next = pickNextFromPool(currentUrl);
    if (!next || !pool.has(next)) return;
    currentUrl = next;
    currentImg = pool.get(next);
    const m = measureCard(currentImg);
    halfW = m.dw * 0.5;
    halfH = m.dh * 0.5;
    clampPos();
  }

  function loadImage(src) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => {
        if (img.decode) {
          img
            .decode()
            .then(() => resolve(img))
            .catch(() => resolve(img));
        } else {
          resolve(img);
        }
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }

  async function warmPool() {
    pool.clear();
    const n = Math.min(POOL_TARGET, urls.length);
    const shuffled = urls.slice().sort(() => Math.random() - 0.5);
    const slice = shuffled.slice(0, n);
    const loaded = await Promise.all(
      slice.map(async u => {
        const img = await loadImage(u);
        return img ? [u, img] : null;
      })
    );
    for (const row of loaded) {
      if (row) pool.set(row[0], row[1]);
    }
  }

  function seedMotion() {
    const theta = Math.random() * Math.PI * 2;
    vx = Math.cos(theta) * SPEED_PX;
    vy = Math.sin(theta) * SPEED_PX;
  }

  function step(dt) {
    if (!ctx || !currentImg) return;
    x += vx * dt;
    y += vy * dt;

    let hitX = false;
    let hitY = false;
    if (x - halfW < 0) {
      x = halfW;
      vx = -vx;
      hitX = true;
    } else if (x + halfW > cssW) {
      x = cssW - halfW;
      vx = -vx;
      hitX = true;
    }
    if (y - halfH < 0) {
      y = halfH;
      vy = -vy;
      hitY = true;
    } else if (y + halfH > cssH) {
      y = cssH - halfH;
      vy = -vy;
      hitY = true;
    }

    if (hitX || hitY) {
      swapCardOnBounce();
      const sp = Math.hypot(vx, vy) || 1;
      vx = (vx / sp) * SPEED_PX;
      vy = (vy / sp) * SPEED_PX;
    }
  }

  function drawFrame() {
    if (!ctx || !currentImg) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#0a1610';
    ctx.fillRect(0, 0, cssW, cssH);
    const { dw, dh } = measureCard(currentImg);
    ctx.drawImage(currentImg, x - dw * 0.5, y - dh * 0.5, dw, dh);
    ctx.fillStyle = DARKEN;
    ctx.fillRect(0, 0, cssW, cssH);
  }

  function frame(ts) {
    if (!lastTs) lastTs = ts;
    const dt = Math.min(0.05, Math.max(0, (ts - lastTs) / 1000));
    lastTs = ts;
    step(dt);
    drawFrame();
    rafId = window.requestAnimationFrame(frame);
  }

  function onResize() {
    if (!syncSize()) return;
    const m = measureCard(currentImg);
    halfW = m.dw * 0.5;
    halfH = m.dh * 0.5;
    clampPos();
    drawFrame();
  }

  function stop() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
    window.removeEventListener('resize', onResize);
    pool.clear();
    canvas.classList.remove('lobby-bg-canvas--fill');
    if (canvas._lobbyBounceStop === stop) delete canvas._lobbyBounceStop;
  }

  canvas.classList.add('lobby-bg-canvas--fill');
  canvas._lobbyBounceStop = stop;

  return fetch('/api/lobby/background-card-urls')
    .then(res => (res.ok ? res.json() : {}))
    .then(data => {
      urls = Array.isArray(data.urls) ? data.urls : [];
    })
    .catch(() => {
      urls = [];
    })
    .then(async () => {
      if (!urls.length) {
        stop();
        return;
      }
      if (!syncSize()) {
        stop();
        return;
      }
      await warmPool();
      if (!pool.size) {
        stop();
        return;
      }
      currentUrl = pickRandomUrl('');
      currentImg = pool.get(currentUrl) || pool.values().next().value;
      if (!currentImg) {
        stop();
        return;
      }
      const m0 = measureCard(currentImg);
      halfW = m0.dw * 0.5;
      halfH = m0.dh * 0.5;
      x = cssW * 0.5;
      y = cssH * 0.5;
      clampPos();
      seedMotion();
      lastTs = 0;
      window.addEventListener('resize', onResize);
      drawFrame();
      rafId = window.requestAnimationFrame(frame);
    });
}

async function initLobbyBackgroundCanvas(canvas) {
  if (LOBBY_BACKGROUND_MODE === 'collage') {
    await paintLobbyBackgroundCollage(canvas);
    return;
  }
  await startLobbyBackgroundBounce(canvas);
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
  const bgCanvas = document.getElementById('lobby-bg-canvas');
  if (bgCanvas) initLobbyBackgroundCanvas(bgCanvas).catch(() => {});
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
  initActionConfirmModal();
  window.addEventListener('resize', () => {
    const zone = document.getElementById('zone-center');
    if (zone) syncBoardTabState(zone);
  });
}
