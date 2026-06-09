// ── Player detail modal (tableau drill-down) ────────────────────────────
function detailPill(label, value) {
  return `<span class="player-detail-pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
}

function detailRolePill(role, label, value) {
  return `<span class="player-detail-pill player-detail-pill--role" title="${escapeHtml(label)}">${roleIconHtml(role)}<strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
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
  if (sn > 0) roleParts.push(`${roleIconHtml('shadow')}Shadow +${sn}`);
  if (hn > 0) roleParts.push(`${roleIconHtml('holy')}Holy +${hn}`);
  if (son > 0) roleParts.push(`${roleIconHtml('soldier')}Soldier +${son}`);
  if (wn > 0) roleParts.push(`${roleIconHtml('worker')}Worker +${wn}`);
  const isDomain = card.domain_id !== undefined && card.domain_id !== null;
  const showRoleRow = (isCitizen || isDomain) && roleParts.length;
  const roleBlock = showRoleRow
    ? `<div class="player-detail-item-sub"><strong>Roles:</strong> ${roleParts.map(p => `<span class="role-inline">${p}</span>`).join(' ')}</div>`
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
  const dukeVisible = !!duke && !cardObscuredFromViewer(duke);
  const dukeName = dukeVisible ? (duke.name || 'Duke') : 'Hidden';
  const dukeText = dukeVisible ? tableauCardFullText(duke) : '';
  const dukeLine = `<div class="player-detail-mini" style="margin-bottom:12px;"><strong>Duke:</strong> ${escapeHtml(dukeVisible ? dukeName : '(hidden from opponents)')}${dukeText ? `<div style="margin-top:6px;white-space:pre-wrap;">${escapeHtml(dukeText)}</div>` : ''}</div>`;

  const kv = `
    <div class="player-detail-kv">
      ${detailPill('Seat', ord >= 0 ? `${ord + 1} / ${players.length}` : '?')}
      ${detailPill('Gold', subject.gold_score ?? 0)}
      ${detailPill('Strength', subject.strength_score ?? 0)}
      ${detailPill('Magic', subject.magic_score ?? 0)}
      ${detailPill('Victory', subject.victory_score ?? 0)}
      ${detailRolePill('shadow', 'Shadow', subject.shadow_count ?? 0)}
      ${detailRolePill('holy', 'Holy', subject.holy_count ?? 0)}
      ${detailRolePill('soldier', 'Soldier', subject.soldier_count ?? 0)}
      ${detailRolePill('worker', 'Worker', subject.worker_count ?? 0)}
      ${detailPill('Minion', subject.minion_count ?? 0)}
      ${detailPill('Titan', subject.titan_count ?? 0)}
      ${detailPill('Warden', subject.warden_count ?? 0)}
      ${detailPill('Boss', subject.boss_count ?? 0)}
      ${detailPill('Beast', subject.beast_count ?? 0)}
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

function _renderPlayerDetailContents(playerId) {
  const state = latestGameState;
  const body = document.getElementById('player-detail-body');
  const panel = document.getElementById('player-detail-modal');
  const titleEl = document.getElementById('player-detail-title');
  if (!body || !panel || !state) return;
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
}

function openPlayerDetailModal(playerId) {
  const panel = document.getElementById('player-detail-modal');
  if (!panel) return;
  if (!latestGameState) return;
  _renderPlayerDetailContents(playerId);
  panel.classList.add('is-open');
  panel.setAttribute('aria-hidden', 'false');
  // Keep the panel current as harvest payouts, hires, slays, etc. land while
  // it's open. Stash the target player on the panel so `_refreshFromLiveState`
  // knows which player to re-render against `latestGameState`.
  panel._refreshPlayerId = playerId;
  panel._refreshFromLiveState = () => {
    if (!panel.classList.contains('is-open')) return;
    _renderPlayerDetailContents(panel._refreshPlayerId);
  };
}

function closePlayerDetailModal() {
  const panel = document.getElementById('player-detail-modal');
  if (!panel) return;
  panel.classList.remove('is-open');
  panel.setAttribute('aria-hidden', 'true');
  panel._refreshFromLiveState = null;
  panel._refreshPlayerId = null;
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
    if (e.key !== 'Escape') return;
    const ac = document.getElementById('action-confirm-modal');
    if (ac && ac.classList.contains('is-open')) return;
    closePlayerDetailModal();
  });
}

// ── Game over overlay ─────────────────────────────────────────────────────
let _gameOverDetailsPage = 0;

function finalScoresSorted(state) {
  return [...(state.final_scores || [])].sort(
    (a, b) => (Number(a.rank) || 99) - (Number(b.rank) || 99)
  );
}

function finalResultFromState(state) {
  if (state.final_result && typeof state.final_result === 'object') {
    return state.final_result;
  }
  const scores = finalScoresSorted(state);
  if (!scores.length) return null;
  const topVp = Number(scores[0].total_vp);
  const vpTied = scores.filter(s => Number(s.total_vp) === topVp);
  if (vpTied.length === 1) {
    return { kind: 'win', headline: `${scores[0].name} wins!`, detail: null };
  }
  const maxTableau = Math.max(...vpTied.map(s => Number(s.tableau_size) || 0));
  const winners = vpTied.filter(s => Number(s.tableau_size) === maxTableau);
  if (winners.length === 1) {
    const w = winners[0];
    return {
      kind: 'tiebreak',
      headline: `${w.name} wins on tie-break!`,
      detail: `Tied at ${topVp} VP; ${w.name} had the larger tableau.`,
    };
  }
  const names = winners.map(s => s.name).join(', ');
  return {
    kind: 'tie',
    headline: 'Tie game!',
    detail: `${names} tied at ${topVp} VP with ${maxTableau} tableau cards each.`,
  };
}

function dukeCardFromScore(s) {
  const duke = s && s.duke;
  if (!duke || typeof duke !== 'object') return null;
  if (duke.card && typeof duke.card === 'object') return duke.card;
  if (duke.duke_id != null) return duke;
  return null;
}

function appendGameOverFooter(panel, state) {
  const shutdown = state.shutdown || null;
  let countdown = panel.querySelector('#game-shutdown-countdown');
  if (!countdown) {
    countdown = mk('game-shutdown-countdown');
    countdown.id = 'game-shutdown-countdown';
    panel.appendChild(countdown);
  }
  countdown.textContent = shutdown?.redirect_at
    ? `Returning to lobby in ${fmtSecondsRemaining(shutdown.redirect_at)}s…`
    : 'Returning to lobby soon…';

  let actions = panel.querySelector('.game-shutdown-actions');
  if (!actions) {
    actions = mk('game-shutdown-actions');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'game-shutdown-btn';
    btn.textContent = 'Go to lobby now';
    btn.addEventListener('click', () => goToLobbyNow());
    actions.appendChild(btn);
    panel.appendChild(actions);
  }
}

function fillGameOverSummaryBody(body, state) {
  body.replaceChildren();
  body.className = 'game-over-body game-over-body-summary';

  const fr = finalResultFromState(state);
  if (fr && fr.headline) {
    const headline = mk('game-over-winner');
    headline.textContent = fr.headline;
    body.appendChild(headline);
    if (fr.detail) {
      const note = mk('game-over-result-note');
      note.textContent = fr.detail;
      body.appendChild(note);
    }
  }

  const list = mk('game-over-standings');
  finalScoresSorted(state).forEach(s => {
    const row = mk('game-over-standing-row');
    const rank = mk('rank');
    rank.textContent = `#${s.rank}`;
    row.appendChild(rank);
    const name = mk('sname');
    name.textContent = s.name;
    row.appendChild(name);
    const total = mk('total');
    total.textContent = `${s.total_vp} VP`;
    row.appendChild(total);
    list.appendChild(row);
  });
  body.appendChild(list);

  const actions = mk('game-over-summary-actions');
  const detailsBtn = document.createElement('button');
  detailsBtn.type = 'button';
  detailsBtn.className = 'game-shutdown-btn game-over-details-btn';
  detailsBtn.textContent = 'Scoring details';
  detailsBtn.addEventListener('click', () => {
    _gameOverDetailsPage = 0;
    showGameOverDetailsView(state);
  });
  actions.appendChild(detailsBtn);
  body.appendChild(actions);
}

