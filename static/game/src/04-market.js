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

/** Fixed 20 center-board market piles: 5 monsters, 10 citizens, 5 domains (no wrap). */
const MARKET_BOARD_PILE_COUNT = 20;

function marketPileFromGlobalIndex(globalIdx) {
  const g = Math.max(0, Math.min(MARKET_BOARD_PILE_COUNT - 1, globalIdx));
  if (g < 5) return { kind: 'monster', gridProp: 'monster_grid', stackIndex: g };
  if (g < 15) return { kind: 'citizen', gridProp: 'citizen_grid', stackIndex: g - 5 };
  return { kind: 'domain', gridProp: 'domain_grid', stackIndex: g - 15 };
}

function globalMarketPileIndexFromCard(card, state) {
  const loc = findMarketStack(card, state);
  if (!loc) return null;
  if (card.monster_id != null) return loc.stackIndex;
  if (card.citizen_id != null) return 5 + loc.stackIndex;
  if (card.domain_id != null) return 15 + loc.stackIndex;
  return null;
}

function marketStackAtGlobalIndex(state, globalIdx) {
  const slot = marketPileFromGlobalIndex(globalIdx);
  const grid = Array.isArray(state?.[slot.gridProp]) ? state[slot.gridProp] : [];
  const stack = grid[slot.stackIndex];
  return Array.isArray(stack) ? stack : [];
}

/**
 * Center-board market: ‹ › within the current pile; « » walks all 20 piles in order
 * (monsters 1–5, citizens 6–15, domains 16–20), including empty slots. Hire / Build / Slay
 * only on a non-empty pile when viewing its face-up top. Uses live `latestGameState`.
 */
