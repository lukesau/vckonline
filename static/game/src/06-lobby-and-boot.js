// ── Lobby background ───────────────────────────────────────────────────────
// One card at a time, constant speed, specular wall bounces, with a new random
// card chosen on each bounce.
//
// Card faces for the background are expressed as inclusive id ranges per card
// type and resolved through the shared `/card-image/{type}/{id}` endpoint, so
// adding art only means widening a range (server is the source of truth via
// `/api/lobby/background-cards`; this is the fallback if that fetch fails).
// Each type maps to a list of inclusive `[lo, hi]` sub-ranges so disjoint id
// blocks can skip empty ids between them.
const LOBBY_BG_FALLBACK_RANGES = {
  citizen: [[1, 49]],
  domain: [[1, 80]],
  monster: [[1, 189]],
  duke: [[1, 25]],
  event: [[1, 36]],
  noble: [[1, 16]],
  agent: [[1, 15]],
  relic: [[1, 13]],
};

// Crimson Seas Nobles are smaller cards with a taller/narrower proportion than
// the standard 400×570 face. In the bounce background we draw them at ~75% of
// a regular card's height; width then follows their own natural aspect ratio.
const LOBBY_BG_NOBLE_HEIGHT_SCALE = 0.75;

function lobbyBgCardUrl(type, id) {
  return `/card-image/${type}/${id}`;
}

// One random `/card-image` URL from the ranges. Picks a type uniformly, then an
// id uniformly across that type's sub-ranges (weighted by sub-range size). Ids
// without art on disk 404; callers preload and skip those.
function lobbyBgPickCardUrl(ranges) {
  const types = Object.keys(ranges || {});
  if (!types.length) return '';
  const type = types[(Math.random() * types.length) | 0];
  const spans = ranges[type];
  if (!Array.isArray(spans) || !spans.length) return '';
  let total = 0;
  for (const s of spans) {
    if (Array.isArray(s) && s.length >= 2) total += s[1] - s[0] + 1;
  }
  if (total <= 0) return '';
  let r = (Math.random() * total) | 0;
  for (const s of spans) {
    if (!Array.isArray(s) || s.length < 2) continue;
    const count = s[1] - s[0] + 1;
    if (r < count) return lobbyBgCardUrl(type, s[0] + r);
    r -= count;
  }
  return '';
}

async function lobbyBgFetchRanges() {
  try {
    const res = await fetch('/api/lobby/background-cards');
    if (res.ok) {
      const data = await res.json();
      if (data && data.ranges && typeof data.ranges === 'object') {
        return data.ranges;
      }
    }
  } catch (_) {}
  return LOBBY_BG_FALLBACK_RANGES;
}

// Per-type outline colors mirroring the in-game `.card-*` border vars in
// style.css (events reuse the exhausted border, matching `.card-event`).
const LOBBY_BG_TYPE_BORDERS = {
  citizen: '#3D6785',
  domain: '#4CA366',
  monster: '#644A4C',
  duke: '#823956',
  starter: '#526263',
  event: '#A83524',
  noble: '#423632',
  agent: '#A0782C',
  relic: '#AB5A21',
};

function lobbyBgTypeFromUrl(url) {
  const m = /\/card-image\/([^/]+)\//.exec(url || '');
  return m ? m[1] : '';
}

function lobbyBgBorderColor(url) {
  return LOBBY_BG_TYPE_BORDERS[lobbyBgTypeFromUrl(url)] || '#526263';
}

