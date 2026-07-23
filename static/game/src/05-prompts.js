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

// Returns true if a passive poll would clobber UI the player is actively
// using (an open confirm modal, a focused number/text input — e.g. the slay
// payment fields). The poll itself is safe to skip; the next poll tick or
// the next WS push will reconcile.
function passivePollWouldDisruptUi() {
  const confirmModal = document.getElementById('action-confirm-modal');
  if (confirmModal && confirmModal.classList.contains('is-open')) return true;
  const active = document.activeElement;
  if (active && active !== document.body) {
    const tag = (active.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (active.isContentEditable) return true;
  }
  return false;
}

function startPassiveStatePolling() {
  if (passiveStatePollTimer) return;
  passiveStatePollTimer = setInterval(() => {
    if (!CAN_VIEW_GAME) return;
    if (document.hidden) return;
    if (concurrentPollTimer) return;
    if (passivePollWouldDisruptUi()) return;
    fetchGameStateFromApi();
  }, PASSIVE_GAME_POLL_MS);
}

function stopPassiveStatePolling() {
  if (!passiveStatePollTimer) return;
  clearInterval(passiveStatePollTimer);
  passiveStatePollTimer = null;
}

async function fetchGameStateFromApi() {
  if (!CAN_VIEW_GAME) return;
  try {
    const stateUrl = PLAYER_ID
      ? `/api/game/${encodeURIComponent(GAME_ID)}/state?player_id=${encodeURIComponent(PLAYER_ID)}`
      : `/api/game/${encodeURIComponent(GAME_ID)}/state`;
    const res = await fetch(stateUrl);
    if (!res.ok) {
      if (res.status === 404) {
        const payload = await res.json().catch(() => ({}));
        if (clientShouldDropStoredGame(payload)) {
          // A finished game can be reclaimed server-side; keep the cached
          // results on screen and just stop polling instead of redirecting.
          if (gameHasEnded) {
            stopPassiveStatePolling();
            return;
          }
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
      if (gameHasEnded) return false;
      redirectToLobby();
      return false;
    }
    // Duplicate or stale finalize_roll (e.g. second tab, double network delivery): roll already applied.
    const detailStr = typeof detail === 'string' ? detail : '';
    if (
      body?.action_type === 'finalize_roll' &&
      detailStr &&
      /not waiting to finalize/i.test(detailStr)
    ) {
      fetchGameStateFromApi();
      return false;
    }
    window.alert(detail);
    return false;
  }
  if (payload?.game_state) render(payload.game_state);
  else fetchGameStateFromApi();
  return true;
}
// ── Hint button ("what would the Hard bot do?") ───────────────────────────
let hintBtnEl = null;
let hintPanelEl = null;
let hintBusy = false;
let hintShownForKey = '';

function hintStateKey(state) {
  return `${state?.tick_id ?? ''}:${(state?.game_log || []).length}`;
}

function viewerOwesDecision(state) {
  if (!PLAYER_ID || !state || state.phase === 'game_over') return false;
  const ca = state.concurrent_action;
  if (ca && Array.isArray(ca.pending) && ca.pending.some(pid => idsMatch(pid, PLAYER_ID))) {
    return true;
  }
  const req = state.action_required || {};
  return idsMatch(req.id, PLAYER_ID);
}

function ensureHintElements() {
  if (hintBtnEl) return;
  hintBtnEl = document.createElement('button');
  hintBtnEl.type = 'button';
  hintBtnEl.id = 'hint-btn';
  hintBtnEl.className = 'hint-btn';
  hintBtnEl.textContent = '\u{1F4A1} Hint';
  hintBtnEl.title = 'Ask the Hard bot what it would play here';
  hintBtnEl.hidden = true;
  hintBtnEl.addEventListener('click', requestHint);
  document.body.appendChild(hintBtnEl);

  hintPanelEl = document.createElement('div');
  hintPanelEl.id = 'hint-panel';
  hintPanelEl.className = 'hint-panel';
  hintPanelEl.hidden = true;
  hintPanelEl.addEventListener('click', () => { hintPanelEl.hidden = true; });
  document.body.appendChild(hintPanelEl);
}

function syncHintControl(state) {
  ensureHintElements();
  const show = viewerOwesDecision(state) && state?.hints_enabled !== false;
  hintBtnEl.hidden = !show || hintBusy;
  // A hint describes one specific decision point; drop it once the game moved.
  if (!show || (hintShownForKey && hintShownForKey !== hintStateKey(state))) {
    hintPanelEl.hidden = true;
    hintShownForKey = '';
  }
}

function renderHintPanel(lines) {
  hintPanelEl.innerHTML = '';
  lines.forEach((line, i) => {
    const p = document.createElement('div');
    p.className = i === 0 ? 'hint-panel-main' : 'hint-panel-alt';
    p.textContent = line;
    hintPanelEl.appendChild(p);
  });
  hintPanelEl.hidden = false;
}

async function requestHint() {
  if (hintBusy || !PLAYER_ID) return;
  hintBusy = true;
  hintBtnEl.disabled = true;
  hintBtnEl.textContent = '\u{1F4A1} Thinking…';
  try {
    const res = await fetch(
      `/api/game/${encodeURIComponent(GAME_ID)}/hint?player_id=${encodeURIComponent(PLAYER_ID)}`
    );
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = payload?.detail || res.statusText || 'Hint unavailable';
      renderHintPanel([String(detail)]);
      hintShownForKey = hintStateKey(latestGameState);
      return;
    }
    const lines = [`Bot suggests: ${payload.hint || '?'}`];
    if (payload.only_move) {
      lines.push('(only legal move)');
    } else {
      (payload.candidates || []).slice(1).forEach(c => {
        lines.push(`alt: ${c.label} (${c.visit_pct}%)`);
      });
    }
    renderHintPanel(lines);
    hintShownForKey = hintStateKey(latestGameState);
  } catch (e) {
    renderHintPanel(['Hint failed — try again.']);
  } finally {
    hintBusy = false;
    hintBtnEl.disabled = false;
    hintBtnEl.textContent = '\u{1F4A1} Hint';
    if (latestGameState) syncHintControl(latestGameState);
  }
}

// ── Training-mode move feedback ───────────────────────────────────────────
let feedbackPanelEl = null;
let feedbackShownSeq = -1;

const FEEDBACK_STYLES = {
  perfect: { icon: '✅', title: 'Perfect!', cls: 'is-perfect' },
  great: { icon: '\u{1F44D}', title: 'Great move', cls: 'is-great' },
  fine: { icon: '\u{1F44C}', title: 'Fine move', cls: 'is-fine' },
  blunder: { icon: '❌', title: 'Blunder', cls: 'is-blunder' },
  unrated: { icon: '❓', title: 'Unrated move', cls: 'is-unrated' },
};

function ensureFeedbackPanel() {
  if (feedbackPanelEl) return;
  feedbackPanelEl = document.createElement('div');
  feedbackPanelEl.id = 'training-feedback';
  feedbackPanelEl.className = 'training-feedback';
  feedbackPanelEl.hidden = true;
  feedbackPanelEl.addEventListener('click', () => { feedbackPanelEl.hidden = true; });
  document.body.appendChild(feedbackPanelEl);
}

function syncTrainingFeedback(state) {
  ensureFeedbackPanel();
  const fb = state && state.training_mode ? state.move_feedback : null;
  if (!fb) {
    feedbackPanelEl.hidden = true;
    return;
  }
  if ((fb.seq ?? 0) === feedbackShownSeq && feedbackPanelEl.hidden) {
    return; // user dismissed this one; don't resurrect it on re-renders
  }
  const style = FEEDBACK_STYLES[fb.category] || FEEDBACK_STYLES.unrated;
  const alreadyShown = (fb.seq ?? 0) === feedbackShownSeq && !feedbackPanelEl.hidden;
  if (alreadyShown) return;
  feedbackShownSeq = fb.seq ?? 0;
  feedbackPanelEl.className = `training-feedback ${style.cls}`;
  feedbackPanelEl.innerHTML = '';
  const head = document.createElement('div');
  head.className = 'training-feedback-head';
  head.textContent = `${style.icon} ${style.title}`;
  feedbackPanelEl.appendChild(head);
  const body = document.createElement('div');
  body.className = 'training-feedback-body';
  if (fb.category === 'perfect') {
    body.textContent = `${fb.your_label} — exactly what the bot would play.`;
  } else if (fb.category === 'unrated') {
    body.textContent = `${fb.your_label} — outside the bot's analyzed lines.`;
  } else {
    const delta = fb.delta_pct != null ? `−${fb.delta_pct}% win chance` : '';
    body.textContent = `${fb.your_label} (${delta}). Bot preferred: ${fb.bot_label}.`;
  }
  feedbackPanelEl.appendChild(body);
  feedbackPanelEl.hidden = false;
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

// Compact "current resources" strip for resource-affecting prompts. Listed in
// turn order so the table reads top-to-bottom in seat order; the viewer's row
// is highlighted so they can scan their own supply quickly. Other prompts
// (duke select, flip citizen, monster strength bump) deliberately skip this.
function makePromptResourcesPanel(state) {
  const players = Array.isArray(state?.player_list) ? state.player_list : [];
  const panel = mk('prompt-modal-resources');

  const title = mk('prompt-modal-resources-title');
  title.textContent = 'Resources';
  panel.appendChild(title);

  const list = mk('prompt-modal-resources-list');
  players.forEach(p => {
    const row = mk('prompt-modal-resources-row');
    if (idsMatch(p.player_id, PLAYER_ID)) row.classList.add('is-you');

    const nameWrap = mk('prompt-modal-resources-name');
    const nm = document.createElement('span');
    nm.className = 'prompt-modal-resources-name-text';
    nm.textContent = (p.name || p.player_id || 'Player').toString();
    nameWrap.appendChild(nm);
    if (idsMatch(p.player_id, PLAYER_ID)) {
      const tag = mk('prompt-modal-resources-you-tag');
      tag.textContent = 'You';
      nameWrap.appendChild(tag);
    }
    row.appendChild(nameWrap);

    const pills = mk('prompt-modal-resources-pills');
    pills.appendChild(makeResourceScorePill('gold', p.gold_score, 'Gold', TABLEAU_RESOURCE_ICONS.gold));
    pills.appendChild(makeResourceScorePill('strength', p.strength_score, 'Strength', TABLEAU_RESOURCE_ICONS.strength));
    pills.appendChild(makeResourceScorePill('magic', p.magic_score, 'Magic', TABLEAU_RESOURCE_ICONS.magic));
    if (crimsonSeasEnabled(state)) {
      pills.appendChild(makeResourceScorePill('map', p.map_score, 'Map', TABLEAU_RESOURCE_ICONS.map));
    }
    pills.appendChild(makeVpScorePill(p.victory_score));
    row.appendChild(pills);

    list.appendChild(row);
  });
  panel.appendChild(list);

  return panel;
}

function appendPromptResourcesPanel(body, state) {
  if (!body) return;
  body.appendChild(makePromptResourcesPanel(state));
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
  // Mirrors the engine's _parse_roll_set_one_die_kv: three modes
  // (target=N | subtract=N | add=N) and an optional cost spec.
  // Emits one entry per effect tagged with `mode`; the per-die candidate
  // values are computed in listRollSetOneDieOptions.
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
    const domainName = (d?.name || 'Domain').toString();
    const domainId = (d?.domain_id != null) ? Number(d.domain_id) : null;
    const costSpec = (kv.cost || '').toString().trim().toLowerCase();
    if (kv.target) {
      const target = Number(kv.target);
      if (Number.isFinite(target) && target >= 1 && target <= 6) {
        out.push({ domainName, domainId, mode: 'target', target, costSpec });
      }
      return;
    }
    for (const modeKey of ['subtract', 'add']) {
      if (!kv[modeKey]) continue;
      const delta = Number(kv[modeKey]);
      if (Number.isFinite(delta) && delta > 0) {
        out.push({ domainName, domainId, mode: modeKey, delta, costSpec });
      }
      return;
    }
  });
  return out;
}

function rollEffectCostGold(player, costSpec) {
  const spec = (costSpec || '').toString().trim().toLowerCase();
  // Empty cost = free (e.g. Palace of the Dawn's `subtract=1`).
  if (!spec) return 0;
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

function listRollSetOneDieOptions(player, rolled1, rolled2, turnNumber, opts) {
  // `opts.budgetGold` (optional): override the affordability check (used by
  // stage-2 rendering after a first modifier has been staged so we only show
  // second-modifier options the player can still afford on top of the first).
  // `opts.excludeDomainId` (optional): skip effects sourced from this domain
  // (used by stage 2 to enforce the engine's distinct-source rule).
  // `opts.die` (optional): restrict to options that modify only this die
  // number (used by stage 2 so the second click always lands on the
  // unmanipulated die).
  const effects = parseRollSetOneDieEffects(player, turnNumber);
  const opts_ = opts || {};
  const budget = Number.isFinite(Number(opts_.budgetGold))
    ? Number(opts_.budgetGold)
    : Number(player?.gold_score || 0);
  const excludeDomainId = (opts_.excludeDomainId != null) ? Number(opts_.excludeDomainId) : null;
  const onlyDie = (opts_.die === 1 || opts_.die === 2) ? opts_.die : null;
  const options = [];
  // `target` in the returned option is the resolved FINAL die value after
  // applying this effect, regardless of which parser mode produced it, so
  // renderers can treat all options uniformly.
  const pushIfValid = (die, rolled, candidate, e, costGold) => {
    if (!Number.isFinite(candidate)) return;
    if (candidate < 1 || candidate > 6) return;
    if (Number(candidate) === Number(rolled)) return;
    if (onlyDie !== null && die !== onlyDie) return;
    options.push({
      die,
      target: candidate,
      costGold,
      domainName: e.domainName,
      domainId: e.domainId,
    });
  };
  effects.forEach(e => {
    if (excludeDomainId !== null && Number(e.domainId) === excludeDomainId) return;
    const costGold = rollEffectCostGold(player, e.costSpec);
    if (costGold === null || budget < costGold) return;
    if (e.mode === 'target') {
      pushIfValid(1, rolled1, Number(e.target), e, costGold);
      pushIfValid(2, rolled2, Number(e.target), e, costGold);
    } else if (e.mode === 'subtract') {
      pushIfValid(1, rolled1, Number(rolled1) - Number(e.delta), e, costGold);
      pushIfValid(2, rolled2, Number(rolled2) - Number(e.delta), e, costGold);
    } else if (e.mode === 'add') {
      pushIfValid(1, rolled1, Number(rolled1) + Number(e.delta), e, costGold);
      pushIfValid(2, rolled2, Number(rolled2) + Number(e.delta), e, costGold);
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
    resetFinalizeRollStaging();
  }
}

// Two-stage flow state for the finalize_roll modal. The modal lets the
// active player optionally apply up to one roll modifier per die (engine
// rule: each owned domain can only fire once per roll phase, so the two
// modifiers must come from different cards). Stage 1 shows every legal
// (die, modifier) option. Picking one stashes it in `stagedFirstModifier`
// and re-renders into stage 2, which shows: the staged choice, a Confirm
// button (submits using just the first modifier), and another row of
// options scoped to the OTHER die / OTHER source domain / remaining gold
// budget. Picking a stage-2 option submits both modifiers at once.
let stagedFirstModifier = null;
let stagedFirstModifierForRoll = null;

function resetFinalizeRollStaging() {
  stagedFirstModifier = null;
  stagedFirstModifierForRoll = null;
}

function stagedRollKey(rolled1, rolled2) {
  return `${rolled1},${rolled2}`;
}

/** True when the active player owns Twilight Palace (no cooldown) and hasn't re-rolled yet. */
function hasTwilightPalaceReroll(state) {
  const req = state?.action_required || {};
  if ((req.action || '').toString() !== 'finalize_roll') return false;
  if (state?.pending_reroll_twilight_used) return false;
  const reqId = (req.id || '').toString();
  if (!idsMatch(reqId, PLAYER_ID)) return false;
  const player = playerById(state, reqId);
  if (!player) return false;
  const tn = Number(state?.turn_number);
  return hasActionEffectFlag(player, 'roll.reroll_one_die', tn);
}

function hasBloodMoonReroll(state) {
  const req = state?.action_required || {};
  if ((req.action || '').toString() !== 'finalize_roll') return false;
  if (state?.pending_reroll_blood_moon_used) return false;
  const reqId = (req.id || '').toString();
  if (!idsMatch(reqId, PLAYER_ID)) return false;
  const player = playerById(state, reqId);
  if (!player) return false;
  if (Number(player?.magic_score || 0) < 2) return false;
  const tn = Number(state?.turn_number);
  return hasActionEffectFlag(player, 'roll.reroll_both_dice_pay_magic_2', tn);
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
  if (hasTwilightPalaceReroll(state)) return;
  if (hasBloodMoonReroll(state)) return;
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
  if (t === 'p') return 'Map';
  if (t === 't') return 'Tome';
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
    if (!(tl === 'g' || tl === 's' || tl === 'm' || tl === 'v' || tl === 'p' || tl === 't' || tl.startsWith('citizens.'))) continue;
    options.push({ token, amount });
    if (options.length >= 3) break;
  }
  return options;
}

function resourceSpecLabel(spec) {
  const raw = (spec || '').toString().trim().toLowerCase();
  const m = /^(g|s|m|v|vp|p)\s*:\s*(\d+)$/.exec(raw);
  if (!m) return raw || '';
  const n = Number(m[2]);
  const k = m[1] === 'vp' ? 'v' : m[1];
  const word = k === 'g' ? 'gold' : k === 's' ? 'strength' : k === 'm' ? 'magic' : k === 'p' ? 'map' : 'VP';
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
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'submit_concurrent_action',
          kind: 'choose_duke',
          response: String(id),
        },
        {
          title: 'Keep this Duke?',
          message: `Keep ${name} (#${id}) and discard your other Duke card(s).`,
        },
      );
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

function renderConcurrentChooseRelic(state, concurrent) {
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
    `Starting setup: ${completed.length}/${totalParticipants} relic choice(s) submitted.` +
    (pending.length ? ` Waiting on: ${waitingLabels.join(', ')}.` : '');
  body.appendChild(status);

  if (!isPending) {
    const youDone = !!(PLAYER_ID && completed.some(pid => idsMatch(pid, PLAYER_ID)));
    const line = mk('prompt-modal-note');
    line.textContent = youDone
      ? 'You have already chosen your relic. Waiting on the other player(s).'
      : 'Starting setup is in progress.';
    body.appendChild(line);
    openPromptOverlayShell({
      title: 'Choose your Relic',
      subtitle: null,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const relics = Array.isArray(you?.owned_relics) ? you.owned_relics : [];
  if (!relics.length) {
    body.appendChild(document.createTextNode('No relics found to choose from.'));
    openPromptOverlayShell({
      title: 'Choose your Relic',
      dismissible: false,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const list = mk('prompt-choice-list');
  relics.forEach(r => {
    const id = r?.relic_id;
    const name = r?.name || `Relic #${id}`;
    const cardEl = mk('prompt-choice-card');

    const inner = mk('prompt-choice-card-inner');
    const url = cardImageUrl(r);
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
    const blurb = (r?.passive_effect_text || '').toString().trim();
    if (blurb) {
      const tx = mk('prompt-choice-card-text');
      tx.textContent = blurb;
      main.appendChild(tx);
    }
    const row = mk('prompt-choice-card-actions');
    row.appendChild(promptButton('Keep this relic', () => {
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'submit_concurrent_action',
          kind: 'choose_relic',
          response: String(id),
        },
        {
          title: 'Keep this Relic?',
          message: `Keep ${name} (#${id}) and return your other Relic card(s) to the box.`,
        },
      );
    }));
    main.appendChild(row);
    inner.appendChild(main);
    cardEl.appendChild(inner);
    list.appendChild(cardEl);
  });
  body.appendChild(list);

  openPromptOverlayShell({
    title: 'Choose 1 Relic to keep',
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
  const sourceLabel = (data.source_label || 'Cursed Cavern').toString();

  const buyer = playerById(state, buyerId);
  const buyerTag = buyer?.name || buyerId || '';
  const waitingLabels = pendingPlayerLabels(state, pending);

  const body = mk('prompt-modal-body');

  const status = mk('prompt-modal-note');
  status.textContent =
    `${sourceLabel} — flip one citizen face-down: ${completed.length}/${totalParticipants} player choice(s) submitted.` +
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
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'submit_concurrent_action',
          kind: 'flip_one_citizen',
          response: String(idx),
        },
        {
          title: 'Flip citizen?',
          message: `Flip ${nm} (slot #${idx}) face-down.`,
        },
      );
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

// Event: each player may pay a resource for a bank gain (e.g. Support The Empire).
// A 'wild' cost lets the player pick which resource (g/s/m) to spend.
function renderConcurrentEventSelfConvert(state, concurrent) {
  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
  const isPending = !!(PLAYER_ID && pending.some(pid => idsMatch(pid, PLAYER_ID)));
  const totalParticipants = pending.length + completed.length;
  const data = concurrent.data || {};
  const name = (data.name || 'Event').toString();
  const payKind = (data.pay_kind || 'g').toString();
  const payAmount = Number(data.pay_amount || 0);
  const payLegs = Array.isArray(data.pay_legs) ? data.pay_legs : null;
  const gainKind = (data.gain_kind || 'v').toString();
  const gainAmount = Number(data.gain_amount || 0);
  const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
  const legsLabel = payLegs ? payLegs.map(([k, a]) => `${a} ${labels[k] || k}`).join(' + ') : '';
  const waitingLabels = pendingPlayerLabels(state, pending);

  const body = mk('prompt-modal-body');
  const status = mk('prompt-modal-note');
  status.textContent =
    `${name}: ${completed.length}/${totalParticipants} player choice(s) submitted.` +
    (pending.length ? ` Waiting on: ${waitingLabels.join(', ')}.` : '');
  body.appendChild(status);

  if (!isPending) {
    const youDone = !!(PLAYER_ID && completed.some(pid => idsMatch(pid, PLAYER_ID)));
    const line = mk('prompt-modal-note');
    line.textContent = youDone
      ? 'You already responded. Waiting on other players.'
      : 'You have no pending response in this event.';
    body.appendChild(line);
    openPromptOverlayShell({ title: name, dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  const desc = mk('prompt-modal-note');
  const costText = payLegs
    ? legsLabel
    : `${payAmount} ${payKind === 'wild' ? '(your choice of gold/strength/magic)' : (labels[payKind] || payKind)}`;
  desc.textContent = `Pay ${costText} for ${gainAmount} ${labels[gainKind] || gainKind}?`;
  body.appendChild(desc);

  const post = (response, message) => confirmAndPostGameAction(
    { player_id: PLAYER_ID, action_type: 'submit_concurrent_action', kind: 'event_self_convert', response: String(response) },
    { title: name, message },
  );

  const row = mk('prompt-choice-card-actions');
  if (payLegs) {
    row.appendChild(promptButton(`Pay ${legsLabel}`, () =>
      post('accept', `Pay ${legsLabel} for ${gainAmount} ${labels[gainKind] || gainKind}.`)));
  } else if (payKind === 'wild') {
    ['g', 's', 'm'].forEach(r => {
      row.appendChild(promptButton(`Pay ${payAmount} ${labels[r]}`, () =>
        post(r, `Pay ${payAmount} ${labels[r]} for ${gainAmount} ${labels[gainKind] || gainKind}.`)));
    });
  } else {
    row.appendChild(promptButton(`Pay ${payAmount} ${labels[payKind] || payKind}`, () =>
      post('accept', `Pay ${payAmount} ${labels[payKind] || payKind} for ${gainAmount} ${labels[gainKind] || gainKind}.`)));
  }
  row.appendChild(promptButton('Decline', () => post('skip', 'Decline this event.')));
  body.appendChild(row);

  openPromptOverlayShell({ title: name, dismissible: false, bodyEl: body, footerEl: null });
}

// Event: each player may banish one owned citizen (optionally role-filtered)
// for a bank reward (e.g. A Call To Arms: banish a Soldier for 3 VP).
function renderConcurrentEventBanishForReward(state, concurrent) {
  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
  const isPending = !!(PLAYER_ID && pending.some(pid => idsMatch(pid, PLAYER_ID)));
  const totalParticipants = pending.length + completed.length;
  const data = concurrent.data || {};
  const name = (data.name || 'Event').toString();
  const role = (data.role || '').toString();
  const gainKind = (data.gain_kind || 'v').toString();
  const gainAmount = Number(data.gain_amount || 0);
  const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
  const roleAttr = { shadow: 'shadow_count', holy: 'holy_count', soldier: 'soldier_count', worker: 'worker_count' }[role];
  const waitingLabels = pendingPlayerLabels(state, pending);

  const body = mk('prompt-modal-body');
  const status = mk('prompt-modal-note');
  status.textContent =
    `${name}: ${completed.length}/${totalParticipants} player choice(s) submitted.` +
    (pending.length ? ` Waiting on: ${waitingLabels.join(', ')}.` : '');
  body.appendChild(status);

  if (!isPending) {
    const youDone = !!(PLAYER_ID && completed.some(pid => idsMatch(pid, PLAYER_ID)));
    const line = mk('prompt-modal-note');
    line.textContent = youDone
      ? 'You already responded. Waiting on other players.'
      : 'You have no pending response in this event.';
    body.appendChild(line);
    openPromptOverlayShell({ title: name, dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  const post = (response, message) => confirmAndPostGameAction(
    { player_id: PLAYER_ID, action_type: 'submit_concurrent_action', kind: 'event_banish_citizen_for_reward', response: String(response) },
    { title: name, message },
  );

  const you = playerById(state, PLAYER_ID);
  const citizens = Array.isArray(you?.owned_citizens) ? you.owned_citizens : [];
  const list = mk('prompt-choice-list');
  citizens.forEach((c, idx) => {
    if (!c || c.is_flipped) return;
    if (roleAttr && !(Number(c[roleAttr] || 0) > 0)) return;
    const nm = (c.name || `Citizen #${idx}`).toString();
    const cardEl = mk('prompt-choice-card');
    const titleEl = mk('prompt-choice-card-title');
    titleEl.textContent = `${nm} (slot #${idx})`;
    cardEl.appendChild(titleEl);
    const actions = mk('prompt-choice-card-actions');
    actions.appendChild(promptButton(`Banish for ${gainAmount} ${labels[gainKind] || gainKind}`, () =>
      post(idx, `Banish ${nm} for ${gainAmount} ${labels[gainKind] || gainKind}.`)));
    cardEl.appendChild(actions);
    list.appendChild(cardEl);
  });
  body.appendChild(list);

  const declineRow = mk('prompt-choice-card-actions');
  declineRow.appendChild(promptButton('Decline', () => post('skip', 'Decline this event.')));
  body.appendChild(declineRow);

  openPromptOverlayShell({
    title: `${name}: banish a${role ? ' ' + role : ''} citizen`,
    dismissible: false,
    bodyEl: body,
    footerEl: null,
  });
}

// ── Concurrent harvest gate ──────────────────────────────────────────────
//
// Single roster modal: one row per harvest participant. Each row shows
// the player's name, a short prompt summary, and an action cell that
// switches between buttons (for the viewer's own prompt), a spinner
// (for other players still pending), or a check (for completed players).
// The modal stays open until every participant has resolved their
// decisions — including any follow-up prompts opened by re-drain.

function harvestPromptSubKindBadge(subKind) {
  switch ((subKind || '').toString()) {
    case 'harvest_optional_exchange':  return 'Optional exchange';
    case 'harvest_wild_cost_exchange': return 'Wild-cost exchange';
    case 'harvest_wild_gain_exchange': return 'Wild-gain exchange';
    case 'bonus_resource_choice':      return 'Harvest bonus';
    case 'harvest_choose':             return 'Choose one';
    default:                           return 'Harvest decision';
  }
}

function harvestPromptSummary(prompt) {
  if (!prompt) return '';
  const sub = (prompt.sub_kind || '').toString();
  const prc = prompt.pending_required_choice || {};

  if (sub === 'harvest_optional_exchange') {
    const cmd = (prc.command || '').toString();
    return harvestExchangeExplain(cmd);
  }
  if (sub === 'harvest_wild_cost_exchange') {
    const gainRes = (prc.gain_resource || '').toLowerCase();
    const gainAmt = Number(prc.gain_amount || 0);
    const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
    const gainLabel = `${gainAmt} ${labels[gainRes] || gainRes}`;
    return `Choose what to pay; gain ${gainLabel}.`;
  }
  if (sub === 'harvest_wild_gain_exchange') {
    const costRes = (prc.cost_resource || '').toLowerCase();
    const costAmt = Number(prc.cost_amount || 0);
    const gainAmt = Number(prc.gain_amount || 0);
    const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
    return `Pay ${costAmt} ${labels[costRes] || costRes}; choose gain (${gainAmt}).`;
  }
  if (sub === 'bonus_resource_choice') {
    return 'Pick +1 resource (no harvest payouts this round).';
  }
  if (sub === 'harvest_choose') {
    const cmd = (prc.command_text || prompt.action_text || prompt.action || prc.command || '').toString();
    return `Choose one: ${cmd}`;
  }
  return harvestPromptSubKindBadge(sub);
}

function harvestPromptButtons(prompt, state) {
  if (!prompt) return [];
  const sub = (prompt.sub_kind || '').toString();
  const prc = prompt.pending_required_choice || {};
  const action = (prompt.action || '').toString();

  // Prefix the prompt id so the server knows WHICH of the player's payouts this
  // resolves — they are all shown at once and may be tackled in any order.
  const idPrefix = prompt.id ? `${prompt.id}|` : '';
  const post = (response, confirmCopy) => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'submit_concurrent_action',
      kind: 'harvest_choices',
      response: `${idPrefix}${response}`,
    },
    confirmCopy || {
      title: 'Confirm harvest choice?',
      message: String(response),
    },
  );

  if (sub === 'harvest_optional_exchange') {
    const explain = harvestExchangeExplain((prc.command || '').toString());
    return [
      promptButton('Take', () => post('confirm_harvest_exchange', {
        title: 'Take exchange?',
        message: explain,
      })),
      promptButton('Skip', () => post('skip_harvest_exchange', {
        title: 'Skip exchange?',
        message: 'Keep your resources and skip this optional harvest exchange.',
        confirmLabel: 'Skip',
      }), true),
    ];
  }

  if (sub === 'harvest_wild_cost_exchange') {
    const costOpts = Array.isArray(prc.cost_options) ? prc.cost_options : [];
    const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'VP' };
    const buttons = costOpts.map(opt => {
      const r = (opt?.resource || '').toLowerCase();
      const n = Number(opt?.amount || 0);
      return promptButton(`Pay ${n} ${labels[r] || r.toUpperCase()}`, () =>
        post(`wild_cost_resource ${r}`));
    });
    buttons.push(promptButton('Skip', () => post('skip_harvest_exchange', {
      title: 'Skip exchange?',
      message: 'Keep your resources and skip this optional harvest exchange.',
      confirmLabel: 'Skip',
    }), true));
    return buttons;
  }

  if (sub === 'harvest_wild_gain_exchange') {
    const gainAmt = Number(prc.gain_amount || 0);
    const labels = { g: 'Gold', s: 'Strength', m: 'Magic' };
    const buttons = ['g', 's', 'm'].map(r =>
      promptButton(`Gain ${gainAmt} ${labels[r]}`, () =>
        post(`wild_gain_resource ${r}`)));
    buttons.push(promptButton('Skip', () => post('skip_harvest_exchange', {
      title: 'Skip exchange?',
      message: 'Keep your resources and skip this optional harvest exchange.',
      confirmLabel: 'Skip',
    }), true));
    return buttons;
  }

  if (sub === 'bonus_resource_choice') {
    return [
      promptButton('+1 Gold', () => post('gold')),
      promptButton('+1 Strength', () => post('strength')),
      promptButton('+1 Magic', () => post('magic')),
    ];
  }

  if (sub === 'harvest_choose') {
    let options = parseChooseCommand(action);
    if (
      prc &&
      prc.kind === 'special_payout_choose' &&
      Array.isArray(prc.options) &&
      prc.options.length
    ) {
      options = prc.options;
    }
    return options.map((opt, idx) => {
      const optLabel = chooseOptionButtonLabel(opt, idx, state);
      return promptButton(optLabel, () => post(`choose ${idx + 1}`, {
        title: 'Confirm choice?',
        message: optLabel,
      }));
    });
  }

  return [];
}

function makeHarvestStatusSpinner() {
  const wrap = mk('prompt-harvest-status prompt-harvest-status--waiting');
  const spin = mk('prompt-harvest-spinner');
  spin.setAttribute('role', 'progressbar');
  spin.setAttribute('aria-label', 'Waiting');
  const label = mk('prompt-harvest-status-label');
  label.textContent = 'Waiting';
  wrap.appendChild(spin);
  wrap.appendChild(label);
  return wrap;
}

function makeHarvestStatusCheck() {
  const wrap = mk('prompt-harvest-status prompt-harvest-status--done');
  const check = mk('prompt-harvest-check');
  check.textContent = '✓';
  check.setAttribute('aria-hidden', 'true');
  const label = mk('prompt-harvest-status-label');
  label.textContent = 'Done';
  wrap.appendChild(check);
  wrap.appendChild(label);
  return wrap;
}

function renderConcurrentHarvestChoices(state, concurrent) {
  const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
  const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
  const prompts = (concurrent?.data && typeof concurrent.data === 'object'
    ? (concurrent.data.prompts || {})
    : {}) || {};
  const phase = (concurrent?.data && concurrent.data.phase) || 'scan';

  // Preserve harvest seat order if known; otherwise fall back to player_list
  // order. We always include every participant (pending + completed) so the
  // viewer can see whose decisions are still outstanding.
  const harvestOrder = Array.isArray(state?.harvest_player_order)
    ? state.harvest_player_order : null;
  const playerOrder = Array.isArray(state?.player_list)
    ? state.player_list.map(p => p?.player_id).filter(Boolean) : [];
  const orderRef = harvestOrder && harvestOrder.length ? harvestOrder : playerOrder;
  const participantSet = new Set([...pending.map(String), ...completed.map(String)]);
  const participantIds = [];
  orderRef.forEach(pid => {
    const s = String(pid);
    if (participantSet.has(s) && !participantIds.includes(s)) participantIds.push(s);
  });
  participantSet.forEach(s => {
    if (!participantIds.includes(s)) participantIds.push(s);
  });

  const total = participantIds.length;
  const done = completed.length;

  const body = mk('prompt-modal-body');

  const status = mk('prompt-modal-note');
  status.textContent = phase === 'finalize_bonus'
    ? `End-of-harvest bonus: ${done}/${total} player(s) submitted.`
    : `Harvest decisions: ${done}/${total} player(s) submitted.`;
  body.appendChild(status);

  appendPromptResourcesPanel(body, state);

  // ── Your payouts ────────────────────────────────────────────────────────
  // Every decision the viewer owns is shown at once so they can resolve them
  // in whatever order they like. The list scrolls when there are many.
  // Match the viewer to their prompt bucket the same way every other concurrent
  // renderer does — via idsMatch, which trims before comparing. A raw === lookup
  // (or prompts[myPid] keyed access) silently fails when a player's PLAYER_ID
  // carries whitespace the server-side id doesn't, dropping them into the
  // "Other players / Deciding…" roster even though they own a live prompt.
  const myPromptKey = PLAYER_ID
    ? Object.keys(prompts).find(k => idsMatch(k, PLAYER_ID))
    : null;
  const myRaw = myPromptKey ? prompts[myPromptKey] : null;
  const myPrompts = Array.isArray(myRaw) ? myRaw : (myRaw ? [myRaw] : []);
  const iAmPending = !!(PLAYER_ID && pending.some(p => idsMatch(p, PLAYER_ID)));

  if (iAmPending && myPrompts.length) {
    const mine = mk('prompt-harvest-mine');
    const title = mk('prompt-harvest-mine-title');
    title.textContent = myPrompts.length > 1
      ? `Your harvest payouts (${myPrompts.length}) — resolve in any order`
      : 'Your harvest payout';
    mine.appendChild(title);

    const list = mk('prompt-harvest-mine-list');
    myPrompts.forEach(prompt => {
      const card = mk('prompt-harvest-decision');

      const head = mk('prompt-harvest-decision-head');
      const badge = mk('prompt-harvest-sub-badge');
      badge.textContent = harvestPromptSubKindBadge(prompt.sub_kind);
      head.appendChild(badge);
      const summaryEl = mk('prompt-harvest-summary');
      summaryEl.textContent = harvestPromptSummary(prompt);
      head.appendChild(summaryEl);
      card.appendChild(head);

      const buttons = harvestPromptButtons(prompt, state);
      const actions = mk('prompt-harvest-buttons');
      if (buttons.length) {
        buttons.forEach(b => actions.appendChild(b));
      } else {
        actions.appendChild(makeHarvestStatusSpinner());
      }
      card.appendChild(actions);

      list.appendChild(card);
    });
    mine.appendChild(list);
    body.appendChild(mine);
  } else if (iAmPending) {
    const note = mk('prompt-modal-note');
    note.classList.add('is-muted');
    note.textContent = 'Resolving your harvest…';
    body.appendChild(note);
  }

  // ── Other players ───────────────────────────────────────────────────────
  // Opponents only get a status indicator (still deciding / finished); we no
  // longer surface which specific payout they happen to be resolving.
  const roster = mk('prompt-harvest-roster');
  participantIds.forEach(pid => {
    if (idsMatch(pid, PLAYER_ID)) return;
    const isPending = pending.some(p => idsMatch(p, pid));

    const row = mk('prompt-harvest-row prompt-harvest-row--status');
    row.classList.add(isPending ? 'is-pending' : 'is-done');

    const nameEl = mk('prompt-harvest-name');
    const nameText = document.createElement('span');
    nameText.className = 'prompt-harvest-name-text';
    nameText.textContent = playerDisplayName(state, pid);
    nameEl.appendChild(nameText);
    row.appendChild(nameEl);

    const actionEl = mk('prompt-harvest-action');
    if (isPending) {
      const wrap = mk('prompt-harvest-status prompt-harvest-status--waiting');
      const spin = mk('prompt-harvest-spinner');
      spin.setAttribute('role', 'progressbar');
      spin.setAttribute('aria-label', 'Deciding');
      const label = mk('prompt-harvest-status-label');
      label.textContent = 'Deciding…';
      wrap.appendChild(spin);
      wrap.appendChild(label);
      actionEl.appendChild(wrap);
    } else {
      actionEl.appendChild(makeHarvestStatusCheck());
    }
    row.appendChild(actionEl);

    roster.appendChild(row);
  });
  if (roster.children.length) {
    const rosterTitle = mk('prompt-harvest-roster-title');
    rosterTitle.textContent = 'Other players';
    body.appendChild(rosterTitle);
    body.appendChild(roster);
  }

  openPromptOverlayShell({
    title: phase === 'finalize_bonus' ? 'Harvest bonus' : 'Harvest decisions',
    subtitle: pending.length
      ? `Waiting on ${pendingPlayerLabels(state, pending).join(', ')}.`
      : 'Finalizing harvest…',
    dismissible: false,
    bodyEl: body,
    footerEl: null,
  });
}

function renderConcurrentPanel(state, concurrent) {
  const kind = concurrent?.kind || '';
  if (kind === 'choose_duke') return renderConcurrentChooseDuke(state, concurrent);
  if (kind === 'choose_relic') return renderConcurrentChooseRelic(state, concurrent);
  if (kind === 'flip_one_citizen') return renderConcurrentFlipCitizen(state, concurrent);
  if (kind === 'harvest_choices') return renderConcurrentHarvestChoices(state, concurrent);
  if (kind === 'event_self_convert') return renderConcurrentEventSelfConvert(state, concurrent);
  if (kind === 'event_banish_citizen_for_reward') return renderConcurrentEventBanishForReward(state, concurrent);

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
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Finalize roll',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const you = playerById(state, PLAYER_ID);
  const rollKey = stagedRollKey(rolled1, rolled2);
  if (stagedFirstModifierForRoll !== rollKey) resetFinalizeRollStaging();
  const staged = stagedFirstModifier;

  const diceLine = mk('prompt-modal-dice-line');
  diceLine.appendChild(makeDie(rolled1));
  diceLine.appendChild(document.createTextNode(' + '));
  diceLine.appendChild(makeDie(rolled2));
  diceLine.appendChild(document.createTextNode(` = ${rolled1 + rolled2}`));
  body.appendChild(diceLine);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');

  if (!staged) {
    // Stage 1: first modifier (or keep).
    const options = listRollSetOneDieOptions(you, rolled1, rolled2, state.turn_number);
    foot.appendChild(promptButton(`Keep ${rolled1} + ${rolled2}`, () => {
      openActionConfirmModal({
        title: 'Finalize roll?',
        message: `Keep dice as ${rolled1} + ${rolled2} (total ${rolled1 + rolled2}).`,
        onConfirm: () => sendFinalizeRollChoice(rolled1, rolled2),
      });
    }));
    options.forEach(o => {
      const fromVal = o.die === 1 ? rolled1 : rolled2;
      foot.appendChild(promptButton(
        `Die ${o.die}: ${fromVal} → ${o.target} (${o.costGold}g · ${o.domainName})`,
        () => {
          stagedFirstModifier = { ...o };
          stagedFirstModifierForRoll = rollKey;
          renderFinalizeRollPrompt(state);
        },
      ));
    });

    if (hasTwilightPalaceReroll(state)) {
      [1, 2].forEach(dieIdx => {
        foot.appendChild(promptButton(
          `Re-roll die ${dieIdx} (Twilight Palace)`,
          () => openActionConfirmModal({
            title: `Re-roll die ${dieIdx}?`,
            message: `Re-roll die ${dieIdx} using Twilight Palace. You will get a new random value.`,
            onConfirm: async () => {
              if (!GAME_ID || !PLAYER_ID || finalizeRollInFlight) return;
              finalizeRollInFlight = true;
              try {
                await postGameAction({
                  player_id: PLAYER_ID,
                  action_type: 'reroll_pending_die',
                  die_one: dieIdx,
                });
              } finally {
                finalizeRollInFlight = false;
                resetFinalizeRollStaging();
              }
            },
          }),
        ));
      });
    }

    if (hasBloodMoonReroll(state)) {
      foot.appendChild(promptButton(
        'Re-roll both dice (Blood Moon Palace, costs 2 Magic)',
        () => openActionConfirmModal({
          title: 'Re-roll both dice?',
          message: 'Re-roll both dice using Blood Moon Palace. Costs 2 Magic. You will get two new random values.',
          onConfirm: async () => {
            if (!GAME_ID || !PLAYER_ID || finalizeRollInFlight) return;
            finalizeRollInFlight = true;
            try {
              await postGameAction({
                player_id: PLAYER_ID,
                action_type: 'reroll_both_dice',
              });
            } finally {
              finalizeRollInFlight = false;
              resetFinalizeRollStaging();
            }
          },
        }),
      ));
    }

    const hint = mk('prompt-modal-note');
    const hintParts = ['Choose a roll modifier (or keep). You can chain a second modifier on the other die.'];
    if (hasTwilightPalaceReroll(state)) hintParts.push('Twilight Palace: re-roll one die (once per turn).');
    if (hasBloodMoonReroll(state)) hintParts.push('Blood Moon Palace: re-roll both dice (costs 2 Magic, once per turn).');
    hint.textContent = hintParts.join(' ');
    body.appendChild(hint);
  } else {
    // Stage 2: staged first modifier; offer Confirm (apply only the staged
    // change), Back (clear staging), and any legal second-modifier buttons
    // scoped to the OTHER die / different source / remaining gold budget.
    const stagedFromVal = staged.die === 1 ? rolled1 : rolled2;
    const d1AfterFirst = staged.die === 1 ? staged.target : rolled1;
    const d2AfterFirst = staged.die === 2 ? staged.target : rolled2;

    const stagedNote = mk('prompt-modal-note');
    stagedNote.appendChild(document.createTextNode('Staged: '));
    const stagedStrong = document.createElement('strong');
    stagedStrong.textContent = `Die ${staged.die}: ${stagedFromVal} → ${staged.target}`;
    stagedNote.appendChild(stagedStrong);
    stagedNote.appendChild(document.createTextNode(
      ` (${staged.costGold}g · ${staged.domainName}). Result so far: `,
    ));
    const stagedResult = document.createElement('strong');
    stagedResult.textContent = `${d1AfterFirst} + ${d2AfterFirst} = ${d1AfterFirst + d2AfterFirst}`;
    stagedNote.appendChild(stagedResult);
    stagedNote.appendChild(document.createTextNode('.'));
    body.appendChild(stagedNote);

    foot.appendChild(promptButton(`Confirm ${d1AfterFirst} + ${d2AfterFirst}`, () => {
      sendFinalizeRollChoice(d1AfterFirst, d2AfterFirst);
    }));

    const otherDie = staged.die === 1 ? 2 : 1;
    const remainingGold = Math.max(0, Number(you?.gold_score || 0) - Number(staged.costGold || 0));
    const stage2Options = listRollSetOneDieOptions(
      you, rolled1, rolled2, state.turn_number,
      { die: otherDie, excludeDomainId: staged.domainId, budgetGold: remainingGold },
    );
    stage2Options.forEach(o => {
      const fromVal = o.die === 1 ? rolled1 : rolled2;
      const d1 = o.die === 1 ? o.target : d1AfterFirst;
      const d2 = o.die === 2 ? o.target : d2AfterFirst;
      const totalGold = Number(staged.costGold || 0) + Number(o.costGold || 0);
      const btn = promptButton(
        `+ Die ${o.die}: ${fromVal} → ${o.target} (${o.costGold}g · ${o.domainName}) → ${d1} + ${d2}`,
        () => sendFinalizeRollChoice(d1, d2),
      );
      btn.title = `Apply both modifiers (total ${totalGold}g).`;
      foot.appendChild(btn);
    });

    foot.appendChild(promptButton('Back', () => {
      resetFinalizeRollStaging();
      renderFinalizeRollPrompt(state);
    }, true));

    const hint = mk('prompt-modal-note');
    hint.textContent = stage2Options.length
      ? 'Optionally chain a second modifier on the other die, or confirm with just the first.'
      : 'No second modifier available — confirm to apply just the staged change.';
    body.appendChild(hint);
  }

  appendPromptResourcesPanel(body, state);

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
    appendPromptResourcesPanel(body, state);
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

  appendPromptResourcesPanel(body, state);

  const foot = promptActionsRow([
    promptButton('Confirm trade', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'confirm_self_convert',
      },
      {
        title: 'Confirm trade?',
        message: `Apply the optional trade for ${dn} as described above.`,
      },
    )),
    promptButton('Decline', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'skip',
      },
      {
        title: 'Decline trade?',
        message: 'Skip this optional trade and keep your resources as they are.',
        confirmLabel: 'Decline',
      },
    ), true),
  ]);

  openPromptOverlayShell({
    title: `${dn}: optional trade`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderEventGainActionPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const name = (prc?.event_name || 'Event').toString();
  const payKind = (prc?.pay_kind || 'm').toString();
  const payAmount = Number(prc?.pay_amount || 0);
  const labels = { g: 'gold', s: 'strength', m: 'magic' };
  const payLabel = `${payAmount} ${labels[payKind] || payKind}`;

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${name} additional-action choice.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({ title: name, dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = `Pay ${payLabel} for an additional action?`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const foot = promptActionsRow([
    promptButton(`Pay ${payLabel}`, () => confirmAndPostGameAction(
      { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: 'accept' },
      { title: 'Pay for an action?', message: `Pay ${payLabel} to gain an additional action.` },
    )),
    promptButton('Decline', () => confirmAndPostGameAction(
      { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: 'skip' },
      { title: 'Decline?', message: 'Skip the additional action.', confirmLabel: 'Decline' },
    ), true),
  ]);

  openPromptOverlayShell({ title: name, dismissible: false, bodyEl: body, footerEl: foot });
}

// Golden Idol: the active player must pick exactly one of two options.
function renderEventActiveChoosePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const name = (prc?.event_name || 'Event').toString();
  const options = Array.isArray(prc?.options) ? prc.options : [];
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'Victory Points' };

  const optionText = (o) => {
    const res = labels[(o?.kind || '').toString()] || (o?.kind || '').toString().toUpperCase();
    const amt = Number(o?.amount || 0);
    if ((o?.audience || '') === 'active') return `You gain ${amt} ${res}`;
    return `All players gain ${amt} ${res}`;
  };

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${name} choice.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({ title: name, dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = 'Choose one:';
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  options.forEach((o, idx) => {
    const txt = optionText(o);
    foot.appendChild(promptButton(txt, () => confirmAndPostGameAction(
      { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `choose ${idx + 1}` },
      { title: name, message: txt },
    )));
  });

  openPromptOverlayShell({ title: name, dismissible: false, bodyEl: body, footerEl: foot });
}

// "In turn order" events (Alms for the Poor, Night Terror, Worthy Sacrifice).
// The acting player is always action_required.id; pending_required_choice.verb
// selects which sub-prompt to render.
function renderEventSequencePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const name = (prc?.event_name || 'Event').toString();
  const verb = (prc?.verb || '').toString();
  const data = prc?.data || {};

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${name}.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({ title: name, dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'Victory Points' };

  if (verb === 'pay_to_chosen') {
    const amt = Number(data?.pay_amount || 0);
    const me = (state?.player_list || []).find((p) => idsMatch(p?.player_id, PLAYER_ID)) || {};
    const bal = { g: Number(me.gold_score || 0), s: Number(me.strength_score || 0), m: Number(me.magic_score || 0) };
    const sub = mk('prompt-modal-note');
    sub.textContent = `Pay ${amt} of one resource to another player.`;
    body.appendChild(sub);
    appendPromptResourcesPanel(body, state);
    (state?.player_list || []).forEach((p) => {
      if (idsMatch(p?.player_id, PLAYER_ID)) return;
      const nm = (p?.name || p?.player_id || '?').toString();
      ['g', 's', 'm'].forEach((res) => {
        if (bal[res] < amt) return;
        foot.appendChild(promptButton(`${nm}: ${amt} ${labels[res]}`, () => confirmAndPostGameAction(
          { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `pay ${res} ${p.player_id}` },
          { title: name, message: `Pay ${amt} ${labels[res]} to ${nm}.` },
        )));
      });
    });
  } else if (verb === 'banish_center_citizen') {
    const sub = mk('prompt-modal-note');
    sub.textContent = 'Banish a citizen from the center stacks.';
    body.appendChild(sub);
    const grid = state?.citizen_grid || [];
    const stackOpts = Array.isArray(prc?.stack_options) ? prc.stack_options : [];
    stackOpts.forEach((idx) => {
      const stack = grid[idx] || [];
      const top = stack[stack.length - 1] || {};
      const nm = (top?.name || `Stack ${idx}`).toString();
      foot.appendChild(promptButton(`Banish ${nm}`, () => confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `${idx}` },
        { title: name, message: `Banish ${nm} from the center.` },
      )));
    });
  } else if (verb === 'place_reserve_monster') {
    const cardName = (prc?.next_card_name || 'Undead Samurai').toString();
    const remaining = Number(prc?.reserve_remaining || 0);
    const sub = mk('prompt-modal-note');
    sub.textContent = `Place an ${cardName} on a stack of your choice (it blocks the card beneath until slain). ${remaining} left in reserve.`;
    body.appendChild(sub);
    const gridLabels = { monster: 'Monster', citizen: 'Citizen', domain: 'Domain' };
    const opts = Array.isArray(prc?.placement_options) ? prc.placement_options : [];
    opts.forEach((opt) => {
      const g = (opt?.grid || '').toString();
      const idx = Number(opt?.idx || 0);
      const onTop = (opt?.label || '?').toString();
      foot.appendChild(promptButton(`${gridLabels[g] || g} #${idx} (on ${onTop})`, () => confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `place ${g} ${idx}` },
        { title: name, message: `Place ${cardName} on the ${gridLabels[g] || g} stack #${idx}.` },
      )));
    });
  } else if (verb === 'banish_owned_citizen') {
    const gainKind = (data?.gain_kind || 'v').toString();
    const gainAmt = Number(data?.gain_amount || 0);
    const sub = mk('prompt-modal-note');
    sub.textContent = `Banish one of your citizens to gain ${gainAmt} ${labels[gainKind] || gainKind}?`;
    body.appendChild(sub);
    const me = (state?.player_list || []).find((p) => idsMatch(p?.player_id, PLAYER_ID)) || {};
    const oc = Array.isArray(me?.owned_citizens) ? me.owned_citizens : [];
    const ownedOpts = Array.isArray(prc?.owned_options) ? prc.owned_options : [];
    ownedOpts.forEach((idx) => {
      const c = oc[idx] || {};
      const nm = (c?.name || `Citizen ${idx}`).toString();
      foot.appendChild(promptButton(`Banish ${nm}`, () => confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `${idx}` },
        { title: name, message: `Banish ${nm} for ${gainAmt} ${labels[gainKind] || gainKind}.` },
      )));
    });
    if (!prc?.mandatory) {
      foot.appendChild(promptButton('Skip (optional)', () => confirmAndPostGameAction(
        { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: 'skip' },
        { title: name, message: 'Decline to banish a citizen.', confirmLabel: 'Skip' },
      ), true));
    }
  }

  openPromptOverlayShell({ title: name, dismissible: false, bodyEl: body, footerEl: foot });
}

function renderDomainChooseResourcePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const dn = (prc?.domain_name || 'Domain').toString();
  const choices = Array.isArray(prc?.choices) ? prc.choices : [];
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'Victory Point' };

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — ${dn}: choose a resource.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: `${dn}: choose`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = `${dn}: choose one resource to gain.`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const buttons = choices.map(([r, n], idx) => {
    const label = `+${n} ${labels[r] || r.toUpperCase()}`;
    return promptButton(label, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `choose ${idx + 1}`,
    }));
  });

  const foot = promptActionsRow(buttons);
  openPromptOverlayShell({
    title: `${dn}: choose resource`,
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
    appendPromptResourcesPanel(body, state);
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

  appendPromptResourcesPanel(body, state);

  const foot = promptActionsRow([
    promptButton('Take exchange', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'confirm_harvest_exchange',
      },
      {
        title: 'Take exchange?',
        message: explain,
      },
    )),
    promptButton('Skip (keep resources)', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'skip_harvest_exchange',
      },
      {
        title: 'Skip exchange?',
        message: 'Keep your resources and skip this optional harvest exchange.',
        confirmLabel: 'Skip',
      },
    ), true),
  ]);

  openPromptOverlayShell({
    title: 'Harvest: optional exchange',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderHarvestWildCostExchangePrompt(state) {
  // exchange wild N <gain_res> M — player chooses which resource to PAY N of; gains M of gain_res.
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const gainRes = (prc?.gain_resource || '').toLowerCase();
  const gainAmt = Number(prc?.gain_amount || 0);
  const costOpts = Array.isArray(prc?.cost_options) ? prc.cost_options : [];
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'Victory Points' };

  const body = mk('prompt-modal-body');
  const gainLabel = `${gainAmt} ${labels[gainRes] || gainRes.toUpperCase()}`;

  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — choosing what to pay for +${gainLabel}.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Harvest: wild-cost exchange',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = `Choose which resource to pay. You will gain ${gainLabel}.`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const buttons = costOpts.map(opt => {
    const r = (opt.resource || '').toLowerCase();
    const n = Number(opt.amount || 0);
    const label = `Pay ${n} ${labels[r] || r.toUpperCase()}`;
    return promptButton(label, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `wild_cost_resource ${r}`,
    }));
  });
  buttons.push(promptButton('Skip (keep resources)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip_harvest_exchange',
    },
    {
      title: 'Skip exchange?',
      message: 'Keep your resources and skip this optional harvest exchange.',
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: `Harvest: gain ${gainLabel}`,
    dismissible: false,
    bodyEl: body,
    footerEl: promptActionsRow(buttons),
  });
}

