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
    if (!GAME_ID || !PLAYER_ID) return;
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
    const cmd = (prompt.action || prc.command || '').toString();
    return `Choose one: ${cmd}`;
  }
  return harvestPromptSubKindBadge(sub);
}

function harvestPromptButtons(prompt, state) {
  if (!prompt) return [];
  const sub = (prompt.sub_kind || '').toString();
  const prc = prompt.pending_required_choice || {};
  const action = (prompt.action || '').toString();

  const post = (response, confirmCopy) => confirmAndPostGameAction(
    {
      player_id: PLAYER_ID,
      action_type: 'submit_concurrent_action',
      kind: 'harvest_choices',
      response: String(response),
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
    return costOpts.map(opt => {
      const r = (opt?.resource || '').toLowerCase();
      const n = Number(opt?.amount || 0);
      return promptButton(`Pay ${n} ${labels[r] || r.toUpperCase()}`, () =>
        post(`wild_cost_resource ${r}`));
    });
  }

  if (sub === 'harvest_wild_gain_exchange') {
    const gainAmt = Number(prc.gain_amount || 0);
    const labels = { g: 'Gold', s: 'Strength', m: 'Magic' };
    return ['g', 's', 'm'].map(r =>
      promptButton(`Gain ${gainAmt} ${labels[r]}`, () =>
        post(`wild_gain_resource ${r}`)));
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

  const myPid = (PLAYER_ID || '').toString();

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

  const roster = mk('prompt-harvest-roster');
  participantIds.forEach(pid => {
    const isMe = String(pid) === myPid;
    const isPending = pending.some(p => String(p) === String(pid));
    const prompt = prompts[String(pid)] || prompts[pid] || null;

    const row = mk('prompt-harvest-row');
    if (isMe) row.classList.add('is-you');
    if (isPending) row.classList.add('is-pending');
    else row.classList.add('is-done');

    const nameEl = mk('prompt-harvest-name');
    const nameText = document.createElement('span');
    nameText.className = 'prompt-harvest-name-text';
    nameText.textContent = playerDisplayName(state, pid);
    nameEl.appendChild(nameText);
    if (isMe) {
      const tag = mk('prompt-harvest-you-tag');
      tag.textContent = 'You';
      nameEl.appendChild(tag);
    }
    if (prompt) {
      const badge = mk('prompt-harvest-sub-badge');
      badge.textContent = harvestPromptSubKindBadge(prompt.sub_kind);
      nameEl.appendChild(badge);
    }
    row.appendChild(nameEl);

    const summaryEl = mk('prompt-harvest-summary');
    if (prompt) {
      summaryEl.textContent = harvestPromptSummary(prompt);
    } else {
      summaryEl.textContent = isPending
        ? 'Resolving harvest…'
        : 'All decisions complete.';
      summaryEl.classList.add('is-muted');
    }
    row.appendChild(summaryEl);

    const actionEl = mk('prompt-harvest-action');
    if (!isPending) {
      actionEl.appendChild(makeHarvestStatusCheck());
    } else if (isMe && prompt) {
      const buttons = harvestPromptButtons(prompt, state);
      if (buttons.length) {
        const actions = mk('prompt-harvest-buttons');
        buttons.forEach(b => actions.appendChild(b));
        actionEl.appendChild(actions);
      } else {
        actionEl.appendChild(makeHarvestStatusSpinner());
      }
    } else {
      actionEl.appendChild(makeHarvestStatusSpinner());
    }
    row.appendChild(actionEl);

    roster.appendChild(row);
  });
  body.appendChild(roster);

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
  if (kind === 'flip_one_citizen') return renderConcurrentFlipCitizen(state, concurrent);
  if (kind === 'harvest_choices') return renderConcurrentHarvestChoices(state, concurrent);

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

  openPromptOverlayShell({
    title: `Harvest: pay ${costLabel}`,
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
  const dn = (prc?.item?.domain_name || 'Domain').toString();
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
        if (payload?.game_state) render(payload.game_state);
        else fetchGameStateFromApi();
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
// in stage 1, then submit `slay_pay <g> <s> <m>`. Gold is only allowed when an
// event added an exact gold slay cost.
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
  const gMax = Number(me?.gold_score || 0);
  const sMax = Number(me?.strength_score || 0);
  const mMax = Number(me?.magic_score || 0);

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
  const wildBudget = Math.max(0, mMax - magicCost - reservation.total);
  const remainingMagicTotal = Math.max(0, mMax - magicCost);
  let suggestedStrength = 0;
  let suggestedMagic = magicCost;
  if (strengthCost > 0) {
    suggestedStrength = Math.max(1, strengthCost - wildBudget);
    suggestedStrength = Math.min(suggestedStrength, sMax, strengthCost);
    if (suggestedStrength > 1 && suggestedStrength >= sMax && remainingMagicTotal >= strengthCost - 1) {
      suggestedStrength = 1;
    }
    suggestedMagic = magicCost + Math.max(0, strengthCost - suggestedStrength);
  }

  const sub = mk('prompt-modal-note');
  const goldText = goldCost > 0 ? `gold cost ${goldCost}, ` : '';
  sub.textContent = `Slay "${monsterName}" — ${goldText}strength cost ${strengthCost}, magic minimum ${magicCost}. Magic above the minimum can cover any strength shortfall (gold costs are exact; 1g equivalent rule does not apply to monsters).`;
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
  payWrap.appendChild(mkPayField('', 'pay-m', magicCost, mMax, suggestedMagic, false, 'Magic payment (minimum required)', 'magic'));

  const fields = mk('market-pay-fields');
  fields.appendChild(payWrap);
  body.appendChild(fields);

  const foot = mk('prompt-modal-actions prompt-modal-actions--wrap');
  foot.appendChild(promptButton(`Slay ${monsterName}`, () => {
    const p = readMarketPayRow(payWrap);
    confirmAndPostGameAction(
      {
        player_id: PLAYER_ID,
        action_type: 'act_on_required_action',
        action: `slay_pay ${p.gold} ${p.strength} ${p.magic}`,
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
  const noun = cardKind === 'monster' ? 'monster' : 'citizen';

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
    return {
      title: `Banish a center-stack ${noun}`,
      explain: `Choose one of the available ${noun}s from the center stacks. It is removed from play permanently (sent to the banish pile).`,
      waiting: (label) => `Waiting on ${label} to banish a center-stack ${noun}.`,
      confirmTitle: `Banish center-stack ${noun}?`,
      confirmMessage: (nm) => `Permanently banish center-stack ${noun} "${nm}" to the banish pile.`,
      skipLabel: 'Skip (optional)',
      skipMessage: `Skip banishing a center-stack ${noun}.`,
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
  sub.textContent = 'Choose a domain to build (paying its Gold cost), or decline.';
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
        title: 'Build domain?',
        message: gc > 0 ? `Build "${nm}" for ${gc} Gold.` : `Build "${nm}" for free.`,
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

  if (reqAction === 'choose_domain_to_build') {
    renderBuildDomainPrompt(state);
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

  if (reqAction === 'harvest_steal') {
    renderHarvestStealPrompt(state);
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
