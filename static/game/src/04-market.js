// ── Board market actions (hire / build / slay) ─────────────────────────────
function topOfStack(stack) {
  if (!Array.isArray(stack) || stack.length === 0) return null;
  return stack[stack.length - 1];
}

// Inspect the player's tableau for citizens whose off-turn special payout is an `exchange m N ...`
// effect (pay N magic, gain something on someone else's turn). We use this to "reserve" that much
// magic from the magic-first payment suggestion so a player isn't recommended to dump all their
// blue and then find themselves unable to convert during an opponent's harvest. Flipped citizens
// can't activate their off-turn payouts, so they're skipped.
//
// Returns { total, breakdown: [{name, perCard, count}] }; callers can use `total` for the math
// and `breakdown` for an explanatory hint in the UI.
function magicOffTurnExchangeReservation(player) {
  const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
  const byName = new Map();
  for (const c of citizens) {
    if (!c || c.is_flipped) continue;
    const off = (c.special_payout_off_turn ?? '').toString().trim().toLowerCase();
    if (!off.startsWith('exchange m')) continue;
    const m = off.match(/^exchange\s+m\s+(\d+)/);
    if (!m) continue;
    const perCard = Number(m[1]) || 0;
    if (perCard <= 0) continue;
    const name = (c.name ?? '').toString() || '?';
    const entry = byName.get(name) || { name, perCard, count: 0 };
    entry.count += 1;
    byName.set(name, entry);
  }
  let total = 0;
  const breakdown = [];
  for (const entry of byName.values()) {
    total += entry.perCard * entry.count;
    breakdown.push(entry);
  }
  return { total, breakdown };
}

function reservedMagicForOffTurnConverts(player) {
  return magicOffTurnExchangeReservation(player).total;
}

function canAffordCost(player, cost) {
  const G = Number(player?.gold_score || 0);
  const S = Number(player?.strength_score || 0);
  const M = Number(player?.magic_score || 0);
  const goldCost = Number(cost?.gold || 0);
  const strengthCost = Number(cost?.strength || 0);
  const magicMin = Number(cost?.magicMin || 0);

  const remainingMagic = M - magicMin;
  if (remainingMagic < 0) return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold: 0, deficitStrength: 0, remainingMagic: 0, reservedMagic: 0 };

  const deficitGold = Math.max(0, goldCost - G);
  const deficitStrength = Math.max(0, strengthCost - S);

  const reservedMagic = reservedMagicForOffTurnConverts(player);

  if (goldCost > 0 && deficitGold > 0 && G <= 0) return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold, deficitStrength, remainingMagic, reservedMagic };
  if (strengthCost > 0 && deficitStrength > 0 && S <= 0) return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold, deficitStrength, remainingMagic, reservedMagic };

  const ok = (deficitGold + deficitStrength) <= remainingMagic;

  // Magic-first suggestion: cover as much of the primary cost as possible with magic, paying just 1 of
  // the primary resource (the minimum the server validator requires when using magic as a wild). Fall
  // back to spending more primary when the player doesn't have enough magic to cover the remainder.
  //
  // The `reservedMagic` budget reduces how much magic we *prefer* to spend as wild — but only as a
  // suggestion. If the player has no other way to pay the cost, we still dip into the reservation
  // (the action stays affordable; the suggestion just stops being "polite").
  //
  // Don't-drain-the-primary override: if respecting the reservation would force the suggestion to
  // spend the player's *last* unit of the primary resource, and the player has enough total magic
  // (ignoring the reservation) to instead spend just 1 primary, prefer that — even if it dips into
  // the reservation. Burning the last strength/gold is worse than dipping a magic reserve.
  const wildBudget = Math.max(0, remainingMagic - reservedMagic);
  const primaryCost = goldCost > 0 ? goldCost : strengthCost;
  const primaryHave = goldCost > 0 ? G : S;
  let primaryPay = 0;
  let wildPay = 0;
  if (primaryCost > 0) {
    primaryPay = Math.max(1, primaryCost - wildBudget);
    primaryPay = Math.min(primaryPay, primaryHave, primaryCost);
    if (primaryPay > 1 && primaryPay >= primaryHave && remainingMagic >= primaryCost - 1) {
      primaryPay = 1;
    }
    wildPay = Math.max(0, primaryCost - primaryPay);
  }

  const payGold = goldCost > 0 ? primaryPay : 0;
  const payStrength = strengthCost > 0 ? primaryPay : 0;
  const payMagic = magicMin + wildPay;
  return { ok, payGold, payStrength, payMagic, deficitGold, deficitStrength, remainingMagic, reservedMagic };
}