function openBoardMarketStackModal(initialTopCard) {
  if (document.getElementById('game-prompt-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;

  const state0 = latestGameState;
  const g0 = globalMarketPileIndexFromCard(initialTopCard, state0);
  const loc0 = state0 ? findMarketStack(initialTopCard, state0) : null;
  if (g0 == null || !Number.isFinite(g0) || !loc0 || !Array.isArray(loc0.stack) || loc0.stack.length === 0) {
    openMarketCardModal(initialTopCard);
    return;
  }

  let globalPileIndex = g0;
  let cardIdx = loc0.stack.length - 1;

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';

  const modal = mk('card-modal card-modal--stack card-modal--board-stack');
  modal.addEventListener('click', e => e.stopPropagation());

  const main = mk('card-modal-board-stack-main');

  const leftNav = mk('card-modal-board-stack-nav card-modal-board-stack-nav--left');
  const cardPrevBtn = document.createElement('button');
  cardPrevBtn.type = 'button';
  cardPrevBtn.className = 'card-modal-nav card-modal-nav--prev';
  cardPrevBtn.setAttribute('aria-label', 'Toward top of pile (face-up card)');
  cardPrevBtn.textContent = '\u2039';
  const stackPrevBtn = document.createElement('button');
  stackPrevBtn.type = 'button';
  stackPrevBtn.className = 'card-modal-nav card-modal-nav--stack-prev';
  stackPrevBtn.setAttribute('aria-label', 'Previous market pile (of 20)');
  stackPrevBtn.textContent = '\u00ab';

  const center = mk('card-modal-board-stack-center');
  const imgHost = mk('card-modal-stack-img-host');
  const posEl = mk('card-modal-stack-pos');
  posEl.setAttribute('aria-live', 'polite');

  const rightNav = mk('card-modal-board-stack-nav card-modal-board-stack-nav--right');
  const cardNextBtn = document.createElement('button');
  cardNextBtn.type = 'button';
  cardNextBtn.className = 'card-modal-nav card-modal-nav--next';
  cardNextBtn.setAttribute('aria-label', 'Deeper in pile (toward bottom)');
  cardNextBtn.textContent = '\u203a';
  const stackNextBtn = document.createElement('button');
  stackNextBtn.type = 'button';
  stackNextBtn.className = 'card-modal-nav card-modal-nav--stack-next';
  stackNextBtn.setAttribute('aria-label', 'Next market pile (of 20)');
  stackNextBtn.textContent = '\u00bb';

  leftNav.appendChild(cardPrevBtn);
  leftNav.appendChild(stackPrevBtn);
  center.appendChild(imgHost);
  center.appendChild(posEl);
  rightNav.appendChild(cardNextBtn);
  rightNav.appendChild(stackNextBtn);

  main.appendChild(leftNav);
  main.appendChild(center);
  main.appendChild(rightNav);

  const info = mk('card-modal-info');
  modal.appendChild(main);
  modal.appendChild(info);

  function syncFromLiveState() {
    const state = latestGameState;
    const slot = marketPileFromGlobalIndex(globalPileIndex);
    const stack = marketStackAtGlobalIndex(state, globalPileIndex);
    if (stack.length) {
      cardIdx = Math.max(0, Math.min(stack.length - 1, cardIdx));
    } else {
      cardIdx = 0;
    }
    const card = stack.length ? stack[cardIdx] : null;
    return { state, slot, stack, card };
  }

  function renderAt() {
    const { state, slot, stack, card } = syncFromLiveState();
    const isEmpty = stack.length === 0;

    posEl.textContent = isEmpty
      ? `Market pile ${globalPileIndex + 1} / ${MARKET_BOARD_PILE_COUNT} · Empty`
      : `Market pile ${globalPileIndex + 1} / ${MARKET_BOARD_PILE_COUNT} · Card ${cardIdx + 1} / ${stack.length}`;

    imgHost.innerHTML = '';
    if (!isEmpty && card) {
      const img = makeInspectModalImageEl(card);
      if (img) imgHost.appendChild(img);
    }

    cardPrevBtn.disabled = isEmpty || cardIdx >= stack.length - 1;
    cardNextBtn.disabled = isEmpty || cardIdx <= 0;
    stackPrevBtn.disabled = globalPileIndex <= 0;
    stackNextBtn.disabled = globalPileIndex >= MARKET_BOARD_PILE_COUNT - 1;

    info.innerHTML = '';

    if (isEmpty) {
      const heading = document.createElement('h2');
      heading.className = 'modal-card-name';
      heading.textContent = 'Empty pile';
      info.appendChild(heading);
      const note = document.createElement('p');
      note.className = 'modal-card-text';
      const kindLabel = slot.kind === 'monster' ? 'Monster' : slot.kind === 'citizen' ? 'Citizen' : 'Domain';
      note.textContent = `This ${kindLabel} slot has no cards.`;
      info.appendChild(note);
      return;
    }

    const top = topOfStack(stack);
    const viewingTop = cardIdx === stack.length - 1;

    if (viewingTop && isDomainStackFaceDown(top)) {
      const heading = document.createElement('h2');
      heading.className = 'modal-card-name';
      heading.textContent = 'Face-down domain';
      info.appendChild(heading);
      const note = document.createElement('p');
      note.className = 'modal-card-text';
      note.textContent =
        'The next domain in this pile stays face-down until the end of the turn of the player who built from here.';
      info.appendChild(note);
      return;
    }

    if (viewingTop && cardObscuredFromViewer(top)) {
      fillCardModalInspectInfo(info, top);
      return;
    }

    if (viewingTop) {
      const heading = document.createElement('h2');
      heading.className = 'modal-card-name';
      heading.textContent = top.name || '?';
      info.appendChild(heading);
      appendMarketFaceUpInspectBody(info, top);
      appendMarketActionUI(info, top, evaluateMarketCardContext(top, state));
      return;
    }

    fillCardModalInspectInfo(info, card);
  }

  cardPrevBtn.addEventListener('click', e => {
    e.stopPropagation();
    const stack = marketStackAtGlobalIndex(latestGameState, globalPileIndex);
    if (cardIdx < stack.length - 1) {
      cardIdx += 1;
      renderAt();
    }
  });
  cardNextBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (cardIdx > 0) {
      cardIdx -= 1;
      renderAt();
    }
  });
  stackPrevBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (globalPileIndex <= 0) return;
    globalPileIndex -= 1;
    const st = marketStackAtGlobalIndex(latestGameState, globalPileIndex);
    cardIdx = st.length ? st.length - 1 : 0;
    renderAt();
  });
  stackNextBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (globalPileIndex >= MARKET_BOARD_PILE_COUNT - 1) return;
    globalPileIndex += 1;
    const st = marketStackAtGlobalIndex(latestGameState, globalPileIndex);
    cardIdx = st.length ? st.length - 1 : 0;
    renderAt();
  });

  const onStackKey = e => {
    if (e.key === 'ArrowLeft') {
      const stack = marketStackAtGlobalIndex(latestGameState, globalPileIndex);
      if (cardIdx < stack.length - 1) {
        cardIdx += 1;
        renderAt();
        e.preventDefault();
      }
    } else if (e.key === 'ArrowRight') {
      if (cardIdx > 0) {
        cardIdx -= 1;
        renderAt();
        e.preventDefault();
      }
    }
  };
  document.addEventListener('keydown', onStackKey);
  overlay._stackArrowHandler = onStackKey;

  renderAt();

  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
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

  const cardLabel = ((card && card.name) || 'Card').toString().trim() || 'Card';

  if (card.citizen_id != null) {
    attachPrimary(promptButton('Hire', () => {
      const p = readMarketPayRow(payWrap);
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'hire_citizen',
          citizen_id: Number(card.citizen_id),
          payment: { gold: p.gold, strength: p.strength, magic: p.magic },
        },
        {
          title: 'Hire citizen?',
          message: `Hire ${cardLabel} using the gold and magic amounts set in this panel.`,
        },
        () => dismissCardInspectModal(),
      );
    }), hireDisabled);
  } else if (card.domain_id != null) {
    attachPrimary(promptButton('Build', () => {
      const p = readMarketPayRow(payWrap);
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'build_domain',
          domain_id: Number(card.domain_id),
          payment: { gold: p.gold, strength: p.strength, magic: p.magic },
        },
        {
          title: 'Build domain?',
          message: `Build ${cardLabel} using the gold and magic amounts set in this panel.`,
        },
        () => dismissCardInspectModal(),
      );
    }), buildDisabled);
  } else if (card.monster_id != null) {
    attachPrimary(promptButton('Slay', () => {
      const p = readMarketPayRow(payWrap);
      confirmAndPostGameAction(
        {
          player_id: PLAYER_ID,
          action_type: 'slay_monster',
          monster_id: Number(card.monster_id),
          payment: { gold: p.gold, strength: p.strength, magic: p.magic },
        },
        {
          title: 'Slay monster?',
          message: `Slay ${cardLabel} using the strength and magic amounts set in this panel.`,
        },
        () => dismissCardInspectModal(),
      );
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

/** Stats, roles, text, and detailed rules for a face-up market card (domain / citizen / monster). */
function appendMarketFaceUpInspectBody(infoEl, card) {
  appendCardModalStatRows(infoEl, card);

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
    infoEl.appendChild(row);
  }

  if (card.text) {
    const t = document.createElement('p');
    t.className = 'modal-card-text';
    t.textContent = card.text;
    infoEl.appendChild(t);
  }

  const rules = cardDetailedRules(card);
  if (rules && rules !== (card.text || '').toString().trim()) {
    const t2 = document.createElement('p');
    t2.className = 'modal-card-text market-rules-extra';
    t2.textContent = rules;
    infoEl.appendChild(t2);
  }
}

function openMarketCardModal(card) {
  if (document.getElementById('game-prompt-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;

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
  if (isDomainStackFaceDown(card)) {
    heading.textContent = 'Face-down domain';
  } else if (cardObscuredFromViewer(card)) {
    heading.textContent = 'Hidden card';
  } else {
    heading.textContent = card.name || '?';
  }
  info.appendChild(heading);

  if (isDomainStackFaceDown(card)) {
    const note = document.createElement('p');
    note.className = 'modal-card-text';
    note.textContent =
      'The next domain in this pile stays face-down until the end of the turn of the player who built from here.';
    info.appendChild(note);
  } else if (cardObscuredFromViewer(card)) {
    const note = document.createElement('p');
    note.className = 'modal-card-text';
    note.textContent = 'This card is not visible to you right now.';
    info.appendChild(note);
  } else {
    appendMarketFaceUpInspectBody(info, card);
    appendMarketActionUI(info, card, evaluateMarketCardContext(card, latestGameState));
  }

  modal.appendChild(info);
  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

function isBoardMarketCard(card, cardEl) {
  if (!cardEl || !cardEl.closest('.center-board')) return false;
  return card.monster_id != null || card.citizen_id != null || card.domain_id != null;
}