function startLobbyBackgroundBounce(layer) {
  const overlay = layer.closest('.lobby-overlay');
  if (!overlay) return Promise.resolve();

  const existingStop = layer._lobbyBounceStop;
  if (typeof existingStop === 'function') existingStop();

  const SPEED_PX = 220;
  const CARD_MAX_H_FRAC = 0.28;
  // Bounces can land on an id with no art on disk; retry a few random picks
  // so a single 404 never stalls the rotation.
  const MAX_PICK_ATTEMPTS = 16;

  let cardEl = layer.querySelector('.lobby-bg-card');
  if (!cardEl) {
    cardEl = document.createElement('img');
    cardEl.className = 'lobby-bg-card';
    cardEl.alt = '';
    cardEl.decoding = 'async';
    cardEl.draggable = false;
    layer.appendChild(cardEl);
  }

  let ranges = LOBBY_BG_FALLBACK_RANGES;
  let rafId = 0;
  let stopped = false;
  let lastTs = 0;
  let cssW = 1;
  let cssH = 1;
  let x = 0;
  let y = 0;
  let vx = 0;
  let vy = 0;
  let currentImg = null;
  let currentUrl = '';
  let currentBorderColor = '#526263';
  let currentSizeScale = 1;   // <1 shrinks smaller-format cards (e.g. Nobles)
  let nextCard = null;   // { url, img } — decoded and ready to show on the next bounce
  let preparing = false;
  let halfW = 60;
  let halfH = 84;

  function syncSize() {
    const rect = overlay.getBoundingClientRect();
    cssW = Math.max(1, Math.floor(rect.width || window.innerWidth || 1));
    cssH = Math.max(1, Math.floor(rect.height || window.innerHeight || 1));
    return true;
  }

  function measureCard(img) {
    if (!img || !img.naturalWidth) return { dw: halfW * 2, dh: halfH * 2 };
    const ar = img.naturalWidth / img.naturalHeight;
    // Smaller-format cards (Nobles) are drawn shorter; width then follows their
    // own natural aspect ratio so the narrower frame is preserved.
    let dh = Math.min(cssH * CARD_MAX_H_FRAC, 240) * currentSizeScale;
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

  // Resolve one random card that actually has art, retrying past 404 gaps so
  // every id in the configured ranges is reachable.
  async function loadRandomCard() {
    for (let i = 0; i < MAX_PICK_ATTEMPTS; i++) {
      if (stopped) return null;
      const url = lobbyBgPickCardUrl(ranges);
      if (!url) return null;
      const img = await loadImage(url);
      if (img && img.naturalWidth) return { url, img };
    }
    return null;
  }

  function applyCard(card) {
    currentUrl = card.url;
    currentImg = card.img;
    currentBorderColor = lobbyBgBorderColor(card.url);
    currentSizeScale = lobbyBgTypeFromUrl(card.url) === 'noble' ? LOBBY_BG_NOBLE_HEIGHT_SCALE : 1;
    const m = measureCard(currentImg);
    halfW = m.dw * 0.5;
    halfH = m.dh * 0.5;
    clampPos();
    renderCard();
  }

  // Preload exactly one card ahead so a bounce never reveals a half-loaded
  // (decoding) image.
  function prepareNext() {
    if (preparing || nextCard || stopped) return;
    preparing = true;
    loadRandomCard().then(card => {
      preparing = false;
      if (!stopped && card) nextCard = card;
    });
  }

  function swapCardOnBounce() {
    if (!nextCard) {
      // Preload hasn't landed yet; keep the current card and try again.
      prepareNext();
      return;
    }
    const card = nextCard;
    nextCard = null;
    applyCard(card);
    prepareNext();
  }

  function seedMotion() {
    // Start on a diagonal-ish heading so the card doesn't crawl near-vertically
    // or near-horizontally. Pick one of four 30°-wide arcs centered on the
    // diagonals (30–60, 120–150, 210–240, 300–330) then jitter within it.
    const baseDeg = [30, 120, 210, 300][(Math.random() * 4) | 0];
    const deg = baseDeg + Math.random() * 30;
    const theta = (deg * Math.PI) / 180;
    vx = Math.cos(theta) * SPEED_PX;
    vy = Math.sin(theta) * SPEED_PX;
  }

  function step(dt) {
    if (!currentImg) return;
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

  function renderCard() {
    if (!currentImg) return;
    const { dw, dh } = measureCard(currentImg);
    // Match the in-game card look (5px radius / 1px border on a ~158px card),
    // scaled to the larger background card.
    const radius = Math.max(4, Math.min(dw, dh) * 0.04);
    const border = Math.max(2, Math.min(dw, dh) * 0.016);

    cardEl.src = currentUrl;
    cardEl.style.width = `${dw}px`;
    cardEl.style.height = `${dh}px`;
    cardEl.style.borderColor = currentBorderColor;
    cardEl.style.borderRadius = `${radius}px`;
    cardEl.style.borderWidth = `${border}px`;
    renderPosition();
  }

  function renderPosition() {
    if (!currentImg) return;
    cardEl.style.transform = `translate3d(${x - halfW}px, ${y - halfH}px, 0)`;
  }

  function frame(ts) {
    if (!lastTs) lastTs = ts;
    const dt = Math.min(0.05, Math.max(0, (ts - lastTs) / 1000));
    lastTs = ts;
    step(dt);
    renderPosition();
    rafId = window.requestAnimationFrame(frame);
  }

  function onResize() {
    if (!syncSize()) return;
    const m = measureCard(currentImg);
    halfW = m.dw * 0.5;
    halfH = m.dh * 0.5;
    clampPos();
    renderCard();
  }

  function stop() {
    stopped = true;
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
    window.removeEventListener('resize', onResize);
    nextCard = null;
    cardEl.removeAttribute('src');
    cardEl.style.transform = '';
    if (layer._lobbyBounceStop === stop) delete layer._lobbyBounceStop;
  }

  layer._lobbyBounceStop = stop;

  return lobbyBgFetchRanges()
    .then(async r => {
      ranges = r || LOBBY_BG_FALLBACK_RANGES;
      if (stopped) return;
      if (!syncSize()) {
        stop();
        return;
      }
      const first = await loadRandomCard();
      if (stopped) return;
      if (!first) {
        stop();
        return;
      }
      applyCard(first);
      x = cssW * 0.5;
      y = cssH * 0.5;
      clampPos();
      seedMotion();
      lastTs = 0;
      prepareNext();
      window.addEventListener('resize', onResize);
      renderCard();
      rafId = window.requestAnimationFrame(frame);
    });
}

async function initLobbyBackgroundBounce(layer) {
  await startLobbyBackgroundBounce(layer);
}

// ── Lobby modal when visiting without game_id / player_id ────────────────
// Full preset labels live in the HTML <option> markup. The JS only needs
// short labels for compact lobby browser/wait rows.
const LOBBY_PRESET_SHORT_LABELS = {
  current: 'Rotating',
  june2026: 'Rotating',
  base: 'Base Set',
  flamesandfrost: 'Flames+Frost',
  shadowvale: 'Shadowvale',
  crimsonseas: 'Crimson Seas',
  random: 'Random',
  draft: 'Draft',
};

const LOBBY_PRESETS_WITH_EXPANSION_ONLY = new Set([
  'base', 'flamesandfrost', 'shadowvale',
]);

function lobbySupportsExpansionOnly(preset) {
  return LOBBY_PRESETS_WITH_EXPANSION_ONLY.has(preset);
}

function lobbyOptionsShortLabel(lobby) {
  const parts = [];
  const dukeCount = Number(lobby.duke_select_count) || 2;
  if (dukeCount === 3) parts.push('3 dukes');
  if (lobby.expansion_only) parts.push('exp-only');
  return parts.length ? ` • ${parts.join(', ')}` : '';
}

// The unlabeled row-1 dropdown ("All …" / "Expansion …") controls whether
// dukes/domains/events are drawn from every set or just the preset's
// expansion. It's only meaningful for the expansion-capable presets; for the
// others we force it back to "all" and disable it.
function syncPoolControl(preset, selectEl, expansionOnly, ownerEnabled) {
  if (!selectEl) return;
  const supported = lobbySupportsExpansionOnly(preset);
  selectEl.value = (supported && expansionOnly) ? 'expansion' : 'all';
  selectEl.disabled = !ownerEnabled || !supported;
}

function syncPresetWarning(preset, warningEl) {
  if (!warningEl) return;
  warningEl.hidden = preset !== 'crimsonseas';
}

// ── Draft mode client state ──────────────────────────────────────────────────
let _draftPhaseKey = '';      // 'agents', 'monsters', 'starters', or 'citizens_1' etc
let _draftMonsterVotes = [];  // area names the player has locally selected (up to 5)
let _draftStarterVote = null; // starter_id the player has locally selected
let _draftCitizenVote = null; // citizen_id the player has locally selected
let _draftAgentsVote = null;  // true = yes, false = no
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
  if (draft.phase === 'agents') return 'agents';
  if (draft.phase === 'monsters') return 'monsters';
  if (draft.phase === 'starters') return 'starters';
  if (draft.phase === 'citizens') return `citizens_${draft.current_roll}`;
  return '';
}

function _draftHasServerVote(draft) {
  if (!draft) return false;
  if (draft.phase === 'agents') return draft.my_agents_vote != null;
  if (draft.phase === 'monsters') return !!(draft.my_monster_votes && draft.my_monster_votes.length > 0);
  if (draft.phase === 'starters') return draft.my_starter_vote != null;
  if (draft.phase === 'citizens') return draft.my_citizen_vote != null;
  return false;
}

function _syncDraftVoteFromServer(draft) {
  if (!_draftHasServerVote(draft)) return;
  if (draft.phase === 'agents') {
    _draftAgentsVote = draft.my_agents_vote;
  } else if (draft.phase === 'monsters') {
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

// ── Preset card-preview modal ────────────────────────────────────────────────
// Clicking the preset label in a lobby opens a near-fullscreen overlay that
// lists every card the chosen preset can put in play: the deterministic
// selections plus the full candidate pools that are dealt at random. Data
// comes from GET /api/lobby/preset-preview (see preset_preview.py).

const PRESET_PREVIEW_SELECTION_LABELS = {
  fixed: 'Always dealt',
  random: 'Random pool',
  draft: 'Drafted',
  mixed: 'Mixed',
};

let _presetPreviewReqToken = 0;

function _closePresetPreview() {
  const existing = document.getElementById('preset-preview-overlay');
  if (existing) existing.remove();
  document.removeEventListener('keydown', _presetPreviewKeydown);
}

function _presetPreviewKeydown(e) {
  if (e.key === 'Escape') _closePresetPreview();
}

function _presetPreviewCardTile(card) {
  const tile = document.createElement('div');
  tile.className = 'preset-preview-card';
  if (card.extra_5p) tile.classList.add('preset-preview-card--extra-5p');
  const img = document.createElement('img');
  img.src = `/card-image/${card.kind}/${card.id}`;
  img.alt = card.name || '';
  img.loading = 'lazy';
  tile.appendChild(img);
  if (card.extra_5p) {
    const badge = document.createElement('span');
    badge.className = 'preset-preview-card-badge';
    badge.textContent = '5P';
    badge.title = 'Only dealt in 5-player games';
    tile.appendChild(badge);
  }
  const label = document.createElement('div');
  label.className = 'preset-preview-card-label';
  label.textContent = card.name || '';
  label.title = card.name || '';
  tile.appendChild(label);
  return tile;
}

function _presetPreviewRenderSection(section) {
  const wrap = document.createElement('section');
  wrap.className = 'preset-preview-section';

  const head = document.createElement('div');
  head.className = 'preset-preview-section-head';
  const title = document.createElement('h3');
  title.className = 'preset-preview-section-title';
  title.textContent = section.title;
  head.appendChild(title);
  const badge = document.createElement('span');
  badge.className = `preset-preview-badge preset-preview-badge--${section.selection || 'random'}`;
  badge.textContent = PRESET_PREVIEW_SELECTION_LABELS[section.selection] || 'Pool';
  head.appendChild(badge);
  wrap.appendChild(head);

  if (section.note) {
    const note = document.createElement('p');
    note.className = 'preset-preview-section-note';
    note.textContent = section.note;
    wrap.appendChild(note);
  }

  if (Array.isArray(section.groups)) {
    section.groups.forEach(group => {
      const groupEl = document.createElement('div');
      groupEl.className = 'preset-preview-group';
      const gLabel = document.createElement('div');
      gLabel.className = 'preset-preview-group-label';
      gLabel.textContent = group.label;
      groupEl.appendChild(gLabel);
      const grid = document.createElement('div');
      grid.className = 'preset-preview-grid';
      (group.cards || []).forEach(c => grid.appendChild(_presetPreviewCardTile(c)));
      groupEl.appendChild(grid);
      wrap.appendChild(groupEl);
    });
  } else {
    const grid = document.createElement('div');
    grid.className = 'preset-preview-grid';
    (section.cards || []).forEach(c => grid.appendChild(_presetPreviewCardTile(c)));
    wrap.appendChild(grid);
  }

  return wrap;
}

async function openPresetPreview(preset, opts = {}) {
  _closePresetPreview();
  const token = ++_presetPreviewReqToken;

  const overlay = document.createElement('div');
  overlay.id = 'preset-preview-overlay';
  overlay.className = 'preset-preview-overlay';
  overlay.addEventListener('click', e => { if (e.target === overlay) _closePresetPreview(); });

  const panel = document.createElement('div');
  panel.className = 'preset-preview-panel';

  const header = document.createElement('div');
  header.className = 'preset-preview-header';
  const heading = document.createElement('h2');
  heading.className = 'preset-preview-heading';
  heading.textContent = `${lobbyPresetShortLabel(preset)} — card preview`;
  header.appendChild(heading);
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'preset-preview-close';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', _closePresetPreview);
  header.appendChild(closeBtn);
  panel.appendChild(header);

  const body = document.createElement('div');
  body.className = 'preset-preview-body';
  const loading = document.createElement('p');
  loading.className = 'preset-preview-status';
  loading.textContent = 'Loading cards…';
  body.appendChild(loading);
  panel.appendChild(body);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  document.addEventListener('keydown', _presetPreviewKeydown);

  const params = new URLSearchParams({ preset });
  if (opts.expansionOnly) params.set('expansion_only', 'true');
  if (opts.players) params.set('players', String(opts.players));
  if (opts.dukeSelectCount) params.set('duke_select_count', String(opts.dukeSelectCount));

  try {
    const res = await fetch(`/api/lobby/preset-preview?${params.toString()}`);
    const data = await res.json().catch(() => ({}));
    if (token !== _presetPreviewReqToken) return;
    if (!res.ok) {
      const detail = data.detail != null ? String(data.detail) : res.statusText;
      throw new Error(detail || 'Preview request failed');
    }
    heading.textContent = `${data.label || lobbyPresetShortLabel(preset)} — card preview`;
    body.innerHTML = '';
    (data.sections || []).forEach(section => body.appendChild(_presetPreviewRenderSection(section)));
    if (!(data.sections || []).length) {
      const empty = document.createElement('p');
      empty.className = 'preset-preview-status';
      empty.textContent = 'No cards found for this preset.';
      body.appendChild(empty);
    }
  } catch (err) {
    if (token !== _presetPreviewReqToken) return;
    body.innerHTML = '';
    const errEl = document.createElement('p');
    errEl.className = 'preset-preview-status preset-preview-status--error';
    errEl.textContent = `Could not load preview: ${err.message || err}`;
    body.appendChild(errEl);
  }
}

// ── Active games / spectate dialog ───────────────────────────────────────────
// Clicking the "N active games" text in the lobby footer opens this overlay,
// which lists every live game with light metadata (players, turn/phase, whose
// turn it is) and a Spectate button. Spectating is just the game URL with no
// player_id, so the button navigates to `/?game_id=<id>`.
const ACTIVE_GAME_PHASE_LABELS = {
  roll: 'Roll phase',
  harvest: 'Harvest phase',
  action: 'Action phase',
  cleanup: 'Cleanup',
  setup: 'Setup',
  game_over: 'Game over',
};

function _closeActiveGamesDialog() {
  const existing = document.getElementById('active-games-overlay');
  if (existing) existing.remove();
  document.removeEventListener('keydown', _activeGamesKeydown);
}

function _activeGamesKeydown(e) {
  if (e.key === 'Escape') _closeActiveGamesDialog();
}

function _activeGamePhaseLabel(phase) {
  return ACTIVE_GAME_PHASE_LABELS[phase] || (phase ? String(phase) : '');
}

function _renderActiveGameRow(game) {
  const row = document.createElement('li');
  row.className = 'active-games-row';

  const info = document.createElement('div');
  info.className = 'active-games-info';

  const title = document.createElement('div');
  title.className = 'active-games-title';
  const preset = lobbyPresetShortLabel(game.preset);
  const pc = Number(game.player_count) || (game.players || []).length;
  title.textContent = `${preset} • ${pc} player${pc === 1 ? '' : 's'}`;
  info.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'active-games-meta';
  const bits = [];
  if (game.turn_number) bits.push(`Turn ${game.turn_number}`);
  const phaseLabel = _activeGamePhaseLabel(game.phase);
  if (phaseLabel) bits.push(phaseLabel);
  if (game.active_player_name) bits.push(`${truncateLobbyName(game.active_player_name, 12)}'s turn`);
  meta.textContent = bits.join(' • ');
  info.appendChild(meta);

  const roster = (game.players || []).map(n => truncateLobbyName(n, 10)).join(', ');
  if (roster) {
    const rosterEl = document.createElement('div');
    rosterEl.className = 'active-games-roster';
    rosterEl.textContent = roster;
    info.appendChild(rosterEl);
  }

  row.appendChild(info);

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'lobby-btn lobby-btn-primary active-games-spectate-btn';
  btn.textContent = 'Spectate';
  btn.addEventListener('click', () => {
    window.location.href = `/?game_id=${encodeURIComponent(game.game_id)}`;
  });
  row.appendChild(btn);

  if (typeof VCK_REJOIN !== 'undefined' && VCK_REJOIN.openRejoinPrompt) {
    const rejoinBtn = document.createElement('button');
    rejoinBtn.type = 'button';
    rejoinBtn.className = 'lobby-btn lobby-btn-ghost active-games-rejoin-btn';
    rejoinBtn.textContent = 'Rejoin';
    rejoinBtn.addEventListener('click', () => {
      _closeActiveGamesDialog();
      VCK_REJOIN.openRejoinPrompt(game.game_id);
    });
    row.appendChild(rejoinBtn);
  }

  return row;
}

async function openActiveGamesDialog() {
  _closeActiveGamesDialog();

  const overlay = document.createElement('div');
  overlay.id = 'active-games-overlay';
  overlay.className = 'active-games-overlay';
  overlay.addEventListener('click', e => { if (e.target === overlay) _closeActiveGamesDialog(); });

  const panel = document.createElement('div');
  panel.className = 'active-games-panel';

  const header = document.createElement('div');
  header.className = 'active-games-header';
  const heading = document.createElement('h2');
  heading.className = 'active-games-heading';
  heading.textContent = 'Active games';
  header.appendChild(heading);
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'active-games-close';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', _closeActiveGamesDialog);
  header.appendChild(closeBtn);
  panel.appendChild(header);

  const body = document.createElement('div');
  body.className = 'active-games-body';
  const loading = document.createElement('p');
  loading.className = 'active-games-status';
  loading.textContent = 'Loading games…';
  body.appendChild(loading);
  panel.appendChild(body);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  document.addEventListener('keydown', _activeGamesKeydown);

  try {
    const res = await fetch('/api/lobby/active-games');
    const data = await res.json().catch(() => ({}));
    if (!document.getElementById('active-games-overlay')) return;
    if (!res.ok) {
      const detail = data.detail != null ? String(data.detail) : res.statusText;
      throw new Error(detail || 'Request failed');
    }
    body.innerHTML = '';
    const list = Array.isArray(data.games) ? data.games : [];
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'active-games-status';
      empty.textContent = 'No active games right now.';
      body.appendChild(empty);
      return;
    }
    const ul = document.createElement('ul');
    ul.className = 'active-games-list';
    list.forEach(g => ul.appendChild(_renderActiveGameRow(g)));
    body.appendChild(ul);
  } catch (err) {
    if (!document.getElementById('active-games-overlay')) return;
    body.innerHTML = '';
    const errEl = document.createElement('p');
    errEl.className = 'active-games-status active-games-status--error';
    errEl.textContent = `Could not load games: ${err.message || err}`;
    body.appendChild(errEl);
  }
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
    _draftAgentsVote = null;
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
    if (lr && lr.phase === 'agents') {
      lastResultEl.textContent = lr.include_agents ? 'Agents: Yes' : 'Agents: No';
    } else if (lr && lr.phase === 'monsters' && lr.selected && lr.selected.length) {
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

  if (draft.phase === 'agents') {
    if (titleEl) titleEl.textContent = 'Use Agents?';
    if (progressEl) progressEl.textContent = 'Optional module vote';
    if (instrEl) instrEl.textContent = _draftVoteSubmitted
      ? 'Vote submitted — waiting for others or timer'
      : 'Should this game include the Agents module?';
    _renderAgentsVote(draft, gridEl, selfId);
    _updateDraftAgentsFooter(draft, statusEl, voteBtn, selfId);
  } else if (draft.phase === 'monsters') {
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

function _renderAgentsVote(draft, gridEl, selfId) {
  gridEl.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'draft-agents-vote';

  const desc = document.createElement('p');
  desc.className = 'draft-agents-desc';
  desc.textContent = 'Agents are an optional module: four face-up cards you may Engage during your turn for their listed effect.';
  wrap.appendChild(desc);

  const choices = document.createElement('div');
  choices.className = 'draft-agents-choices';

  [
    { value: true, label: 'Yes — include Agents' },
    { value: false, label: 'No — skip Agents' },
  ].forEach(opt => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'draft-agents-choice';
    if (_draftAgentsVote === opt.value) btn.classList.add('draft-agents-choice--selected');
    if (_draftVoteSubmitted) btn.disabled = true;
    btn.textContent = opt.label;
    const yesVotes = draft.agents_yes_votes || 0;
    const noVotes = draft.agents_no_votes || 0;
    if (opt.value === true && yesVotes > 0) btn.textContent += ` (${yesVotes})`;
    if (opt.value === false && noVotes > 0) btn.textContent += ` (${noVotes})`;
    if (!_draftVoteSubmitted) {
      btn.addEventListener('click', () => {
        _draftAgentsVote = opt.value;
        _renderAgentsVote(draft, gridEl, selfId);
        const statusEl = document.getElementById('draft-vote-status');
        const voteBtn = document.getElementById('draft-vote-btn');
        _updateDraftAgentsFooter(draft, statusEl, voteBtn, selfId);
      });
    }
    choices.appendChild(btn);
  });

  wrap.appendChild(choices);
  gridEl.appendChild(wrap);
}

function _updateDraftAgentsFooter(draft, statusEl, voteBtn, selfId) {
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
    voteBtn.disabled = _draftVoteSubmitted || _draftAgentsVote == null || !draft.am_participant;
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
  const createDukeSelect = document.getElementById('lobby-create-duke-select');
  const createPoolSelect = document.getElementById('lobby-create-pool');
  const createPresetWarning = document.getElementById('lobby-create-preset-warning');
  const createBtn = document.getElementById('lobby-create-btn');
  const backToNameBtn = document.getElementById('lobby-back-to-name-btn');
  const lobbySheet = overlay ? overlay.querySelector('.lobby-sheet') : null;
  const waitMetaEl = document.getElementById('lobby-wait-meta');
  const presetSelect = document.getElementById('lobby-preset-select');
  const minPlayersSelect = document.getElementById('lobby-min-players-select');
  const dukeSelect = document.getElementById('lobby-duke-select');
  const poolSelect = document.getElementById('lobby-pool-select');
  const presetWarning = document.getElementById('lobby-preset-warning');
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
      // Covers both an owner closing/emptying the lobby and this player being
      // kicked by the owner — in either case we're no longer a member.
      showLobbyError('You are no longer in that lobby. Pick another or create a new one.');
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
      metaEl.innerHTML = '';
      metaEl.appendChild(
        document.createTextNode(`${lc} open lobb${lc === 1 ? 'y' : 'ies'} • `),
      );
      const gamesLabel = `${gc} active game${gc === 1 ? '' : 's'}`;
      if (gc > 0) {
        const gamesLink = document.createElement('button');
        gamesLink.type = 'button';
        gamesLink.className = 'lobby-active-games-link';
        gamesLink.textContent = gamesLabel;
        gamesLink.title = 'View active games and spectate';
        gamesLink.addEventListener('click', () => openActiveGamesDialog());
        metaEl.appendChild(gamesLink);
      } else {
        metaEl.appendChild(document.createTextNode(gamesLabel));
      }
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
      primary.textContent = `${lobbyPresetShortLabel(lb.preset)} • ${minLabel}${lobbyOptionsShortLabel(lb)}`;
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
      waitMetaEl.innerHTML = '';
      waitMetaEl.appendChild(document.createTextNode(`${role} • `));
      const presetLink = document.createElement('button');
      presetLink.type = 'button';
      presetLink.className = 'lobby-preset-link';
      presetLink.textContent = lobbyPresetShortLabel(lobby.preset);
      presetLink.title = 'Preview every card in this set';
      presetLink.addEventListener('click', () => openPresetPreview(lobby.preset, {
        expansionOnly: !!lobby.expansion_only,
        players: (lobby.members || []).length || 4,
        dukeSelectCount: Number(lobby.duke_select_count) || 2,
      }));
      waitMetaEl.appendChild(presetLink);
      waitMetaEl.appendChild(document.createTextNode(` • ${floorLabel}${lobbyOptionsShortLabel(lobby)}`));
    }
    if (presetSelect) {
      presetSelect.value = lobby.preset || 'current';
      presetSelect.disabled = !isOwner;
    }
    if (minPlayersSelect) {
      minPlayersSelect.value = String(minPlayers);
      minPlayersSelect.disabled = !isOwner;
    }
    if (dukeSelect) {
      dukeSelect.value = String(Number(lobby.duke_select_count) || 2);
      dukeSelect.disabled = !isOwner;
    }
    syncPoolControl(
      lobby.preset || 'current',
      poolSelect,
      lobby.expansion_only,
      isOwner,
    );
    syncPresetWarning(lobby.preset || 'current', presetWarning);
    // A poll/broadcast-driven re-render destroys and recreates the inline
    // rename <input>, which would silently steal focus and reset the caret
    // mid-keystroke. Capture the live focus + selection so we can restore it
    // onto the freshly-built input below.
    const activeEl = document.activeElement;
    const renameWasFocused =
      editingSelfName &&
      activeEl &&
      activeEl.classList &&
      activeEl.classList.contains('lobby-name-edit-input');
    const renameSelStart = renameWasFocused ? activeEl.selectionStart : null;
    const renameSelEnd = renameWasFocused ? activeEl.selectionEnd : null;
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
      const rightGroup = document.createElement('span');
      rightGroup.className = 'lobby-p-right';
      const stSpan = document.createElement('span');
      stSpan.className = 'lobby-p-status' + (m.is_ready ? ' is-ready' : '');
      stSpan.textContent = m.is_ready ? 'Ready' : 'Waiting';
      rightGroup.appendChild(stSpan);
      // Owner-only: let the owner remove a stuck member who never readies up.
      if (isOwner && !isSelf) {
        const kickBtn = document.createElement('button');
        kickBtn.type = 'button';
        kickBtn.className = 'lobby-icon-btn lobby-kick-btn';
        const who = m.name || 'player';
        kickBtn.setAttribute('aria-label', `Remove ${who} from lobby`);
        kickBtn.title = `Remove ${who} from lobby`;
        kickBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false" fill="currentColor"><path d="M4.646 4.646a.5.5 0 0 1 .708 0L8 7.293l2.646-2.647a.5.5 0 0 1 .708.708L8.707 8l2.647 2.646a.5.5 0 0 1-.708.708L8 8.707l-2.646 2.647a.5.5 0 0 1-.708-.708L7.293 8 4.646 5.354a.5.5 0 0 1 0-.708z"/></svg>';
        kickBtn.addEventListener('click', () => kickMember(m.player_id, who));
        rightGroup.appendChild(kickBtn);
      }
      li.appendChild(rightGroup);
      playerList.appendChild(li);
    });
    if (focusInputEl && renameJustBegan) {
      renameJustBegan = false;
      setTimeout(() => {
        try { focusInputEl.focus(); focusInputEl.select(); } catch (_) { /* ignore */ }
      }, 0);
    } else if (focusInputEl && renameWasFocused) {
      // Re-render landed while the user was mid-edit: put focus back on the
      // new input and restore the caret/selection so polling never interrupts
      // typing.
      try {
        focusInputEl.focus();
        if (renameSelStart != null) {
          focusInputEl.setSelectionRange(renameSelStart, renameSelEnd);
        }
      } catch (_) { /* ignore */ }
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

  async function kickMember(targetId, targetName) {
    const pid = lobbyPlayerId || vckStoredPlayerId();
    if (!pid || !targetId) return;
    showLobbyError('');
    try {
      const res = await fetch('/api/lobby/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: pid, target_player_id: targetId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Kick failed');
      }
      // The server broadcasts the updated roster; nothing else to do here.
    } catch (e) {
      showLobbyError(e.message || `Could not remove ${targetName || 'player'}.`);
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
      // Send our persistent client id so the server can recognise a rejoin
      // (e.g. after hitting "back") and refresh our existing member instead
      // of spawning a duplicate that can never ready up.
      const existingPid = lobbyPlayerId || vckStoredPlayerId() || '';
      const res = await fetch('/api/lobby/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, lobby_id: lobbyId, player_id: existingPid || null }),
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
      const dukeSelectCount = Number(createDukeSelect && createDukeSelect.value) || 2;
      const expansionOnly = !!(
        createPoolSelect
        && createPoolSelect.value === 'expansion'
        && lobbySupportsExpansionOnly(preset)
      );
      const res = await fetch('/api/lobby/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          preset,
          min_players: minPlayers,
          duke_select_count: dukeSelectCount,
          expansion_only: expansionOnly,
        }),
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
        const stillExpansion = poolSelect
          && poolSelect.value === 'expansion'
          && lobbySupportsExpansionOnly(preset);
        syncPoolControl(preset, poolSelect, stillExpansion, true);
        syncPresetWarning(preset, presetWarning);
      } catch (e) {
        showLobbyError(e.message || 'Could not change preset.');
      }
    });
  }

  if (poolSelect) {
    poolSelect.addEventListener('change', async () => {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) return;
      const preset = presetSelect ? (presetSelect.value || 'current') : 'current';
      if (!lobbySupportsExpansionOnly(preset)) {
        poolSelect.value = 'all';
        return;
      }
      showLobbyError('');
      try {
        const res = await fetch('/api/lobby/expansion_only', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            player_id: pid,
            expansion_only: poolSelect.value === 'expansion',
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Card pool update failed');
        }
      } catch (e) {
        showLobbyError(e.message || 'Could not change card pool setting.');
      }
    });
  }

  if (dukeSelect) {
    dukeSelect.addEventListener('change', async () => {
      const pid = lobbyPlayerId || vckStoredPlayerId();
      if (!pid) return;
      const dukeSelectCount = Number(dukeSelect.value) || 2;
      showLobbyError('');
      try {
        const res = await fetch('/api/lobby/duke_select_count', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            player_id: pid,
            duke_select_count: dukeSelectCount,
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail != null ? String(data.detail) : res.statusText || 'Duke count update failed');
        }
      } catch (e) {
        showLobbyError(e.message || 'Could not change duke count.');
      }
    });
  }

  if (createPresetSelect) {
    createPresetSelect.addEventListener('change', () => {
      const preset = createPresetSelect.value || 'current';
      const stillExpansion = createPoolSelect
        && createPoolSelect.value === 'expansion'
        && lobbySupportsExpansionOnly(preset);
      syncPoolControl(preset, createPoolSelect, stillExpansion, true);
      syncPresetWarning(preset, createPresetWarning);
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
      if (draft.phase === 'agents') {
        if (_draftAgentsVote == null) {
          showLobbyError('Choose Yes or No before voting.');
          return;
        }
        vote = _draftAgentsVote;
      } else if (draft.phase === 'monsters') {
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

  if (createPresetSelect) {
    syncPoolControl(createPresetSelect.value || 'current', createPoolSelect, false, true);
    syncPresetWarning(createPresetSelect.value || 'current', createPresetWarning);
  }

  openOverlay();
  showStep('name');
  const bgLayer = document.getElementById('lobby-bg-layer');
  if (bgLayer) initLobbyBackgroundBounce(bgLayer).catch(() => {});
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

if (!CAN_VIEW_GAME) {
  initLobbyModal();
} else {
  if (SPECTATOR) showSpectatorBanner();
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
    if (!CAN_VIEW_GAME) return;
    fetchGameStateFromApi();
  });
  window.addEventListener('resize', () => {
    const zone = document.getElementById('zone-center');
    if (zone) syncBoardTabState(zone);
  });
}
