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
  foot.appendChild(promptButton(`Keep ${rolled1} + ${rolled2}`, () => {
    openActionConfirmModal({
      title: 'Finalize roll?',
      message: `Keep dice as ${rolled1} + ${rolled2} (total ${rolled1 + rolled2}).`,
      onConfirm: () => sendFinalizeRollChoice(rolled1, rolled2),
    });
  }));
  options.forEach(o => {
    const fromVal = o.die === 1 ? rolled1 : rolled2;
    const d1 = o.die === 1 ? o.target : rolled1;
    const d2 = o.die === 2 ? o.target : rolled2;
    foot.appendChild(promptButton(
      `Die ${o.die}: ${fromVal} → ${o.target} (${o.costGold}g · ${o.domainName})`,
      () => openActionConfirmModal({
        title: 'Finalize roll?',
        message: `Change die ${o.die} from ${fromVal} to ${o.target} (${o.costGold} gold, ${o.domainName}). Resulting dice: ${d1} + ${d2}.`,
        onConfirm: () => sendFinalizeRollChoice(d1, d2),
      }),
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
    const optLabel = chooseOptionButtonLabel(opt, idx);
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
    openPromptOverlayShell({
      title: 'Harvest bonus',
      dismissible: true,
      bodyEl: body,
      footerEl: null,
    });
    return;
  }

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
