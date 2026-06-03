// ── Lobby background ───────────────────────────────────────────────────────
// `'collage'` = static overlapping card grid (original). `'bounce'` = one card, constant speed, specular wall bounces, new random card each bounce.
const LOBBY_BACKGROUND_MODE = 'bounce';

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
// Full preset labels live in the HTML <option> markup. The JS only needs
// short labels for compact lobby browser/wait rows.
const LOBBY_PRESET_SHORT_LABELS = {
  current: 'Default',
  base: 'Base Set',
  flamesandfrost: 'Flames+Frost',
  shadowvale: 'Shadowvale',
  random: 'Random',
  draft: 'Draft',
};

// ── Draft mode client state ──────────────────────────────────────────────────
let _draftPhaseKey = '';      // 'monsters', 'starters', or 'citizens_1' etc — reset votes on change
let _draftMonsterVotes = [];  // area names the player has locally selected (up to 5)
let _draftStarterVote = null; // starter_id the player has locally selected
let _draftCitizenVote = null; // citizen_id the player has locally selected
let _draftVoteSubmitted = false;
let _draftTimerInterval = null;
let _draftTimerEnd = 0;

function _stopDraftTimer() {
  if (_draftTimerInterval) {
    clearInterval(_draftTimerInterval);
    _draftTimerInterval = null;
  }
}

function _startDraftTimer(timerEl) {
  _stopDraftTimer();
  function tick() {
    const secs = Math.max(0, Math.ceil(_draftTimerEnd - Date.now() / 1000));
    if (timerEl) {
      timerEl.textContent = secs;
      timerEl.classList.toggle('draft-timer--urgent', secs <= 10);
    }
  }
  tick();
  _draftTimerInterval = setInterval(tick, 500);
}

function _getDraftPhaseKey(draft) {
  if (!draft) return '';
  if (draft.phase === 'monsters') return 'monsters';
  if (draft.phase === 'starters') return 'starters';
  if (draft.phase === 'citizens') return `citizens_${draft.current_roll}`;
  return '';
}

function _draftHasServerVote(draft) {
  if (!draft) return false;
  if (draft.phase === 'monsters') return !!(draft.my_monster_votes && draft.my_monster_votes.length > 0);
  if (draft.phase === 'starters') return draft.my_starter_vote != null;
  if (draft.phase === 'citizens') return draft.my_citizen_vote != null;
  return false;
}

function _syncDraftVoteFromServer(draft) {
  if (!_draftHasServerVote(draft)) return;
  if (draft.phase === 'monsters') {
    _draftMonsterVotes = [...draft.my_monster_votes];
  } else if (draft.phase === 'starters') {
    _draftStarterVote = draft.my_starter_vote;
  } else if (draft.phase === 'citizens') {
    _draftCitizenVote = draft.my_citizen_vote;
  }
}

function lobbyPresetShortLabel(preset) {
  return LOBBY_PRESET_SHORT_LABELS[preset] || preset || 'Custom';
}

// Some players pick very long display names. In compact "meta" surfaces
// inside the lobby modal (the comma-separated roster on each lobby
// card, the owner name embedded in the in-lobby meta line, etc.) those
// names would otherwise blow out the layout on mobile, so we cap them
// fairly aggressively here. Player-row UIs render the full name and
// rely on CSS ellipsis instead, since each row has its own line.
const LOBBY_META_NAME_MAX = 8;
function truncateLobbyName(name, max = LOBBY_META_NAME_MAX) {
  const s = String(name == null ? '' : name);
  return s.length > max ? s.slice(0, max) + '…' : s;
}

function handleDraftState(draft, selfId) {
  const phaseKey = _getDraftPhaseKey(draft);
  if (phaseKey !== _draftPhaseKey) {
    _draftPhaseKey = phaseKey;
    _draftMonsterVotes = [];
    _draftStarterVote = null;
    _draftCitizenVote = null;
    _draftVoteSubmitted = false;
    _syncDraftVoteFromServer(draft);
    _draftVoteSubmitted = _draftHasServerVote(draft);
  } else {
    _draftVoteSubmitted = _draftHasServerVote(draft);
    _syncDraftVoteFromServer(draft);
  }

  _draftTimerEnd = draft.timer_end || 0;

  const titleEl = document.getElementById('draft-title');
  const progressEl = document.getElementById('draft-progress');
  const instrEl = document.getElementById('draft-instructions');
  const lastResultEl = document.getElementById('draft-last-result');
  const gridEl = document.getElementById('draft-grid');
  const timerEl = document.getElementById('draft-timer');
  const statusEl = document.getElementById('draft-vote-status');
  const voteBtn = document.getElementById('draft-vote-btn');

  if (!gridEl || !voteBtn) return;

  _startDraftTimer(timerEl);

  // Last result banner
  if (lastResultEl) {
    const lr = draft.last_result;
    if (lr && lr.phase === 'monsters' && lr.selected && lr.selected.length) {
      lastResultEl.textContent = `Monsters selected: ${lr.selected.join(', ')}`;
    } else if (lr && lr.phase === 'starters' && lr.winner_id != null) {
      const allS = draft.available_starters || [];
      const winner = allS.find(s => s.id === lr.winner_id);
      const name = winner ? winner.name : `Starter #${lr.winner_id}`;
      lastResultEl.textContent = `Third starter: ${name} selected`;
    } else if (lr && lr.phase === 'citizens' && lr.winner_id != null) {
      const roll = lr.roll;
      // Find the citizen name from available data
      const allC = draft.available_citizens || [];
      const winner = allC.find(c => c.id === lr.winner_id);
      const name = winner ? winner.name : `Citizen #${lr.winner_id}`;
      lastResultEl.textContent = `Roll ${roll}: ${name} selected`;
    } else {
      lastResultEl.textContent = '';
    }
  }

  if (draft.phase === 'monsters') {
    if (titleEl) titleEl.textContent = 'Monster Draft';
    if (progressEl) progressEl.textContent = `Select your top 5 monster stacks`;
    if (instrEl) instrEl.textContent = _draftVoteSubmitted
      ? 'Votes submitted — waiting for others or timer'
      : 'Click up to 5 stacks to vote for them, then submit';
    _renderMonsterGrid(draft, gridEl, selfId);
    _updateDraftMonstersFooter(draft, statusEl, voteBtn, selfId);
  } else if (draft.phase === 'starters') {
    if (titleEl) titleEl.textContent = 'Starter Draft';
    if (progressEl) progressEl.textContent = 'Choose the third starter for this game';
    if (instrEl) instrEl.textContent = _draftVoteSubmitted
      ? 'Vote submitted — waiting for others or timer'
      : 'Pick Herald, Margrave, or another third-slot starter';
    _renderStarterGrid(draft, gridEl, selfId);
    _updateDraftStartersFooter(draft, statusEl, voteBtn, selfId);
  } else if (draft.phase === 'citizens') {
    const round = draft.citizen_draft_round || 1;
    const total = draft.citizen_draft_total || 10;
    const roll = draft.current_roll;
    if (titleEl) titleEl.textContent = `Citizen Draft — Roll ${roll}`;
    if (progressEl) progressEl.textContent = `Citizen slot ${round} of ${total}`;
    if (instrEl) instrEl.textContent = _draftVoteSubmitted
      ? 'Vote submitted — waiting for others or timer'
      : `Choose which citizen fills the roll ${roll} slot`;
    _renderCitizenGrid(draft, gridEl, selfId);
    _updateDraftCitizensFooter(draft, statusEl, voteBtn, selfId);
  }
}