function renderHarvestWildGainExchangePrompt(state) {
  // exchange wild <cost_res> N M — player pays N of cost_res, chooses which resource to GAIN M of.
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const costRes = (prc?.cost_resource || '').toLowerCase();
  const costAmt = Number(prc?.cost_amount || 0);
  const gainAmt = Number(prc?.gain_amount || 0);
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'Victory Points' };

  const body = mk('prompt-modal-body');
  const costLabel = `${costAmt} ${labels[costRes] || costRes.toUpperCase()}`;

  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — choosing what to gain for ${costLabel}.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Harvest: wild-gain exchange',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = `Pay ${costLabel}. Choose which resource to gain (${gainAmt}).`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const gainOptions = ['g', 's', 'm'];
  const buttons = gainOptions.map(r => {
    const label = `Gain ${gainAmt} ${labels[r] || r.toUpperCase()}`;
    return promptButton(label, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `wild_gain_resource ${r}`,
    }));
  });
  buttons.push(promptButton('Skip (keep resources)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip_harvest_exchange',
    },
    {
      title: 'Skip exchange?',
      message: 'Keep your resources and skip this optional harvest exchange.',
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: `Harvest: pay ${costLabel}`,
    dismissible: false,
    bodyEl: body,
    footerEl: promptActionsRow(buttons),
  });
}