function canAffordMonsterCost(player, cost) {
  const G = Number(player?.gold_score || 0);
  const S = Number(player?.strength_score || 0);
  const M = Number(player?.magic_score || 0);
  const goldCost = Number(cost?.gold || 0);
  const strengthCost = Number(cost?.strength || 0);
  const magicMin = Number(cost?.magicMin || 0);

  const remainingMagic = M - magicMin;
  const deficitGold = Math.max(0, goldCost - G);
  const deficitStrength = Math.max(0, strengthCost - S);
  if (remainingMagic < 0) {
    return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold, deficitStrength, remainingMagic: 0, reservedMagic: 0 };
  }

  const reservedMagic = reservedMagicForOffTurnConverts(player);
  const lacksStrengthFloor = strengthCost > 0 && deficitStrength > 0 && S <= 0;
  const wildBudget = Math.max(0, remainingMagic - reservedMagic);
  let payStrength = 0;
  let wildPay = 0;
  if (strengthCost > 0) {
    payStrength = Math.max(1, strengthCost - wildBudget);
    payStrength = Math.min(payStrength, S, strengthCost);
    if (payStrength > 1 && payStrength >= S && remainingMagic >= strengthCost - 1) {
      payStrength = 1;
    }
    wildPay = Math.max(0, strengthCost - payStrength);
  }

  const payGold = Math.min(goldCost, G);
  const payMagic = magicMin + wildPay;
  const ok = deficitGold === 0 && !lacksStrengthFloor && deficitStrength <= remainingMagic;
  return { ok, payGold, payStrength, payMagic, deficitGold, deficitStrength, remainingMagic, reservedMagic };
}

function ownedNameCount(player, name) {
  const target = (name ?? '').toString();
  if (!target) return 0;
  const starters = Array.isArray(player?.owned_starters) ? player.owned_starters : [];
  const citizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
  let n = 0;
  starters.forEach(c => { if ((c?.name ?? '').toString() === target) n += 1; });
  citizens.forEach(c => {
    if (c?.is_flipped) return;
    if ((c?.name ?? '').toString() === target) n += 1;
  });
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
  const parts = [];
  if (gv !== 0) parts.push(`G ${gv}`);
  if (sv !== 0) parts.push(`S ${sv}`);
  if (mv !== 0) parts.push(`M ${mv}`);
  return parts.join(', ');
}

function pushHarvestHints(hints, card) {
  const hasOn = card.gold_payout_on_turn !== undefined || card.strength_payout_on_turn !== undefined || card.magic_payout_on_turn !== undefined;
  const hasOff = card.gold_payout_off_turn !== undefined || card.strength_payout_off_turn !== undefined || card.magic_payout_off_turn !== undefined;
  if (!hasOn && !hasOff) return;
  const onStr = formatHarvestGSM(card, true);
  const offStr = formatHarvestGSM(card, false);
  if (onStr === offStr) {
    if (onStr) hints.push(`Harvest: ${onStr} (on & off turn)`);
  } else {
    if (onStr) hints.push(`Harvest (on turn): ${onStr}`);
    if (offStr) hints.push(`Harvest (off turn): ${offStr}`);
  }
}