function _openStackViewer(area) {
  const cards = area.stack_cards || (area.front_card ? [area.front_card] : []);
  const viewer = document.createElement('div');
  viewer.className = 'draft-stack-viewer';

  const panel = document.createElement('div');
  panel.className = 'draft-stack-viewer-panel';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'draft-stack-viewer-close';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => viewer.remove());
  panel.appendChild(closeBtn);

  const title = document.createElement('h3');
  title.className = 'draft-stack-viewer-title';
  title.textContent = `${area.area} — full stack (${cards.length} card${cards.length !== 1 ? 's' : ''})`;
  panel.appendChild(title);

  const grid = document.createElement('div');
  grid.className = 'draft-stack-viewer-grid';
  cards.forEach((c, i) => {
    const wrap = document.createElement('div');
    wrap.className = 'draft-stack-viewer-card';
    const img = document.createElement('img');
    img.src = `/card-image/monster/${c.id}`;
    img.alt = c.name;
    img.loading = 'lazy';
    wrap.appendChild(img);
    const lbl = document.createElement('div');
    lbl.className = 'draft-stack-viewer-card-label';
    lbl.textContent = i === 0 ? `${c.name} (top)` : c.name;
    wrap.appendChild(lbl);
    grid.appendChild(wrap);
  });
  panel.appendChild(grid);

  viewer.appendChild(panel);
  viewer.addEventListener('click', e => { if (e.target === viewer) viewer.remove(); });
  document.body.appendChild(viewer);
}

function _renderMonsterGrid(draft, gridEl, selfId) {
  const areas = draft.available_monsters || [];
  gridEl.innerHTML = '';

  areas.forEach(area => {
    const wrap = document.createElement('div');
    wrap.className = 'draft-card-wrap';

    const card = document.createElement('div');
    card.className = 'draft-card';
    const selIdx = _draftMonsterVotes.indexOf(area.area);
    if (selIdx !== -1) card.classList.add('draft-card--selected');
    if (_draftVoteSubmitted) card.classList.add('draft-card--locked');

    if (area.front_card) {
      const img = document.createElement('img');
      img.className = 'draft-card-img';
      img.src = `/card-image/monster/${area.front_card.id}`;
      img.alt = area.area;
      img.loading = 'lazy';
      card.appendChild(img);
    } else {
      const placeholder = document.createElement('div');
      placeholder.className = 'draft-card-img';
      placeholder.style.cssText = 'display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:11px';
      placeholder.textContent = area.area;
      card.appendChild(placeholder);
    }

    const label = document.createElement('div');
    label.className = 'draft-card-label';
    label.textContent = area.area;
    card.appendChild(label);

    if (area.vote_count > 0) {
      const badge = document.createElement('div');
      badge.className = 'draft-vote-badge';
      badge.textContent = area.vote_count;
      card.appendChild(badge);
    }

    if (selIdx !== -1) {
      const rank = document.createElement('div');
      rank.className = 'draft-select-rank';
      rank.textContent = `#${selIdx + 1}`;
      card.appendChild(rank);
    }

    if (!_draftVoteSubmitted) {
      card.addEventListener('click', () => {
        const i = _draftMonsterVotes.indexOf(area.area);
        if (i !== -1) {
          _draftMonsterVotes.splice(i, 1);
        } else if (_draftMonsterVotes.length < 5) {
          _draftMonsterVotes.push(area.area);
        }
        _renderMonsterGrid(draft, gridEl, selfId);
        const statusEl = document.getElementById('draft-vote-status');
        const voteBtn = document.getElementById('draft-vote-btn');
        _updateDraftMonstersFooter(draft, statusEl, voteBtn, selfId);
      });
    }

    wrap.appendChild(card);

    const stackBtn = document.createElement('button');
    stackBtn.type = 'button';
    stackBtn.className = 'draft-stack-btn';
    const stackCount = (area.stack_cards || []).length;
    stackBtn.textContent = `View stack (${stackCount})`;
    stackBtn.addEventListener('click', e => {
      e.stopPropagation();
      _openStackViewer(area);
    });
    wrap.appendChild(stackBtn);

    gridEl.appendChild(wrap);
  });
}