function fillGameOverDetailsBody(body, state, pageIndex) {
  body.replaceChildren();
  body.className = 'game-over-body game-over-body-details';

  const scores = finalScoresSorted(state);
  const totalPages = scores.length;
  const idx = Math.max(0, Math.min(pageIndex, Math.max(0, totalPages - 1)));
  _gameOverDetailsPage = idx;
  const s = scores[idx];
  if (!s) return;

  const header = mk('game-over-details-header');
  const backBtn = document.createElement('button');
  backBtn.type = 'button';
  backBtn.className = 'game-over-back-btn';
  backBtn.textContent = '← Summary';
  backBtn.addEventListener('click', () => showGameOverSummaryView(state));
  header.appendChild(backBtn);

  const pageLbl = mk('game-over-details-page');
  pageLbl.textContent = totalPages > 1 ? `${idx + 1} / ${totalPages}` : '';
  header.appendChild(pageLbl);
  body.appendChild(header);

  const title = mk('game-over-details-player');
  title.textContent = `#${s.rank} — ${s.name}`;
  body.appendChild(title);

  const dukeCard = dukeCardFromScore(s);
  const dukeInfo = s.duke;
  if (dukeInfo && dukeInfo.duke_id != null) {
    const dukeBlock = mk('game-over-duke-block');
    const strip = mk('score-duke-strip');
    const img = document.createElement('img');
    img.className = 'score-duke-thumb';
    img.alt = '';
    img.loading = 'lazy';
    img.src = `/card-image/duke/${dukeInfo.duke_id}`;
    strip.appendChild(img);
    const dn = mk('score-duke-name');
    dn.textContent = dukeInfo.name || 'Duke';
    strip.appendChild(dn);
    dukeBlock.appendChild(strip);
    const dukeText = tableauCardFullText(dukeCard);
    if (dukeText) {
      const rules = mk('game-over-duke-text');
      rules.textContent = dukeText;
      dukeBlock.appendChild(rules);
    }
    body.appendChild(dukeBlock);
  } else if (Number(s.duke_vp) > 0) {
    const legacy = mk('score-duke-none');
    legacy.textContent = 'Duke (card not in snapshot)';
    body.appendChild(legacy);
  } else {
    const noDuke = mk('score-duke-none');
    noDuke.textContent = 'No Duke';
    body.appendChild(noDuke);
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
    body.appendChild(list);
  }

  const summary = mk('score-vp-summary');
  summary.textContent = `${s.base_vp} base + ${s.duke_vp} Duke = ${s.total_vp} VP`;
  body.appendChild(summary);

  if (Number(s.tableau_size) > 0 || s.tied_on_vp) {
    const tb = mk('game-over-tableau-note');
    tb.textContent = `Tableau: ${s.tableau_size ?? '?'} cards`;
    body.appendChild(tb);
  }

  if (totalPages > 1) {
    const pager = mk('game-over-details-pager');
    const prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'game-shutdown-btn';
    prev.textContent = 'Previous';
    prev.disabled = idx <= 0;
    prev.addEventListener('click', () => showGameOverDetailsView(state, idx - 1));
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'game-shutdown-btn';
    next.textContent = 'Next';
    next.disabled = idx >= totalPages - 1;
    next.addEventListener('click', () => showGameOverDetailsView(state, idx + 1));
    pager.appendChild(prev);
    pager.appendChild(next);
    body.appendChild(pager);
  }
}