// Treant Chest (both-wild exchange): stage 1 lets the player pick which resource
// to pay N of (one button per resource they hold >= N of); stage 2 lets them pick
// which resource to gain M of (always all three). Both stages submit through
// act_on_required_action (relic_pay <r> / relic_gain <r>).
function renderRelicWildExchangePrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const stage = (prc?.stage || 'pay').toString();
  const relicName = (prc?.relic_name || 'Relic').toString();
  const gainAmt = Number(prc?.gain_amount || 0);
  const labels = { g: 'Gold', s: 'Strength', m: 'Magic' };

  const body = mk('prompt-modal-body');

  if (!isYou) {
    const note = mk('prompt-modal-note');
    const what = stage === 'gain' ? 'what to gain' : 'what to pay';
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — choosing ${what} (${relicName}).`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: relicName,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  if (stage === 'gain') {
    const sub = mk('prompt-modal-note');
    sub.textContent = `Choose which resource to gain ${gainAmt} of.`;
    body.appendChild(sub);
    appendPromptResourcesPanel(body, state);
    const buttons = ['g', 's', 'm'].map(r =>
      promptButton(`Gain ${gainAmt} ${labels[r]}`, () => postGameAction({
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `relic_gain ${r}`,
      })));
    openPromptOverlayShell({
      title: `${relicName}: gain ${gainAmt}`,
      dismissible: false,
      bodyEl: body,
      footerEl: promptActionsRow(buttons),
    });
    return;
  }

  const costOpts = Array.isArray(prc?.cost_options) ? prc.cost_options : [];
  const sub = mk('prompt-modal-note');
  sub.textContent = `Choose which resource to pay. You will then choose a resource to gain ${gainAmt} of.`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);
  const buttons = costOpts.map(opt => {
    const r = (opt?.resource || '').toLowerCase();
    const n = Number(opt?.amount || 0);
    return promptButton(`Pay ${n} ${labels[r] || r.toUpperCase()}`, () => postGameAction({
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: `relic_pay ${r}`,
    }));
  });
  openPromptOverlayShell({
    title: relicName,
    dismissible: false,
    bodyEl: body,
    footerEl: promptActionsRow(buttons),
  });
}

function renderHarvestStealPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const stage = (prc?.stage || 'victim').toString();
  const victimOptions = Array.isArray(prc?.victim_options) ? prc.victim_options : [];
  const resourceOptions = Array.isArray(prc?.resource_options) ? prc.resource_options : [];
  const victim = prc?.victim || null;

  const body = mk('prompt-modal-body');
  const chip = harvestTurnChip(state, reqId);
  const headRow = mk('prompt-modal-inline');
  const ht = mk('prompt-modal-note');
  ht.textContent = isYou
    ? (stage === 'resource' ? 'Steal: choose resource' : 'Steal: choose opponent')
    : `Waiting on ${playerDisplayName(state, reqId)} — steal choice.`;
  headRow.appendChild(ht);
  if (chip) headRow.appendChild(chip);
  body.appendChild(headRow);

  if (!isYou) {
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Harvest steal',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  if (stage === 'resource') {
    const victimName = (victim?.victim_name || victim?.victim_id || 'opponent').toString();
    const note = mk('prompt-modal-note');
    note.textContent = `Choose what to steal from ${victimName}.`;
    body.appendChild(note);
    resourceOptions.forEach((o, idx) => {
      const amount = Number(o?.amount);
      const amountText = Number.isFinite(amount) ? amount : o?.amount;
      const resLabel = labelForChoiceToken(o?.resource);
      const label = `Steal ${amountText} ${resLabel}`;
      foot.appendChild(promptButton(label, () => confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'act_on_required_action',
          action: `steal_resource ${idx + 1}`,
        },
        {
          title: 'Steal resource?',
          message: `${label} from ${victimName}.`,
        },
      )));
    });
  } else {
    const note = mk('prompt-modal-note');
    note.textContent = 'Choose an opponent to steal from.';
    body.appendChild(note);
    victimOptions.forEach((o, idx) => {
      const victimName = (o?.victim_name || o?.victim_id || 'opponent').toString();
      foot.appendChild(promptButton(victimName, () => confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'act_on_required_action',
          action: `steal_victim ${idx + 1}`,
        },
        {
          title: 'Choose opponent?',
          message: `Steal from ${victimName}.`,
        },
      )));
    });
  }

  appendPromptResourcesPanel(body, state);

  openPromptOverlayShell({
    title: 'Harvest steal',
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
  const dn = (prc?.item?.domain_name || prc?.domain_name || 'Domain').toString();
  const explain = prc?.explain
    ? prc.explain.toString()
    : prc?.kind === 'domain_manipulate_player'
    ? domainManipulateExplain(prc)
    : 'Choose another player.';

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} to choose a player for ${dn}.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
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

  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || o?.player_id || '?').toString();
    foot.appendChild(promptButton(nm, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `choose_player ${idx + 1}`,
      },
      {
        title: 'Choose player?',
        message: `Target ${nm} for ${dn}.`,
      },
    )));
  });

  const kv = prc?.item?.kv || {};
  const skipLabel = prc?.allow_skip && domainEffectGainIsVp(kv)
    ? 'Decline (no pay, no VP)'
    : 'Skip (optional)';
  if (prc?.allow_skip) {
    foot.appendChild(promptButton(skipLabel, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'skip',
      },
      {
        title: 'Skip?',
        message: `${skipLabel} for ${dn}.`,
        confirmLabel: 'Skip',
      },
    ), true));
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
    foot.appendChild(promptButton(nm, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `choose_monster ${idx + 1}`,
      },
      {
        title: 'Choose monster?',
        message: `Add +${delta} strength cost to ${nm} for ${dn}.`,
      },
    )));
  });

  openPromptOverlayShell({
    title: `${dn}: strengthen a center monster`,
    subtitle: `Add +${delta} to strength cost`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// "May slay a Monster" prompt — stage 1: pick a monster (or pass).
// Triggered by a bare-verb `slay` payout. The activation source is in
// pending_required_choice.source_label (e.g. "Eye of Asteraten" for the
// build-time activation; later, a citizen name for harvest-time slays).
function renderImmediateSlayPickMonster(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];
  const sourceLabel = (prc?.source_label || 'Effect').toString();

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — \"${sourceLabel}\" may slay a monster.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: `${sourceLabel}: may slay a Monster`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = 'Choose a monster to slay (you will set strength/magic payment next), or pass.';
  body.appendChild(sub);

  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || '?').toString();
    const gc = Number(o?.gold_cost || 0);
    const sc = Number(o?.strength_cost || 0);
    const mc = Number(o?.magic_cost || 0);
    const area = (o?.area || '').toString();
    const tail = area ? ` · ${area}` : '';
    const goldPart = gc > 0 ? `${gc} gold + ` : '';
    const label = `${nm} (${goldPart}${sc} str + ${mc} mag${tail})`;
    foot.appendChild(promptButton(label, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `choose_monster_slay ${idx + 1}`,
      },
      {
        title: 'Choose monster?',
        message: `Pick "${nm}" — you'll set the slay payment on the next step.`,
      },
    )));
  });

  foot.appendChild(promptButton('Pass (do not slay)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Pass on slay?',
      message: `Decline the may-slay-a-Monster effect from "${sourceLabel}".`,
      confirmLabel: 'Pass',
    },
  ), true));

  openPromptOverlayShell({
    title: `${sourceLabel}: may slay a Monster`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// Event roll effect: player must choose which accessible monster gets extra slay cost.
function renderEventSlayCostPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const pesc = state?.pending_event_slay_cost || {};
  const eventName = (pesc.event_name || 'Event').toString();
  const resource = (pesc.resource || 's').toString();
  const amount = Number(pesc.amount || 1);
  const resourceLabel = resource === 'g' ? 'Gold' : resource === 'm' ? 'Magic' : 'Strength';

  const body = mk('prompt-modal-body');
  const sub = mk('prompt-modal-note');

  if (!isYou) {
    sub.textContent = `Waiting on ${playerDisplayName(state, reqId)} to choose a monster for the "${eventName}" extra cost.`;
    body.appendChild(sub);
    openPromptOverlayShell({
      title: `"${eventName}": add +${amount} ${resourceLabel} slay cost`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  sub.textContent = `Choose a monster to apply +${amount} ${resourceLabel} to its slay cost.`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  // Collect accessible monsters/events from the top of the monster grid.
  const targets = [];
  const grid = state?.monster_grid || [];
  for (const stack of grid) {
    if (!Array.isArray(stack) || !stack.length) continue;
    const top = stack[stack.length - 1];
    if (!top?.is_accessible) continue;
    if (top.monster_id != null || top.event_id != null) targets.push(top);
  }

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');

  if (targets.length === 0) {
    const none = mk('prompt-modal-note');
    none.textContent = 'No accessible monsters on the board — effect cannot be applied.';
    body.appendChild(none);
  } else {
    targets.forEach(card => {
      const nm = (card.name || '?').toString();
      const sc = Number(card.strength_cost || 0) + Number(card.extra_strength_cost || 0);
      const mc = Number(card.magic_cost || 0) + Number(card.extra_magic_cost || 0);
      const label = `${nm} (${sc} str + ${mc} mag)`;
      foot.appendChild(promptButton(label, async () => {
        const body2 = { player_id: PLAYER_ID };
        if (card.event_id != null) body2.event_id = Number(card.event_id);
        else body2.monster_id = Number(card.monster_id);
        const res = await fetch(`/api/game/${encodeURIComponent(GAME_ID)}/apply_event_slay_cost`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body2),
        });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) { window.alert(payload?.detail || res.statusText || 'Request failed'); return; }
        removePromptOverlay();
        if (payload?.game_state) {
          // Bust render dedup so the harvest gate that just opened is never
          // skipped when tick_id is unchanged (roll effects don't bump it).
          lastRenderedStateJson = '';
          render(payload.game_state);
          if ((payload.game_state.concurrent_action?.pending || []).length) {
            renderPromptModal(payload.game_state);
          }
        } else fetchGameStateFromApi();
      }));
    });
  }

  openPromptOverlayShell({
    title: `"${eventName}": add +${amount} ${resourceLabel} slay cost`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot.children.length > 0 ? foot : null,
  });
}

// "May slay a Monster" prompt — stage 2: collect payment for the monster picked
// in stage 1, then submit `slay_pay <g> <s> <m> [tg ts tm]`. Gold is only
// allowed when an event added an exact gold slay cost. Tome chips default to
// "used" and are appended as the optional trailing tome portion.
// Per-prompt "saved" (toggled-off) tome indices, keyed so the choice survives
// the live-state re-render that rebuilds the prompt body. Shared by the slay
// and Ararmartin-Ridge build payment prompts.
const promptPaymentSavedTomes = {};

// Per-prompt Thunder Axe waiver selection ('none' | 'magic' | 'strength'),
// keyed like the tome state so it survives prompt re-renders.
const promptThunderAxeModes = {};

function immediateSlayPromptKey(prc) {
  if (!prc) return 'unknown';
  if (prc.event_id != null) return `event:${prc.event_id}`;
  if (prc.monster_id != null) return `monster:${prc.monster_id}`;
  return (prc.monster_name || 'monster').toString();
}

// Resolve the Thunder Axe waiver for the immediate-slay prompt from the viewer's
// owned relics and the monster's face-value costs carried on the prompt. Returns
// null when the player can't apply it to this monster.
function immediateSlayThunderAxe(me, prc, promptKey) {
  const axe = (typeof viewerThunderAxe === 'function') ? viewerThunderAxe(me) : null;
  if (!axe || !prc) return null;
  const faceMagic = Number(prc.face_magic_cost || 0);
  const faceStrength = Number(prc.face_strength_cost || 0);
  const canMagic = axe.magic > 0 && faceMagic > 0;
  const canStrength = axe.strength > 0 && faceStrength > 0;
  if (!canMagic && !canStrength) return null;
  let mode = promptThunderAxeModes[promptKey] || 'none';
  if (mode === 'magic' && !canMagic) mode = 'none';
  if (mode === 'strength' && !canStrength) mode = 'none';
  return {
    name: axe.name,
    canMagic,
    canStrength,
    magicWaive: canMagic ? Math.min(axe.magic, faceMagic) : 0,
    strengthWaive: canStrength ? Math.min(axe.strength, faceStrength) : 0,
    mode,
  };
}

function promptSavedTomeSets(key) {
  if (!promptPaymentSavedTomes[key]) {
    promptPaymentSavedTomes[key] = { gold: new Set(), strength: new Set(), magic: new Set() };
  }
  return promptPaymentSavedTomes[key];
}

// Append tome chips (one per face-up tome of each listed type) to a prompt
// body. Chips default to "used" (tome-first); clicking saves/uses a tome and
// re-renders. Mirrors the market modal's tome UI.
function appendPromptTomeChips(body, savedTomes, tomeAvail, types, onToggle) {
  const total = types.reduce((n, t) => n + (tomeAvail[t] || 0), 0);
  if (total <= 0) return;
  const trow = mk('market-tome-row');
  const tlbl = mk('market-tome-label');
  tlbl.textContent = 'Tomes';
  trow.appendChild(tlbl);

  const chips = mk('market-tome-chips');
  types.forEach(type => {
    for (let i = 0; i < (tomeAvail[type] || 0); i++) {
      const used = !savedTomes[type].has(i);
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = `market-tome-chip market-tome-chip--${type} ${used ? 'is-used' : 'is-saved'}`;
      const img = document.createElement('img');
      img.src = SAIL_TOME_IMAGES[type] || '';
      img.alt = `${type} tome`;
      chip.appendChild(img);
      chip.title = used
        ? `${type} tome — used to pay (click to save)`
        : `${type} tome — saved (click to use)`;
      chip.addEventListener('click', e => {
        e.stopPropagation();
        if (savedTomes[type].has(i)) savedTomes[type].delete(i);
        else savedTomes[type].add(i);
        onToggle();
      });
      chips.appendChild(chip);
    }
  });
  trow.appendChild(chips);
  const hint = mk('market-tome-hint');
  hint.textContent = 'Used tomes pay before treasury and flip back face-up at end of your turn.';
  trow.appendChild(hint);
  body.appendChild(trow);
}

function renderImmediateSlayPayment(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const sourceLabel = (prc?.source_label || 'Effect').toString();
  const monsterName = (prc?.monster_name || '?').toString();
  const goldCost = Number(prc?.gold_cost || 0);
  const strengthCost = Number(prc?.strength_cost || 0);
  const magicCost = Number(prc?.magic_cost || 0);

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — paying for slay of "${monsterName}".`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: `${sourceLabel}: pay to slay`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const me = playerById(state, PLAYER_ID) || {};
  const promptKey = `slay:${immediateSlayPromptKey(prc)}`;
  const thunderAxe = immediateSlayThunderAxe(me, prc, promptKey);
  // Effective costs the payment must cover, after any Thunder Axe waiver.
  let effStrengthCost = strengthCost;
  let effMagicCost = magicCost;
  if (thunderAxe && thunderAxe.mode === 'strength') effStrengthCost = Math.max(0, strengthCost - thunderAxe.strengthWaive);
  if (thunderAxe && thunderAxe.mode === 'magic') effMagicCost = Math.max(0, magicCost - thunderAxe.magicWaive);
  const savedTomes = promptSavedTomeSets(promptKey);
  const tomeAvail = crimsonSeasEnabled(state) ? faceUpTomeCountsForPlayer(me) : { gold: 0, strength: 0, magic: 0 };
  const tomeUse = {
    gold: Math.max(0, tomeAvail.gold - savedTomes.gold.size),
    strength: Math.max(0, tomeAvail.strength - savedTomes.strength.size),
    magic: Math.max(0, tomeAvail.magic - savedTomes.magic.size),
  };
  const gMax = Number(me?.gold_score || 0) + tomeUse.gold;
  const sMax = Number(me?.strength_score || 0) + tomeUse.strength;
  const mMax = Number(me?.magic_score || 0) + tomeUse.magic;

  // Suggested payment: prefer using magic as the wild resource so the player only spends 1 strength
  // (the validator minimum to use magic-as-wild). Fall back to spending more strength when the player
  // doesn't have enough magic to cover the remainder of the strength cost.
  //
  // Also try to keep magic available for any off-turn `exchange m N ...` citizen exchanges in the
  // player's tableau (e.g. a magic-cost convert) so the default doesn't recommend spending magic
  // the player will want for an opponent's harvest. The reservation gives way to a "don't drain the
  // last of the primary resource" rule — if respecting it would force spending the player's last
  // strength, dip into the reserved magic instead.
  const reservation = magicOffTurnExchangeReservation(me);
  const wildBudget = Math.max(0, mMax - effMagicCost - reservation.total);
  const remainingMagicTotal = Math.max(0, mMax - effMagicCost);
  let suggestedStrength = 0;
  let suggestedMagic = effMagicCost;
  if (effStrengthCost > 0) {
    suggestedStrength = Math.max(1, effStrengthCost - wildBudget);
    suggestedStrength = Math.min(suggestedStrength, sMax, effStrengthCost);
    if (suggestedStrength > 1 && suggestedStrength >= sMax && remainingMagicTotal >= effStrengthCost - 1) {
      suggestedStrength = 1;
    }
    suggestedMagic = effMagicCost + Math.max(0, effStrengthCost - suggestedStrength);
  }

  const sub = mk('prompt-modal-note');
  const goldText = goldCost > 0 ? `gold cost ${goldCost}, ` : '';
  sub.textContent = `Slay "${monsterName}" — ${goldText}strength cost ${effStrengthCost}, magic minimum ${effMagicCost}. Magic above the minimum can cover any strength shortfall (gold costs are exact; 1g equivalent rule does not apply to monsters).`;
  body.appendChild(sub);

  if (reservation.total > 0) {
    const reserveNote = mk('prompt-modal-note');
    const detail = reservation.breakdown
      .map(e => (e.count > 1 ? `${e.name} ×${e.count}` : e.name))
      .join(', ');
    reserveNote.textContent = `Suggestion tries to keep ${reservation.total}m for off-turn exchanges (${detail}).`;
    body.appendChild(reserveNote);
  }

  appendPromptResourcesPanel(body, state);

  const payWrap = mk('market-pay-row');
  const goldDisabled = goldCost === 0;
  payWrap.appendChild(mkPayField('', 'pay-g', goldCost, goldCost, goldCost, goldDisabled, goldCost ? `Gold cost: ${goldCost} (exact)` : 'No gold cost', 'gold', gMax));
  payWrap.appendChild(mkPayField('', 'pay-s', 0, sMax, suggestedStrength, false, 'Strength payment', 'strength'));
  payWrap.appendChild(mkPayField('', 'pay-m', effMagicCost, mMax, suggestedMagic, false, 'Magic payment (minimum required)', 'magic'));

  const fields = mk('market-pay-fields');
  fields.appendChild(payWrap);
  body.appendChild(fields);

  if (thunderAxe) {
    const row = mk('market-thunder-axe-row');
    const lbl = mk('market-thunder-axe-label');
    lbl.textContent = thunderAxe.name;
    row.appendChild(lbl);
    const group = mk('market-thunder-axe-options');
    const opts = [{ mode: 'none', text: 'Pay full' }];
    if (thunderAxe.canMagic) opts.push({ mode: 'magic', text: `Ignore ${thunderAxe.magicWaive} Magic` });
    if (thunderAxe.canStrength) opts.push({ mode: 'strength', text: `Ignore ${thunderAxe.strengthWaive} Strength` });
    opts.forEach(o => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `market-thunder-axe-chip ${thunderAxe.mode === o.mode ? 'is-active' : ''}`;
      btn.textContent = o.text;
      btn.title = 'Thunder Axe: ignore part of this monster\u2019s face-value cost when slaying.';
      btn.addEventListener('click', e => {
        e.stopPropagation();
        promptThunderAxeModes[promptKey] = o.mode;
        renderPromptModal(latestGameState || state);
      });
      group.appendChild(btn);
    });
    row.appendChild(group);
    const hint = mk('market-thunder-axe-hint');
    hint.textContent = 'Reduces only the printed cost — magic paid as wild Strength is never waived.';
    row.appendChild(hint);
    body.appendChild(row);
  }

  appendPromptTomeChips(body, savedTomes, tomeAvail, ['gold', 'strength', 'magic'],
    () => renderPromptModal(latestGameState || state));

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  foot.appendChild(promptButton(`Slay ${monsterName}`, () => {
    const p = readMarketPayRow(payWrap);
    const tomePay = {
      gold: Math.min(tomeUse.gold, p.gold),
      strength: Math.min(tomeUse.strength, p.strength),
      magic: Math.min(tomeUse.magic, p.magic),
    };
    const axeSuffix = (thunderAxe && (thunderAxe.mode === 'magic' || thunderAxe.mode === 'strength'))
      ? ` axe:${thunderAxe.mode}` : '';
    confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `slay_pay ${p.gold} ${p.strength} ${p.magic} ${tomePay.gold} ${tomePay.strength} ${tomePay.magic}${axeSuffix}`,
      },
      {
        title: 'Slay monster?',
        message: `Slay "${monsterName}" using ${p.gold} gold, ${p.strength} strength, and ${p.magic} magic.`,
      },
    );
  }));
  foot.appendChild(promptButton('Back (pick a different monster)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'back',
    },
    {
      title: 'Back to monster list?',
      message: 'Return to the monster selection step.',
      confirmLabel: 'Back',
    },
  ), true));
  foot.appendChild(promptButton('Pass (do not slay)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Pass on slay?',
      message: `Decline the may-slay-a-Monster effect from "${sourceLabel}".`,
      confirmLabel: 'Pass',
    },
  ), true));

  openPromptOverlayShell({
    title: `${sourceLabel}: pay to slay "${monsterName}"`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// Maps `pending_required_choice.kind` (paired with action_required="choose_owned_card")
// to user-facing copy. New consumers register their kind here so the renderer can show
// the right title/explainer instead of a generic "Choose one of your cards" fallback.
function chooseOwnedCardCopy(prc, state) {
  const kind = (prc?.kind || '').toString();
  const cardKind = (prc?.card_kind || '').toString().toLowerCase();
  const noun = cardKind === 'monster' ? 'monster'
    : cardKind === 'domain' ? 'domain'
    : cardKind === 'noble' ? 'noble'
    : 'citizen';

  if (kind === 'domain_return_owned') {
    const dn = (prc?.domain_name || 'Domain').toString();
    const res = (prc?.resource || '').toString().toLowerCase();
    const amt = Number(prc?.amount) || 0;
    const rewardLine = amt > 0
      ? ` Reward: ${amt} ${labelForChoiceToken(res)}.`
      : '';
    return {
      title: `${dn}: return a ${noun}`,
      explain: `Return one of your owned ${noun}s to its stack.${rewardLine}`,
      waiting: (label) => `Waiting on ${label} to return a ${noun} for ${dn}.`,
      confirmTitle: `Return ${noun}?`,
      confirmMessage: (nm) => `Return ${noun} "${nm}" to its board stack.`,
      skipLabel: 'Decline (skip activation)',
      skipMessage: `Decline the activation effect on ${dn}.`,
      tableauOwner: 'self',
    };
  }

  if (kind === 'banish_owned_card') {
    return {
      title: `Banish a ${noun}`,
      explain: `Choose one of your owned ${noun}s. It is removed from play permanently (sent to the banish pile) — not face-down like a flip.`,
      waiting: (label) => `Waiting on ${label} to banish a ${noun}.`,
      confirmTitle: `Banish ${noun}?`,
      confirmMessage: (nm) => `Permanently banish ${noun} "${nm}" to the banish pile.`,
      skipLabel: 'Skip (optional)',
      skipMessage: `Skip banishing a ${noun}.`,
      tableauOwner: 'self',
    };
  }

  if (kind === 'banish_center_card') {
    // Nobles live in the Amarynth slots, not a center grid.
    const where = cardKind === 'noble' ? 'Amarynth' : 'the center stacks';
    const placeAdj = cardKind === 'noble' ? 'face-up Amarynth' : 'center-stack';
    return {
      title: `Banish a ${placeAdj} ${noun}`,
      explain: `Choose one of the available ${noun}s from ${where}. It is removed from play permanently (sent to the banish pile)${cardKind === 'noble' ? ', and the slot refills from the noble deck' : ''}.`,
      waiting: (label) => `Waiting on ${label} to banish a ${placeAdj} ${noun}.`,
      confirmTitle: `Banish ${placeAdj} ${noun}?`,
      confirmMessage: (nm) => `Permanently banish ${placeAdj} ${noun} "${nm}" to the banish pile.`,
      skipLabel: 'Skip (optional)',
      skipMessage: `Skip banishing a ${placeAdj} ${noun}.`,
      tableauOwner: 'center',
    };
  }

  if (kind === 'banish_player_citizen') {
    const targetName = prc?.target_player_id
      ? playerDisplayName(state, prc.target_player_id)
      : 'that player';
    return {
      title: `Sunder Bay: banish a citizen from ${targetName}`,
      explain: `Choose one of ${targetName}'s citizens to permanently banish (Sunder Bay).`,
      waiting: (label) => `Waiting on ${label} to banish a citizen (Sunder Bay).`,
      confirmTitle: 'Banish citizen?',
      confirmMessage: (nm) => `Permanently banish "${nm}" from ${targetName}'s tableau.`,
      skipLabel: 'Skip',
      skipMessage: 'Skip banishing a citizen.',
      tableauOwner: 'target',
    };
  }

  if (kind === 'steal_citizen') {
    const targetName = prc?.target_player_id
      ? playerDisplayName(state, prc.target_player_id)
      : 'that player';
    const maxCost = Number(prc?.max_cost ?? 2);
    return {
      title: `Hobb's End: steal a citizen from ${targetName}`,
      explain: `Choose one of ${targetName}'s citizens (cost ≤${maxCost}g) to take for yourself (Hobb's End).`,
      waiting: (label) => `Waiting on ${label} to steal a citizen (Hobb's End).`,
      confirmTitle: 'Steal citizen?',
      confirmMessage: (nm) => `Take "${nm}" from ${targetName}'s tableau and add it to yours.`,
      skipLabel: 'Skip',
      skipMessage: "Skip Hobb's End.",
      tableauOwner: 'target',
    };
  }

  if (kind === 'banish_roll_minion') {
    return {
      title: 'The Northern Wall: banish a Minion',
      explain: 'You may banish one accessible Minion Monster from the center stacks (The Northern Wall). This is optional.',
      waiting: (label) => `Waiting on ${label} to optionally banish a Minion (The Northern Wall).`,
      confirmTitle: 'Banish Minion?',
      confirmMessage: (nm) => `Permanently banish Minion "${nm}" from the center stacks.`,
      skipLabel: 'Decline (keep Minion)',
      skipMessage: 'Decline to banish a Minion this roll phase.',
      tableauOwner: 'center',
    };
  }

  if (kind === 'monster_flip_citizen_targeted') {
    const targetName = prc?.target_player_id
      ? playerDisplayName(state, prc.target_player_id)
      : 'that player';
    return {
      title: `Flip a citizen on ${targetName}'s tableau`,
      explain: `Choose one of ${targetName}'s face-up citizens. It will be flipped face-down (no harvest payout, no role spend) until something restores it.`,
      waiting: (label) => `Waiting on ${label} to flip a citizen on ${targetName}'s tableau.`,
      confirmTitle: 'Flip citizen?',
      confirmMessage: (nm) => `Flip "${nm}" face-down on ${targetName}'s tableau.`,
      skipLabel: 'Skip',
      skipMessage: 'Decline to flip a citizen.',
      tableauOwner: 'target',
    };
  }

  if (kind === 'flip_domain_targeted') {
    const targetName = prc?.target_player_id
      ? playerDisplayName(state, prc.target_player_id)
      : 'that player';
    return {
      title: `Flip a domain on ${targetName}'s tableau`,
      explain: `Choose one of ${targetName}'s face-up domains. Its power is disabled while flipped face-down; at the end of the game it is restored face-up and scored as usual.`,
      waiting: (label) => `Waiting on ${label} to flip a domain on ${targetName}'s tableau.`,
      confirmTitle: 'Flip domain?',
      confirmMessage: (nm) => `Flip "${nm}" face-down on ${targetName}'s tableau.`,
      skipLabel: 'Skip',
      skipMessage: 'Decline to flip a domain.',
      tableauOwner: 'target',
    };
  }

  return {
    title: `Choose one of your ${noun}s`,
    explain: `Choose one of your owned ${noun}s.`,
    waiting: (label) => `Waiting on ${label}.`,
    confirmTitle: 'Confirm?',
    confirmMessage: (nm) => `Choose ${noun} "${nm}".`,
    skipLabel: 'Skip',
    skipMessage: 'Skip.',
    tableauOwner: 'self',
  };
}