function _starterDraftSubtitle(s) {
  const parts = [];
  const trig = (s.activation_trigger || '').toString();
  if (trig) parts.push(trig.replace(/_/g, ' '));
  if (s.has_special_payout_on_turn || s.has_special_payout_off_turn) {
    const sp = (s.special_payout_on_turn || s.special_payout_off_turn || '').toString();
    if (sp && sp !== '0') parts.push(sp);
  }
  const gOn = Number(s.gold_payout_on_turn || 0);
  const gOff = Number(s.gold_payout_off_turn || 0);
  const sOn = Number(s.strength_payout_on_turn || 0);
  const sOff = Number(s.strength_payout_off_turn || 0);
  const mOn = Number(s.magic_payout_on_turn || 0);
  const mOff = Number(s.magic_payout_off_turn || 0);
  if (gOn || gOff || sOn || sOff || mOn || mOff) {
    parts.push(`on ${gOn}/${sOn}/${mOn} off ${gOff}/${sOff}/${mOff}`);
  }
  return parts.join(' · ') || 'Doubles / no-payout slot';
}

function _renderStarterGrid(draft, gridEl, selfId) {
  const starters = draft.available_starters || [];
  gridEl.innerHTML = '';

  starters.forEach(s => {
    const card = document.createElement('div');
    card.className = 'draft-card';
    const isSelected = _draftStarterVote === s.id;
    if (isSelected) card.classList.add('draft-card--selected');
    if (_draftVoteSubmitted) card.classList.add('draft-card--locked');

    const img = document.createElement('img');
    img.className = 'draft-card-img';
    img.src = `/card-image/starter/${s.id}`;
    img.alt = s.name;
    img.loading = 'lazy';
    card.appendChild(img);

    const label = document.createElement('div');
    label.className = 'draft-card-label';
    label.textContent = s.name;
    card.appendChild(label);

    const sub = document.createElement('div');
    sub.className = 'draft-card-label';
    sub.style.fontSize = '10px';
    sub.style.opacity = '0.85';
    sub.textContent = _starterDraftSubtitle(s);
    card.appendChild(sub);

    if (s.vote_count > 0) {
      const badge = document.createElement('div');
      badge.className = 'draft-vote-badge';
      badge.textContent = s.vote_count;
      card.appendChild(badge);
    }

    if (!_draftVoteSubmitted) {
      card.addEventListener('click', () => {
        _draftStarterVote = s.id;
        _renderStarterGrid(draft, gridEl, selfId);
        const statusEl = document.getElementById('draft-vote-status');
        const voteBtn = document.getElementById('draft-vote-btn');
        _updateDraftStartersFooter(draft, statusEl, voteBtn, selfId);
      });
    }

    gridEl.appendChild(card);
  });
}

function _updateDraftStartersFooter(draft, statusEl, voteBtn, selfId) {
  const submitted = draft.votes_submitted_count || 0;
  const total = draft.total_players || 1;
  if (statusEl) {
    if (_draftVoteSubmitted) {
      statusEl.textContent = `✓ Vote submitted (${submitted}/${total} players voted)`;
    } else {
      statusEl.textContent = `${submitted}/${total} players voted`;
    }
  }
  if (voteBtn) {
    voteBtn.textContent = 'Confirm Vote';
    voteBtn.disabled = _draftVoteSubmitted || _draftStarterVote == null || !draft.am_participant;
  }
}

function _renderCitizenGrid(draft, gridEl, selfId) {
  const citizens = draft.available_citizens || [];
  gridEl.innerHTML = '';

  citizens.forEach(c => {
    const card = document.createElement('div');
    card.className = 'draft-card';
    const isSelected = _draftCitizenVote === c.id;
    if (isSelected) card.classList.add('draft-card--selected');
    if (_draftVoteSubmitted) card.classList.add('draft-card--locked');

    const img = document.createElement('img');
    img.className = 'draft-card-img';
    img.src = `/card-image/citizen/${c.id}`;
    img.alt = c.name;
    img.loading = 'lazy';
    card.appendChild(img);

    const label = document.createElement('div');
    label.className = 'draft-card-label';
    label.textContent = c.name;
    card.appendChild(label);

    if (c.vote_count > 0) {
      const badge = document.createElement('div');
      badge.className = 'draft-vote-badge';
      badge.textContent = c.vote_count;
      card.appendChild(badge);
    }

    if (!_draftVoteSubmitted) {
      card.addEventListener('click', () => {
        _draftCitizenVote = c.id;
        _renderCitizenGrid(draft, gridEl, selfId);
        const statusEl = document.getElementById('draft-vote-status');
        const voteBtn = document.getElementById('draft-vote-btn');
        _updateDraftCitizensFooter(draft, statusEl, voteBtn, selfId);
      });
    }

    gridEl.appendChild(card);
  });
}

function _updateDraftMonstersFooter(draft, statusEl, voteBtn, selfId) {
  const n = _draftMonsterVotes.length;
  const submitted = draft.votes_submitted_count || 0;
  const total = draft.total_players || 1;
  if (statusEl) {
    if (_draftVoteSubmitted) {
      statusEl.textContent = `✓ Votes submitted (${submitted}/${total} players voted)`;
    } else {
      statusEl.textContent = `${n}/5 selected • ${submitted}/${total} players voted`;
    }
  }
  if (voteBtn) {
    voteBtn.textContent = 'Submit Votes';
    voteBtn.disabled = _draftVoteSubmitted || n === 0 || !draft.am_participant;
  }
}