function showGameOverSummaryView(state) {
  const overlay = document.getElementById('game-over-overlay');
  if (!overlay) return;
  const body = overlay.querySelector('.game-over-body');
  if (!body) return;
  overlay.dataset.view = 'summary';
  fillGameOverSummaryBody(body, state);
}

function showGameOverDetailsView(state, pageIndex) {
  const overlay = document.getElementById('game-over-overlay');
  if (!overlay) return;
  const body = overlay.querySelector('.game-over-body');
  if (!body) return;
  overlay.dataset.view = 'details';
  const page = pageIndex != null ? pageIndex : _gameOverDetailsPage;
  fillGameOverDetailsBody(body, state, page);
}

function renderGameOver(state) {
  const existing = document.getElementById('game-over-overlay');
  if (state.phase !== 'game_over' || !state.final_scores) {
    if (existing) existing.remove();
    return;
  }
  if (existing) return;

  const overlay = mk('game-over-overlay');
  overlay.id = 'game-over-overlay';
  overlay.dataset.view = 'summary';

  const panel = mk('game-over-panel');
  const title = mk('game-over-title');
  title.textContent = 'Game Over';
  panel.appendChild(title);

  const body = mk('game-over-body');
  panel.appendChild(body);
  fillGameOverSummaryBody(body, state);

  appendGameOverFooter(panel, state);

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

// ── Card click modal ──────────────────────────────────────────────────────
function makeInspectModalImageEl(card) {
  const url = cardImageUrl(card);
  if (!url) return null;
  const img = document.createElement('img');
  img.className = 'card-modal-img';
  installImgVariantFallback(img);
  img.src = url;
  return img;
}

// ── Margrave artwork chooser ──────────────────────────────────────────────
// Shown once per game (when a Margrave is in play) so each player can pick the
// artwork they prefer, styled after the draft pick grid. The choice is stored
// locally via setMargraveArtworkVariant and applied through cardImageUrl.
let _margraveArtworkPromptGame = null;

function _margravePromptedKey(gid) {
  return 'vck_margrave_prompted_' + gid;
}

function _markMargravePrompted(gid) {
  try { localStorage.setItem(_margravePromptedKey(gid), '1'); } catch (_) {}
}

function maybePromptMargraveArtwork(state) {
  if (!state || !state.game_id) return;
  if (state.phase === 'game_over') return;
  if (!gameIncludesMargrave(state)) return;

  const gid = String(state.game_id);
  if (_margraveArtworkPromptGame === gid) return;

  let prompted = false;
  try { prompted = localStorage.getItem(_margravePromptedKey(gid)) === '1'; } catch (_) {}
  if (prompted) { _margraveArtworkPromptGame = gid; return; }

  // Never stack on top of an open modal/prompt; retry on a later render tick.
  if (document.getElementById('margrave-artwork-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;
  if (getVisiblePromptOverlay()) return;

  _margraveArtworkPromptGame = gid;
  openMargraveArtworkPrompt(gid);
}

async function openMargraveArtworkPrompt(gid) {
  let variants = [];
  try {
    const resp = await fetch(`/card-image-variants/starter/${MARGRAVE_STARTER_ID}`);
    if (resp.ok) {
      const data = await resp.json();
      if (data && Array.isArray(data.variants)) variants = data.variants;
    }
  } catch (_) {}

  if (!variants.length) { _markMargravePrompted(gid); return; }

  // Something may have grabbed the screen while we were fetching. If a blocking
  // prompt appeared, defer (clear the session guard so we retry); otherwise
  // bail if a chooser/modal is already up.
  if (getVisiblePromptOverlay()) { _margraveArtworkPromptGame = null; return; }
  if (document.getElementById('margrave-artwork-overlay')) return;
  if (document.getElementById('card-modal-overlay')) return;

  _markMargravePrompted(gid);
  _buildMargraveArtworkOverlay(variants);
}

function closeMargraveArtworkOverlay() {
  const overlay = document.getElementById('margrave-artwork-overlay');
  if (!overlay) return;
  if (overlay._escHandler) document.removeEventListener('keydown', overlay._escHandler);
  overlay.remove();
}

function _buildMargraveArtworkOverlay(variants) {
  const current = getMargraveArtworkVariant();
  let selected = variants.includes(current) ? current : '';

  const overlay = document.createElement('div');
  overlay.id = 'margrave-artwork-overlay';
  overlay.className = 'card-modal-overlay margrave-art-overlay';

  const modal = mk('card-modal margrave-art-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const title = document.createElement('h2');
  title.className = 'margrave-art-title';
  title.textContent = 'Choose your Margrave artwork';
  modal.appendChild(title);

  const sub = document.createElement('p');
  sub.className = 'margrave-art-sub';
  sub.textContent = 'This game includes Margraves. Pick the artwork you’d like to see — it’s cosmetic and only changes your view. Close this to keep the original.';
  modal.appendChild(sub);

  const grid = document.createElement('div');
  grid.className = 'draft-grid margrave-art-grid';
  modal.appendChild(grid);

  const actions = document.createElement('div');
  actions.className = 'draft-actions margrave-art-actions';
  const spacer = document.createElement('span');
  spacer.className = 'draft-vote-status';
  actions.appendChild(spacer);
  const confirmBtn = document.createElement('button');
  confirmBtn.type = 'button';
  confirmBtn.className = 'lobby-btn lobby-btn-primary';
  confirmBtn.textContent = 'Use this artwork';
  actions.appendChild(confirmBtn);
  modal.appendChild(actions);

  const syncSelection = () => {
    grid.querySelectorAll('.draft-card').forEach(c => {
      c.classList.toggle('draft-card--selected', c.dataset.variant === selected);
    });
    confirmBtn.disabled = !selected;
  };

  variants.forEach((v, i) => {
    const card = document.createElement('div');
    card.className = 'draft-card';
    card.dataset.variant = v;

    const img = document.createElement('img');
    img.className = 'draft-card-img';
    img.loading = 'lazy';
    img.alt = `Margrave artwork ${i + 1}`;
    installImgVariantFallback(img);
    img.src = `/card-image/starter/${MARGRAVE_STARTER_ID}?variant=${encodeURIComponent(v)}`;
    card.appendChild(img);

    const label = document.createElement('div');
    label.className = 'draft-card-label';
    label.textContent = `Artwork ${i + 1}`;
    card.appendChild(label);

    card.addEventListener('click', () => { selected = v; syncSelection(); });
    grid.appendChild(card);
  });
  syncSelection();

  confirmBtn.addEventListener('click', () => {
    if (!selected) return;
    setMargraveArtworkVariant(selected);
    closeMargraveArtworkOverlay();
    if (typeof latestGameState !== 'undefined' && latestGameState) {
      lastRenderedStateJson = '';  // force the dedup guard to rebuild the board
      render(latestGameState);
    }
  });

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'card-modal-close';
  closeBtn.setAttribute('aria-label', 'Keep current artwork');
  closeBtn.textContent = '\u00d7';
  closeBtn.addEventListener('click', closeMargraveArtworkOverlay);
  modal.appendChild(closeBtn);

  overlay.appendChild(modal);
  overlay.addEventListener('click', closeMargraveArtworkOverlay);
  const onKey = e => { if (e.key === 'Escape') closeMargraveArtworkOverlay(); };
  overlay._escHandler = onKey;
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
}

function fillCardModalInspectInfo(infoEl, card, ownerPlayerId) {
  infoEl.innerHTML = '';
  const heading = document.createElement('h2');
  heading.className = 'modal-card-name';
  if (cardObscuredFromViewer(card)) {
    if (isDomainStackFaceDown(card)) {
      heading.textContent = 'Face-down domain';
    } else if (card?.duke_id != null) {
      heading.textContent = 'Hidden duke';
    } else {
      heading.textContent = 'Hidden card';
    }
  } else {
    heading.textContent = card.name || '?';
  }
  infoEl.appendChild(heading);

  if (cardObscuredFromViewer(card)) {
    const isHiddenDuke = card?.duke_id != null;
    const dukeTableData = isHiddenDuke && ownerDukeVpTable(ownerPlayerId).length;
    const note = document.createElement('p');
    note.className = 'modal-card-text';
    if (isDomainStackFaceDown(card)) {
      note.textContent = 'The next domain in this pile stays face-down until the end of the turn of the player who built from here.';
    } else if (isHiddenDuke) {
      note.textContent = dukeTableData
        ? "This duke is hidden, but here's how every duke except yours would score for this tableau right now."
        : "This duke is hidden from opponents. You'll see its identity at end-of-game scoring.";
    } else {
      note.textContent = 'This card is not visible to you right now.';
    }
    infoEl.appendChild(note);
    if (isHiddenDuke) {
      appendOpponentDukeVpTable(infoEl, ownerPlayerId);
    }
  } else {
    appendCardModalStatRows(infoEl, card);
    if (card.text) {
      const t = document.createElement('p');
      t.className = 'modal-card-text';
      t.textContent = card.text;
      infoEl.appendChild(t);
    }
    if (card?.duke_id != null) {
      appendDukeVpProjectionBlock(infoEl, card);
    }
  }
}

// ── Duke modal: live "if the game ended right now" VP projection ─────────
// The server attaches `duke_vp_projection` to the viewer's own player payload
// (see _serialize_game_for_player). We surface it in the duke inspect modal
// so the player can see how their resources / tableau translate to VP via
// their duke's multipliers in real time.
function findDukeOwnerInState(dukeCard) {
  const state = latestGameState;
  if (!state || !dukeCard || dukeCard.duke_id == null) return null;
  const players = state.player_list || [];
  for (const p of players) {
    const owned = Array.isArray(p?.owned_dukes) ? p.owned_dukes : [];
    if (owned.some(d => d && d.duke_id != null && d.duke_id === dukeCard.duke_id)) {
      return p;
    }
  }
  return null;
}

function appendDukeVpProjectionBlock(infoEl, dukeCard) {
  const owner = findDukeOwnerInState(dukeCard);
  const proj = owner && owner.duke_vp_projection;
  if (!proj) return;

  const wrap = mk('duke-vp-projection');

  const lines = Array.isArray(proj.duke_vp_breakdown) ? proj.duke_vp_breakdown : [];
  if (lines.length) {
    const list = mk('duke-vp-breakdown');
    lines.forEach(line => {
      const li = mk('duke-vp-line');
      const top = mk('duke-vp-line-top');
      const lbl = mk('duke-vp-line-label');
      lbl.textContent = line.label || '';
      const val = mk('duke-vp-line-vp');
      val.textContent = `+${Number(line.vp || 0)} VP`;
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
    wrap.appendChild(list);
  } else {
    const empty = mk('duke-vp-projection-empty');
    empty.textContent = 'No duke VP yet — keep building toward this duke\'s multipliers.';
    wrap.appendChild(empty);
  }

  const summary = mk('duke-vp-projection-summary');
  summary.textContent =
    `${Number(proj.base_vp || 0)} base + ${Number(proj.duke_vp || 0)} Duke = ${Number(proj.total_vp || 0)} VP`;
  wrap.appendChild(summary);

  infoEl.appendChild(wrap);
}

function playerFromState(playerId) {
  const state = latestGameState;
  if (!state || playerId == null) return null;
  const players = state.player_list || [];
  return players.find(p => idsMatch(p.player_id, playerId)) || null;
}

function ownerDukeVpTable(ownerPlayerId) {
  const owner = playerFromState(ownerPlayerId);
  return owner && Array.isArray(owner.duke_vp_table) ? owner.duke_vp_table : [];
}

// ── Hidden opponent duke: "every duke vs this tableau" VP list ────────────
// When inspecting an opponent's face-down duke we can't reveal which duke they
// hold, so instead we list every catalog duke and the VP it would score for
// their current tableau (server-computed via `duke_vp_table`, identical math
// for every duke so nothing leaks). The one row that maps to the *viewer's*
// own duke is swapped to a "You" row showing the viewer's own projection
// (their tableau), matching what they'd see inspecting their own duke.
function appendOpponentDukeVpTable(infoEl, ownerPlayerId) {
  const table = ownerDukeVpTable(ownerPlayerId);
  if (!table.length) return;

  const me = playerFromState(PLAYER_ID);
  const myDuke = me && Array.isArray(me.owned_dukes) && me.owned_dukes.length ? me.owned_dukes[0] : null;
  const myDukeId = myDuke && myDuke.duke_id != null ? myDuke.duke_id : null;
  const myProj = me && me.duke_vp_projection ? me.duke_vp_projection : null;

  const rows = table.map(entry => {
    if (myDukeId != null && entry.duke_id === myDukeId) {
      return {
        isYou: true,
        name: entry.name,
        total_vp: myProj ? Number(myProj.total_vp || 0) : Number(entry.total_vp || 0),
      };
    }
    return {
      isYou: false,
      name: entry.name,
      total_vp: Number(entry.total_vp || 0),
    };
  });
  rows.sort((a, b) => (b.total_vp - a.total_vp) || String(a.name).localeCompare(String(b.name)));

  const wrap = mk('duke-vp-table');
  rows.forEach(r => {
    const row = mk('duke-vp-table-row');
    if (r.isYou) row.classList.add('is-you');

    const nameWrap = mk('duke-vp-table-name');
    const nm = document.createElement('span');
    nm.className = 'duke-vp-table-name-text';
    nm.textContent = r.name || 'Duke';
    nameWrap.appendChild(nm);
    if (r.isYou) {
      const tag = mk('prompt-modal-resources-you-tag');
      tag.textContent = 'You';
      nameWrap.appendChild(tag);
    }
    row.appendChild(nameWrap);

    const vp = mk('duke-vp-table-vp');
    vp.textContent = `${r.total_vp} VP`;
    row.appendChild(vp);

    wrap.appendChild(row);
  });

  infoEl.appendChild(wrap);
}

function openCardStackInspectModal(cards, startIndex) {
  if (getVisiblePromptOverlay()) return;
  if (document.getElementById('card-modal-overlay')) return;
  const arr = Array.isArray(cards) ? cards.filter(Boolean) : [];
  if (arr.length < 2) {
    if (arr.length === 1) openCardModal(arr[0]);
    return;
  }

  let idx = Number(startIndex);
  if (!Number.isFinite(idx)) idx = arr.length - 1;
  idx = Math.max(0, Math.min(arr.length - 1, idx));

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';

  const modal = mk('card-modal card-modal--stack');
  modal.addEventListener('click', e => e.stopPropagation());

  const layout = mk('card-modal-stack-layout');
  const visual = mk('card-modal-stack-visual');

  const prevBtn = document.createElement('button');
  prevBtn.type = 'button';
  prevBtn.className = 'card-modal-nav card-modal-nav--prev';
  prevBtn.setAttribute('aria-label', 'Toward top of stack (newer card)');
  prevBtn.textContent = '\u2039';

  const imgHost = mk('card-modal-stack-img-host');

  const nextBtn = document.createElement('button');
  nextBtn.type = 'button';
  nextBtn.className = 'card-modal-nav card-modal-nav--next';
  nextBtn.setAttribute('aria-label', 'Deeper in stack (older card)');
  nextBtn.textContent = '\u203a';

  const posEl = mk('card-modal-stack-pos');
  posEl.setAttribute('aria-live', 'polite');

  const info = mk('card-modal-info');

  visual.appendChild(prevBtn);
  visual.appendChild(imgHost);
  visual.appendChild(nextBtn);
  layout.appendChild(visual);
  layout.appendChild(posEl);
  modal.appendChild(layout);
  modal.appendChild(info);

  const renderAt = i => {
    idx = i;
    const c = arr[idx];
    imgHost.innerHTML = '';
    const img = makeInspectModalImageEl(c);
    if (img) imgHost.appendChild(img);
    fillCardModalInspectInfo(info, c);
    posEl.textContent = `${idx + 1} / ${arr.length}`;
    prevBtn.disabled = idx >= arr.length - 1;
    nextBtn.disabled = idx <= 0;
  };

  prevBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (idx < arr.length - 1) renderAt(idx + 1);
  });
  nextBtn.addEventListener('click', e => {
    e.stopPropagation();
    if (idx > 0) renderAt(idx - 1);
  });

  const onStackKey = e => {
    if (e.key === 'ArrowLeft' && idx < arr.length - 1) {
      e.preventDefault();
      renderAt(idx + 1);
    } else if (e.key === 'ArrowRight' && idx > 0) {
      e.preventDefault();
      renderAt(idx - 1);
    }
  };
  document.addEventListener('keydown', onStackKey);
  overlay._stackArrowHandler = onStackKey;

  // Keep the info panel of the currently-shown card in sync with live state
  // (duke VP projection, visibility/flip toggles, etc.). Image + nav stay put.
  overlay._refreshFromLiveState = () => {
    fillCardModalInspectInfo(info, arr[idx]);
  };

  renderAt(idx);

  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
  document.body.appendChild(overlay);
}

document.addEventListener('click', e => {
  const cardEl = e.target.closest('.card[data-card]');
  if (!cardEl) return;

  const stackHost = cardEl.closest('.tableau-card-stack[data-stack]');
  if (stackHost && !cardEl.closest('.center-board')) {
    let arr;
    try {
      arr = JSON.parse(stackHost.dataset.stack);
    } catch (_) {
      arr = null;
    }
    if (Array.isArray(arr) && arr.length > 1) {
      // Honor the clicked card's stack index so tapping a partially-visible
      // older card in the monster fan opens the inspector on that card.
      let startIdx = arr.length - 1;
      const rawIdx = cardEl.dataset.stackIndex;
      if (rawIdx != null && rawIdx !== '') {
        const n = Number(rawIdx);
        if (Number.isFinite(n) && n >= 0 && n < arr.length) startIdx = n;
      }
      openCardStackInspectModal(arr, startIdx);
      return;
    }
  }

  const card = JSON.parse(cardEl.dataset.card);
  if (isBoardMarketCard(card, cardEl)) {
    openBoardMarketStackModal(card);
    return;
  }
  // A hidden opponent duke renders as an anonymous card back, so the card data
  // carries no owner. Recover the owning seat so the inspect modal can list
  // each catalog duke's projected VP against that player's tableau.
  const seatEl = cardEl.closest('.seat[data-player-id]');
  const ownerPlayerId = seatEl ? seatEl.dataset.playerId : null;
  openCardModal(card, ownerPlayerId);
});

function openCardModal(card, ownerPlayerId) {
  if (getVisiblePromptOverlay()) return;
  if (document.getElementById('card-modal-overlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'card-modal-overlay';
  overlay.className = 'card-modal-overlay';

  const modal = mk('card-modal');
  modal.addEventListener('click', e => e.stopPropagation());

  const img = makeInspectModalImageEl(card);
  if (img) modal.appendChild(img);

  const info = mk('card-modal-info');
  fillCardModalInspectInfo(info, card, ownerPlayerId);
  modal.appendChild(info);

  // Re-render the info panel whenever the global game state updates so
  // anything live-derived (e.g. the duke VP projection) stays current.
  // The image element doesn't depend on game state, so we leave it alone.
  overlay._refreshFromLiveState = () => {
    fillCardModalInspectInfo(info, card, ownerPlayerId);
  };

  overlay.appendChild(modal);
  mountCardInspectOverlay(overlay, modal);
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
  else if (card.starter_id  != null) push('Type', 'Starter', null, null, false);

  if (card.gold_cost)       push('Gold cost',    card.gold_cost,       'modal-gold', 'gold', false);
  if (card.strength_cost)   push('Str cost',     card.strength_cost,   'modal-str',  'strength', false);
  if (card.magic_cost)      push('Mag cost',     card.magic_cost,      'modal-mag',  'magic', false);
  if (card.vp_reward)      push('VP reward',    card.vp_reward,       'modal-vp',   'vp', false);
  if (card.gold_reward)     push('Gold reward',  card.gold_reward,     'modal-gold', 'gold', true);
  if (card.strength_reward) push('Str reward',   card.strength_reward, 'modal-str',  'strength', true);
  if (card.magic_reward)    push('Mag reward',   card.magic_reward,    'modal-mag',  'magic', true);

  if (card.domain_id != null) {
    const reqRoles = [
      ['shadow',  'Shadow',  card.shadow_count],
      ['holy',    'Holy',    card.holy_count],
      ['soldier', 'Soldier', card.soldier_count],
      ['worker',  'Worker',  card.worker_count],
    ].filter(([, , n]) => n);
    if (reqRoles.length) {
      const html = reqRoles
        .map(([role, label, n]) => `<span class="role-inline">${roleIconHtml(role)}${n} ${label}</span>`)
        .join(' ');
      const text = reqRoles.map(([, label, n]) => `${n} ${label}`).join(', ');
      rows.push({ label: 'Requires', value: text, html, cls: '', resource: null, leadingPlus: false });
    }
  }

  if (card.starter_id != null) {
    const m1 = card.roll_match1, m2 = card.roll_match2;
    if (m1 && m2 && m1 !== m2) push('Rolls', `${m1}, ${m2}`);
    else if (m1) push('Roll', String(m1));
  }

  if (card.is_flipped) push('Status', 'Flipped');

  return rows;
}

let actionConfirmHandler = null;

function closeActionConfirmModal() {
  const backdrop = document.getElementById('action-confirm-modal');
  if (!backdrop) return;
  backdrop.classList.remove('is-open');
  backdrop.setAttribute('aria-hidden', 'true');
  actionConfirmHandler = null;
  const ok = document.getElementById('action-confirm-ok');
  const cancel = document.getElementById('action-confirm-cancel');
  if (ok) ok.disabled = false;
  if (cancel) cancel.disabled = false;
}

function openActionConfirmModal(opts) {
  const backdrop = document.getElementById('action-confirm-modal');
  const titleEl = document.getElementById('action-confirm-title');
  const msgEl = document.getElementById('action-confirm-message');
  const ok = document.getElementById('action-confirm-ok');
  if (!backdrop || !titleEl || !msgEl || !ok) return;
  if (backdrop.classList.contains('is-open')) return;
  titleEl.textContent = (opts.title || 'Confirm').toString();
  msgEl.textContent = (opts.message || '').toString();
  ok.textContent = (opts.confirmLabel || 'Confirm').toString();
  actionConfirmHandler = opts.onConfirm;
  backdrop.classList.add('is-open');
  backdrop.setAttribute('aria-hidden', 'false');
  ok.focus();
}

function confirmAndPostGameAction(body, ui, afterSuccess) {
  const title = ui && ui.title != null ? String(ui.title) : 'Confirm action';
  const message = ui && ui.message != null ? String(ui.message) : '';
  const confirmLabel = ui && ui.confirmLabel != null ? String(ui.confirmLabel) : 'Confirm';
  openActionConfirmModal({
    title,
    message,
    confirmLabel,
    onConfirm: async () => {
      const ok = await postGameAction(body);
      if (ok && typeof afterSuccess === 'function') afterSuccess();
    },
  });
}

/**
 * Detect on-screen keyboard presence by comparing the visual viewport (which shrinks
 * when the soft keyboard opens on iOS / Android) to the layout viewport. Toggles
 * `body.is-virtual-keyboard-open` so CSS can collapse non-essential modal chrome
 * (e.g. the large card image) and the focused input stays in view above the keyboard.
 * Also nudges the active input into the visible area after focus so number entry
 * doesn't disappear behind the keyboard.
 */
function initVirtualKeyboardWatcher() {
  const KB_THRESHOLD_PX = 150;

  function setKbOpen(open) {
    document.body.classList.toggle('is-virtual-keyboard-open', !!open);
  }

  function scrollFocusedInputIntoView() {
    const el = document.activeElement;
    if (!el) return;
    const tag = el.tagName;
    if (tag !== 'INPUT' && tag !== 'TEXTAREA') return;
    try {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } catch (_) {
      try { el.scrollIntoView(); } catch (_) { /* ignore */ }
    }
  }

  const vv = window.visualViewport;
  if (vv) {
    const recheck = () => {
      const layoutH = window.innerHeight || vv.height;
      const open = (layoutH - vv.height) > KB_THRESHOLD_PX;
      setKbOpen(open);
      if (open) requestAnimationFrame(scrollFocusedInputIntoView);
    };
    vv.addEventListener('resize', recheck);
    vv.addEventListener('scroll', recheck);
    recheck();
  }

  document.addEventListener('focusin', e => {
    const t = e.target;
    if (!t || (t.tagName !== 'INPUT' && t.tagName !== 'TEXTAREA')) return;
    // Wait for the keyboard animation + viewport resize before deciding so the
    // kb-open class reflects whether the soft keyboard actually appeared. On
    // desktop the class stays off and we skip the scroll, avoiding stray jumps.
    setTimeout(() => {
      if (document.activeElement !== t) return;
      if (!document.body.classList.contains('is-virtual-keyboard-open')) return;
      try { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
      catch (_) { /* ignore */ }
    }, 280);
  });
}

function initActionConfirmModal() {
  const backdrop = document.getElementById('action-confirm-modal');
  const ok = document.getElementById('action-confirm-ok');
  const cancel = document.getElementById('action-confirm-cancel');
  if (!backdrop || !ok || !cancel) return;

  const runAndClose = async () => {
    const fn = actionConfirmHandler;
    if (!fn) return;
    ok.disabled = true;
    cancel.disabled = true;
    closeActionConfirmModal();
    try {
      await fn();
    } catch (e) {
      console.error(e);
    }
  };

  ok.addEventListener('click', () => {
    void runAndClose();
  });
  cancel.addEventListener('click', () => closeActionConfirmModal());
  backdrop.addEventListener('click', e => {
    if (e.target === backdrop) closeActionConfirmModal();
  });
  document.addEventListener(
    'keydown',
    e => {
      if (e.key !== 'Escape') return;
      if (!backdrop.classList.contains('is-open')) return;
      e.preventDefault();
      e.stopPropagation();
      closeActionConfirmModal();
    },
    true,
  );
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
  clearPromptMinimizationOnPromptGone();
}

// ── Prompt minimize ("Peek board") ────────────────────────────────────────
//
// Non-dismissible prompts (free-slay, finalize_roll, choose_owned_card, etc.)
// can be temporarily hidden so the player can inspect the board. While the
// prompt is minimized:
//   • a floating "Open prompt" button (FAB) is rendered bottom-right
//   • body scroll is unlocked so the player can pan/scroll the board
//   • the market action panel (Hire / Build / Slay payment fields + buttons)
//     is suppressed inside any card-inspect modal the player opens — see
//     `appendMarketActionUI` in 04-market.js. The player can still read card
//     details, just not trigger market actions until they resume the prompt.
//   • the prompt overlay stays in the DOM (display:none) so updates from new
//     game state apply in-place; if the prompt's fingerprint changes
//     (different action / stage / kind) we auto-restore so the player can
//     see what the engine is asking for now
let promptMinimized = false;
let promptResumeFabEl = null;

function isPromptMinimized() {
  return promptMinimized;
}

/** Returns the prompt overlay only if it's actually visible (not minimized). */
function getVisiblePromptOverlay() {
  const el = document.getElementById('game-prompt-overlay');
  if (!el) return null;
  if (el.style.display === 'none') return null;
  return el;
}

function minimizePromptOverlay() {
  const overlay = document.getElementById('game-prompt-overlay');
  if (!overlay) return;
  if (!overlay._promptMinimizable) return;
  if (promptMinimized) return;
  promptMinimized = true;
  if (overlay._prevBodyOverflow !== undefined) {
    document.body.style.overflow = overlay._prevBodyOverflow;
  } else {
    document.body.style.overflow = '';
  }
  overlay.style.display = 'none';
  ensurePromptResumeFab();
}

function restorePromptOverlay() {
  if (!promptMinimized) return;
  promptMinimized = false;
  removePromptResumeFab();
  const overlay = document.getElementById('game-prompt-overlay');
  if (!overlay) return;
  document.body.style.overflow = 'hidden';
  overlay.style.display = '';
}

function clearPromptMinimizationOnPromptGone() {
  if (!promptMinimized) return;
  promptMinimized = false;
  removePromptResumeFab();
}

function ensurePromptResumeFab() {
  if (promptResumeFabEl && document.body.contains(promptResumeFabEl)) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = 'prompt-resume-fab';
  btn.className = 'prompt-resume-fab';
  btn.setAttribute('aria-label', 'Open the active prompt');
  const icon = document.createElement('span');
  icon.className = 'prompt-resume-fab-icon';
  icon.setAttribute('aria-hidden', 'true');
  icon.textContent = '\u25B2';
  const label = document.createElement('span');
  label.className = 'prompt-resume-fab-label';
  label.textContent = 'Open prompt';
  btn.appendChild(icon);
  btn.appendChild(label);
  btn.addEventListener('click', () => restorePromptOverlay());
  document.body.appendChild(btn);
  promptResumeFabEl = btn;
}

function removePromptResumeFab() {
  if (promptResumeFabEl) {
    promptResumeFabEl.remove();
    promptResumeFabEl = null;
  }
  const stray = document.getElementById('prompt-resume-fab');
  if (stray) stray.remove();
}

/** True if a prompt overlay is in the DOM (visible OR minimized). */
function isPromptOverlayActive() {
  return !!document.getElementById('game-prompt-overlay');
}

/** Dismisses the card image / market inspect overlay and clears its Escape listener. */
function dismissCardInspectModal() {
  const overlay = document.getElementById('card-modal-overlay');
  if (overlay && overlay._stackArrowHandler) {
    document.removeEventListener('keydown', overlay._stackArrowHandler);
    overlay._stackArrowHandler = null;
  }
  if (!overlay) return;
  if (overlay._cardModalEscHandler) {
    document.removeEventListener('keydown', overlay._cardModalEscHandler);
    overlay._cardModalEscHandler = null;
  }
  overlay.remove();
}

// IDs of every long-lived panel that exposes a `_refreshFromLiveState` hook.
// The main render loop calls `refreshOpenCardInspectModal()` on every state
// change; we fan that out to all open modals so things like:
//   • a slay/build/hire button becoming enabled when it becomes your turn
//   • the duke VP projection updating as you collect resources
//   • a player-detail panel reflecting just-applied harvest payouts
//   • the dice/turn info popup tracking phase/turn changes
// all happen without the user having to close and reopen the modal.
const LIVE_REFRESH_PANEL_IDS = [
  'card-modal-overlay',
  'player-detail-modal',
  'dice-info-modal-overlay',
];

function refreshOpenCardInspectModal() {
  for (const id of LIVE_REFRESH_PANEL_IDS) {
    const el = document.getElementById(id);
    if (!el) continue;
    const fn = el._refreshFromLiveState;
    if (typeof fn !== 'function') continue;
    try {
      fn();
    } catch (err) {
      console.error(`live-refresh failed for #${id}`, err);
    }
  }
}

/** Shared close control for any panel using `.card-modal` (inspect, market, dismissible prompts). */
function syncCardShellCloseButton(modal, visible, onClose) {
  if (!modal) return;
  const existing = modal.querySelector('.card-modal-close:not(.prompt-modal-minimize)');
  if (!visible) {
    existing?.remove();
    return;
  }
  if (!onClose) return;
  let btn = existing;
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'card-modal-close';
    btn.setAttribute('aria-label', 'Close');
    btn.textContent = 'Close';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const fn = btn._modalCloseFn;
      if (fn) fn();
    });
    modal.appendChild(btn);
  }
  btn._modalCloseFn = onClose;
}

/** "Peek board" control for non-dismissible prompts. Positioned like the close button. */
function syncPromptMinimizeButton(modal, minimizable, onMinimize) {
  if (!modal) return;
  const existing = modal.querySelector('.prompt-modal-minimize');
  if (!minimizable) {
    existing?.remove();
    return;
  }
  if (!onMinimize) return;
  let btn = existing;
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'card-modal-close prompt-modal-minimize';
    btn.setAttribute('aria-label', 'Peek the board (you can reopen this prompt later)');
    btn.title = 'Peek the board (you must resolve this prompt to continue your turn)';
    btn.textContent = 'Peek board';
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const fn = btn._modalMinimizeFn;
      if (fn) fn();
    });
    modal.appendChild(btn);
  }
  btn._modalMinimizeFn = onMinimize;
}

function mountCardInspectOverlay(overlay, modal) {
  syncCardShellCloseButton(modal, true, dismissCardInspectModal);
  const dismiss = () => dismissCardInspectModal();
  overlay.addEventListener('click', dismiss);
  const onKey = e => {
    if (e.key === 'Escape') dismiss();
  };
  overlay._cardModalEscHandler = onKey;
  document.addEventListener('keydown', onKey);
}

function openPromptOverlayShell(opts) {
  const { title, subtitle, dismissible, bodyEl, footerEl } = opts;
  const newTitle = (title || '').toString();

  function configureDismissBehavior(overlay) {
    const modal = overlay.querySelector('.card-modal');
    // Clear prior handlers first.
    if (overlay._promptClickHandler) {
      overlay.removeEventListener('click', overlay._promptClickHandler);
      overlay._promptClickHandler = null;
    }
    if (overlay._promptEscHandler) {
      document.removeEventListener('keydown', overlay._promptEscHandler);
      overlay._promptEscHandler = null;
    }

    syncCardShellCloseButton(
      modal,
      !!dismissible,
      dismissible ? () => removePromptOverlay() : null,
    );

    // Non-dismissible prompts (active-player choice prompts) get a "Peek board"
    // minimize button instead, so the player can browse the board without
    // losing their pending choice. Waiting/spectator prompts (dismissible:true)
    // already let the player click out, so no minimize button there.
    const minimizable = !dismissible;
    overlay._promptMinimizable = minimizable;
    syncPromptMinimizeButton(
      modal,
      minimizable,
      minimizable ? () => minimizePromptOverlay() : null,
    );

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
    const preservedHarvestList = modal.querySelector('.prompt-harvest-mine-list');
    const preservedHarvestListScroll = preservedHarvestList ? preservedHarvestList.scrollTop : 0;

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
    const harvestList = modal.querySelector('.prompt-harvest-mine-list');
    if (harvestList) harvestList.scrollTop = preservedHarvestListScroll;
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