function chooseOwnedCardButtonLabel(opt) {
  const nm = (opt?.name || '?').toString();
  return opt?.is_flipped ? `${nm} (flipped)` : nm;
}

function renderChooseOwnedCard(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];
  const copy = chooseOwnedCardCopy(prc, state);
  // Only domain_return_owned (and its reward) directly pays resources. Other
  // owned-card prompts (banish, monster-flip targeting) only nudge future
  // harvests, so we skip the supply strip there.
  const affectsResources = (prc?.kind || '').toString() === 'domain_return_owned';

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = copy.waiting(playerDisplayName(state, reqId));
    body.appendChild(note);
    if (affectsResources) appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: copy.title,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = copy.explain;
  body.appendChild(sub);

  if (!opts.length) {
    const empty = mk('prompt-modal-note');
    empty.textContent = 'No eligible cards.';
    body.appendChild(empty);
  }

  if (affectsResources) appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || '?').toString();
    const label = chooseOwnedCardButtonLabel(o);
    foot.appendChild(promptButton(label, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `choose_owned_card ${idx + 1}`,
      },
      {
        title: copy.confirmTitle,
        message: copy.confirmMessage(nm),
      },
    )));
  });

  if (prc?.allow_skip) {
    foot.appendChild(promptButton(copy.skipLabel, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'skip',
      },
      {
        title: copy.skipLabel,
        message: copy.skipMessage,
        confirmLabel: 'Skip',
      },
    ), true));
  }

  openPromptOverlayShell({
    title: copy.title,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function boardCitizenCountById(state, citizenId) {
  const cid = Number(citizenId);
  if (!Number.isFinite(cid)) return 0;
  const grid = Array.isArray(state?.citizen_grid) ? state.citizen_grid : [];
  let n = 0;
  for (const stack of grid) {
    if (!Array.isArray(stack)) continue;
    for (const card of stack) {
      if (Number(card?.citizen_id) === cid) n += 1;
    }
  }
  return n;
}

function ownedCitizenCountById(state, playerId, citizenId) {
  const cid = Number(citizenId);
  if (!Number.isFinite(cid)) return 0;
  const player = playerById(state, playerId);
  const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
  let n = 0;
  for (const card of citizens) {
    if (Number(card?.citizen_id) === cid) n += 1;
  }
  return n;
}

function chooseOptionButtonLabel(opt, idx, state) {
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
  if (tl === 'count_monster_name') {
    const name = (opt?.name ?? '').toString();
    const res = (opt?.resource ?? '').toString().toLowerCase();
    const mult = Number(opt?.mult);
    const rLabel = labelForChoiceToken(res);
    const mText = Number.isFinite(mult) ? mult : opt?.mult;
    return `+(${mText} × ${name}) ${rLabel}`;
  }
  if (tl === 'count_type') {
    const monsterType = (opt?.monster_type ?? '').toString();
    const res = (opt?.resource ?? '').toString().toLowerCase();
    const mult = Number(opt?.mult);
    const rLabel = labelForChoiceToken(res);
    const mText = Number.isFinite(mult) ? mult : opt?.mult;
    return `+(${mText} × ${monsterType}) ${rLabel}`;
  }
  if (tl === 'tome.choice') {
    const ttype = (opt?.tome_type ?? '').toString().toLowerCase();
    const tLabel = ttype ? ttype.charAt(0).toUpperCase() + ttype.slice(1) : 'Tome';
    return `Gain 1 ${tLabel} Tome (free)`;
  }
  if (tl === 'noble.choice') {
    const name = (opt?.name ?? '').toString().trim();
    return name ? `Gain Noble ${name} (free)` : 'Gain 1 Noble (free)';
  }
  if (tl === 'goods.choice') {
    const gtype = (opt?.goods_type ?? '').toString().trim();
    const gLabel = gtype ? gtype.charAt(0).toUpperCase() + gtype.slice(1) : 'Goods';
    return `Gain ${gLabel} Goods (free)`;
  }
  if (tl === 'citizens_chain') {
    return `Gain ${prettyAmt} citizens`;
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
    const cost = Number(opt?.gold_cost);
    const prettyCost = Number.isFinite(cost) ? cost : 0;
    const have = opt?.citizen_id != null ? ownedCitizenCountById(state, PLAYER_ID, opt.citizen_id) : 0;
    const remaining = opt?.citizen_id != null ? boardCitizenCountById(state, opt.citizen_id) : 0;
    const infoSuffix = ` (Cost: ${prettyCost} Have: ${have} Remain: ${remaining})`;
    const who = name ? `${name} citizen${infoSuffix}` : `${label}${infoSuffix}`;
    return `Gain ${prettyAmt} ${who}${extraSuffix}`;
  }
  return `+${prettyAmt} ${label}`;
}

function renderChoosePrompt(state, chooseCmd) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const pendingChoice = state?.pending_required_choice || null;
  const displayCmd = (pendingChoice?.command_text || req.action_text || chooseCmd || '').toString();

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
      ? `Waiting on required choice: ${displayCmd}`
      : `Waiting on ${playerDisplayName(state, reqId)} — ${displayCmd}`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
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
    const optLabel = chooseOptionButtonLabel(opt, idx, state);
    foot.appendChild(promptButton(optLabel, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `choose ${idx + 1}`,
      },
      {
        title: 'Confirm choice?',
        message: optLabel,
      },
    )));
  });

  appendPromptResourcesPanel(body, state);

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
    appendPromptResourcesPanel(body, state);
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

  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  slots.forEach(s => {
    const ai = Number(s.activation_index);
    const dup = Number.isFinite(ai) && ai > 0 ? ` · #${ai + 1}` : '';
    const ci = Number(s.card_idx);
    const copy = Number.isFinite(ci) ? ` · copy ${ci + 1}` : '';
    const label = `${s.name || ''} (${s.kind} #${s.card_id}${copy}${dup})`;
    const sk = (s.slot_key || '').toString();
    foot.appendChild(promptButton(`Harvest: ${label}`, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'harvest_card',
        harvest_slot_key: sk,
      },
      {
        title: 'Harvest card?',
        message: `Harvest ${label} next.`,
      },
    )));
  });

  openPromptOverlayShell({
    title: 'Harvest',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// Crimson Seas: rolling a 6 forces the active player to place 1 of their
// resources into the Exekratys pool (one prompt per 6 owed).
function renderExekratysOfferingPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const options = Array.isArray(prc?.options) ? prc.options : [];
  const remaining = Number(prc?.remaining || 0);

  const body = mk('prompt-modal-body');
  const note = mk('prompt-modal-note');
  if (!isYou) {
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — placing a resource on Exekratys (rolled a 6).`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({ title: 'Exekratys', dismissible: true, bodyEl: body, footerEl: null });
    return;
  }

  note.textContent = remaining > 1
    ? `You rolled a 6 — place 1 of your resources on Exekratys (${remaining} to place).`
    : 'You rolled a 6 — place 1 of your resources on Exekratys.';
  body.appendChild(note);
  appendPromptResourcesPanel(body, state);

  const labels = { gold: 'Gold', strength: 'Strength', magic: 'Magic' };
  const buttons = options.map(opt => {
    const res = (opt?.resource || '').toString();
    const lbl = labels[res] || res;
    return promptButton(`Place ${lbl}`, () => confirmAndPostGameAction(
      { player_id: PLAYER_ID, action_type: 'act_on_required_action', action: `exekratys_offering ${res}` },
      { title: 'Place on Exekratys', message: `Move 1 ${lbl} from your supply onto Exekratys.`, confirmLabel: `Place ${lbl}` },
    ));
  });

  openPromptOverlayShell({
    title: 'Exekratys offering',
    dismissible: false,
    bodyEl: body,
    footerEl: promptActionsRow(buttons),
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
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Harvest bonus',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  appendPromptResourcesPanel(body, state);

  const foot = promptActionsRow([
    promptButton('+1 Gold', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'gold',
      },
      {
        title: 'Harvest bonus',
        message: 'Take +1 Gold from the bank.',
        confirmLabel: 'Take gold',
      },
    )),
    promptButton('+1 Strength', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'strength',
      },
      {
        title: 'Harvest bonus',
        message: 'Take +1 Strength from the bank.',
        confirmLabel: 'Take strength',
      },
    )),
    promptButton('+1 Magic', () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: 'magic',
      },
      {
        title: 'Harvest bonus',
        message: 'Take +1 Magic from the bank.',
        confirmLabel: 'Take magic',
      },
    )),
  ]);

  openPromptOverlayShell({
    title: 'Harvest bonus',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderGrantDomainRewardPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];
  const sourceName = (prc?.source_name || 'Effect').toString();

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} to choose a free domain from "${sourceName}".`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: `${sourceName}: free domain`,
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = `Choose a domain to acquire for free (from "${sourceName}").`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || '?').toString();
    foot.appendChild(promptButton(nm, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `grant_domain ${idx + 1}`,
      },
      {
        title: 'Take domain?',
        message: `Acquire "${nm}" for free from "${sourceName}".`,
      },
    )));
  });

  openPromptOverlayShell({
    title: `${sourceName}: choose a free domain`,
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// Dampiar's Workshop "you may Sail": offer one free Sail (no regular action
// spent; the sail still pays its own gold/map cost, funded by the +1 Map this
// domain grants). Each button opens the matching Sail modal; the prompt is
// minimizable so the player can instead click a specific target on the mat
// (e.g. a particular noble). Declining resumes the turn.
function renderMaySailPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — may Sail (Dampiar's Workshop).`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: "Dampiar's Workshop: may Sail",
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = 'Take one free Sail action (you still pay its gold/map cost). '
    + 'Pick a destination, or minimize this prompt to click a specific target on the Sail mat. Or decline.';
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const goods = Array.isArray(state?.goods_slots) ? state.goods_slots : [];
  const tomes = Array.isArray(state?.tome_slots) ? state.tome_slots : [];
  const nobles = Array.isArray(state?.noble_slots) ? state.noble_slots : [];
  const pool = state?.exekratys_resources || {};
  const firstNobleSlot = nobles.findIndex(n => !!n);
  const poolTotal = Number(pool.gold || 0) + Number(pool.strength || 0) + Number(pool.magic || 0);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  const openVia = (fn) => () => { removePromptOverlay(); fn(); };

  if (goods.some(g => !!g)) {
    foot.appendChild(promptButton('Araby (buy Goods)', openVia(openArabyGoodsModal)));
  }
  if (tomes.some(t => !!t)) {
    foot.appendChild(promptButton('Nae Aerie (buy Tomes)', openVia(openNaeAerieTomesModal)));
  }
  if (poolTotal > 0) {
    foot.appendChild(promptButton('Exekratys (take resources)', openVia(openExekratysSailModal)));
  }
  if (firstNobleSlot >= 0) {
    foot.appendChild(promptButton('Amarynth (rescue Noble)', openVia(() => openAmarynthNobleModal(firstNobleSlot))));
  }

  foot.appendChild(promptButton('Decline (skip)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Skip Sail?',
      message: "Decline the free Sail from Dampiar's Workshop.",
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: "Dampiar's Workshop: may Sail",
    dismissible: true,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderMayRecruitPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — may recruit a Citizen (Town Crier).`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Town Crier: may recruit',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = 'Recruit one Citizen for free of the duplicate surcharge (you still pay its '
    + 'normal Gold cost). Minimize this prompt, then click a Citizen on the board to recruit it. Or decline.';
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  foot.appendChild(promptButton('Decline (skip)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Skip recruit?',
      message: 'Decline the free Citizen recruit from Town Crier.',
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: 'Town Crier: may recruit',
    dismissible: true,
    bodyEl: body,
    footerEl: foot,
  });
}

function renderBuildDomainPrompt(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const opts = Array.isArray(prc?.options) ? prc.options : [];

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — may build a domain.`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Ararmartin Ridge: may build a Domain',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const sub = mk('prompt-modal-note');
  sub.textContent = 'Choose a domain to build, then set its payment (Magic can cover the Gold cost as wild). Or decline.';
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  opts.forEach((o, idx) => {
    const nm = (o?.name || '?').toString();
    const gc = Number(o?.gold_cost || 0);
    const label = gc > 0 ? `${nm} (${gc} Gold)` : `${nm} (free)`;
    foot.appendChild(promptButton(label, () => confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `build_domain_pick ${idx + 1}`,
      },
      {
        title: 'Build this domain?',
        message: gc > 0 ? `Set payment for "${nm}" (cost ${gc} Gold) next.` : `Build "${nm}" for free.`,
      },
    )));
  });

  foot.appendChild(promptButton('Decline (skip)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Skip domain build?',
      message: 'Decline the optional domain build from Ararmartin Ridge.',
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: 'Ararmartin Ridge: may build a Domain',
    dismissible: false,
    bodyEl: body,
    footerEl: foot,
  });
}

// Ararmartin Ridge build — stage 2: collect payment for the domain picked in
// stage 1, then submit `build_pay <g> <m> [tg ts tm]`. This is a full build
// action: Magic covers the Gold cost as a wild (pay at least 1 gold when using
// magic), and face-up Gold/Magic tomes can help.
function renderBuildDomainPayment(state) {
  const req = state?.action_required || {};
  const reqId = (req?.id || '').toString();
  const isYou = !!(PLAYER_ID && idsMatch(reqId, PLAYER_ID));
  const prc = state?.pending_required_choice || null;
  const domainName = (prc?.domain_name || 'Domain').toString();
  const goldCost = Number(prc?.gold_cost || 0);

  const body = mk('prompt-modal-body');
  if (!isYou) {
    const note = mk('prompt-modal-note');
    note.textContent = `Waiting on ${playerDisplayName(state, reqId)} — paying to build "${domainName}".`;
    body.appendChild(note);
    appendPromptResourcesPanel(body, state);
    openPromptOverlayShell({
      title: 'Ararmartin Ridge: pay to build',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

  const me = playerById(state, PLAYER_ID) || {};
  const promptKey = `build:${prc?.domain_id ?? 'x'}`;
  const savedTomes = promptSavedTomeSets(promptKey);
  const tomeAvail = crimsonSeasEnabled(state) ? faceUpTomeCountsForPlayer(me) : { gold: 0, strength: 0, magic: 0 };
  const tomeUse = {
    gold: Math.max(0, tomeAvail.gold - savedTomes.gold.size),
    strength: 0,
    magic: Math.max(0, tomeAvail.magic - savedTomes.magic.size),
  };
  const gMax = Number(me?.gold_score || 0) + tomeUse.gold;
  const mMax = Number(me?.magic_score || 0) + tomeUse.magic;

  // Suggested split via the shared magic-as-wild affordability (effective pool
  // folds in the tomes the player intends to use).
  const effPlayer = { ...me, gold_score: gMax, magic_score: mMax };
  const suggestion = canAffordCost(effPlayer, { gold: goldCost, strength: 0, magicMin: 0 });

  const sub = mk('prompt-modal-note');
  sub.textContent = `Build "${domainName}" — Gold cost ${goldCost}. Magic can cover the cost as a wild (pay at least 1 gold when using magic).`;
  body.appendChild(sub);
  appendPromptResourcesPanel(body, state);

  const payWrap = mk('market-pay-row');
  payWrap.appendChild(mkPayField('', 'pay-g', 0, gMax, suggestion.payGold ?? 0, false, 'Gold payment', 'gold', gMax));
  payWrap.appendChild(mkPayField('', 'pay-s', 0, 0, 0, true, 'Domains use gold and magic', 'strength'));
  payWrap.appendChild(mkPayField('', 'pay-m', 0, mMax, suggestion.payMagic ?? 0, false, 'Magic payment (wild)', 'magic', mMax));

  const fields = mk('market-pay-fields');
  fields.appendChild(payWrap);
  body.appendChild(fields);

  appendPromptTomeChips(body, savedTomes, tomeAvail, ['gold', 'magic'],
    () => renderPromptModal(latestGameState || state));

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  foot.appendChild(promptButton(`Build ${domainName}`, () => {
    const p = readMarketPayRow(payWrap);
    const tomePay = {
      gold: Math.min(tomeUse.gold, p.gold),
      strength: 0,
      magic: Math.min(tomeUse.magic, p.magic),
    };
    confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `build_pay ${p.gold} ${p.magic} ${tomePay.gold} ${tomePay.strength} ${tomePay.magic}`,
      },
      {
        title: 'Build domain?',
        message: `Build "${domainName}" using ${p.gold} gold and ${p.magic} magic.`,
      },
    );
  }));
  foot.appendChild(promptButton('Back (pick a different domain)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'back',
    },
    {
      title: 'Back to domain list?',
      message: 'Return to the domain selection step.',
      confirmLabel: 'Back',
    },
  ), true));
  foot.appendChild(promptButton('Decline (skip)', () => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'act_on_required_action',
      action: 'skip',
    },
    {
      title: 'Skip domain build?',
      message: 'Decline the optional domain build from Ararmartin Ridge.',
      confirmLabel: 'Skip',
    },
  ), true));

  openPromptOverlayShell({
    title: `Ararmartin Ridge: pay to build "${domainName}"`,
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

// Identity for the "current prompt". When this changes between state pushes
// we auto-restore a minimized prompt so the player sees the new ask. Tracks
// action+id+stage+kind but NOT concurrent.pending — the latter changes as
// other players submit, and we don't want every submission to pop the prompt
// back open while the viewer is browsing the board.
function computePromptFingerprint(state) {
  const req = state?.action_required || {};
  const prc = state?.pending_required_choice || null;
  const ca = state?.concurrent_action || null;
  return [
    String(req.action || ''),
    String(req.id || ''),
    String(prc?.kind || ''),
    String(prc?.stage || ''),
    String(ca?.kind || ''),
  ].join('|');
}

let lastPromptFingerprint = '';

function renderPromptModal(state) {
  if (!CAN_VIEW_GAME) return;

  // If the prompt has materially changed since the last render and the user
  // had it minimized, surface the new state so they don't miss it.
  const fingerprint = computePromptFingerprint(state);
  if (
    typeof isPromptMinimized === 'function' &&
    isPromptMinimized() &&
    fingerprint !== lastPromptFingerprint
  ) {
    restorePromptOverlay();
  }
  lastPromptFingerprint = fingerprint;

  const req = state?.action_required || {};
  const reqId = req?.id || '';
  const reqAction = (req?.action || '').toString();

  // Roll-phase monster events (Corrupted Cleric, Mimic, …) open an
  // event_slay_cost_choice before harvest decisions. Show that first even if
  // a stale harvest_choices gate is still present client-side.
  if (reqAction === 'event_slay_cost_choice' || state?.pending_event_slay_cost) {
    if (reqAction === 'event_slay_cost_choice') {
      renderEventSlayCostPrompt(state);
      return;
    }
  }

  const concurrent = state?.concurrent_action || null;
  const concurrentPending = concurrent && Array.isArray(concurrent.pending) ? concurrent.pending : [];
  if (concurrentPending.length > 0) {
    renderConcurrentPanel(state, concurrent);
    return;
  }

  if (!reqId || reqId === state?.game_id) {
    removePromptOverlay();
    return;
  }

  if (reqAction === 'standard_action') {
    removePromptOverlay();
    return;
  }

  if (reqAction === 'finalize_roll') {
    if (finalizeRollModifierOptions(state).length === 0 && !hasTwilightPalaceReroll(state) && !hasBloodMoonReroll(state)) {
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

  if (reqAction === 'event_gain_action') {
    renderEventGainActionPrompt(state);
    return;
  }

  if (reqAction === 'event_active_choose') {
    renderEventActiveChoosePrompt(state);
    return;
  }

  if (reqAction === 'event_sequence') {
    renderEventSequencePrompt(state);
    return;
  }

  if (reqAction === 'domain_choose_resource') {
    renderDomainChooseResourcePrompt(state);
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

  if (reqAction === 'choose_monster_slay') {
    renderImmediateSlayPickMonster(state);
    return;
  }

  if (reqAction === 'slay_monster_payment') {
    renderImmediateSlayPayment(state);
    return;
  }

  if (reqAction === 'choose_owned_card') {
    renderChooseOwnedCard(state);
    return;
  }

  if (reqAction === 'event_slay_cost_choice') {
    renderEventSlayCostPrompt(state);
    return;
  }

  if (reqAction === 'choose_domain_reward') {
    renderGrantDomainRewardPrompt(state);
    return;
  }

  if (reqAction === 'may_sail') {
    // While a Sail modal is open (launched from this prompt or the mat), don't
    // re-stack the prompt on top of it. The prompt re-renders once the modal
    // closes without completing the bonus sail.
    if (document.getElementById('card-modal-overlay')) return;
    renderMaySailPrompt(state);
    return;
  }

  if (reqAction === 'may_recruit') {
    // Don't re-stack over an open market modal; the player recruits a Citizen
    // through the normal market UI. The prompt re-renders once that modal
    // closes without completing the bonus recruit.
    if (document.getElementById('card-modal-overlay')) return;
    renderMayRecruitPrompt(state);
    return;
  }

  if (reqAction === 'choose_domain_to_build') {
    renderBuildDomainPrompt(state);
    return;
  }

  if (reqAction === 'build_domain_payment') {
    renderBuildDomainPayment(state);
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

  if (reqAction === 'harvest_wild_cost_exchange') {
    renderHarvestWildCostExchangePrompt(state);
    return;
  }

  if (reqAction === 'harvest_wild_gain_exchange') {
    renderHarvestWildGainExchangePrompt(state);
    return;
  }

  if (reqAction === 'relic_wild_exchange') {
    renderRelicWildExchangePrompt(state);
    return;
  }

  if (reqAction === 'harvest_steal') {
    renderHarvestStealPrompt(state);
    return;
  }

  if (reqAction === 'manual_harvest') {
    renderManualHarvestPrompt(state);
    return;
  }

  if (reqAction === 'exekratys_offering') {
    renderExekratysOfferingPrompt(state);
    return;
  }

  if (reqAction !== 'bonus_resource_choice') {
    renderUnknownRequired(state, reqAction, reqId);
    return;
  }

  renderBonusResourcePrompt(state);
}