function _updateDraftCitizensFooter(draft, statusEl, voteBtn, selfId) {
  const submitted = draft.votes_submitted_count || 0;
  const total = draft.total_players || 1;
  if (statusEl) {
    if (_draftVoteSubmitted) {
      statusEl.textContent = `✓ Vote submitted (${submitted}/${total} players voted)`;
    } else {
      statusEl.textContent = `${submitted}/${total} players voted`;
    }
  }
  if (voteBtn) {
    voteBtn.textContent = 'Confirm Vote';
    voteBtn.disabled = _draftVoteSubmitted || _draftCitizenVote == null || !draft.am_participant;
  }
}

function initLobbyModal() {
  const overlay = document.getElementById('lobby-overlay');
  const connEl = document.getElementById('conn-status');
  const errEl = document.getElementById('lobby-error');
  const stepName = document.getElementById('lobby-step-name');
  const stepBrowse = document.getElementById('lobby-step-browse');
  const stepWait = document.getElementById('lobby-step-wait');
  const nameInput = document.getElementById('lobby-display-name');
  const continueNameBtn = document.getElementById('lobby-name-continue-btn');
  const lobbyListEl = document.getElementById('lobby-list');
  const lobbyListEmptyEl = document.getElementById('lobby-list-empty');
  const createPresetSelect = document.getElementById('lobby-create-preset');
  const createMinPlayersSelect = document.getElementById('lobby-create-min-players');
  const createBtn = document.getElementById('lobby-create-btn');
  const backToNameBtn = document.getElementById('lobby-back-to-name-btn');
  const lobbySheet = overlay ? overlay.querySelector('.lobby-sheet') : null;
  const waitMetaEl = document.getElementById('lobby-wait-meta');
  const presetSelect = document.getElementById('lobby-preset-select');
  const minPlayersSelect = document.getElementById('lobby-min-players-select');
  const readyBtn = document.getElementById('lobby-ready-btn');
  const leaveBtn = document.getElementById('lobby-leave-btn');
  const playerList = document.getElementById('lobby-player-list');
  const metaEl = document.getElementById('lobby-meta');

  const required = [
    overlay, stepName, stepBrowse, stepWait, nameInput, continueNameBtn,
    lobbyListEl, createPresetSelect, createMinPlayersSelect, createBtn,
    presetSelect, minPlayersSelect, readyBtn, leaveBtn, playerList,
  ];
  if (required.some(el => !el)) {
    if (connEl) connEl.textContent = 'Missing game_id or player_id in URL';
    return;
  }

  const savedDisplay = vckStoredDisplayName();
  if (savedDisplay && !String(nameInput.value || '').trim()) {
    nameInput.value = savedDisplay;
  }

  let lobbyPlayerId = '';
  let currentLobbyId = '';
  let lobbyWs = null;
  let lobbyWsReconnectTimer = null;
  let lastLobbySnapshot = null;
  // Safety nets for silent WS disconnects + reconnect/identify races.
  // The lobby WS goes flaky on long-running draft lobbies (browser
  // throttling backgrounded tabs, OS suspends, transient network
  // blips). When it dies silently the user keeps seeing the last
  // snapshot but stops receiving updates from other players' votes,
  // and clicks against stale state silently no-op. The passive poll
  // refetches lobby state every few seconds so we always recover, and
  // the visibilitychange handler forces an immediate refetch the
  // moment the tab regains focus. The dedupe timer collapses the
  // burst of refetches that can fire when several missing-draft
  // broadcasts arrive back-to-back.
  const PASSIVE_LOBBY_POLL_MS = 5000;
  let passiveLobbyPollTimer = null;
  let lobbyRefetchPending = false;
  // In-lobby rename UX: the pencil next to the user's own row swaps the
  // name span for an inline input. The flag survives WS broadcasts so a
  // ready/unready by another player doesn't wipe an in-progress edit;
  // the draft mirrors the input value for the same reason.
  // `renameJustBegan` triggers focus+select on the next render only —
  // subsequent broadcast-driven re-renders leave focus alone.
  let editingSelfName = false;
  let editingSelfNameDraft = '';
  let renameJustBegan = false;

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

  // Coalesce rapid-fire HTTP refetches into one. Used when an incoming
  // WS broadcast is missing draft data (identify race) or when the
  // passive poll fires.
  function _scheduleLobbyRefetch() {
    if (lobbyRefetchPending) return;
    lobbyRefetchPending = true;
    Promise.resolve().then(async () => {
      try {
        const fresh = await fetchLobbyPayload();
        if (fresh) applyLobbyStatusPayload(fresh);
      } catch (_) { /* ignore */ } finally {
        lobbyRefetchPending = false;
      }
    });
  }

  // Decide whether we should be passively polling lobby state. We only
  // poll when the user is "in" a lobby/draft and the tab is visible.
  // Anything else (browsing the lobby list, name entry, hidden tab) is
  // either already kept fresh on user action, or shouldn't burn the
  // server with HTTP requests.
  function _lobbyPassivePollEligible() {
    if (document.hidden) return false;
    if (!currentLobbyId) return false;
    const pid = lobbyPlayerId || vckStoredPlayerId();
    if (!pid) return false;
    const stepWaitEl = document.getElementById('lobby-step-wait');
    const stepDraftEl = document.getElementById('lobby-step-draft');
    const inWait = stepWaitEl && !stepWaitEl.classList.contains('lobby-hidden');
    const inDraft = stepDraftEl && !stepDraftEl.classList.contains('lobby-hidden');
    return !!(inWait || inDraft);
  }

  function _startPassiveLobbyPoll() {
    if (passiveLobbyPollTimer) return;
    passiveLobbyPollTimer = setInterval(() => {
      if (_lobbyPassivePollEligible()) _scheduleLobbyRefetch();
    }, PASSIVE_LOBBY_POLL_MS);
  }

  function _stopPassiveLobbyPoll() {
    if (passiveLobbyPollTimer) {
      clearInterval(passiveLobbyPollTimer);
      passiveLobbyPollTimer = null;
    }
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

  function findLobbyById(snapshot, lobbyId) {
    if (!snapshot || !lobbyId) return null;
    return (snapshot.lobbies || []).find(l => l.lobby_id === lobbyId) || null;
  }

  function findLobbyOfPlayer(snapshot, pid) {
    if (!snapshot || !pid) return null;
    return (snapshot.lobbies || []).find(l =>
      (l.members || []).some(m => idsMatch(m.player_id, pid)),
    ) || null;
  }

  function showStep(step) {
    stepName.classList.toggle('lobby-hidden', step !== 'name');
    stepBrowse.classList.toggle('lobby-hidden', step !== 'browse');
    stepWait.classList.toggle('lobby-hidden', step !== 'wait');
    const stepDraftEl = document.getElementById('lobby-step-draft');
    if (stepDraftEl) stepDraftEl.classList.toggle('lobby-hidden', step !== 'draft');
    if (lobbySheet) lobbySheet.dataset.step = step;
    if (step === 'name') {
      try { nameInput.focus(); } catch (_) { /* ignore */ }
    }
    if (step !== 'wait' && step !== 'draft') {
      editingSelfName = false;
      editingSelfNameDraft = '';
    }
    if (step !== 'draft') _stopDraftTimer();
  }

  function applyLobbyStatusPayload(data) {
    // Defensive: WS broadcasts that race ahead of `identify` (e.g. just after
    // a silent reconnect) arrive with `pid=None` on the server and therefore
    // omit the `draft` key for participants who ARE in an active draft. If
    // we blindly overwrite lastLobbySnapshot with that thin payload, the
    // draft vote click handler later reads `lastLobbySnapshot.draft` as
    // undefined and silently no-ops. Preserve the previous draft data,
    // and trigger a re-identify + HTTP refetch so the next snapshot is
    // authoritative.
    if (lastLobbySnapshot && lastLobbySnapshot.draft && !data.draft) {
      data = { ...data, draft: lastLobbySnapshot.draft };
      try { sendLobbyIdentify(); } catch (_) { /* ignore */ }
      _scheduleLobbyRefetch();
    }
    lastLobbySnapshot = data;
    if (data.in_game && data.game_id) {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (pid) enterGameFromLobby(data.game_id, pid);
      return;
    }

    const selfId = lobbyPlayerId || vckStoredPlayerId() || '';
    const myLobby = findLobbyOfPlayer(data, selfId);

    if (selfId && currentLobbyId && !myLobby) {
      showLobbyError('Your lobby has closed. Pick another or create a new one.');
      lobbyPlayerId = '';
      currentLobbyId = '';
      vckClientPatch({ player_id: null });
      tearDownLobbyConnection();
      connectLobbyWs();
      showStep('browse');
    } else if (myLobby) {
      currentLobbyId = myLobby.lobby_id;
    }

    if (metaEl) {
      const lc = (data.lobbies || []).length;
      const gc = typeof data.game_count === 'number' ? data.game_count : 0;
      metaEl.textContent = `${lc} open lobb${lc === 1 ? 'y' : 'ies'} • ${gc} active game${gc === 1 ? '' : 's'}`;
    }

    if (!stepBrowse.classList.contains('lobby-hidden')) {
      renderLobbyList(data.lobbies || []);
    }

    if (data.draft && myLobby) {
      handleDraftState(data.draft, selfId);
      const stepDraftEl = document.getElementById('lobby-step-draft');
      if (!stepDraftEl || stepDraftEl.classList.contains('lobby-hidden')) {
        showStep('draft');
      }
    } else if (!stepWait.classList.contains('lobby-hidden') && myLobby) {
      renderInLobby(myLobby, selfId);
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

  function renderLobbyList(list) {
    lobbyListEl.innerHTML = '';
    if (!list.length) {
      if (lobbyListEmptyEl) lobbyListEmptyEl.classList.remove('lobby-hidden');
      return;
    }
    if (lobbyListEmptyEl) lobbyListEmptyEl.classList.add('lobby-hidden');
    list.forEach(lb => {
      const li = document.createElement('li');
      li.className = 'lobby-list-row';
      const info = document.createElement('div');
      info.className = 'lobby-list-info';
      const memberCount = (lb.members || []).length;
      // The lobby-card roster is the most cramped surface (one line that
      // has to fit several comma-separated names alongside a Join
      // button on mobile widths), so cap each name harder than the
      // default 8 used for in-lobby meta text.
      const memberNames = (lb.members || [])
        .map(m => truncateLobbyName(m.name || 'Player', 6))
        .join(', ');
      const minPlayers = Number(lb.min_players) || 2;
      // Always show the raw N/M fraction, even when N > M. Lobbies can
      // legitimately exceed the floor while waiting for everyone to
      // ready up, and the "min N met" phrasing previously hid that.
      const minLabel = `${memberCount}/${minPlayers} to start`;
      const primary = document.createElement('div');
      primary.className = 'lobby-list-name';
      primary.textContent = `${lobbyPresetShortLabel(lb.preset)} • ${minLabel}`;
      info.appendChild(primary);
      if (memberNames) {
        const roster = document.createElement('div');
        roster.className = 'lobby-list-roster';
        roster.textContent = memberNames;
        info.appendChild(roster);
      }
      const joinBtn = document.createElement('button');
      joinBtn.type = 'button';
      joinBtn.className = 'lobby-btn lobby-btn-primary lobby-list-join-btn';
      joinBtn.textContent = 'Join';
      joinBtn.addEventListener('click', () => joinLobbyById(lb.lobby_id));
      li.appendChild(info);
      li.appendChild(joinBtn);
      lobbyListEl.appendChild(li);
    });
  }

  function renderInLobby(lobby, selfId) {
    const isOwner = idsMatch(lobby.owner_id, selfId);
    const minPlayers = Number(lobby.min_players) || 2;
    const memberCount = (lobby.members || []).length;
    const floorLabel = `${memberCount}/${minPlayers} to start`;
    if (waitMetaEl) {
      const owner = (lobby.members || []).find(m => idsMatch(m.player_id, lobby.owner_id));
      const ownerName = truncateLobbyName(owner ? (owner.name || 'Owner') : 'Owner');
      const role = isOwner ? 'You are the owner' : `Owner: ${ownerName}`;
      waitMetaEl.textContent = `${role} • ${lobbyPresetShortLabel(lobby.preset)} • ${floorLabel}`;
    }
    if (presetSelect) {
      presetSelect.value = lobby.preset || 'current';
      presetSelect.disabled = !isOwner;
    }
    if (minPlayersSelect) {
      minPlayersSelect.value = String(minPlayers);
      minPlayersSelect.disabled = !isOwner;
    }
    playerList.innerHTML = '';
    let focusInputEl = null;
    (lobby.members || []).forEach(m => {
      const li = document.createElement('li');
      const isSelf = idsMatch(m.player_id, selfId);
      const isLobbyOwner = idsMatch(m.player_id, lobby.owner_id);
      li.className = 'lobby-player-row' + (isSelf ? ' is-self' : '');
      if (isSelf && editingSelfName) {
        const form = document.createElement('div');
        form.className = 'lobby-name-edit';
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'lobby-name-edit-input';
        input.maxLength = 40;
        input.value = editingSelfNameDraft || (m.name || '');
        input.placeholder = 'Display name';
        input.setAttribute('aria-label', 'Display name');
        input.addEventListener('input', () => { editingSelfNameDraft = input.value; });
        input.addEventListener('keydown', ev => {
          if (ev.key === 'Enter') { ev.preventDefault(); submitRenameSelf(); }
          else if (ev.key === 'Escape') { ev.preventDefault(); cancelRenameSelf(); }
        });
        const saveBtn = document.createElement('button');
        saveBtn.type = 'button';
        saveBtn.className = 'lobby-name-edit-btn lobby-name-edit-btn--primary';
        saveBtn.textContent = 'Save';
        saveBtn.addEventListener('click', submitRenameSelf);
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'lobby-name-edit-btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', cancelRenameSelf);
        form.appendChild(input);
        form.appendChild(saveBtn);
        form.appendChild(cancelBtn);
        li.appendChild(form);
        focusInputEl = input;
      } else {
        const nameSpan = document.createElement('span');
        nameSpan.className = 'lobby-p-name';
        // Only the name text itself should ellipsize; the Owner tag and
        // edit-pencil button (when present) live alongside it as
        // unshrinkable siblings so they remain visible for long names.
        const nameText = document.createElement('span');
        nameText.className = 'lobby-p-name-text';
        nameText.textContent = m.name || 'Player';
        nameText.title = m.name || 'Player';
        nameSpan.appendChild(nameText);
        if (isLobbyOwner) {
          const ownerTag = document.createElement('span');
          ownerTag.className = 'lobby-owner-tag';
          ownerTag.textContent = 'Owner';
          nameSpan.appendChild(ownerTag);
        }
        if (isSelf) {
          const editBtn = document.createElement('button');
          editBtn.type = 'button';
          editBtn.className = 'lobby-icon-btn lobby-icon-btn--inline';
          editBtn.setAttribute('aria-label', 'Change display name');
          editBtn.title = 'Change display name';
          editBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false" fill="currentColor"><path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207 11.207 2.5zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293l6.5-6.5zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325z"/></svg>';
          editBtn.addEventListener('click', () => beginRenameSelf(m.name || ''));
          nameSpan.appendChild(editBtn);
        }
        li.appendChild(nameSpan);
      }
      const stSpan = document.createElement('span');
      stSpan.className = 'lobby-p-status' + (m.is_ready ? ' is-ready' : '');
      stSpan.textContent = m.is_ready ? 'Ready' : 'Waiting';
      li.appendChild(stSpan);
      playerList.appendChild(li);
    });
    if (focusInputEl && renameJustBegan) {
      renameJustBegan = false;
      setTimeout(() => {
        try { focusInputEl.focus(); focusInputEl.select(); } catch (_) { /* ignore */ }
      }, 0);
    }
    const me = (lobby.members || []).find(m => idsMatch(m.player_id, selfId));
    if (me) {
      const ready = !!me.is_ready;
      readyBtn.textContent = ready ? 'Cancel ready' : 'Ready';
      readyBtn.classList.toggle('is-cancel', ready);
    }
  }

  async function tryResumeStoredPlayer() {
    const saved = vckStoredPlayerId();
    if (!saved) return;
    try {
      const data = await fetchLobbyPayload();
      if (data.in_game && data.game_id) {
        enterGameFromLobby(data.game_id, saved);
        return;
      }
      const myLobby = findLobbyOfPlayer(data, saved);
      if (myLobby) {
        lobbyPlayerId = saved;
        currentLobbyId = myLobby.lobby_id;
        applyLobbyStatusPayload(data);
        sendLobbyIdentify();
        return;
      }
      if (vckStoredDisplayName()) {
        showStep('browse');
        renderLobbyList(data.lobbies || []);
      }
    } catch (_) {
      /* ignore */
    }
  }

  function rememberDisplayName() {
    const name = nameInput.value.trim();
    if (!name) return '';
    vckClientPatch({ display_name: name });
    return name;
  }

  function beginRenameSelf(currentName) {
    editingSelfName = true;
    editingSelfNameDraft = currentName || '';
    renameJustBegan = true;
    showLobbyError('');
    if (lastLobbySnapshot) applyLobbyStatusPayload(lastLobbySnapshot);
  }

  function cancelRenameSelf() {
    editingSelfName = false;
    editingSelfNameDraft = '';
    showLobbyError('');
    if (lastLobbySnapshot) applyLobbyStatusPayload(lastLobbySnapshot);
  }

  async function submitRenameSelf() {
    const newName = (editingSelfNameDraft || '').trim();
    if (!newName) {
      showLobbyError('Enter a display name.');
      return;
    }
    const pid = lobbyPlayerId || vckStoredPlayerId();
    if (!pid) return;
    showLobbyError('');
    try {
      const res = await fetch('/api/lobby/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: pid, name: newName }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail != null ? String(data.detail) : 'Rename failed');
      }
      vckClientPatch({ display_name: newName });
      if (nameInput) nameInput.value = newName;
      editingSelfName = false;
      editingSelfNameDraft = '';
      // Server broadcasts the rename via WS, but render now in case the
      // snapshot hasn't arrived yet.
      if (lastLobbySnapshot) applyLobbyStatusPayload(lastLobbySnapshot);
    } catch (e) {
      showLobbyError(e.message || 'Rename failed.');
    }
  }

  async function joinLobbyById(lobbyId) {
    const name = rememberDisplayName();
    if (!name) {
      showLobbyError('Enter a display name first.');
      showStep('name');
      return;
    }
    showLobbyError('');
    try {
      const res = await fetch('/api/lobby/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, lobby_id: lobbyId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Join failed');
      }
      lobbyPlayerId = data.player_id || '';
      currentLobbyId = data.lobby_id || lobbyId;
      vckClientPatch({ player_id: lobbyPlayerId });
      showStep('wait');
      sendLobbyIdentify();
    } catch (e) {
      showLobbyError(e.message || 'Could not join lobby.');
    }
  }

  async function createLobby() {
    const name = rememberDisplayName();
    if (!name) {
      showLobbyError('Enter a display name first.');
      showStep('name');
      return;
    }
    showLobbyError('');
    createBtn.disabled = true;
    try {
      const preset = createPresetSelect.value || 'current';
      const minPlayers = Number(createMinPlayersSelect.value) || 2;
      const res = await fetch('/api/lobby/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, preset, min_players: minPlayers }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Create failed');
      }
      lobbyPlayerId = data.player_id || '';
      currentLobbyId = data.lobby_id || '';
      vckClientPatch({ player_id: lobbyPlayerId });
      showStep('wait');
      sendLobbyIdentify();
    } catch (e) {
      showLobbyError(e.message || 'Could not create lobby.');
    } finally {
      createBtn.disabled = false;
    }
  }

  continueNameBtn.addEventListener('click', async () => {
    const name = rememberDisplayName();
    if (!name) {
      showLobbyError('Enter a display name.');
      return;
    }
    showLobbyError('');
    showStep('browse');
    try {
      const data = await fetchLobbyPayload();
      lastLobbySnapshot = data;
      renderLobbyList(data.lobbies || []);
    } catch (e) {
      showLobbyError(e.message || 'Could not load lobbies.');
    }
  });

  nameInput.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') continueNameBtn.click();
  });

  createBtn.addEventListener('click', () => {
    createLobby();
  });

  if (backToNameBtn) {
    backToNameBtn.addEventListener('click', () => {
      // Mirror the user's display name into the input so the title
      // step shows what they last entered. We deliberately don't clear
      // the stored name — they can edit and re-continue.
      try {
        const stored = vckStoredDisplayName();
        if (stored) nameInput.value = stored;
      } catch (_) { /* ignore */ }
      showLobbyError('');
      showStep('name');
    });
  }

  if (presetSelect) {
    presetSelect.addEventListener('change', async () => {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) return;
      const preset = presetSelect.value || 'current';
      showLobbyError('');
      try {
        const res = await fetch('/api/lobby/preset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ player_id: pid, preset }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Preset update failed');
        }
      } catch (e) {
        showLobbyError(e.message || 'Could not change preset.');
      }
    });
  }

  if (minPlayersSelect) {
    minPlayersSelect.addEventListener('change', async () => {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) return;
      const minPlayers = Number(minPlayersSelect.value) || 2;
      showLobbyError('');
      try {
        const res = await fetch('/api/lobby/min_players', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ player_id: pid, min_players: minPlayers }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Minimum players update failed');
        }
      } catch (e) {
        showLobbyError(e.message || 'Could not change minimum players.');
      }
    });
  }

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
      const myLobby = findLobbyOfPlayer(st, pid);
      const me = myLobby ? (myLobby.members || []).find(x => idsMatch(x.player_id, pid)) : null;
      const endpoint = me && me.is_ready ? '/api/lobby/unready' : '/api/lobby/ready';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: pid, debug_mode: false }),
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
    currentLobbyId = '';
    vckClientPatch({ player_id: null });
    showLobbyError('');
    sendLobbyIdentify();
    showStep('browse');
    try {
      const data = await fetchLobbyPayload();
      lastLobbySnapshot = data;
      renderLobbyList(data.lobbies || []);
    } catch (_) {
      /* ignore */
    }
    leaveBtn.disabled = false;
  });

  // ── Draft vote button ──────────────────────────────────────────────────
  const draftVoteBtn = document.getElementById('draft-vote-btn');
  if (draftVoteBtn) {
    draftVoteBtn.addEventListener('click', async () => {
      // The previous handler had six different silent `return` paths.
      // The bug we were chasing — "Confirm Vote does nothing after
      // someone else votes; refresh fixes it" — was a WS race that
      // leaves lastLobbySnapshot without a `draft` key. From the
      // user's POV the button just stops working. Defensive rules:
      //   * Never bail silently — every failure path surfaces a
      //     lobby error so the user has a reason to retry.
      //   * If we somehow lost the draft snapshot, do one HTTP
      //     refetch before giving up.
      //   * On any error, re-enable the button so the user can retry.
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) {
        showLobbyError('No player ID — please refresh.');
        return;
      }
      if (_draftVoteSubmitted) {
        showLobbyError('Vote already submitted — waiting for others or timer.');
        return;
      }

      let draft = lastLobbySnapshot && lastLobbySnapshot.draft;
      if (!draft) {
        try { sendLobbyIdentify(); } catch (_) { /* ignore */ }
        try {
          const fresh = await fetchLobbyPayload();
          if (fresh) applyLobbyStatusPayload(fresh);
          draft = lastLobbySnapshot && lastLobbySnapshot.draft;
        } catch (_) { /* ignore */ }
      }
      if (!draft) {
        showLobbyError('Lost connection to draft. Please refresh.');
        return;
      }

      let vote;
      if (draft.phase === 'monsters') {
        if (_draftMonsterVotes.length === 0) {
          showLobbyError('Pick at least one monster stack before voting.');
          return;
        }
        vote = [..._draftMonsterVotes];
      } else if (draft.phase === 'starters') {
        if (_draftStarterVote == null) {
          showLobbyError('Pick a starter before voting.');
          return;
        }
        vote = _draftStarterVote;
      } else if (draft.phase === 'citizens') {
        if (_draftCitizenVote == null) {
          showLobbyError('Pick a citizen before voting.');
          return;
        }
        vote = _draftCitizenVote;
      } else {
        showLobbyError(`Draft is in an unexpected phase (${draft.phase}). Refresh to recover.`);
        return;
      }

      const submittedPhaseKey = _getDraftPhaseKey(draft);
      draftVoteBtn.disabled = true;
      showLobbyError('');
      try {
        const res = await fetch('/api/lobby/draft/vote', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ player_id: pid, vote }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail != null ? String(data.detail) : 'Vote failed');
        }
        if (_draftPhaseKey === submittedPhaseKey) {
          _draftVoteSubmitted = true;
          const statusEl = document.getElementById('draft-vote-status');
          if (statusEl) statusEl.textContent = '✓ Vote submitted — waiting for others or timer';
          draftVoteBtn.disabled = true;
        } else {
          _scheduleLobbyRefetch();
        }
      } catch (e) {
        showLobbyError(e.message || 'Could not submit vote.');
        if (_draftPhaseKey === submittedPhaseKey) {
          draftVoteBtn.disabled = false;
        } else {
          _scheduleLobbyRefetch();
        }
      }
    });
  }

  // ── Draft leave button ─────────────────────────────────────────────────
  const draftLeaveBtn = document.getElementById('draft-leave-btn');
  if (draftLeaveBtn) {
    draftLeaveBtn.addEventListener('click', async () => {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) return;
      draftLeaveBtn.disabled = true;
      try {
        await fetch(`/api/lobby/leave?player_id=${encodeURIComponent(pid)}`, { method: 'POST' });
      } catch (_) { /* ignore */ }
      _stopDraftTimer();
      lobbyPlayerId = '';
      currentLobbyId = '';
      vckClientPatch({ player_id: null });
      showLobbyError('');
      sendLobbyIdentify();
      showStep('browse');
      try {
        const data = await fetchLobbyPayload();
        lastLobbySnapshot = data;
        renderLobbyList(data.lobbies || []);
      } catch (_) { /* ignore */ }
      draftLeaveBtn.disabled = false;
    });
  }

  openOverlay();
  showStep('name');
  const bgCanvas = document.getElementById('lobby-bg-canvas');
  if (bgCanvas) initLobbyBackgroundCanvas(bgCanvas).catch(() => {});
  connectLobbyWs();
  tryResumeStoredPlayer();

  // Belt-and-suspenders: passively poll lobby state every few seconds
  // while we're in a lobby or draft, and immediately refetch when the
  // tab regains focus. Together these recover from silent WS deaths
  // (browser throttling, OS suspends, transient network blips) where
  // the broadcast loop on the server never reaches us and the UI
  // would otherwise sit on stale state until the user manually
  // refreshes — the specific failure mode players hit in draft
  // mode where another player's vote made the page require a refresh.
  _startPassiveLobbyPoll();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (!_lobbyPassivePollEligible()) return;
    try { sendLobbyIdentify(); } catch (_) { /* ignore */ }
    _scheduleLobbyRefetch();
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────
initVirtualKeyboardWatcher();

if (!GAME_ID || !PLAYER_ID) {
  initLobbyModal();
} else {
  connect();
  initOpponentTableauWheelScroll();
  initPlayerDetailModal();
  initActionConfirmModal();
  // Defense-in-depth against lost WS state pushes: poll at a low cadence so
  // a dropped broadcast still surfaces the next prompt within a few seconds.
  startPassiveStatePolling();
  // When the tab returns from being backgrounded (mobile, switched apps,
  // screen lock) browsers commonly suspend the WS — anything broadcast
  // during the suspend is gone. Force an immediate refetch on revisit so
  // we don't sit on a stale board waiting for the next event.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (!GAME_ID || !PLAYER_ID) return;
    fetchGameStateFromApi();
  });
  window.addEventListener('resize', () => {
    const zone = document.getElementById('zone-center');
    if (zone) syncBoardTabState(zone);
  });
}