function cardDetailedRules(card) {
  if (!card || typeof card !== 'object') return '';
  const rawText = (card.text ?? '').toString().trim();
  if (rawText) return rawText;

  const parts = [];
  pushHarvestHints(parts, card);

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
  else if (card.event_id != null) {
    // Events can land on any grid — search all three and track which one for global-index math.
    const candidates = [
      { g: state?.monster_grid, offset: 0  },
      { g: state?.citizen_grid, offset: 5  },
      { g: state?.domain_grid,  offset: 15 },
    ];
    for (const { g, offset } of candidates) {
      const stacks = Array.isArray(g) ? g : [];
      for (let i = 0; i < stacks.length; i++) {
        const top = topOfStack(stacks[i]);
        if (!top || top['event_id'] !== card.event_id) continue;
        return { stack: stacks[i], stackIndex: i, top, globalOffset: offset };
      }
    }
    return null;
  }
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
  if (card.event_id   != null) return (loc.globalOffset ?? 0) + loc.stackIndex;
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
      const topCtx = evaluateMarketCardContext(top, state);
      appendMarketFaceUpInspectBody(info, top, topCtx);
      appendMarketActionUI(info, top, topCtx);
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
  overlay._refreshFromLiveState = renderAt;

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
  const shilinaActive = actingPlayer ? hasActionEffectFlag(actingPlayer, 'action.newshilinatower', tn) : false;
  const defiantActive = actingPlayer ? hasActionEffectFlag(actingPlayer, 'action.defiantridge', tn) : false;
  const fortskylerActive = actingPlayer ? hasActionEffectFlag(actingPlayer, 'action.fortskyler', tn) : false;

  const loc = state ? findMarketStack(card, state) : null;
  let blockReason = '';
  let top = loc ? loc.top : null;
  let stackSize = loc ? loc.stack.length : 0;

  if (!state) {
    blockReason = 'Game state not loaded.';
  } else if (!loc) {
    blockReason = 'This card is not on the market (stacks may have changed).';
  } else if ((card.monster_id != null || card.event_id != null) && !top.is_accessible) {
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
  let defiantHint = '';
  let fortskylerHint = '';

  if (actingPlayer && loc && top && !blockReason) {
    if (card.citizen_id != null) {
      baseCost = Number(top.gold_cost || 0);
      surcharge = emeraldActive ? 0 : ownedNameCount(actingPlayer, top.name);
      scaledCost = baseCost + surcharge;
      if (defiantActive) scaledCost = Math.max(0, scaledCost - 1);
      if (shilinaActive) {
        const G = Number(actingPlayer?.gold_score || 0);
        const S = Number(actingPlayer?.strength_score || 0);
        const M = Number(actingPlayer?.magic_score || 0);
        const ok = G + S + M >= scaledCost;
        const payGold = Math.min(G, scaledCost);
        const rem1 = scaledCost - payGold;
        const payStrength = Math.min(S, rem1);
        const payMagic = Math.max(0, scaledCost - payGold - payStrength);
        evalRes = { ok, payGold, payStrength, payMagic };
      } else {
        evalRes = canAffordCost(actingPlayer, { gold: scaledCost, strength: 0, magicMin: 0 });
      }
      dupHint = surcharge ? `base ${baseCost}g + ${surcharge} duplicate(s)` : '';
      emeraldHint = (!surcharge && emeraldActive) ? 'Emerald Stronghold: no duplicate surcharge.' : '';
      defiantHint = defiantActive ? 'Defiant Ridge: −1 citizen cost.' : '';
    } else if (card.domain_id != null) {
      baseCost = Number(top.gold_cost || 0);
      effectiveGold = Math.max(0, baseCost - (pratchettActive ? 1 : 0));
      evalRes = canAffordCost(actingPlayer, { gold: effectiveGold, strength: 0, magicMin: 0 });
      pratchettHint = pratchettActive && baseCost !== effectiveGold ? `base ${baseCost}g − 1 (Pratchett's Plateau)` : '';
    } else if (card.monster_id != null) {
      const rawStr = Number(top.strength_cost || 0) + Number(top.extra_strength_cost || 0);
      evalRes = canAffordMonsterCost(actingPlayer, {
        gold:     Number(top.extra_gold_cost || 0),
        strength: Math.max(0, rawStr - (fortskylerActive ? 1 : 0)),
        magicMin: Number(top.magic_cost || 0) + Number(top.extra_magic_cost || 0),
      });
      fortskylerHint = fortskylerActive && rawStr > 0 ? 'Fort Skyler: −1 monster strength cost.' : '';
    } else if (card.event_id != null) {
      evalRes = canAffordMonsterCost(actingPlayer, {
        gold:     Number(top.extra_gold_cost     || 0),
        strength: Number(top.strength_cost       || 0) + Number(top.extra_strength_cost || 0),
        magicMin: Number(top.magic_cost          || 0) + Number(top.extra_magic_cost    || 0),
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
    shilinaActive,
    defiantActive,
    fortskylerActive,
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
    defiantHint,
    fortskylerHint,
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

function mkPayField(label, cls, minV, maxV, value, disabled, title, resourceIconKey, currentValue) {
  const lab = document.createElement('label');
  lab.className = 'market-pay-field';
  if (title) lab.title = title;
  const span = document.createElement('span');
  span.className = 'market-pay-field-label';
  if (resourceIconKey && TABLEAU_RESOURCE_ICONS[resourceIconKey]) {
    span.classList.add(`market-pay-field-label--${resourceIconKey}`);
    span.classList.add('market-pay-field-label--pill');
    const img = document.createElement('img');
    img.className = 'market-pay-label-icon';
    img.src = TABLEAU_RESOURCE_ICONS[resourceIconKey];
    img.alt = '';
    span.appendChild(img);
    if (currentValue !== undefined && currentValue !== null) {
      span.appendChild(document.createTextNode(String(currentValue)));
    }
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

function appendMarketActionUI(infoEl, card, ctx) {
  const panel = mk('market-action-panel');

  const fx = [];
  if (ctx.emeraldActive) fx.push('Emerald Stronghold: ignore citizen duplicate surcharge');
  if (ctx.pratchettActive) fx.push("Pratchett's Plateau: domains cost 1 less gold");
  if (ctx.shilinaActive) fx.push('New Shilina Tower: may pay Citizen cost with Strength');
  if (ctx.defiantActive) fx.push('Defiant Ridge: citizens cost 1 less');
  if (ctx.fortskylerActive) fx.push('Fort Skyler: monsters cost 1 less Strength');
  if (fx.length) {
    const fb = mk('market-effects-banner');
    fb.textContent = `Active: ${fx.join(' · ')}`;
    panel.appendChild(fb);
  }

  const reservation = magicOffTurnExchangeReservation(ctx.actingPlayer);
  if (reservation.total > 0) {
    const rb = mk('market-effects-banner');
    const detail = reservation.breakdown
      .map(e => (e.count > 1 ? `${e.name} ×${e.count}` : e.name))
      .join(', ');
    rb.textContent = `Suggestion tries to keep ${reservation.total}m for off-turn exchanges (${detail}).`;
    panel.appendChild(rb);
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
    payWrap.appendChild(mkPayField('', 'pay-g', 0, Gmax, pay.payGold ?? 0, inputsDisabled, 'Gold payment', 'gold', Gmax));
    if (ctx.shilinaActive) {
      payWrap.appendChild(mkPayField('', 'pay-s', 0, Smax, pay.payStrength ?? 0, inputsDisabled, 'Strength payment (New Shilina Tower)', 'strength', Smax));
    } else {
      payWrap.appendChild(mkPayField('', 'pay-s', 0, 0, 0, true, 'Citizens use gold and magic', 'strength', Smax));
    }
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic', Mmax));
  } else if (card.domain_id != null) {
    primaryLabel = 'Build domain';
    payWrap.dataset.domainId = String(card.domain_id);
    payWrap.appendChild(mkPayField('', 'pay-g', 0, Gmax, pay.payGold ?? 0, inputsDisabled, 'Gold payment', 'gold', Gmax));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, 0, 0, true, 'Domains use gold and magic', 'strength', Smax));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic', Mmax));
  } else if (card.monster_id != null) {
    primaryLabel = 'Slay monster';
    payWrap.dataset.monsterId = String(card.monster_id);
    const effGold = Number(ctx.top?.extra_gold_cost || 0);
    const goldDisabled = inputsDisabled || effGold === 0;
    payWrap.appendChild(mkPayField('', 'pay-g', effGold, effGold, effGold, goldDisabled, effGold ? `Gold cost: ${effGold} (exact)` : 'No gold cost', 'gold', Gmax));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, Smax, pay.payStrength ?? 0, inputsDisabled, 'Strength payment', 'strength', Smax));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic', Mmax));
  } else if (card.event_id != null) {
    primaryLabel = 'Slay monster';
    payWrap.dataset.eventId = String(card.event_id);
    const effGold = Number(ctx.top?.extra_gold_cost || 0);
    const goldDisabled = inputsDisabled || effGold === 0;
    payWrap.appendChild(mkPayField('', 'pay-g', effGold, effGold, effGold, goldDisabled, effGold ? `Gold cost: ${effGold} (exact)` : 'No gold cost', 'gold', Gmax));
    payWrap.appendChild(mkPayField('', 'pay-s', 0, Smax, pay.payStrength ?? 0, inputsDisabled, 'Strength payment', 'strength', Smax));
    payWrap.appendChild(mkPayField('', 'pay-m', 0, Mmax, pay.payMagic ?? 0, inputsDisabled, 'Magic payment', 'magic', Mmax));
  }

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
  const slayDisabled = !((card.monster_id != null || card.event_id != null) && ctx.canActThisCard);

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
  } else if (card.monster_id != null || card.event_id != null) {
    attachPrimary(promptButton('Slay', () => {
      const p = readMarketPayRow(payWrap);
      const action = {
        player_id: PLAYER_ID,
        action_type: 'slay_monster',
        payment: { gold: p.gold, strength: p.strength, magic: p.magic },
      };
      if (card.monster_id != null) action.monster_id = Number(card.monster_id);
      if (card.event_id   != null) action.event_id   = Number(card.event_id);
      confirmAndPostGameAction(
        action,
        {
          title: 'Slay monster?',
          message: `Slay ${cardLabel} using the amounts set in this panel.`,
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

/** Inline resource value with an explicit sign prefix (e.g. "-3 × icon" or "+1 × icon"). */
function makeSignedModalResource(kind, val, cls, prefix, tipOverride) {
  const wrap = document.createElement('span');
  wrap.className = cls
    ? `modal-stat-value ${cls} modal-resource-inline`
    : 'modal-stat-value modal-resource-inline';
  if (prefix) wrap.appendChild(document.createTextNode(prefix));
  wrap.appendChild(document.createTextNode(String(val)));
  wrap.appendChild(document.createTextNode(' \u00D7 '));
  const img = document.createElement('img');
  img.className = 'modal-resource-icon';
  img.alt = '';
  const iconKey = kind === 'vp' ? 'victory' : kind;
  img.src = TABLEAU_RESOURCE_ICONS[iconKey];
  const names = { gold: 'Gold', strength: 'Strength', magic: 'Magic', vp: 'Victory Points' };
  const tip = (tipOverride && String(tipOverride).trim()) || `${prefix}${val} ${names[kind] || ''}`.trim();
  wrap.title = tip;
  wrap.setAttribute('aria-label', tip);
  wrap.appendChild(img);
  return wrap;
}

/**
 * Compute the *true* purchase cost for `card` (after duplicate surcharges and active
 * passive discounts), preferring values already computed by `evaluateMarketCardContext`
 * when a usable acting player is in view. Falls back to the printed face values
 * (`gold_cost`, `strength_cost`, `magic_cost`) when no context is available — e.g.
 * inspect-only views or non-action phases where no buyer is implied.
 *
 * Returns the costs plus an optional one-line breakdown tooltip explaining any delta
 * from face value (e.g. "base 3g + 2 duplicate(s)" or "base 4g − 1 (Pratchett's Plateau)").
 */
function effectiveMarketCardCosts(card, ctx) {
  const out = {
    gold: Number(card.gold_cost || 0),
    strength: Number(card.strength_cost || 0),
    magic: Number(card.magic_cost || 0),
    goldTip: '',
    strengthTip: '',
    magicTip: '',
  };
  if (!ctx || !ctx.actingPlayer || ctx.blockReason) return out;
  if (card.citizen_id != null) {
    const base = Number(ctx.baseCost || 0);
    const sur = Number(ctx.surcharge || 0);
    out.gold = Number(ctx.scaledCost || 0) || out.gold;
    if (sur > 0) {
      out.goldTip = `base ${base}g + ${sur} duplicate${sur === 1 ? '' : 's'} = ${out.gold}g`;
    } else if (ctx.emeraldActive) {
      out.goldTip = `base ${base}g (Emerald Stronghold waives duplicate surcharge)`;
    }
  } else if (card.domain_id != null) {
    const base = Number(ctx.baseCost || 0);
    out.gold = Number(ctx.effectiveGold || 0);
    if (ctx.pratchettActive && base !== out.gold) {
      out.goldTip = `base ${base}g − 1 (Pratchett's Plateau) = ${out.gold}g`;
    }
  } else if (card.monster_id != null && ctx.top) {
    out.strength = Number(ctx.top.strength_cost || 0) + Number(ctx.top.extra_strength_cost || 0);
    out.magic    = Number(ctx.top.magic_cost    || 0) + Number(ctx.top.extra_magic_cost    || 0);
    if (Number(ctx.top.extra_gold_cost || 0) > 0) {
      out.gold = Number(ctx.top.extra_gold_cost || 0);
    }
  }
  return out;
}

function appendMarketCompactStatLine(infoEl, card, ctx) {
  const row = mk('market-stat-inline');

  const items = [];

  let typeLabel = null;
  if (card.monster_id != null) typeLabel = 'Monster';
  else if (card.event_id != null) typeLabel = 'Event';
  else if (card.citizen_id != null) typeLabel = 'Citizen';
  else if (card.domain_id != null) typeLabel = 'Domain';
  else if (card.duke_id != null) typeLabel = 'Duke';
  else if (card.starter_id != null) typeLabel = 'Starter';
  if (typeLabel) {
    const el = document.createElement('span');
    el.className = 'market-stat-inline-text';
    el.textContent = typeLabel;
    items.push(el);
  }

  const costs = effectiveMarketCardCosts(card, ctx);
  if (costs.gold)     items.push(makeSignedModalResource('gold', costs.gold, 'modal-gold', '-', costs.goldTip));
  if (costs.strength) items.push(makeSignedModalResource('strength', costs.strength, 'modal-str', '-', costs.strengthTip));
  if (costs.magic)    items.push(makeSignedModalResource('magic', costs.magic, 'modal-mag', '-', costs.magicTip));

  if (card.vp_reward)       items.push(makeSignedModalResource('vp', card.vp_reward, 'modal-vp', '+'));
  if (card.gold_reward)     items.push(makeSignedModalResource('gold', card.gold_reward, 'modal-gold', '+'));
  if (card.strength_reward) items.push(makeSignedModalResource('strength', card.strength_reward, 'modal-str', '+'));
  if (card.magic_reward)    items.push(makeSignedModalResource('magic', card.magic_reward, 'modal-mag', '+'));

  if (card.domain_id != null) {
    const req = [];
    if (card.shadow_count)  req.push(`${card.shadow_count} Shadow`);
    if (card.holy_count)    req.push(`${card.holy_count} Holy`);
    if (card.soldier_count) req.push(`${card.soldier_count} Soldier`);
    if (card.worker_count)  req.push(`${card.worker_count} Worker`);
    if (req.length) {
      const el = document.createElement('span');
      el.className = 'market-stat-inline-text';
      el.textContent = `Requires ${req.join(', ')}`;
      items.push(el);
    }
  }

  if (card.citizen_id != null || card.domain_id != null) {
    const rc = citizenRoleCounts(card);
    const rp = [];
    if (rc.sn > 0)  rp.push(`Shadow +${rc.sn}`);
    if (rc.hn > 0)  rp.push(`Holy +${rc.hn}`);
    if (rc.son > 0) rp.push(`Soldier +${rc.son}`);
    if (rc.wn > 0)  rp.push(`Worker +${rc.wn}`);
    if (rp.length) {
      const el = document.createElement('span');
      el.className = 'market-stat-inline-text';
      el.textContent = rp.join(' · ');
      items.push(el);
    }
  }

  if (card.is_flipped) {
    const el = document.createElement('span');
    el.className = 'market-stat-inline-text';
    el.textContent = 'Flipped';
    items.push(el);
  }

  if (!items.length) return;

  items.forEach((el, i) => {
    if (i > 0) {
      const sep = document.createElement('span');
      sep.className = 'market-stat-inline-sep';
      sep.textContent = '\u00B7';
      row.appendChild(sep);
    }
    row.appendChild(el);
  });

  infoEl.appendChild(row);
}

/** Stats, roles, text, and detailed rules for a face-up market card (domain / citizen / monster). */
function appendMarketFaceUpInspectBody(infoEl, card, ctx) {
  appendMarketCompactStatLine(infoEl, card, ctx);

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

  function renderInfo() {
    info.innerHTML = '';

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
      const cardCtx = evaluateMarketCardContext(card, latestGameState);
      appendMarketFaceUpInspectBody(info, card, cardCtx);
      appendMarketActionUI(info, card, cardCtx);
    }
  }

  overlay._refreshFromLiveState = renderInfo;
  renderInfo();

  modal.appendChild(info);
  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

function isBoardMarketCard(card, cardEl) {
  if (!cardEl || !cardEl.closest('.center-board')) return false;
  return card.monster_id != null || card.citizen_id != null || card.domain_id != null || (card.event_id != null && card.is_monster);
}
