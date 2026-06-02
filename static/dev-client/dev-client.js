// ── URL params + cookie-backed ids (vck_client) ───────────────────────────
            // Mirrors static/game/src/01-core.js so the debug page shares the same
            // active-game / user-id storage as the visual game client.
            const _vckParams = new URLSearchParams(location.search);
            const _vckStored =
                (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.read) ? VCK_CLIENT_META.read() : {};
            const _vckQueryGameId = (_vckParams.get('game_id') || '').trim();
            const _vckQueryPlayerId = (_vckParams.get('player_id') || '').trim();
            let playerId = _vckQueryPlayerId || String(_vckStored.player_id || '').trim();
            let currentGameId = _vckQueryGameId || String(_vckStored.game_id || '').trim();
            if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.patch) {
                const _vckBootPatch = {};
                if (_vckQueryPlayerId) _vckBootPatch.player_id = _vckQueryPlayerId;
                if (_vckQueryGameId) _vckBootPatch.game_id = _vckQueryGameId;
                if (Object.keys(_vckBootPatch).length) VCK_CLIENT_META.patch(_vckBootPatch);
            }

            function vckPatchClient(updates) {
                try {
                    if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.patch) {
                        VCK_CLIENT_META.patch(updates);
                    }
                } catch (_) { /* ignore */ }
            }
            /** Avoid duplicate tabs when toggleReady and lobby poll both notice the new game */
            let openedVisualGameTabForGameId = '';
            let lastGameState = null;
            let lastRenderedGameLogKey = null;
            let finalizeRollInFlight = false;
            let autoHarvestInFlight = false;

            function getDebugModeEnabled() {
                return localStorage.getItem('debugModeEnabled') === 'true';
            }

            function getAutoHarvestEnabled() {
                const v = localStorage.getItem('autoHarvestEnabled');
                if (v === null) return true;
                return v === 'true';
            }

            function syncDebugModeUiFromStorage() {
                const el = document.getElementById('debugModeEnabled');
                if (!el) return;
                el.checked = getDebugModeEnabled();
            }

            function wireDebugModeUi() {
                const el = document.getElementById('debugModeEnabled');
                if (!el) return;
                el.addEventListener('change', () => {
                    localStorage.setItem('debugModeEnabled', String(!!el.checked));
                });
                syncDebugModeUiFromStorage();
            }

            function syncAutoHarvestUiFromStorage() {
                const el = document.getElementById('autoHarvestEnabled');
                if (!el) return;
                el.checked = getAutoHarvestEnabled();
            }

            function wireAutoHarvestUi() {
                const el = document.getElementById('autoHarvestEnabled');
                if (!el) return;
                el.addEventListener('change', () => {
                    localStorage.setItem('autoHarvestEnabled', String(!!el.checked));
                });
                syncAutoHarvestUiFromStorage();
            }

            function clampDie(n) {
                const x = Number(n);
                if (!Number.isFinite(x)) return 1;
                return Math.max(1, Math.min(6, Math.trunc(x)));
            }
            // Poll handle used while a concurrent (non-ordered) prompt is active so
            // every browser session sees other players' progress in near-real-time.
            // Intentionally NOT an unconditional global poll: the standard-action panel
            // rebuilds payment inputs from gameState, and polling would wipe in-progress edits.
            // We do poll when waiting on others (passive) or during concurrent_action (below).
            let concurrentPollHandle = null;
            let passiveGamePollHandle = null;
            if (playerId) {
                document.getElementById('playerId').textContent = 'Player ID: ' + playerId;
            }
            wireDebugModeUi();
            wireAutoHarvestUi();

            function openVisualGameClientTab(gameId) {
                if (!gameId || !playerId) return;
                if (openedVisualGameTabForGameId === gameId) return;
                openedVisualGameTabForGameId = gameId;
                const q = new URLSearchParams({ game_id: gameId, player_id: playerId });
                window.open(`${location.origin}/?${q}`, '_blank', 'noopener,noreferrer');
            }
            
            async function createLobby() {
                const name = document.getElementById('playerName').value;
                if (!name) {
                    alert('Please enter a display name');
                    return;
                }
                const preset = document.getElementById('createLobbyPreset').value || 'current';
                const minPlayers = Number(document.getElementById('createLobbyMinPlayers').value) || 2;
                try {
                    const response = await fetch('/api/lobby/create', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: name, preset: preset, min_players: minPlayers})
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Create failed');
                    playerId = data.player_id;
                    vckPatchClient({ player_id: playerId });
                    document.getElementById('playerId').textContent = 'Player ID: ' + playerId;
                    getLobbyStatus();
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            async function joinLobbyById(lobbyId) {
                const name = document.getElementById('playerName').value;
                if (!name) {
                    alert('Please enter a display name first');
                    return;
                }
                try {
                    const response = await fetch('/api/lobby/join', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({name: name, lobby_id: lobbyId})
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Join failed');
                    playerId = data.player_id;
                    vckPatchClient({ player_id: playerId });
                    document.getElementById('playerId').textContent = 'Player ID: ' + playerId;
                    getLobbyStatus();
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            async function leaveLobby() {
                if (!playerId) return;
                try {
                    await fetch('/api/lobby/leave?player_id=' + encodeURIComponent(playerId), {method: 'POST'});
                } catch (_) { /* ignore */ }
                playerId = '';
                vckPatchClient({ player_id: null });
                document.getElementById('playerId').textContent = '';
                getLobbyStatus();
            }

            async function setLobbyPreset(preset) {
                if (!playerId) return;
                try {
                    const response = await fetch('/api/lobby/preset', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({player_id: playerId, preset: preset})
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Preset update failed');
                    getLobbyStatus();
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            async function setLobbyMinPlayers(minPlayers) {
                if (!playerId) return;
                try {
                    const response = await fetch('/api/lobby/min_players', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({player_id: playerId, min_players: Number(minPlayers) || 2})
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Min players update failed');
                    getLobbyStatus();
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            function findMyLobby(lobbies) {
                if (!Array.isArray(lobbies) || !playerId) return null;
                for (const lb of lobbies) {
                    if (Array.isArray(lb.members) && lb.members.some(m => m.player_id === playerId)) return lb;
                }
                return null;
            }

            // Cache of the last HTML written into #lobbyStatus. The debug page
            // polls /api/lobby/status every 2s; before this cache, every poll
            // unconditionally replaced innerHTML, which closed any open
            // <select> dropdowns (e.g. the owner's preset / min-players menus
            // are nested inside the lobby card HTML, so they got destroyed
            // mid-interaction). Only touching innerHTML when the html string
            // actually changes preserves open dropdowns.
            let _lastLobbyStatusHtml = null;
            function _writeLobbyStatusHtml(html) {
                if (html === _lastLobbyStatusHtml) return;
                _lastLobbyStatusHtml = html;
                document.getElementById('lobbyStatus').innerHTML = html;
            }

            async function getLobbyStatus() {
                try {
                    const url = playerId
                        ? `/api/lobby/status?player_id=${encodeURIComponent(playerId)}`
                        : '/api/lobby/status';
                    const response = await fetch(url);
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.detail || 'Status failed');

                    if (data.in_game && data.game_id) {
                        _writeLobbyStatusHtml(`<p><strong>You are in game: ${data.game_id}</strong></p>`);
                        if (data.game_id !== currentGameId) {
                            openVisualGameClientTab(data.game_id);
                            currentGameId = data.game_id;
                            vckPatchClient({ game_id: currentGameId });
                            getGameState(false);
                        }
                        return;
                    }
                    if (currentGameId) {
                        currentGameId = '';
                        vckPatchClient({ game_id: null });
                        stopGamePollingIntervals();
                    }

                    const lobbies = Array.isArray(data.lobbies) ? data.lobbies : [];
                    const myLobby = findMyLobby(lobbies);
                    let html = `<p>${lobbies.length} open lobb${lobbies.length === 1 ? 'y' : 'ies'} • ${data.game_count || 0} active game${data.game_count === 1 ? '' : 's'}</p>`;
                    if (!lobbies.length) {
                        html += '<p class="mini">No open lobbies. Create one above.</p>';
                    }
                    lobbies.forEach(lb => {
                        const isMine = !!(myLobby && myLobby.lobby_id === lb.lobby_id);
                        const isOwner = isMine && lb.owner_id === playerId;
                        const escapedId = lb.lobby_id.replace(/"/g, '&quot;');
                        const minPlayers = Number(lb.min_players) || 2;
                        const minLabel = lb.members.length >= minPlayers
                            ? `min ${minPlayers}`
                            : `${lb.members.length}/${minPlayers} to start`;
                        let card = `<div class="lobby-card${isMine ? ' is-mine' : ''}">`;
                        card += '<div class="lobby-card-header">';
                        card += `<div><span class="lobby-card-title">Preset: ${lb.preset}</span>`;
                        if (isMine) card += ' <span class="lobby-self-tag">You</span>';
                        card += `</div>`;
                        card += '<div class="lobby-card-sub">';
                        card += `${lb.members.length} player${lb.members.length === 1 ? '' : 's'} • ${minLabel}`;
                        card += '</div>';
                        if (!isMine) {
                            card += `<button onclick="joinLobbyById('${escapedId}')">Join</button>`;
                        }
                        card += '</div>';
                        if (isOwner) {
                            const presetOpts = ['current', 'base', 'flamesandfrost', 'shadowvale', 'random']
                                .map(v => `<option value="${v}"${v === lb.preset ? ' selected' : ''}>${v}</option>`)
                                .join('');
                            const minOpts = [2, 3, 4, 5]
                                .map(v => `<option value="${v}"${v === minPlayers ? ' selected' : ''}>${v}</option>`)
                                .join('');
                            card += `<div style="margin-top:6px;">Owner preset: <select onchange="setLobbyPreset(this.value)">${presetOpts}</select>`;
                            card += ` &nbsp; Min players: <select onchange="setLobbyMinPlayers(this.value)">${minOpts}</select></div>`;
                        }
                        card += '<ul class="lobby-card-members">';
                        lb.members.forEach(m => {
                            const isMember = m.player_id === playerId;
                            const ownerBadge = m.player_id === lb.owner_id ? ' <span class="lobby-owner-tag">Owner</span>' : '';
                            const debugTag = m.debug_mode ? ' <span class="mini">(debug)</span>' : '';
                            card += `<li class="lobby-player ${m.is_ready ? 'ready' : ''}">`;
                            card += `${m.name || 'Player'}${ownerBadge}${debugTag} — ${m.is_ready ? 'Ready' : 'Not Ready'}`;
                            if (isMember) card += ' <button onclick="toggleReady()">Toggle ready</button>';
                            card += '</li>';
                        });
                        card += '</ul>';
                        card += '</div>';
                        html += card;
                    });
                    _writeLobbyStatusHtml(html);
                } catch (error) {
                    console.error('Error:', error);
                }
            }

            async function toggleReady() {
                if (!playerId) return;
                let endpoint = '/api/lobby/ready';
                try {
                    const probe = await fetch(`/api/lobby/status?player_id=${encodeURIComponent(playerId)}`);
                    const ps = await probe.json();
                    const lb = findMyLobby(ps.lobbies || []);
                    const me = lb ? lb.members.find(m => m.player_id === playerId) : null;
                    if (me && me.is_ready) endpoint = '/api/lobby/unready';
                } catch (_) { /* fall through to /ready */ }
                try {
                    const response = await fetch(endpoint, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            debug_mode: getDebugModeEnabled(),
                        })
                    });
                    const data = await response.json();
                    if (data.game_id) {
                        currentGameId = data.game_id;
                        vckPatchClient({ game_id: currentGameId });
                        openVisualGameClientTab(data.game_id);
                        getGameState(false);
                    }
                    getLobbyStatus();
                } catch (error) {
                    console.error('Error:', error);
                }
            }
            
            function applyGameStateClientUpdate(data) {
                lastGameState = data;
                renderDice(data);
                maybeFinalizePendingRoll(data);
                const pre = document.getElementById('gameState');
                if (pre) pre.textContent = JSON.stringify(data, null, 2);
                updateConcurrentPolling(data);
                updatePassiveGamePolling(data);
                refreshTableauActionButtons(data);
                maybeAutoHarvest(data);
                refreshHistoryStatus();
            }

            // ── In-memory back-stepping (debug) ────────────────────────────
            // Server keeps a per-game ring buffer of save-dict snapshots and
            // exposes /history (read) and /back (pop+rehydrate). The button
            // is enabled iff there's an earlier snapshot to step back to.
            async function refreshHistoryStatus() {
                const btn = document.getElementById('stepBackBtn');
                const status = document.getElementById('historyStatus');
                if (!currentGameId) {
                    if (btn) btn.disabled = true;
                    if (status) status.textContent = '';
                    return;
                }
                try {
                    const r = await fetch(`/api/game/${encodeURIComponent(currentGameId)}/history`);
                    if (!r.ok) {
                        if (btn) btn.disabled = true;
                        if (status) status.textContent = '';
                        return;
                    }
                    const data = await r.json();
                    const hist = Array.isArray(data?.history) ? data.history : [];
                    const cur = Number.isInteger(data?.current_index) ? data.current_index : -1;
                    if (btn) btn.disabled = !data?.can_step_back;
                    if (status) {
                        if (!hist.length) {
                            status.textContent = '';
                        } else {
                            const tail = hist[hist.length - 1] || {};
                            const turn = tail.turn_number != null ? `T${tail.turn_number}` : '';
                            const phase = tail.phase ? ` ${tail.phase}` : '';
                            status.textContent = `Step ${cur + 1} of ${hist.length} (${turn}${phase})`;
                        }
                    }
                } catch (_) {
                    if (btn) btn.disabled = true;
                    if (status) status.textContent = '';
                }
            }

            async function stepGameBack() {
                if (!currentGameId) return;
                const btn = document.getElementById('stepBackBtn');
                if (btn) btn.disabled = true;
                try {
                    const r = await fetch(`/api/game/${encodeURIComponent(currentGameId)}/back`, { method: 'POST' });
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok) {
                        alert('Back step failed: ' + (data?.detail || r.status));
                        return;
                    }
                    await getGameState(false);
                } catch (e) {
                    alert('Error: ' + e.message);
                } finally {
                    refreshHistoryStatus();
                }
            }

            function maybeAutoHarvest(gameState) {
                if (!playerId || !currentGameId) return;
                if (!gameState || autoHarvestInFlight) return;
                if (!getAutoHarvestEnabled()) return;
                const concurrent = gameState?.concurrent_action || null;
                if (concurrent && Array.isArray(concurrent.pending) && concurrent.pending.length > 0) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const reqAction = (req?.action || '').toString();
                if (reqAction !== 'manual_harvest') return;
                if (!reqId || reqId !== playerId) return;
                const slots = Array.isArray(gameState?.harvest_prompt_slots) ? gameState.harvest_prompt_slots : [];
                if (slots.length !== 1) return;
                const slotKey = (slots[0]?.slot_key || '').toString().trim();
                if (!slotKey) return;
                autoHarvestInFlight = true;
                sendHarvestCard(slotKey, { suppressAlert: true })
                    .finally(() => { autoHarvestInFlight = false; });
            }

            async function maybeFinalizePendingRoll(gameState) {
                if (!playerId || !currentGameId) return;
                if (!gameState) return;
                if (finalizeRollInFlight) return;
                const phase = (gameState.phase || '').toString();
                if (phase !== 'roll_pending') return;

                const req = gameState.action_required || {};
                const reqId = (req.id || '').toString();
                const reqAction = (req.action || '').toString();
                if (reqAction !== 'finalize_roll') return;
                if (reqId !== playerId) return;

                // Don't auto-finalize when the player owns roll modifiers; the
                // prompt should wait for them to choose to spend or keep.
                const rolled1 = clampDie(gameState.rolled_die_one ?? gameState.die_one ?? 1);
                const rolled2 = clampDie(gameState.rolled_die_two ?? gameState.die_two ?? 1);
                const player = Array.isArray(gameState?.player_list)
                    ? gameState.player_list.find(p => (p?.player_id || '') === playerId)
                    : null;
                const opts = listRollSetOneDieOptions(player, rolled1, rolled2, gameState.turn_number);
                if (opts.length > 0) return;

                finalizeRollInFlight = true;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'finalize_roll',
                            die_one: rolled1,
                            die_two: rolled2
                        })
                    });
                    const payload = await res.json();
                    if (!res.ok) {
                        console.error(payload);
                        return;
                    }
                    if (payload && payload.game_state) {
                        applyGameStateClientUpdate(payload.game_state);
                    } else {
                        getGameState(false);
                    }
                } catch (e) {
                    console.error(e);
                } finally {
                    finalizeRollInFlight = false;
                }
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
                citizens.forEach((c) => {
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
                // Emits one entry per effect tagged with `mode`; the per-die
                // candidate values are computed in listRollSetOneDieOptions.
                const out = [];
                const domains = Array.isArray(player?.owned_domains) ? player.owned_domains : [];
                domains.forEach((d) => {
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
                // `opts.budgetGold` (optional): override the gold-affordability
                // check (used by stage-2 rendering to subtract the staged
                // first modifier's cost from the player's pool).
                // `opts.excludeDomainId` (optional): drop effects sourced from
                // this domain (engine forbids the same card firing twice in
                // one roll phase).
                // `opts.die` (optional, 1 or 2): restrict to options that
                // modify only this die number.
                const effects = parseRollSetOneDieEffects(player, turnNumber);
                const opts_ = opts || {};
                const budget = Number.isFinite(Number(opts_.budgetGold))
                    ? Number(opts_.budgetGold)
                    : Number(player?.gold_score || 0);
                const excludeDomainId = (opts_.excludeDomainId != null) ? Number(opts_.excludeDomainId) : null;
                const onlyDie = (opts_.die === 1 || opts_.die === 2) ? opts_.die : null;
                const options = [];
                // `target` in the returned option is the resolved FINAL die value
                // after applying this effect, regardless of which parser mode
                // produced it. Renderers can treat all options uniformly.
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
                effects.forEach((e) => {
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
                if (!playerId || !currentGameId) return;
                if (finalizeRollInFlight) return;
                finalizeRollInFlight = true;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'finalize_roll',
                            die_one: clampDie(d1),
                            die_two: clampDie(d2)
                        })
                    });
                    const payload = await res.json();
                    if (!res.ok) {
                        const msg = payload?.detail || 'Finalize roll failed';
                        const msgStr = typeof msg === 'string' ? msg : '';
                        if (msgStr && /not waiting to finalize/i.test(msgStr)) {
                            getGameState(false);
                            return;
                        }
                        alert(msg);
                        return;
                    }
                    if (payload && payload.game_state) applyGameStateClientUpdate(payload.game_state);
                    else getGameState(false);
                } catch (e) {
                    console.error(e);
                } finally {
                    finalizeRollInFlight = false;
                    resetFinalizeRollStaging();
                }
            }

            // Two-stage flow state for the finalize_roll prompt. Stage 1 picks
            // the first modifier (or keep). Picking one stashes it here and
            // re-renders into stage 2, which offers Confirm-with-just-this-one,
            // Back, and any second-modifier buttons scoped to the OTHER die /
            // a different source domain / remaining gold budget.
            let stagedFirstModifier = null;
            let stagedFirstModifierForRoll = null;

            function resetFinalizeRollStaging() {
                stagedFirstModifier = null;
                stagedFirstModifierForRoll = null;
            }

            function stagedRollKey(rolled1, rolled2) {
                return rolled1 + ',' + rolled2;
            }

            function refreshTableauActionButtons(gameState) {
                const wrap = document.getElementById('tableauSeatLayout');
                if (!wrap) return;
                wrap.innerHTML = '';
                const players = gameState && Array.isArray(gameState.player_list) ? gameState.player_list : [];
                const possessive = (name) => {
                    const s = (name ?? '').toString().trim();
                    if (!s) return 'Player';
                    const lower = s.toLowerCase();
                    if (lower.endsWith('s')) return `${s}'`;
                    return `${s}'s`;
                };

                // Board button (center)
                const boardBtn = document.createElement('button');
                boardBtn.type = 'button';
                boardBtn.className = 'tableau-seat-btn board-seat';
                boardBtn.textContent = 'Board';
                boardBtn.style.left = '50%';
                boardBtn.style.top = '50%';
                boardBtn.onclick = () => {
                    window.open(`/?game_id=${currentGameId}&player_id=${playerId}`, '_blank');
                };
                wrap.appendChild(boardBtn);

                const cleanPlayers = players.filter(p => p && p.player_id);
                const n = cleanPlayers.length;
                if (!n) return;

                const seatAnglesDeg = (count) => {
                    if (count === 1) return [-90];
                    if (count === 2) return [180, 0];            // left / right
                    if (count === 3) return [-90, 150, 30];      // triangle around board
                    if (count === 4) return [-90, 0, 90, 180];   // top / right / bottom / left
                    // 5+ evenly spaced circle, starting at top, clockwise
                    const out = [];
                    for (let i = 0; i < count; i++) out.push(-90 + (360 * i) / count);
                    return out;
                };

                const angles = seatAnglesDeg(n);
                const w = wrap.clientWidth || 760;
                const h = wrap.clientHeight || 220;
                const radius = Math.max(70, Math.min(w, h) * 0.42);
                const firstPid = cleanPlayers[0]?.player_id || '';

                cleanPlayers.forEach((p, idx) => {
                    const pid = p.player_id;
                    const nm = ((p.name ?? '').toString().trim() || pid);
                    const isSelf = pid === playerId;
                    const isFirst = pid === firstPid;
                    const label = isSelf ? 'My Tableau' : `${possessive(nm)} Tableau`;

                    const deg = angles[idx % angles.length];
                    const rad = (deg * Math.PI) / 180;
                    const x = (w / 2) + radius * Math.cos(rad);
                    const y = (h / 2) + radius * Math.sin(rad);

                    const btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'tableau-seat-btn' + (isFirst ? ' first-seat' : '');
                    btn.textContent = isFirst ? `${label} (First)` : label;
                    btn.style.left = `${x}px`;
                    btn.style.top = `${y}px`;
                    btn.onclick = () => { openSeatTableau(pid); };
                    wrap.appendChild(btn);
                });
            }

            async function getGameState(forcePrompt = true) {
                let gameId = currentGameId;
                if (!gameId && forcePrompt) {
                    gameId = prompt('Enter game ID:');
                }
                if (!gameId) return;
                currentGameId = gameId;
                vckPatchClient({ game_id: currentGameId });
                try {
                    const qs = playerId ? `?player_id=${encodeURIComponent(playerId)}` : '';
                    const response = await fetch(`/api/game/${gameId}/state${qs}`);
                    const data = await response.json();
                    applyGameStateClientUpdate(data);
                } catch (error) {
                    alert('Error: ' + error.message);
                }
            }

            async function ensureGameStateForTableau() {
                if (!currentGameId) {
                    alert('No game id yet. Start a game or refresh lobby status first.');
                    return false;
                }
                if (lastGameState && lastGameState.game_id === currentGameId) return true;
                try {
                    const qs = playerId ? `?player_id=${encodeURIComponent(playerId)}` : '';
                    const response = await fetch(`/api/game/${currentGameId}/state${qs}`);
                    const data = await response.json();
                    applyGameStateClientUpdate(data);
                    return true;
                } catch (e) {
                    alert('Error: ' + e.message);
                    return false;
                }
            }

            function stopGamePollingIntervals() {
                if (concurrentPollHandle) {
                    clearInterval(concurrentPollHandle);
                    concurrentPollHandle = null;
                }
                if (passiveGamePollHandle) {
                    clearInterval(passiveGamePollHandle);
                    passiveGamePollHandle = null;
                }
            }

            function updateConcurrentPolling(gameState) {
                // Only poll while a concurrent action is active. This keeps
                // non-pending players' UI honest as others submit, without
                // disturbing the rest of the in-game UI (which rebuilds inputs
                // on every render).
                const ca = gameState?.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                const shouldPoll = pend.length > 0;
                if (shouldPoll && !concurrentPollHandle) {
                    concurrentPollHandle = setInterval(() => {
                        if (!currentGameId) return;
                        getGameState(false);
                    }, 1500);
                } else if (!shouldPoll && concurrentPollHandle) {
                    clearInterval(concurrentPollHandle);
                    concurrentPollHandle = null;
                }
            }

            function localGameUiIsFragile(gameState) {
                if (!playerId || !gameState) return false;
                const ca = gameState.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                if (pend.length && pend.includes(playerId)) return true;
                const req = gameState.action_required || {};
                const reqId = req.id || '';
                const reqAction = (req.action || '').toString();
                if (!reqId || reqId === gameState.game_id) return false;
                if (reqId !== playerId) return false;
                if (reqAction === 'manual_harvest') return true;
                if (reqAction === 'bonus_resource_choice') return true;
                const trimmed = reqAction.trim();
                if (trimmed.startsWith('choose ')) return true;
                if (
                    trimmed === 'choose_player' ||
                    trimmed === 'choose_monster_strength' ||
                    trimmed === 'choose_owned_card' ||
                    trimmed === 'domain_self_convert' ||
                    trimmed === 'event_gain_action' ||
                    trimmed === 'harvest_optional_exchange' ||
                    trimmed === 'harvest_wild_gain_exchange' ||
                    trimmed === 'harvest_wild_cost_exchange'
                ) return true;
                if (reqAction === 'standard_action' && (gameState.phase || '') === 'action') return true;
                return false;
            }

            function updatePassiveGamePolling(gameState) {
                if (!currentGameId) {
                    if (passiveGamePollHandle) {
                        clearInterval(passiveGamePollHandle);
                        passiveGamePollHandle = null;
                    }
                    return;
                }
                const ca = gameState?.concurrent_action || null;
                const pend = ca && Array.isArray(ca.pending) ? ca.pending : [];
                const concurrentBlocking = pend.length > 0;
                const fragile = localGameUiIsFragile(gameState);
                const shouldPoll = !concurrentBlocking && !fragile;

                if (shouldPoll && !passiveGamePollHandle) {
                    passiveGamePollHandle = setInterval(() => {
                        if (!currentGameId) {
                            clearInterval(passiveGamePollHandle);
                            passiveGamePollHandle = null;
                            return;
                        }
                        getGameState(false);
                    }, 2000);
                } else if (!shouldPoll && passiveGamePollHandle) {
                    clearInterval(passiveGamePollHandle);
                    passiveGamePollHandle = null;
                }
            }

            function escapeHtml(s) {
                return (s ?? '').toString()
                    .replaceAll('&', '&amp;')
                    .replaceAll('<', '&lt;')
                    .replaceAll('>', '&gt;')
                    .replaceAll('"', '&quot;')
                    .replaceAll("'", '&#039;');
            }

            function openModal() {
                const m = document.getElementById('tableauModal');
                if (m) m.classList.add('open');
            }

            function closeTableau() {
                const m = document.getElementById('tableauModal');
                if (m) m.classList.remove('open');
            }

            function onTableauBackdropClick(e) {
                // Click-out closes (panel stops propagation)
                closeTableau();
            }

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') closeTableau();
            });

            function pill(label, value) {
                return `<span class="pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</span>`;
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

            function renderCardItem(card, count = 1) {
                if (!card || typeof card !== 'object') {
                    return `<div class="item"><div class="item-title">${escapeHtml(String(card))}</div></div>`;
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
                if (sn > 0) roleParts.push(`Shadow +${sn}`);
                if (hn > 0) roleParts.push(`Holy +${hn}`);
                if (son > 0) roleParts.push(`Soldier +${son}`);
                if (wn > 0) roleParts.push(`Worker +${wn}`);
                const isDomain = card.domain_id !== undefined && card.domain_id !== null;
                if (isDomain && card.is_visible === false) {
                    return '<div class="item"><div class="item-title">Face-down domain</div>'
                        + '<div class="item-sub">Hidden until end of the building player\'s turn</div></div>';
                }
                const showRoleRow = (isCitizen || isDomain) && roleParts.length;
                const roleBlock = showRoleRow
                    ? `<div class="item-sub" style="margin-top:4px;"><strong>Roles:</strong> ${escapeHtml(roleParts.join(' · '))}</div>`
                    : '';

                const subtitle = hints.length ? `<div class="item-sub">${escapeHtml(hints.join(' · '))}</div>` : '';
                const fullText = cardFullText(card);
                const rulesText = fullText
                    ? `<div class="item-sub" style="margin-top:6px;white-space:pre-wrap;color:#333;">${escapeHtml(fullText)}</div>`
                    : '';
                const idText = id !== '' ? ` <span class="mini">(#${escapeHtml(id)})</span>` : '';
                const qty = Number(count) || 1;
                const qtyText = qty > 1 ? ` <span class="mini">x${qty}</span>` : '';
                return `<div class="item"><div class="item-title">${escapeHtml(name)}${qtyText}${idText}</div>${subtitle}${roleBlock}${rulesText}</div>`;
            }

            // Citizens get a roll-based primary sort key (ascending by trigger value,
            // highest positive roll_match per card) so the tableau lays them out in
            // dice-roll order. For non-citizens the roll key ties out and behavior
            // falls back to name/id.
            function groupCardsForTableau(cards) {
                const arr = Array.isArray(cards) ? cards : [];
                const map = new Map();
                arr.forEach((c) => {
                    if (!c || typeof c !== 'object') return;
                    const name = (c.name || c.title || '').toString().trim();
                    const id = c.starter_id || c.citizen_id || c.monster_id || c.domain_id || c.duke_id || c.id || '';
                    const isCitizenKey = c.citizen_id !== undefined && c.citizen_id !== null;
                    const flipSeg = isCitizenKey ? `||flip:${c.is_flipped ? 1 : 0}` : '';
                    const key = `${name}||${id}${flipSeg}`;
                    const cur = map.get(key);
                    if (cur) cur.count += 1;
                    else map.set(key, {
                        card: c,
                        count: 1,
                        sortName: name.toLowerCase(),
                        sortId: String(id),
                        sortRoll: isCitizenKey ? bestCitizenRollSortValue(c) : Number.POSITIVE_INFINITY,
                    });
                });
                // If we saw non-objects in the list, just fall back to rendering raw items.
                if (map.size === 0 && arr.length) return null;
                return Array.from(map.values()).sort((a, b) => {
                    if (a.sortRoll !== b.sortRoll) return a.sortRoll - b.sortRoll;
                    if (a.sortName < b.sortName) return -1;
                    if (a.sortName > b.sortName) return 1;
                    if (a.sortId < b.sortId) return -1;
                    if (a.sortId > b.sortId) return 1;
                    return 0;
                });
            }

            // Highest positive dice-roll trigger value for a citizen. Citizens may
            // trigger on roll_match1 and/or roll_match2; pick the largest positive
            // value so cards with multiple triggers sort by their best trigger.
            // Citizens with no positive roll match fall to the end of the citizen group.
            function bestCitizenRollSortValue(card) {
                let best = Number.NEGATIVE_INFINITY;
                for (const v of [card && card.roll_match1, card && card.roll_match2]) {
                    const n = Number(v);
                    if (Number.isFinite(n) && n > 0 && n > best) best = n;
                }
                return best === Number.NEGATIVE_INFINITY ? Number.POSITIVE_INFINITY : best;
            }

            function renderCardList(title, cards) {
                const arr = Array.isArray(cards) ? cards : [];
                if (!arr.length) {
                    return `<div class="tableau-card"><h3>${escapeHtml(title)}</h3><div class="mini">none</div></div>`;
                }
                const grouped = groupCardsForTableau(arr);
                // If grouping failed (unexpected contents), keep the original behavior.
                if (!grouped) {
                    return `<div class="tableau-card">
                        <h3>${escapeHtml(title)} <span class="mini">(${arr.length})</span></h3>
                        <div class="list">${arr.map(renderCardItem).join('')}</div>
                    </div>`;
                }
                return `<div class="tableau-card">
                    <h3>${escapeHtml(title)} <span class="mini">(${arr.length} total, ${grouped.length} types)</span></h3>
                    <div class="list">${grouped.map(x => renderCardItem(x.card, x.count)).join('')}</div>
                </div>`;
            }

            function cardFullText(card) {
                if (!card || typeof card !== 'object') return '';

                // Prefer an explicit "text" field (Domains have this).
                const rawText = (card.text ?? '').toString().trim();
                if (rawText) return rawText;

                // Otherwise synthesize from other special/effect fields we already serialize.
                const parts = [];
                // Include baseline harvest payouts so market rows show core card behavior,
                // not just special/passive text.
                pushHarvestHints(parts, card);
                // Monsters use reward fields instead of harvest payout fields.
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

                // Dukes don't currently have rules text in data, so show their multipliers as the "text".
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
                        // Duke resource scaling is "per N resources" (reciprocal display).
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

                // Newlines separate rule lines when shown in pre-wrap text.
                return parts.join('\n').trim();
            }

            function renderPlayerTableau(gameState, targetPlayerId, isSelfView) {
                const titleEl = document.getElementById('tableauTitle');
                const bodyEl = document.getElementById('tableauBody');
                if (!bodyEl) return;

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const subject = players.find(p => p?.player_id === targetPlayerId) || null;

                if (isSelfView) {
                    if (!playerId) {
                        if (titleEl) titleEl.textContent = 'My Tableau';
                        bodyEl.innerHTML = `<div class="tableau-card"><h3>Not joined</h3><div class="mini">Join the lobby first so we know your player id.</div></div>`;
                        return;
                    }
                    if (!subject) {
                        if (titleEl) titleEl.textContent = 'My Tableau';
                        bodyEl.innerHTML = `<div class="tableau-card"><h3>Player not in game</h3><div class="mini">No player with id <code>${escapeHtml(playerId)}</code> found in this game state.</div></div>`;
                        return;
                    }
                } else if (!subject) {
                    if (titleEl) titleEl.textContent = 'Tableau';
                    bodyEl.innerHTML = `<div class="tableau-card"><h3>Player not in game</h3><div class="mini">No player with id <code>${escapeHtml(targetPlayerId)}</code> in this game state.</div></div>`;
                    return;
                }

                const displayName = ((subject.name ?? '').toString().trim() || subject.player_id || 'Player');
                if (titleEl) {
                    const possessive = (name) => {
                        const s = (name ?? '').toString().trim();
                        if (!s) return 'Player';
                        const lower = s.toLowerCase();
                        if (lower.endsWith('s')) return `${s}'`;
                        return `${s}'s`;
                    };
                    titleEl.textContent = isSelfView ? 'My Tableau' : `${possessive(displayName)} Tableau`;
                }

                const resourceRow = `
                    <div class="kv">
                        ${pill('Gold', subject.gold_score ?? 0)}
                        ${pill('Strength', subject.strength_score ?? 0)}
                        ${pill('Magic', subject.magic_score ?? 0)}
                        ${pill('Victory', subject.victory_score ?? 0)}
                        ${pill('Shadow', subject.shadow_count ?? 0)}
                        ${pill('Holy', subject.holy_count ?? 0)}
                        ${pill('Soldier', subject.soldier_count ?? 0)}
                        ${pill('Worker', subject.worker_count ?? 0)}
                        ${pill('Minion', subject.minion_count ?? 0)}
                        ${pill('Titan', subject.titan_count ?? 0)}
                        ${pill('Warden', subject.warden_count ?? 0)}
                        ${pill('Boss', subject.boss_count ?? 0)}
                        ${pill('Beast', subject.beast_count ?? 0)}
                    </div>
                `;

                const dukes = Array.isArray(subject.owned_dukes) ? subject.owned_dukes : [];
                const duke = dukes.length ? dukes[0] : null;
                const dukeVisible = !!duke && duke.is_visible !== false;
                let dukeName;
                if (!duke) dukeName = 'None';
                else if (!dukeVisible) dukeName = 'Hidden (opponent)';
                else dukeName = duke?.name || 'Duke';
                const dukeText = dukeVisible ? cardFullText(duke) : '';
                const proj = dukeVisible ? subject.duke_vp_projection : null;
                let dukeProjectionBlock = '';
                if (proj && typeof proj === 'object') {
                    const lines = Array.isArray(proj.duke_vp_breakdown) ? proj.duke_vp_breakdown : [];
                    const linesHtml = lines.length
                        ? lines.map(l => `<li><strong>${escapeHtml(l.label || '')}:</strong> +${Number(l.vp || 0)} VP${l.detail ? ` <span style="color:#666;">(${escapeHtml(l.detail)})</span>` : ''}</li>`).join('')
                        : '<li style="color:#666;font-style:italic;">No duke VP yet</li>';
                    dukeProjectionBlock = `
                        <div style="margin-top:8px;padding:6px 8px;background:rgba(0,0,0,0.04);border-radius:4px;">
                            <ul style="margin:0 0 4px 16px;padding:0;font-size:13px;">${linesHtml}</ul>
                            <div style="font-weight:700;font-size:13px;">${Number(proj.base_vp || 0)} base + ${Number(proj.duke_vp || 0)} Duke = ${Number(proj.total_vp || 0)} VP</div>
                        </div>`;
                }
                const dukeLine = `<div class="mini" style="margin-bottom:12px;">
                    <strong>Duke:</strong> ${escapeHtml(dukeName)}
                    ${dukeText ? `<div style="margin-top:6px;white-space:pre-wrap;color:#333;">${escapeHtml(dukeText)}</div>` : ''}
                    ${dukeProjectionBlock}
                </div>`;

                bodyEl.innerHTML = `
                    ${resourceRow}
                    ${dukeLine}
                    <div class="tableau-grid">
                        ${renderCardList('Starters', subject.owned_starters)}
                        ${renderCardList('Citizens', subject.owned_citizens)}
                        ${renderCardList('Monsters', subject.owned_monsters)}
                        ${renderCardList('Domains', subject.owned_domains)}
                    </div>
                `;
            }

            function boardStackMeta(kind, top, depth) {
                const bits = [];
                bits.push(depth + ' card' + (depth === 1 ? '' : 's'));
                if (kind === 'citizen' || kind === 'monster') {
                    bits.push(top.is_accessible ? 'top accessible' : 'top not accessible');
                }
                if (kind === 'domain') {
                    bits.push(top.is_visible ? 'top visible' : 'top hidden');
                    bits.push(top.is_accessible ? 'top accessible' : 'top not accessible');
                }
                return bits.join(' · ');
            }

            const expandedMonsterStacks = new Set();

            function isMonsterStackExpanded(stackIndex) {
                return expandedMonsterStacks.has(Number(stackIndex));
            }

            function toggleMonsterStackExpand(stackIndex) {
                const idx = Number(stackIndex);
                if (Number.isNaN(idx)) return;
                if (expandedMonsterStacks.has(idx)) expandedMonsterStacks.delete(idx);
                else expandedMonsterStacks.add(idx);
                if (lastGameState) renderBoardTableau(lastGameState);
            }
            window.toggleMonsterStackExpand = toggleMonsterStackExpand;

            function renderMonsterStackCards(stack, stackIndex) {
                const expanded = isMonsterStackExpanded(stackIndex);
                const top = topOfStack(stack);
                if (!top) return '';
                if (!expanded) {
                    return renderCardItem(top);
                }
                const cards = [...stack].reverse();
                return `<div class="list">${cards.map((card, i) => {
                    const role = i === 0 ? 'Top (slayable)' : 'Buried';
                    return `<div><div class="mini" style="margin-bottom:4px;">${role}</div>${renderCardItem(card)}</div>`;
                }).join('')}</div>`;
            }

            function renderBoardStackSection(title, grid, kind) {
                const g = Array.isArray(grid) ? grid : [];
                const blocks = g.map((stack, idx) => {
                    const depth = Array.isArray(stack) ? stack.length : 0;
                    if (!depth) {
                        return `<div class="item"><div class="item-title">Stack ${idx + 1}</div><div class="mini">empty</div></div>`;
                    }
                    const top = topOfStack(stack);
                    if (!top) {
                        return `<div class="item"><div class="item-title">Stack ${idx + 1}</div><div class="mini">empty</div></div>`;
                    }
                    const meta = boardStackMeta(kind, top, depth);
                    const expandControl = kind === 'monster'
                        ? `<button type="button" onclick="toggleMonsterStackExpand(${idx})">${isMonsterStackExpanded(idx) ? 'Collapse' : 'Expand'}</button>`
                        : '';
                    const cardHtml = kind === 'monster'
                        ? renderMonsterStackCards(stack, idx)
                        : renderCardItem(top);
                    return `<div class="item" style="margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #eee;">
                        <div class="item-title">Stack ${idx + 1}</div>
                        ${expandControl ? `<div style="margin:6px 0;">${expandControl}</div>` : ''}
                        <div class="mini" style="margin-bottom:6px;">${escapeHtml(meta)}</div>
                        ${cardHtml}
                    </div>`;
                });
                return `<div class="tableau-card"><h3>${escapeHtml(title)}</h3><div class="list">${blocks.join('')}</div></div>`;
            }

            function renderBoardTableau(gameState) {
                const titleEl = document.getElementById('tableauTitle');
                const bodyEl = document.getElementById('tableauBody');
                if (!bodyEl) return;
                if (titleEl) titleEl.textContent = 'Board (stacks)';
                const citizenGrid = Array.isArray(gameState?.citizen_grid) ? gameState.citizen_grid : [];
                const domainGrid = Array.isArray(gameState?.domain_grid) ? gameState.domain_grid : [];
                const monsterGrid = Array.isArray(gameState?.monster_grid) ? gameState.monster_grid : [];
                bodyEl.innerHTML = `
                    <div class="mini" style="margin-bottom:12px;">Top of each stack is the play surface. Monster stacks can be expanded to view buried cards, but only the top monster is slayable.</div>
                    <div class="tableau-grid">
                        ${renderBoardStackSection('Citizens (market)', citizenGrid, 'citizen')}
                        ${renderBoardStackSection('Domains', domainGrid, 'domain')}
                        ${renderBoardStackSection('Monsters', monsterGrid, 'monster')}
                    </div>
                `;
            }

            async function openMyTableau() {
                if (!(await ensureGameStateForTableau())) return;
                renderPlayerTableau(lastGameState, playerId, true);
                openModal();
            }

            async function openPlayerTableau(targetPlayerId) {
                if (!targetPlayerId) return;
                if (!(await ensureGameStateForTableau())) return;
                renderPlayerTableau(lastGameState, targetPlayerId, false);
                openModal();
            }

            async function openSeatTableau(targetPlayerId) {
                if (!targetPlayerId) return;
                if (!(await ensureGameStateForTableau())) return;
                const isSelf = targetPlayerId === playerId;
                renderPlayerTableau(lastGameState, targetPlayerId, isSelf);
                openModal();
            }

            async function openBoardTableau() {
                if (!(await ensureGameStateForTableau())) return;
                renderBoardTableau(lastGameState);
                openModal();
            }

            function diePipMask(value) {
                // grid indices: 0 1 2 / 3 4 5 / 6 7 8
                // positions: TL, TC, TR, ML, MC, MR, BL, BC, BR
                const masks = {
                    1: [4],
                    2: [0, 8],
                    3: [0, 4, 8],
                    4: [0, 2, 6, 8],
                    5: [0, 2, 4, 6, 8],
                    6: [0, 2, 3, 5, 6, 8]
                };
                return masks[value] || [];
            }

            function buildDie(value, status, title) {
                const die = document.createElement('div');
                die.className = 'die' + (status ? ` ${status}` : '');
                const on = new Set(diePipMask(value));
                for (let i = 0; i < 9; i++) {
                    const pip = document.createElement('div');
                    pip.className = 'pip' + (on.has(i) ? '' : ' off');
                    die.appendChild(pip);
                }
                die.title = title || `d${value || 0}`;
                return die;
            }

            function renderGameLog(gameState) {
                const el = document.getElementById('gameLog');
                if (!el) return;
                const entries = Array.isArray(gameState?.game_log) ? gameState.game_log : [];
                const logKey = JSON.stringify([
                    gameState?.game_id || currentGameId || '',
                    entries.map(e => [
                        e && e.tick !== undefined && e.tick !== null ? e.tick : '',
                        (e && (e.msg || e.message)) || ''
                    ])
                ]);
                if (logKey === lastRenderedGameLogKey) return;

                const wasAtBottom = (el.scrollHeight - el.scrollTop - el.clientHeight) < 8;
                const previousScrollTop = el.scrollTop;
                const shouldAutoScroll = lastRenderedGameLogKey === null || wasAtBottom;
                lastRenderedGameLogKey = logKey;

                if (!entries.length) {
                    el.textContent = '(No events yet.)';
                    return;
                }
                el.innerHTML = entries.map(e => {
                    const tick = e && e.tick !== undefined && e.tick !== null ? e.tick : '';
                    const msg = escapeHtml(String((e && e.msg) || (e && e.message) || ''));
                    return `<div class="game-log-line"><span class="game-log-tick">[${tick}]</span>${msg}</div>`;
                }).join('');
                el.scrollTop = shouldAutoScroll ? el.scrollHeight : previousScrollTop;
            }

            function renderDice(gameState) {
                const rolled1 = Number(gameState?.rolled_die_one ?? gameState?.die_one ?? 0);
                const rolled2 = Number(gameState?.rolled_die_two ?? gameState?.die_two ?? 0);
                const rolledSum = Number(gameState?.rolled_die_sum ?? ((rolled1 || 0) + (rolled2 || 0)) ?? 0);
                const final1 = Number(gameState?.die_one || 0);
                const final2 = Number(gameState?.die_two || 0);
                const finalSum = Number(gameState?.die_sum || 0);

                const diceEl = document.getElementById('dice');
                const metaEl = document.getElementById('diceMeta');
                const effectsEl = document.getElementById('rollEffects');
                const deltaEl = document.getElementById('harvestDeltas');
                if (!diceEl || !metaEl) return;

                const die1Changed = rolled1 && final1 && rolled1 !== final1;
                const die2Changed = rolled2 && final2 && rolled2 !== final2;
                const die1Status = die1Changed ? (final1 > rolled1 ? 'increase' : 'decrease') : '';
                const die2Status = die2Changed ? (final2 > rolled2 ? 'increase' : 'decrease') : '';
                const die1Display = die1Changed ? final1 : rolled1;
                const die2Display = die2Changed ? final2 : rolled2;

                diceEl.innerHTML = '';
                diceEl.appendChild(buildDie(die1Display, die1Status, die1Changed ? `d${final1} (rolled ${rolled1})` : `d${die1Display}`));
                diceEl.appendChild(buildDie(die2Display, die2Status, die2Changed ? `d${final2} (rolled ${rolled2})` : `d${die2Display}`));

                const turn = gameState?.turn_number;
                const phase = gameState?.phase;
                const active = gameState?.active_player_id;
                const actionsRemaining = gameState?.actions_remaining;

                const parts = [];
                if (rolled1 && rolled2) parts.push(`<strong>${rolled1}</strong> + <strong>${rolled2}</strong> = <strong>${rolledSum}</strong>`);
                else parts.push(`<strong>Dice</strong>: not rolled`);
                if (rolled1 && rolled2 && final1 && final2 && (rolled1 !== final1 || rolled2 !== final2)) {
                    parts.push(`Final <strong>${final1}</strong> + <strong>${final2}</strong> = <strong>${finalSum}</strong>`);
                }
                if ((gameState?.phase || '') === 'roll_pending') {
                    parts.push(`<span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #d6b26c;background:#fff6d8;color:#5b420a;font-weight:800;font-size:12px;">Awaiting finalize</span>`);
                }
                if ((gameState?.phase || '') === 'action_end_pending') {
                    parts.push(`<span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid #c9d6ea;background:#eef5ff;color:#1f3a5f;font-weight:800;font-size:12px;">Action-end domains</span>`);
                }
                if (turn !== undefined) parts.push(`Turn <strong>${turn}</strong>`);
                if (phase) parts.push(`Phase <strong>${phase}</strong>`);
                if (actionsRemaining !== undefined) parts.push(`Actions remaining <strong>${actionsRemaining}</strong>`);
                if (active) parts.push(`Active <code>${active}</code>`);
                metaEl.innerHTML = parts.join(' · ');

                renderGameLog(gameState);

                if (effectsEl) {
                    const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                    const activePlayerId = (gameState?.active_player_id || '').toString();
                    const activePlayer = players.find(p => (p?.player_id || '').toString() === activePlayerId) || null;
                    const effects = parseRollSetOneDieEffects(activePlayer, gameState.turn_number);
                    if (!effects.length) {
                        effectsEl.innerHTML = '<strong>Roll phase effects:</strong> none';
                    } else {
                        const rows = effects.map((e) => {
                            let effectText = '';
                            if (e.mode === 'target') {
                                effectText = `set one die to <strong>${escapeHtml(String(e.target))}</strong>`;
                            } else if (e.mode === 'subtract') {
                                effectText = `subtract <strong>${escapeHtml(String(e.delta))}</strong> from one die`;
                            } else if (e.mode === 'add') {
                                effectText = `add <strong>${escapeHtml(String(e.delta))}</strong> to one die`;
                            } else {
                                effectText = 'modify one die';
                            }
                            const costText = e.costSpec ? `<code>${escapeHtml(e.costSpec)}</code>` : 'free';
                            return `<li><strong>${escapeHtml(e.domainName)}</strong>: ${effectText} (cost: ${costText})</li>`;
                        }).join('');
                        effectsEl.innerHTML = `<strong>Roll phase effects (active player):</strong><ul>${rows}</ul>`;
                    }
                }

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const restingPid = (gameState?.resting_player_id || '').toString();
                if (deltaEl) {
                deltaEl.innerHTML = '';
                players.forEach(p => {
                    const d = p?.harvest_delta || {};
                    const g = Number(d.gold || 0);
                    const s = Number(d.strength || 0);
                    const m = Number(d.magic || 0);
                    const v = Number(d.victory || 0);
                    const G = Number(p?.gold_score || 0);
                    const S = Number(p?.strength_score || 0);
                    const M = Number(p?.magic_score || 0);
                    const V = Number(p?.victory_score || 0);

                    const card = document.createElement('div');
                    card.className = 'delta-card';
                    const name = p?.name || (p?.player_id ? p.player_id.slice(0, 6) : 'Player');
                    const isResting = restingPid && (p?.player_id || '').toString() === restingPid;
                    const restingTag = isResting
                        ? ' <span title="5-player rule: this seat skips harvest this turn." style="display:inline-block;margin-left:6px;padding:1px 6px;border-radius:999px;border:1px solid #b78b1f;background:#f0d27a;color:#2a1f06;font-size:11px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;">Resting</span>'
                        : '';

                    const fmt = (n) => (n > 0 ? `+${n}` : `${n}`);
                    const cls = (n) => (n > 0 ? 'delta-pos' : (n < 0 ? 'delta-neg' : 'delta-zero'));

                    card.innerHTML = `
                        <div class="delta-grid">
                            <span class="delta-name">${name}${restingTag}</span>
                            <span class="delta-cell"><span class="delta-label">ΔG</span><span class="delta-value ${cls(g)}">${fmt(g)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔS</span><span class="delta-value ${cls(s)}">${fmt(s)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔM</span><span class="delta-value ${cls(m)}">${fmt(m)}</span></span>
                            <span class="delta-cell"><span class="delta-label">ΔVP</span><span class="delta-value ${cls(v)}">${fmt(v)}</span></span>

                            <span class="delta-muted">Totals</span>
                            <span class="delta-cell"><span class="delta-label">G</span><span class="delta-value delta-totals">${G}</span></span>
                            <span class="delta-cell"><span class="delta-label">S</span><span class="delta-value delta-totals">${S}</span></span>
                            <span class="delta-cell"><span class="delta-label">M</span><span class="delta-value delta-totals">${M}</span></span>
                            <span class="delta-cell"><span class="delta-label">VP</span><span class="delta-value delta-totals">${V}</span></span>
                        </div>
                    `;
                    deltaEl.appendChild(card);
                });
                }

                renderChoicePanel(gameState);
            }

            function renderChoicePanel(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                // Concurrent (non-ordered) prompts always take precedence over
                // turn-based action_required: while one is active the engine
                // will not advance and no per-player turn prompts are valid.
                const concurrent = gameState?.concurrent_action || null;
                const concurrentPending = concurrent && Array.isArray(concurrent.pending) ? concurrent.pending : [];
                if (concurrentPending.length > 0) {
                    return renderConcurrentActionPanel(gameState, concurrent);
                }

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const reqAction = req?.action || '';
                const activePlayerId = gameState?.active_player_id || '';

                function harvestTurnBadge(forPlayerId) {
                    const pid = (forPlayerId || '').toString();
                    if (!pid || !activePlayerId) return '';
                    const onTurn = (pid === activePlayerId);
                    const bg = onTurn ? '#e8f7ee' : '#f1f1f1';
                    const border = onTurn ? '#8ad0a4' : '#cfcfcf';
                    const fg = onTurn ? '#1f6a3a' : '#444';
                    const label = onTurn ? 'On-turn harvest' : 'Off-turn harvest';
                    return `<span style="display:inline-block;padding:2px 8px;border-radius:999px;border:1px solid ${border};background:${bg};color:${fg};font-size:12px;font-weight:700;">${label}</span>`;
                }

                if (!reqId || reqId === gameState?.game_id) {
                    panel.innerHTML = '';
                    return;
                }

                if (reqAction === 'finalize_roll') {
                    return renderFinalizeRollPrompt(gameState);
                }

                if (reqAction === 'domain_self_convert') {
                    return renderDomainSelfConvertPrompt(gameState);
                }

                if (reqAction === 'event_gain_action') {
                    return renderEventGainActionPrompt(gameState);
                }

                if (reqAction === 'harvest_optional_exchange') {
                    return renderHarvestOptionalExchangePrompt(gameState);
                }

                if (reqAction === 'harvest_wild_gain_exchange') {
                    return renderHarvestWildGainExchangePrompt(gameState);
                }

                if (reqAction === 'harvest_wild_cost_exchange') {
                    return renderHarvestWildCostExchangePrompt(gameState);
                }

                if (reqAction === 'choose_player') {
                    return renderDomainChoosePlayer(gameState);
                }
                if (reqAction === 'choose_monster_strength') {
                    return renderDomainChooseMonster(gameState);
                }
                if (reqAction === 'choose_owned_card') {
                    return renderChooseOwnedCard(gameState);
                }

                // Generic "choose ..." prompt from special payouts (e.g. "choose g 1 m 1")
                // Engine expects the response to be "choose 1"/"choose 2"/"choose 3".
                if (typeof reqAction === 'string' && reqAction.trim().startsWith('choose ')) {
                    return renderChoosePrompt(gameState, reqAction);
                }

                if (reqAction === 'manual_harvest') {
                    const slots = Array.isArray(gameState?.harvest_prompt_slots) ? gameState.harvest_prompt_slots : [];
                    const isYou = (playerId && reqId === playerId);
                    if (!isYou) {
                        const badge = harvestTurnBadge(reqId);
                        panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                                <div>Manual harvest in progress for <code>${escapeHtml(reqId)}</code> (${slots.length} card(s)).</div>
                                ${badge}
                            </div>
                        </div>`;
                        return;
                    }
                    if (!slots.length) {
                        const badge = harvestTurnBadge(reqId);
                        panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                                <div>Harvest: no slots (try Refresh).</div>
                                ${badge}
                            </div>
                        </div>`;
                        return;
                    }
                    const thiefNote = slots.some(s => s.kind === 'citizen' && s.is_thief)
                        ? '<div class="mini" style="margin-bottom:8px;">If you have the Thief, harvest that citizen before other citizens.</div>'
                        : '';
                    const badge = harvestTurnBadge(reqId);
                    const btns = slots.map(s => {
                        const ai = Number(s.activation_index);
                        const dup = Number.isFinite(ai) && ai > 0 ? ` · #${ai + 1}` : '';
                        const ci = Number(s.card_idx);
                        const copy = Number.isFinite(ci) ? ` · copy ${ci + 1}` : '';
                        const label = `${escapeHtml(s.name || '')} (${escapeHtml(s.kind)} #${escapeHtml(String(s.card_id))}${copy}${dup})`;
                        const sk = escapeHtml(s.slot_key || '');
                        return `<button type="button" onclick="sendHarvestCard('${sk}')">Harvest: ${label}</button>`;
                    }).join(' ');
                    panel.innerHTML = `
                        <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                                <div style="font-weight:700;">Harvest (choose order)</div>
                                ${badge}
                            </div>
                            ${thiefNote}
                            <div style="display:flex;gap:8px;flex-wrap:wrap;">${btns}</div>
                        </div>`;
                    return;
                }

                if (reqAction !== 'bonus_resource_choice') {
                    if (reqAction === 'standard_action') {
                        return renderStandardActionPanel(gameState);
                    }

                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${reqAction}</strong>
                    </div>`;
                    return;
                }

                const isYou = (playerId && reqId === playerId);
                if (!isYou) {
                    const badge = harvestTurnBadge(reqId);
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                            <div>Harvest bonus choice pending for <code>${reqId}</code>.</div>
                            ${badge}
                        </div>
                    </div>`;
                    return;
                }

                const badge = harvestTurnBadge(reqId);
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
                            <div style="font-weight:700;">Harvest bonus: choose +1 resource</div>
                            ${badge}
                        </div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <button onclick="sendBonusChoice('gold')">+1 Gold</button>
                            <button onclick="sendBonusChoice('strength')">+1 Strength</button>
                            <button onclick="sendBonusChoice('magic')">+1 Magic</button>
                        </div>
                    </div>
                `;
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
                // Expected formats:
                // - "choose g 1 m 1" (two options)
                // - "choose g 1 s 1 m 1" (three options)
                const parts = (cmd || '').toString().trim().split(/\s+/);
                if (!parts.length || parts[0] !== 'choose') return [];
                const options = [];
                // pairs start at index 1: [token, amount]
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

            function renderChoosePrompt(gameState, chooseCmd) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const isYou = (playerId && reqId === playerId);
                const pendingChoice = gameState?.pending_required_choice || null;

                let options = parseChooseCommand(chooseCmd);
                if (
                    pendingChoice &&
                    pendingChoice.kind === 'special_payout_choose' &&
                    Array.isArray(pendingChoice.options) &&
                    pendingChoice.options.length
                ) {
                    options = pendingChoice.options;
                }
                if (!options.length) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${escapeHtml(chooseCmd)}</strong>
                    </div>`;
                    return;
                }

                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${reqId}</code>: <strong>${escapeHtml(chooseCmd)}</strong>
                    </div>`;
                    return;
                }

                const buttons = options.map((opt, idx) => {
                    const token = (opt?.token || '').toString();
                    const label = labelForChoiceToken(token);
                    const amt = Number(opt.amount);
                    const prettyAmt = Number.isFinite(amt) ? amt : opt.amount;
                    const isCitizen = token.trim().toLowerCase().startsWith('citizens.');
                    if ((token || '').toString().trim().toLowerCase() === 'count_area') {
                        const area = (opt?.area ?? '').toString();
                        const res = (opt?.resource ?? '').toString().toLowerCase();
                        const mult = Number(opt?.mult);
                        const rLabel = labelForChoiceToken(res);
                        const mText = Number.isFinite(mult) ? mult : opt?.mult;
                        return `<button onclick="sendChooseIndex(${idx + 1})">+(${escapeHtml(mText)} x ${escapeHtml(area)}) ${escapeHtml(rLabel)}</button>`;
                    }
                    if (isCitizen) {
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
                        const cid = Number(opt?.citizen_id);
                        let have = 0;
                        let remaining = 0;
                        if (Number.isFinite(cid)) {
                            const player = Array.isArray(gameState?.player_list)
                                ? gameState.player_list.find(p => (p?.player_id || '') === playerId)
                                : null;
                            const ownedCitizens = Array.isArray(player?.owned_citizens) ? player.owned_citizens : [];
                            for (const card of ownedCitizens) {
                                if (Number(card?.citizen_id) === cid) have += 1;
                            }
                            const grid = Array.isArray(gameState?.citizen_grid) ? gameState.citizen_grid : [];
                            for (const stack of grid) {
                                if (!Array.isArray(stack)) continue;
                                for (const card of stack) {
                                    if (Number(card?.citizen_id) === cid) remaining += 1;
                                }
                            }
                        }
                        const cost = Number(opt?.gold_cost);
                        const prettyCost = Number.isFinite(cost) ? cost : 0;
                        const infoSuffix = ` (Cost: ${prettyCost} Have: ${have} Remain: ${remaining})`;
                        const who = name ? `${name} citizen${infoSuffix}` : `${label}${infoSuffix}`;
                        return `<button onclick="sendChooseIndex(${idx + 1})">Gain ${escapeHtml(prettyAmt)} ${escapeHtml(who)}${escapeHtml(extraSuffix)}</button>`;
                    }
                    return `<button onclick="sendChooseIndex(${idx + 1})">+${escapeHtml(prettyAmt)} ${escapeHtml(label)}</button>`;
                }).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Choose one</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            ${buttons}
                        </div>
                    </div>
                `;
            }

            // Globals so inline onclicks in the two-stage prompt HTML can find
            // them. We pass data via the button's data-* attributes (rather
            // than baking values into the onclick string) so domain names with
            // quotes, backslashes, or HTML can't break attribute parsing.
            // `stageFirstModifierClickFromBtn` stashes the chosen first option
            // and re-renders into stage 2; `stageBackClick` clears the staging
            // and re-renders stage 1. Both rely on `lastGameState` for the
            // re-render input.
            window.stageFirstModifierClickFromBtn = function (btn) {
                if (!btn || !btn.dataset) return;
                const rolled1 = clampDie(lastGameState?.rolled_die_one ?? lastGameState?.die_one ?? 1);
                const rolled2 = clampDie(lastGameState?.rolled_die_two ?? lastGameState?.die_two ?? 1);
                const did = btn.dataset.domainId;
                stagedFirstModifier = {
                    die: Number(btn.dataset.die),
                    target: Number(btn.dataset.target),
                    costGold: Number(btn.dataset.costGold),
                    domainId: (did === '' || did === undefined) ? null : Number(did),
                    domainName: String(btn.dataset.domainName || ''),
                };
                stagedFirstModifierForRoll = stagedRollKey(rolled1, rolled2);
                if (lastGameState) renderFinalizeRollPrompt(lastGameState);
            };
            window.stageBackClick = function () {
                resetFinalizeRollStaging();
                if (lastGameState) renderFinalizeRollPrompt(lastGameState);
            };

            function renderFinalizeRollPrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const rolled1 = clampDie(gameState?.rolled_die_one ?? gameState?.die_one ?? 1);
                const rolled2 = clampDie(gameState?.rolled_die_two ?? gameState?.die_two ?? 1);

                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on required action from <code>${escapeHtml(reqId)}</code>: <strong>finalize_roll</strong>
                    </div>`;
                    return;
                }

                const player = Array.isArray(gameState?.player_list)
                    ? gameState.player_list.find(p => (p?.player_id || '') === playerId)
                    : null;

                const rollKey = stagedRollKey(rolled1, rolled2);
                if (stagedFirstModifierForRoll !== rollKey) resetFinalizeRollStaging();
                const staged = stagedFirstModifier;

                let buttonsHtml = '';
                let noteHtml = '';
                let stagedLine = '';

                if (!staged) {
                    const options = listRollSetOneDieOptions(player, rolled1, rolled2, gameState.turn_number);
                    const keepBtn = `<button onclick="sendFinalizeRollChoice(${rolled1}, ${rolled2})">Keep ${rolled1} + ${rolled2}</button>`;
                    const modBtns = options.map((o) => {
                        const fromVal = (o.die === 1) ? rolled1 : rolled2;
                        const didAttr = (o.domainId === null || o.domainId === undefined) ? '' : Number(o.domainId);
                        return `<button data-die="${o.die}" data-target="${o.target}" data-cost-gold="${o.costGold}" data-domain-id="${didAttr}" data-domain-name="${escapeHtml(o.domainName)}" onclick="stageFirstModifierClickFromBtn(this)">Set die ${o.die}: ${fromVal} → ${o.target} (pay ${o.costGold}g via ${escapeHtml(o.domainName)})</button>`;
                    }).join(' ');
                    buttonsHtml = keepBtn + ' ' + modBtns;
                    noteHtml = options.length
                        ? '<div class="mini" style="margin-top:6px;">Choose a roll modifier (or keep). You can chain a second modifier on the other die.</div>'
                        : '<div class="mini" style="margin-top:6px;">No roll modifiers available; finalize to continue.</div>';
                } else {
                    const stagedFromVal = staged.die === 1 ? rolled1 : rolled2;
                    const d1AfterFirst = staged.die === 1 ? staged.target : rolled1;
                    const d2AfterFirst = staged.die === 2 ? staged.target : rolled2;
                    stagedLine =
                        `<div style="margin:6px 0;">Staged: <strong>Die ${staged.die}: ${stagedFromVal} → ${staged.target}</strong>` +
                        ` (${staged.costGold}g via ${escapeHtml(staged.domainName)}). ` +
                        `Result so far: <strong>${d1AfterFirst} + ${d2AfterFirst} = ${d1AfterFirst + d2AfterFirst}</strong>.</div>`;

                    const confirmBtn = `<button onclick="sendFinalizeRollChoice(${d1AfterFirst}, ${d2AfterFirst})">Confirm ${d1AfterFirst} + ${d2AfterFirst}</button>`;

                    const otherDie = staged.die === 1 ? 2 : 1;
                    const remainingGold = Math.max(0, Number(player?.gold_score || 0) - Number(staged.costGold || 0));
                    const stage2Options = listRollSetOneDieOptions(
                        player, rolled1, rolled2, gameState.turn_number,
                        { die: otherDie, excludeDomainId: staged.domainId, budgetGold: remainingGold }
                    );
                    const chainBtns = stage2Options.map((o) => {
                        const fromVal = (o.die === 1) ? rolled1 : rolled2;
                        const d1 = (o.die === 1) ? o.target : d1AfterFirst;
                        const d2 = (o.die === 2) ? o.target : d2AfterFirst;
                        return `<button onclick="sendFinalizeRollChoice(${d1}, ${d2})">+ Die ${o.die}: ${fromVal} → ${o.target} (pay ${o.costGold}g via ${escapeHtml(o.domainName)}) → ${d1} + ${d2}</button>`;
                    }).join(' ');
                    const backBtn = `<button onclick="stageBackClick()">Back</button>`;

                    buttonsHtml = confirmBtn + ' ' + chainBtns + ' ' + backBtn;
                    noteHtml = stage2Options.length
                        ? '<div class="mini" style="margin-top:6px;">Optionally chain a second modifier on the other die, or confirm with just the first.</div>'
                        : '<div class="mini" style="margin-top:6px;">No second modifier available - confirm to apply just the staged change.</div>';
                }

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Finalize Roll</div>
                        <div style="margin-bottom:8px;">Rolled: <strong>${rolled1} + ${rolled2}</strong></div>
                        ${stagedLine}
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            ${buttonsHtml}
                        </div>
                        ${noteHtml}
                    </div>
                `;
            }

            async function sendChooseIndex(n) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `choose ${Number(n)}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendChoosePlayerIndex(n) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `choose_player ${Number(n)}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendChooseMonsterIndex(n) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `choose_monster ${Number(n)}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendChooseOwnedCardIndex(n) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `choose_owned_card ${Number(n)}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendDomainManipulateSkip() {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: 'skip'
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
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

            function renderDomainSelfConvertPrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const dn = (prc?.domain_name || 'Domain').toString();
                const kv = prc?.kv || {};
                const explain = selfConvertExplain(kv);
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> for <strong>${escapeHtml(dn)}</strong> optional activation trade.
                    </div>`;
                    return;
                }
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">${escapeHtml(dn)}: optional trade</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">${escapeHtml(explain)}</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <button type="button" onclick="sendSelfConvertConfirm()">Confirm trade</button>
                            <button type="button" onclick="sendSelfConvertDecline()">Decline</button>
                        </div>
                    </div>`;
            }

            function renderEventGainActionPrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const name = (prc?.event_name || 'Event').toString();
                const payKind = (prc?.pay_kind || 'm').toString();
                const payAmount = Number(prc?.pay_amount || 0);
                const long = { g: 'gold', s: 'strength', m: 'magic' }[payKind] || payKind;
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> for <strong>${escapeHtml(name)}</strong> additional-action choice.
                    </div>`;
                    return;
                }
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">${escapeHtml(name)}</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">Pay ${payAmount} ${escapeHtml(long)} for an additional action?</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <button type="button" onclick="sendRequiredSimple('accept')">Pay ${payAmount} ${escapeHtml(long)}</button>
                            <button type="button" onclick="sendRequiredSimple('skip')">Decline</button>
                        </div>
                    </div>`;
            }

            async function sendRequiredSimple(action) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: action
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendSelfConvertConfirm() {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: 'confirm_self_convert'
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendSelfConvertDecline() {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: 'skip'
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
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

            function renderHarvestOptionalExchangePrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const cmd = (prc?.command || '').toString();
                const explain = harvestExchangeExplain(cmd);
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> — optional citizen harvest exchange.
                    </div>`;
                    return;
                }
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Harvest: optional exchange</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">${escapeHtml(explain)}</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            <button type="button" onclick="sendHarvestExchangeConfirm()">Take exchange</button>
                            <button type="button" onclick="sendHarvestExchangeSkip()">Skip (keep resources)</button>
                        </div>
                    </div>`;
            }

            async function sendHarvestExchangeConfirm() {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: 'confirm_harvest_exchange'
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendHarvestExchangeSkip() {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: 'skip_harvest_exchange'
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            function renderHarvestWildCostExchangePrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;

                const gainRes = (prc?.gain_resource || '').toLowerCase();
                const gainAmt = Number(prc?.gain_amount || 0);
                const costOpts = Array.isArray(prc?.cost_options) ? prc.cost_options : [];
                const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };

                const gainLabel = `${gainAmt} ${labels[gainRes] || gainRes.toUpperCase()}`;

                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> — choosing what to pay for +${escapeHtml(gainLabel)}.
                    </div>`;
                    return;
                }

                const btns = costOpts.map(opt => {
                    const r = (opt?.resource || '').toLowerCase();
                    const n = Number(opt?.amount || 0);
                    const label = `Pay ${n} ${labels[r] || r.toUpperCase()}`;
                    return `<button type="button" onclick="sendWildCostResource('${escapeHtml(r)}')">${escapeHtml(label)}</button>`;
                }).join(' ');
                const skipBtn = `<button type="button" onclick="sendHarvestExchangeSkip()">Skip (keep resources)</button>`;

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Harvest: pay for +${escapeHtml(gainLabel)}</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">Choose which resource to pay, or skip.</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">${btns}${skipBtn}</div>
                    </div>`;
            }

            async function sendWildCostResource(res) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `wild_cost_resource ${String(res).trim()}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            function renderHarvestWildGainExchangePrompt(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;

                const costRes = (prc?.cost_resource || '').toLowerCase();
                const costAmt = Number(prc?.cost_amount || 0);
                const gainAmt = Number(prc?.gain_amount || 0);
                const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };

                const costLabel = `${costAmt} ${labels[costRes] || costRes.toUpperCase()}`;
                const gainOptions = ['g', 's', 'm'];

                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> — choosing what to gain for ${escapeHtml(costLabel)}.
                    </div>`;
                    return;
                }

                const btns = gainOptions.map(r => {
                    const label = `Gain ${gainAmt} ${labels[r] || r.toUpperCase()}`;
                    return `<button type="button" onclick="sendWildGainResource('${escapeHtml(r)}')">${escapeHtml(label)}</button>`;
                }).join(' ');
                const skipBtn = `<button type="button" onclick="sendHarvestExchangeSkip()">Skip (keep resources)</button>`;

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">Harvest: pay ${escapeHtml(costLabel)}</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">Choose which resource to gain (${gainAmt}), or skip.</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">${btns}${skipBtn}</div>
                    </div>`;
            }

            async function sendWildGainResource(res) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: `wild_gain_resource ${String(res).trim()}`
                        })
                    });
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            function renderDomainChoosePlayer(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const opts = Array.isArray(prc?.options) ? prc.options : [];
                const dn = (prc?.item?.domain_name || 'Domain').toString();
                const explain = prc?.kind === 'domain_manipulate_player'
                    ? domainManipulateExplain(prc)
                    : 'Choose another player.';
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> to choose a player for <strong>${escapeHtml(dn)}</strong>.
                    </div>`;
                    return;
                }
                const kv = prc?.item?.kv || {};
                const skipLabel = (prc?.allow_skip && domainEffectGainIsVp(kv))
                    ? 'Decline (no pay, no VP)'
                    : 'Skip (optional)';
                const skipBtn = prc?.allow_skip
                    ? `<button type="button" onclick="sendDomainManipulateSkip()" style="margin-left:8px;">${escapeHtml(skipLabel)}</button>`
                    : '';
                const btns = opts.map((o, idx) => {
                    const nm = escapeHtml((o?.name || o?.player_id || '?').toString());
                    return `<button type="button" onclick="sendChoosePlayerIndex(${idx + 1})">${nm}</button>`;
                }).join(' ');
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">${escapeHtml(dn)}: choose another player</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">${escapeHtml(explain)}</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">${btns}${skipBtn}</div>
                    </div>`;
            }

            function renderDomainChooseMonster(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const opts = Array.isArray(prc?.options) ? prc.options : [];
                const dn = (prc?.domain_name || 'Domain').toString();
                const delta = Number(prc?.delta) || 0;
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        Waiting on <code>${escapeHtml(reqId)}</code> for <strong>${escapeHtml(dn)}</strong> (monster +${delta} strength cost).
                    </div>`;
                    return;
                }
                const btns = opts.map((o, idx) => {
                    const nm = escapeHtml((o?.name || '?').toString());
                    return `<button type="button" onclick="sendChooseMonsterIndex(${idx + 1})">${nm}</button>`;
                }).join(' ');
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">${escapeHtml(dn)}: add +${delta} to a center monster strength cost</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">${btns}</div>
                    </div>`;
            }

            // Resolve `pending_required_choice.kind` for a choose_owned_card prompt into
            // user-facing copy. Mirrors `chooseOwnedCardCopy` in static/game/src/05-prompts.js;
            // new consumers should be added in both places.
            function chooseOwnedCardCopy(prc, gameState) {
                const kind = (prc?.kind || '').toString();
                const cardKind = (prc?.card_kind || '').toString().toLowerCase();
                const noun = cardKind === 'monster' ? 'monster' : 'citizen';

                const playerName = (pid) => {
                    if (!pid) return 'that player';
                    const list = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                    const p = list.find(x => (x?.player_id || '') === pid);
                    const nm = (p?.name ?? '').toString().trim();
                    return nm || pid;
                };

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
                        waiting: (reqId) => `Waiting on ${reqId} to return a ${noun} for ${dn}.`,
                        skipLabel: 'Decline',
                    };
                }
                if (kind === 'banish_owned_card') {
                    return {
                        title: `Banish a ${noun}`,
                        explain: `Choose one of your owned ${noun}s. It is removed from play permanently (sent to the banish pile) — not face-down like a flip.`,
                        waiting: (reqId) => `Waiting on ${reqId} to banish a ${noun}.`,
                        skipLabel: 'Skip',
                    };
                }
                if (kind === 'banish_center_card') {
                    return {
                        title: `Banish a center-stack ${noun}`,
                        explain: `Choose one of the available ${noun}s from the center stacks. It is removed from play permanently (sent to the banish pile).`,
                        waiting: (reqId) => `Waiting on ${reqId} to banish a center-stack ${noun}.`,
                        skipLabel: 'Skip',
                    };
                }
                if (kind === 'monster_flip_citizen_targeted') {
                    const targetName = playerName(prc?.target_player_id);
                    return {
                        title: `Flip a citizen on ${targetName}'s tableau`,
                        explain: `Choose one of ${targetName}'s face-up citizens. It will be flipped face-down (no harvest payout, no role spend).`,
                        waiting: (reqId) => `Waiting on ${reqId} to flip a citizen on ${targetName}'s tableau.`,
                        skipLabel: 'Skip',
                    };
                }
                return {
                    title: `Choose one of your ${noun}s`,
                    explain: `Choose one of your owned ${noun}s.`,
                    waiting: (reqId) => `Waiting on ${reqId}.`,
                    skipLabel: 'Skip',
                };
            }

            function renderChooseOwnedCard(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const req = gameState?.action_required || {};
                const reqId = (req?.id || '').toString();
                const isYou = (playerId && reqId === playerId);
                const prc = gameState?.pending_required_choice || null;
                const opts = Array.isArray(prc?.options) ? prc.options : [];
                const copy = chooseOwnedCardCopy(prc, gameState);
                if (!isYou) {
                    panel.innerHTML = `<div style="padding:8px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${escapeHtml(copy.waiting(reqId))}
                    </div>`;
                    return;
                }
                const skipBtn = prc?.allow_skip
                    ? `<button type="button" onclick="sendDomainManipulateSkip()" style="margin-left:8px;">${escapeHtml(copy.skipLabel)}</button>`
                    : '';
                const btns = opts.length
                    ? opts.map((o, idx) => {
                        const nm = escapeHtml((o?.name || '?').toString());
                        const flipped = o?.is_flipped ? ' (flipped)' : '';
                        return `<button type="button" onclick="sendChooseOwnedCardIndex(${idx + 1})">${nm}${flipped}</button>`;
                    }).join(' ')
                    : '<span class="mini">No eligible cards.</span>';
                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:700;margin-bottom:8px;">${escapeHtml(copy.title)}</div>
                        <div class="mini" style="margin-bottom:8px;color:#333;">${escapeHtml(copy.explain)}</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">${btns}${skipBtn}</div>
                    </div>`;
            }

            // Concurrent (non-ordered) prompt rendering.
            //
            // The server exposes `concurrent_action = { kind, pending, completed, ... }`.
            // Every participant sees this state at the same time; players in `pending`
            // can submit a response in any order, and the game only advances once
            // `pending` is empty. To add a new kind, register a renderer in
            // CONCURRENT_RENDERERS keyed on the same `kind` used server-side.
            const CONCURRENT_RENDERERS = {
                choose_duke: renderChooseDukeConcurrent,
                flip_one_citizen: renderFlipOneCitizenConcurrent,
                harvest_choices: renderConcurrentHarvestChoices,
                event_self_convert: renderEventSelfConvertConcurrent,
                event_banish_citizen_for_reward: renderEventBanishForRewardConcurrent,
            };

            function renderConcurrentActionPanel(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const renderer = CONCURRENT_RENDERERS[concurrent.kind];
                if (renderer) {
                    return renderer(gameState, concurrent);
                }

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                    Waiting on concurrent action <strong>${escapeHtml(concurrent.kind || 'unknown')}</strong>
                    (${pending.length} player(s) still need to respond).
                </div>`;
            }

            function pendingPlayerLabels(gameState, pending) {
                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                return (pending || []).map(pid => {
                    const p = players.find(x => x?.player_id === pid);
                    return p?.name ? `${p.name}` : pid;
                });
            }

            function renderChooseDukeConcurrent(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const isPending = !!(playerId && pending.includes(playerId));
                const totalParticipants = pending.length + completed.length;

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const you = players.find(p => p?.player_id === playerId) || null;
                const waitingLabels = pendingPlayerLabels(gameState, pending);

                const statusLine = `<div class="mini" style="margin-bottom:8px;">
                    Starting setup: ${completed.length}/${totalParticipants} duke choice(s) submitted.
                    ${pending.length ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.` : ''}
                </div>`;

                if (!isPending) {
                    const youDone = !!(playerId && completed.includes(playerId));
                    const yourLine = youDone
                        ? `<div>You have already chosen your duke. Waiting on the other player(s).</div>`
                        : `<div>Starting setup is in progress.</div>`;
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}${yourLine}
                    </div>`;
                    return;
                }

                const dukes = Array.isArray(you?.owned_dukes) ? you.owned_dukes : [];
                if (!dukes.length) {
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}<div>No dukes found to choose from.</div>
                    </div>`;
                    return;
                }

                const buttons = dukes.map(d => {
                    const id = d?.duke_id;
                    const name = d?.name || `Duke #${id}`;
                    const fullText = cardFullText(d);
                    const sub = fullText ? `<div style="color:#333;font-size:13px;margin-top:6px;white-space:pre-wrap;">${escapeHtml(fullText)}</div>` : '';
                    return `<div style="border:1px solid #e6e6e6;background:#fff;border-radius:10px;padding:10px;">
                        <div style="font-weight:800;">${escapeHtml(name)} <span style="color:#666;font-weight:600;">(#${escapeHtml(id)})</span></div>
                        ${sub}
                        <div style="margin-top:8px;">
                            <button onclick="submitConcurrentAction('choose_duke', ${Number(id)})">Keep this duke</button>
                        </div>
                    </div>`;
                }).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${statusLine}
                        <div style="font-weight:800;margin-bottom:8px;">Choose 1 duke to keep</div>
                        <div style="display:flex;flex-direction:column;gap:8px;">${buttons}</div>
                    </div>
                `;
            }

            function renderFlipOneCitizenConcurrent(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const isPending = !!(playerId && pending.includes(playerId));
                const totalParticipants = pending.length + completed.length;
                const data = concurrent.data || {};
                const buyerId = (data.buyer_id || '').toString();
                const sourceLabel = (data.source_label || 'Cursed Cavern').toString();

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const buyer = players.find(p => (p?.player_id || '') === buyerId) || null;
                const buyerTag = buyer?.name ? `${escapeHtml(buyer.name)}` : (buyerId ? `<code>${escapeHtml(buyerId)}</code>` : '');
                const you = players.find(p => p?.player_id === playerId) || null;
                const waitingLabels = pendingPlayerLabels(gameState, pending);

                const statusLine = `<div class="mini" style="margin-bottom:8px;">
                    ${escapeHtml(sourceLabel)} — flip one citizen face-down: ${completed.length}/${totalParticipants} player choice(s) submitted.
                    ${pending.length ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.` : ''}
                    ${buyerTag ? `<div style="margin-top:6px;">Triggered by <strong>${buyerTag}</strong>.</div>` : ''}
                </div>`;

                if (!isPending) {
                    const youDone = !!(playerId && completed.includes(playerId));
                    const yourLine = youDone
                        ? `<div>You already chose a citizen to flip. Waiting on other players.</div>`
                        : `<div>You have no pending flip choice (no eligible citizens, or not in this prompt).</div>`;
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}${yourLine}
                    </div>`;
                    return;
                }

                const citizens = Array.isArray(you?.owned_citizens) ? you.owned_citizens : [];
                const choices = [];
                citizens.forEach((c, idx) => {
                    if (!c || c.is_flipped) return;
                    const nm = (c.name || `Citizen #${idx}`).toString();
                    choices.push({ idx, card: c, nm });
                });

                if (!choices.length) {
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}<div>No face-up citizens on your tableau — contact host if this seems wrong.</div>
                    </div>`;
                    return;
                }

                const buttons = choices.map(({ idx, card, nm }) => {
                    const rm = card.roll_match1 !== undefined || card.roll_match2 !== undefined
                        ? ` · Roll ${card.roll_match1 ?? ''}/${card.roll_match2 ?? ''}`
                        : '';
                    const gc = card.gold_cost !== undefined ? ` · Cost ${card.gold_cost}g` : '';
                    return `<div style="border:1px solid #e6e6e6;background:#fff;border-radius:10px;padding:10px;margin-bottom:8px;">
                        <div style="font-weight:800;">${escapeHtml(nm)} <span style="color:#666;font-weight:600;">(slot #${idx})</span></div>
                        <div style="color:#555;font-size:13px;margin-top:4px;">${escapeHtml(rm + gc)}</div>
                        <div style="margin-top:8px;">
                            <button type="button" onclick="submitConcurrentAction('flip_one_citizen', '${idx}')">Flip this citizen face-down</button>
                        </div>
                    </div>`;
                }).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${statusLine}
                        <div style="font-weight:800;margin-bottom:8px;">Choose 1 citizen to flip face-down</div>
                        <div style="display:flex;flex-direction:column;">${buttons}</div>
                    </div>
                `;
            }

            // Event: each player may pay a resource for a bank gain (e.g. Support The Empire).
            // For a 'wild' cost the player picks which resource (g/s/m) to spend.
            function renderEventSelfConvertConcurrent(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const isPending = !!(playerId && pending.includes(playerId));
                const totalParticipants = pending.length + completed.length;
                const data = concurrent.data || {};
                const name = (data.name || 'Event').toString();
                const payKind = (data.pay_kind || 'g').toString();
                const payAmount = Number(data.pay_amount || 0);
                const gainKind = (data.gain_kind || 'v').toString();
                const gainAmount = Number(data.gain_amount || 0);
                const waitingLabels = pendingPlayerLabels(gameState, pending);

                const statusLine = `<div class="mini" style="margin-bottom:8px;">
                    ${escapeHtml(name)}: ${completed.length}/${totalParticipants} player choice(s) submitted.
                    ${pending.length ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.` : ''}
                </div>`;

                if (!isPending) {
                    const youDone = !!(playerId && completed.includes(playerId));
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}<div>${youDone ? 'You already responded. Waiting on other players.' : 'You have no pending response in this event.'}</div>
                    </div>`;
                    return;
                }

                let payButtons;
                if (payKind === 'wild') {
                    payButtons = ['g', 's', 'm'].map(r => {
                        const long = { g: 'gold', s: 'strength', m: 'magic' }[r];
                        return `<button type="button" onclick="submitConcurrentAction('event_self_convert', '${r}')">Pay ${payAmount} ${long}</button>`;
                    }).join(' ');
                } else {
                    payButtons = `<button type="button" onclick="submitConcurrentAction('event_self_convert', 'accept')">Pay ${payAmount}${escapeHtml(payKind)}</button>`;
                }

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${statusLine}
                        <div style="font-weight:800;margin-bottom:8px;">${escapeHtml(name)}: pay ${payAmount}${payKind === 'wild' ? ' (your choice of g/s/m)' : escapeHtml(payKind)} for ${gainAmount}${escapeHtml(gainKind)}?</div>
                        <div style="display:flex;gap:8px;flex-wrap:wrap;">
                            ${payButtons}
                            <button type="button" onclick="submitConcurrentAction('event_self_convert', 'skip')">Decline</button>
                        </div>
                    </div>
                `;
            }

            // Event: each player may banish one owned citizen (optionally role-filtered)
            // for a bank reward (e.g. A Call To Arms: banish a Soldier for 3 VP).
            function renderEventBanishForRewardConcurrent(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const isPending = !!(playerId && pending.includes(playerId));
                const totalParticipants = pending.length + completed.length;
                const data = concurrent.data || {};
                const name = (data.name || 'Event').toString();
                const role = (data.role || '').toString();
                const gainKind = (data.gain_kind || 'v').toString();
                const gainAmount = Number(data.gain_amount || 0);
                const roleAttr = { shadow: 'shadow_count', holy: 'holy_count', soldier: 'soldier_count', worker: 'worker_count' }[role];
                const waitingLabels = pendingPlayerLabels(gameState, pending);

                const statusLine = `<div class="mini" style="margin-bottom:8px;">
                    ${escapeHtml(name)}: ${completed.length}/${totalParticipants} player choice(s) submitted.
                    ${pending.length ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.` : ''}
                </div>`;

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const you = players.find(p => p?.player_id === playerId) || null;

                if (!isPending) {
                    const youDone = !!(playerId && completed.includes(playerId));
                    panel.innerHTML = `<div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#fff6d8;">
                        ${statusLine}<div>${youDone ? 'You already responded. Waiting on other players.' : 'You have no pending response in this event.'}</div>
                    </div>`;
                    return;
                }

                const citizens = Array.isArray(you?.owned_citizens) ? you.owned_citizens : [];
                const choices = [];
                citizens.forEach((c, idx) => {
                    if (!c || c.is_flipped) return;
                    if (roleAttr && !(Number(c[roleAttr] || 0) > 0)) return;
                    choices.push({ idx, nm: (c.name || `Citizen #${idx}`).toString() });
                });

                const buttons = choices.map(({ idx, nm }) =>
                    `<div style="border:1px solid #e6e6e6;background:#fff;border-radius:10px;padding:10px;margin-bottom:8px;">
                        <div style="font-weight:800;">${escapeHtml(nm)} <span style="color:#666;font-weight:600;">(slot #${idx})</span></div>
                        <div style="margin-top:8px;">
                            <button type="button" onclick="submitConcurrentAction('event_banish_citizen_for_reward', '${idx}')">Banish for ${gainAmount}${escapeHtml(gainKind)}</button>
                        </div>
                    </div>`
                ).join('');

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${statusLine}
                        <div style="font-weight:800;margin-bottom:8px;">${escapeHtml(name)}: banish a${role ? ' ' + escapeHtml(role) : ''} citizen for ${gainAmount}${escapeHtml(gainKind)}?</div>
                        <div style="display:flex;flex-direction:column;">${buttons || '<div class="mini">No eligible citizen.</div>'}</div>
                        <div style="margin-top:8px;">
                            <button type="button" onclick="submitConcurrentAction('event_banish_citizen_for_reward', 'skip')">Decline</button>
                        </div>
                    </div>
                `;
            }

            // Per-player harvest roster (concurrent gate).
            //
            // Renders ALL participants in one panel. Each row has:
            //   - Player name (with 'You' tag for the viewer)
            //   - A short summary of their current decision
            //   - An action cell: buttons (your own row, with a pending
            //     prompt), a spinner (other players still pending), or
            //     a check (players who finished).
            function harvestPromptSubKindLabel(subKind) {
                switch ((subKind || '').toString()) {
                    case 'harvest_optional_exchange':  return 'Optional exchange';
                    case 'harvest_wild_cost_exchange': return 'Wild-cost exchange';
                    case 'harvest_wild_gain_exchange': return 'Wild-gain exchange';
                    case 'bonus_resource_choice':      return 'Harvest bonus';
                    case 'harvest_choose':             return 'Choose one';
                    default:                           return 'Harvest decision';
                }
            }
            function harvestPromptSummaryText(prompt) {
                if (!prompt) return '';
                const sub = (prompt.sub_kind || '').toString();
                const prc = prompt.pending_required_choice || {};
                if (sub === 'harvest_optional_exchange') {
                    return harvestExchangeExplain((prc.command || '').toString());
                }
                if (sub === 'harvest_wild_cost_exchange') {
                    const gainRes = (prc.gain_resource || '').toLowerCase();
                    const gainAmt = Number(prc.gain_amount || 0);
                    const labels = { g: 'gold', s: 'strength', m: 'magic', v: 'victory points' };
                    return `Choose what to pay; gain ${gainAmt} ${labels[gainRes] || gainRes}.`;
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
                    return `Choose one: ${(prompt.action || prc.command || '').toString()}`;
                }
                return harvestPromptSubKindLabel(sub);
            }
            function harvestPromptButtonsHtml(prompt) {
                if (!prompt) return '';
                const sub = (prompt.sub_kind || '').toString();
                const prc = prompt.pending_required_choice || {};
                const act = (resp) => `submitConcurrentAction('harvest_choices', '${escapeHtml(String(resp).replace(/'/g, "\\'"))}')`;
                if (sub === 'harvest_optional_exchange') {
                    return `
                        <button type="button" onclick="${act('confirm_harvest_exchange')}">Take</button>
                        <button type="button" onclick="${act('skip_harvest_exchange')}">Skip</button>
                    `;
                }
                if (sub === 'harvest_wild_cost_exchange') {
                    const opts = Array.isArray(prc.cost_options) ? prc.cost_options : [];
                    const labels = { g: 'Gold', s: 'Strength', m: 'Magic', v: 'VP' };
                    const choices = opts.map(o => {
                        const r = (o?.resource || '').toLowerCase();
                        const n = Number(o?.amount || 0);
                        return `<button type="button" onclick="${act(`wild_cost_resource ${r}`)}">Pay ${n} ${escapeHtml(labels[r] || r.toUpperCase())}</button>`;
                    }).join(' ');
                    return `${choices} <button type="button" onclick="${act('skip_harvest_exchange')}">Skip</button>`;
                }
                if (sub === 'harvest_wild_gain_exchange') {
                    const gainAmt = Number(prc.gain_amount || 0);
                    const labels = { g: 'Gold', s: 'Strength', m: 'Magic' };
                    const choices = ['g', 's', 'm'].map(r =>
                        `<button type="button" onclick="${act(`wild_gain_resource ${r}`)}">Gain ${gainAmt} ${escapeHtml(labels[r])}</button>`
                    ).join(' ');
                    return `${choices} <button type="button" onclick="${act('skip_harvest_exchange')}">Skip</button>`;
                }
                if (sub === 'bonus_resource_choice') {
                    return `
                        <button type="button" onclick="${act('gold')}">+1 Gold</button>
                        <button type="button" onclick="${act('strength')}">+1 Strength</button>
                        <button type="button" onclick="${act('magic')}">+1 Magic</button>
                    `;
                }
                if (sub === 'harvest_choose') {
                    const options = parseChooseCommand((prompt.action || '').toString());
                    if (!options.length) return '';
                    return options.map((opt, idx) => {
                        const token = (opt?.token || '').toString();
                        const label = labelForChoiceToken(token);
                        const amt = Number(opt.amount);
                        const prettyAmt = Number.isFinite(amt) ? amt : opt.amount;
                        return `<button type="button" onclick="${act(`choose ${idx + 1}`)}">+${prettyAmt} ${escapeHtml(label)}</button>`;
                    }).join(' ');
                }
                return '';
            }
            function renderConcurrentHarvestChoices(gameState, concurrent) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;

                const pending = Array.isArray(concurrent.pending) ? concurrent.pending : [];
                const completed = Array.isArray(concurrent.completed) ? concurrent.completed : [];
                const prompts = (concurrent?.data && concurrent.data.prompts && typeof concurrent.data.prompts === 'object')
                    ? concurrent.data.prompts
                    : {};
                const phase = (concurrent?.data && concurrent.data.phase) || 'scan';

                const myPid = (playerId || '').toString();

                const order = Array.isArray(gameState?.harvest_player_order) && gameState.harvest_player_order.length
                    ? gameState.harvest_player_order
                    : (Array.isArray(gameState?.player_list) ? gameState.player_list.map(p => p?.player_id).filter(Boolean) : []);
                const participantSet = new Set([...pending.map(String), ...completed.map(String)]);
                const participantIds = [];
                order.forEach(pid => {
                    const s = String(pid);
                    if (participantSet.has(s) && !participantIds.includes(s)) participantIds.push(s);
                });
                participantSet.forEach(s => {
                    if (!participantIds.includes(s)) participantIds.push(s);
                });

                const total = participantIds.length;
                const done = completed.length;
                const titleLine = phase === 'finalize_bonus'
                    ? `End-of-harvest bonus: ${done}/${total} player(s) submitted.`
                    : `Harvest decisions: ${done}/${total} player(s) submitted.`;
                const waitingLabels = pendingPlayerLabels(gameState, pending);
                const subtitle = pending.length
                    ? `Waiting on: <strong>${escapeHtml(waitingLabels.join(', '))}</strong>.`
                    : 'Finalizing harvest…';

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                function nameFor(pid) {
                    const p = players.find(x => (x?.player_id || '') === pid);
                    return (p?.name ?? pid ?? 'Player').toString();
                }

                const rowsHtml = participantIds.map(pid => {
                    const isMe = String(pid) === String(myPid);
                    const isPending = pending.some(p => String(p) === String(pid));
                    const prompt = prompts[pid] || prompts[String(pid)] || null;

                    const youTag = isMe
                        ? `<span style="font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:1px 6px;border-radius:999px;background:#fce29a;color:#7a560b;border:1px solid #c7972a;margin-left:6px;">You</span>`
                        : '';
                    const subBadge = prompt
                        ? `<span style="font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:1px 6px;border-radius:999px;background:#eee;color:#555;border:1px solid #ddd;margin-left:6px;">${escapeHtml(harvestPromptSubKindLabel(prompt.sub_kind))}</span>`
                        : '';
                    const nameCell = `<div style="font-weight:700;">${escapeHtml(nameFor(pid))}${youTag}${subBadge}</div>`;

                    let summaryText;
                    if (prompt) summaryText = harvestPromptSummaryText(prompt);
                    else summaryText = isPending ? 'Resolving harvest…' : 'All decisions complete.';
                    const summaryCell = `<div style="font-size:13px;color:#333;">${escapeHtml(summaryText)}</div>`;

                    let actionHtml;
                    if (!isPending) {
                        actionHtml = `
                            <div style="display:inline-flex;align-items:center;gap:6px;color:#1f6a3a;font-weight:700;">
                                <span style="display:inline-flex;width:18px;height:18px;border-radius:50%;background:#e3f5e9;border:1px solid #8ad0a4;align-items:center;justify-content:center;color:#1f6a3a;font-weight:800;font-size:13px;">&#10003;</span>
                                <span>Done</span>
                            </div>`;
                    } else if (isMe && prompt) {
                        const btns = harvestPromptButtonsHtml(prompt);
                        if (btns.trim().length) {
                            actionHtml = `<div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;">${btns}</div>`;
                        } else {
                            actionHtml = `
                                <div style="display:inline-flex;align-items:center;gap:6px;color:#666;font-weight:600;">
                                    <span class="harvest-spinner" style="display:inline-block;width:16px;height:16px;border-radius:50%;border:2px solid #ddd;border-top-color:#7a7a7a;animation:harvest-spin .85s linear infinite;"></span>
                                    <span>Waiting</span>
                                </div>`;
                        }
                    } else {
                        actionHtml = `
                            <div style="display:inline-flex;align-items:center;gap:6px;color:#666;font-weight:600;">
                                <span class="harvest-spinner" style="display:inline-block;width:16px;height:16px;border-radius:50%;border:2px solid #ddd;border-top-color:#7a7a7a;animation:harvest-spin .85s linear infinite;"></span>
                                <span>Waiting</span>
                            </div>`;
                    }
                    const rowBg = isMe ? '#fff8e0' : '#fff';
                    const rowBorder = isMe ? '#e0b941' : '#e6e6e6';
                    return `
                        <div style="display:grid;grid-template-columns:minmax(140px,1.2fr) minmax(160px,2fr) minmax(160px,auto);gap:10px;align-items:center;padding:8px 10px;border:1px solid ${rowBorder};border-radius:8px;background:${rowBg};">
                            ${nameCell}
                            ${summaryCell}
                            <div style="display:flex;justify-content:flex-end;align-items:center;">${actionHtml}</div>
                        </div>`;
                }).join('');

                panel.innerHTML = `
                    <style>@keyframes harvest-spin { to { transform: rotate(360deg); } }</style>
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        <div style="font-weight:800;margin-bottom:4px;">${escapeHtml(phase === 'finalize_bonus' ? 'Harvest bonus' : 'Harvest decisions')}</div>
                        <div class="mini" style="margin-bottom:6px;">${escapeHtml(titleLine)}</div>
                        <div class="mini" style="margin-bottom:10px;color:#444;">${subtitle}</div>
                        <div style="display:flex;flex-direction:column;gap:6px;">${rowsHtml}</div>
                    </div>`;
            }

            async function submitConcurrentAction(kind, response) {
                if (!playerId || !currentGameId) return;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'submit_concurrent_action',
                            kind: String(kind),
                            response: String(response)
                        })
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        alert(err.detail || res.statusText || 'Submit failed');
                        return;
                    }
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            // Magic reserved for off-turn `exchange m N ...` citizen specials (e.g. magic-cost converts
            // a player will want to use on opponents' harvests). Skips flipped citizens since their
            // off-turn payouts can't trigger. Returns { total, breakdown: [{name, perCard, count}] }.
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

                // Rule: you must contribute at least 1 of a required color to use magic as wild.
                // Example: cost S8 cannot be paid with M8 alone; you need at least S1, then M can cover the rest.
                if (goldCost > 0 && deficitGold > 0 && G <= 0) return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold, deficitStrength, remainingMagic, reservedMagic };
                if (strengthCost > 0 && deficitStrength > 0 && S <= 0) return { ok: false, payGold: 0, payStrength: 0, payMagic: 0, deficitGold, deficitStrength, remainingMagic, reservedMagic };

                const ok = (deficitGold + deficitStrength) <= remainingMagic;

                // Magic-first suggestion: cover as much of the primary cost as possible with magic, paying
                // just 1 of the primary resource (the minimum the server validator requires when using
                // magic as wild). Fall back to spending more primary when the player doesn't have enough
                // magic to cover the remainder.
                //
                // The `reservedMagic` budget reduces how much magic we *prefer* to spend as wild — but
                // only as a suggestion. If the player has no other way to pay the cost, we still dip
                // into the reservation (the action stays affordable; the suggestion just stops being
                // "polite").
                //
                // Don't-drain-the-primary override: if respecting the reservation would force the
                // suggestion to spend the player's *last* unit of the primary resource, and the player
                // has enough total magic (ignoring the reservation) to instead spend just 1 primary,
                // prefer that — even if it dips into the reservation.
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

            function topOfStack(stack) {
                if (!Array.isArray(stack) || stack.length === 0) return null;
                return stack[stack.length - 1];
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

            function normalizedPassiveEffects(player, turnNumber) {
                const out = [];
                const domains = Array.isArray(player?.owned_domains) ? player.owned_domains : [];
                domains.forEach((d) => {
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
                    // Backward-compatibility for seed data where passive_effect is NULL
                    // and behavior only exists in human-readable card text.
                    if (name.includes('emerald stronghold') || (text.includes("ignore '+'") && text.includes('buying citizens'))) {
                        out.push('action.emeraldstronghold');
                    }
                    if (name.includes("pratchett") || (text.includes('1gp less') && text.includes('domain'))) {
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

            function readPayRow(row) {
                const gEl = row.querySelector('.pay-g');
                const sEl = row.querySelector('.pay-s');
                const mEl = row.querySelector('.pay-m');
                const g = (!gEl || gEl.disabled) ? 0 : clampPayInt(gEl.value, gEl.min, gEl.max);
                const s = (!sEl || sEl.disabled) ? 0 : clampPayInt(sEl.value, sEl.min, sEl.max);
                const m = (!mEl || mEl.disabled) ? 0 : clampPayInt(mEl.value, mEl.min, mEl.max);
                return { gold: g, strength: s, magic: m };
            }

            function capturePayEditorRenderState(panel) {
                const state = {};
                if (!panel) return state;
                const active = document.activeElement;
                panel.querySelectorAll('.pay-cost-key').forEach((el) => {
                    const key = el.getAttribute('data-pay-key');
                    if (!key) return;
                    const row = el.closest('.pay-row');
                    const box = document.getElementById('pay-editor-' + key);
                    if (!row || !box) return;
                    const gEl = row.querySelector('.pay-g');
                    const sEl = row.querySelector('.pay-s');
                    const mEl = row.querySelector('.pay-m');
                    const entry = {
                        gold: gEl ? gEl.value : '',
                        strength: sEl ? sEl.value : '',
                        magic: mEl ? mEl.value : '',
                        focusClass: '',
                    };
                    if (active && row.contains(active)) {
                        if (active.classList.contains('pay-g')) entry.focusClass = 'pay-g';
                        else if (active.classList.contains('pay-s')) entry.focusClass = 'pay-s';
                        else if (active.classList.contains('pay-m')) entry.focusClass = 'pay-m';
                    }
                    state[key] = entry;
                });
                return state;
            }

            function restorePayEditorRenderState(panel, state) {
                if (!panel || !state) return;
                let focusTarget = null;
                panel.querySelectorAll('.pay-cost-key').forEach((el) => {
                    const key = el.getAttribute('data-pay-key');
                    const entry = key ? state[key] : null;
                    if (!entry) return;
                    const row = el.closest('.pay-row');
                    const box = document.getElementById('pay-editor-' + key);
                    if (!row || !box) return;
                    const gEl = row.querySelector('.pay-g');
                    const sEl = row.querySelector('.pay-s');
                    const mEl = row.querySelector('.pay-m');
                    if (gEl) gEl.value = clampPayInt(entry.gold, gEl.min, gEl.max);
                    if (sEl) sEl.value = clampPayInt(entry.strength, sEl.min, sEl.max);
                    if (mEl) mEl.value = clampPayInt(entry.magic, mEl.min, mEl.max);
                    if (entry.focusClass) {
                        focusTarget = row.querySelector('.' + entry.focusClass);
                    }
                });
                if (focusTarget) {
                    focusTarget.focus();
                }
            }

            async function hireCitizenFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'hire_citizen',
                        citizen_id: Number(row.dataset.citizenId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            async function buildDomainFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'build_domain',
                        domain_id: Number(row.dataset.domainId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            async function slayMonsterFromRow(btn) {
                const row = btn.closest('.pay-row');
                if (!row || !playerId || !currentGameId) return;
                const p = readPayRow(row);
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'slay_monster',
                        monster_id: Number(row.dataset.monsterId),
                        payment: { gold: p.gold, strength: p.strength, magic: p.magic }
                    })
                });
                getGameState(false);
            }

            function renderStandardActionPanel(gameState) {
                const panel = document.getElementById('choicePanel');
                if (!panel) return;
                const payEditorState = capturePayEditorRenderState(panel);

                const req = gameState?.action_required || {};
                const reqId = req?.id || '';
                const isYou = (playerId && reqId === playerId);
                const phase = (gameState?.phase || '').toString();
                const actionsRemaining = Number(gameState?.actions_remaining || 0);

                if (!reqId || reqId === gameState?.game_id || phase !== 'action') {
                    panel.innerHTML = '';
                    return;
                }

                const players = Array.isArray(gameState?.player_list) ? gameState.player_list : [];
                const you = players.find(p => p?.player_id === playerId) || null;
                const active = players.find(p => p?.player_id === reqId) || null;

                const p = (isYou ? you : active);
                const G = Number(p?.gold_score || 0);
                const S = Number(p?.strength_score || 0);
                const M = Number(p?.magic_score || 0);
                const V = Number(p?.victory_score || 0);
                const tn = Number(gameState?.turn_number);
                const emeraldActive = hasActionEffectFlag(p, 'action.emeraldstronghold', tn);
                const pratchettActive = hasActionEffectFlag(p, 'action.pratchettsplateau', tn);

                const affordCitizens = [];
                const affordDomains = [];
                const affordMonsters = [];

                // Evaluate citizens (top of each stack, accessible only)
                const citizenGrid = Array.isArray(gameState?.citizen_grid) ? gameState.citizen_grid : [];
                citizenGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const baseCost = Number(top.gold_cost || 0);
                    const surcharge = emeraldActive ? 0 : ownedNameCount(p, top.name);
                    const scaledCost = baseCost + surcharge;
                    const evalRes = canAffordCost(p, { gold: scaledCost, strength: 0, magicMin: 0 });
                    console.log('[AFFORD_CHECK] citizen', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_accessible && evalRes.ok) {
                        affordCitizens.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes, scaledCost, surcharge, baseCost, emeraldActive });
                    }
                });

                // Evaluate domains (top visible & accessible)
                const domainGrid = Array.isArray(gameState?.domain_grid) ? gameState.domain_grid : [];
                domainGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const baseCost = Number(top.gold_cost || 0);
                    const effectiveGold = Math.max(0, baseCost - (pratchettActive ? 1 : 0));
                    const evalRes = canAffordCost(p, { gold: effectiveGold, strength: 0, magicMin: 0 });
                    console.log('[AFFORD_CHECK] domain', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_visible && top.is_accessible && evalRes.ok) {
                        affordDomains.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes, baseCost, effectiveGold, pratchettActive });
                    }
                });

                // Evaluate monsters (top of each stack, accessible only; magic has minimum requirement)
                const monsterGrid = Array.isArray(gameState?.monster_grid) ? gameState.monster_grid : [];
                monsterGrid.forEach((stack, idx) => {
                    const top = topOfStack(stack);
                    if (!top) return;
                    const evalRes = canAffordCost(p, { gold: 0, strength: Number(top.strength_cost || 0), magicMin: Number(top.magic_cost || 0) });
                    console.log('[AFFORD_CHECK] monster', { stackIndex: idx, stackSize: stack?.length || 0, card: top, player: { G, S, M, V }, eval: evalRes });
                    if (top.is_accessible && evalRes.ok) {
                        affordMonsters.push({ card: top, stackIndex: idx, stackSize: stack.length, pay: evalRes });
                    }
                });

                const header = isYou
                    ? `<div style="font-weight:700;margin-bottom:6px;">Your action (${actionsRemaining} remaining)</div>`
                    : `<div style="font-weight:700;margin-bottom:6px;">Waiting on ${active?.name || reqId} to act (${actionsRemaining} remaining)</div>`;

                const resourcesLine = `<div style="margin-bottom:8px;">
                    Resources: <strong>G ${G}</strong> · <strong>S ${S}</strong> · <strong>M ${M}</strong> · <strong>VP ${V}</strong>
                </div>`;
                const activeEffects = [];
                if (emeraldActive) activeEffects.push('Emerald Stronghold: ignore citizen duplicate surcharge');
                if (pratchettActive) activeEffects.push("Pratchett's Plateau: domains cost 1 less gold");
                const effectsBanner = activeEffects.length
                    ? `<div class="mini" style="margin-bottom:8px;padding:6px 8px;border:1px solid #d5e8ff;background:#f4f9ff;border-radius:6px;">Active effects: ${escapeHtml(activeEffects.join(' · '))}</div>`
                    : '';

                const takeResourceRow = isYou
                    ? `<div style="margin-top:10px;padding-top:10px;border-top:1px solid #ccc;">
                        <strong>Take resource</strong> (uses 1 action, gain +1):
                        <button type="button" style="margin-left:6px;" onclick="takeResourceFromChoice('gold')">+1 Gold</button>
                        <button type="button" style="margin-left:4px;" onclick="takeResourceFromChoice('strength')">+1 Strength</button>
                        <button type="button" style="margin-left:4px;" onclick="takeResourceFromChoice('magic')">+1 Magic</button>
                    </div>`
                    : '';

                const listSection = (title, items, renderItem) => {
                    if (!items.length) return `<div style="margin-top:8px;"><strong>${title}:</strong> <span style="color:#666;">none affordable</span></div>`;
                    const rows = items.map(renderItem).join('');
                    return `<div style="margin-top:8px;"><strong>${title}:</strong><div style="display:flex;flex-direction:column;gap:6px;margin-top:6px;">${rows}</div></div>`;
                };

                const citizenHtml = listSection('Citizens', affordCitizens, (it) => {
                    const c = it.card;
                    const key = 'c-' + c.citizen_id;
                    const cost = Number(it.scaledCost ?? c.gold_cost ?? 0);
                    const pay = it.pay;
                    const rc = citizenRoleCounts(c);
                    const rbits = [];
                    if (rc.sn) rbits.push('Shadow+' + rc.sn);
                    if (rc.hn) rbits.push('Holy+' + rc.hn);
                    if (rc.son) rbits.push('Soldier+' + rc.son);
                    if (rc.wn) rbits.push('Worker+' + rc.wn);
                    const roleHint = rbits.length ? ' <span style="color:#555;">Roles: ' + rbits.join(', ') + '</span>' : '';
                    const dupHint = Number(it.surcharge || 0)
                        ? ' <span style="color:#666;">(base ' + Number(it.baseCost || 0) + ' + ' + Number(it.surcharge || 0) + ' dupes)</span>'
                        : '';
                    const emeraldHint = (!Number(it.surcharge || 0) && it.emeraldActive)
                        ? ' <span style="color:#666;">(Emerald: no duplicate surcharge)</span>'
                        : '';
                    const rulesText = cardFullText(c);
                    const rulesLine = rulesText
                        ? '<div style="margin-top:3px;color:#555;white-space:pre-wrap;">' + escapeHtml(rulesText) + '</div>'
                        : '';
                    const costSummary = 'Cost: G ' + cost + ' · pay G' + pay.payGold + (pay.payMagic ? ', M' + pay.payMagic : '') + dupHint + emeraldHint + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="hireCitizenFromRow(this)">Hire</button>' : '';
                    return '<div class="pay-row" data-citizen-id="' + c.citizen_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(c.name) + '</strong> (#' + c.citizen_id + ')' + roleHint + rulesLine + '</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-key" data-pay-key="' + key + '">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="' + G + '" value="' + pay.payGold + '"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="0" value="0" title="Citizens use gold and magic only"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                const domainHtml = listSection('Domains (visible tops)', affordDomains, (it) => {
                    const d = it.card;
                    const key = 'd-' + d.domain_id;
                    const cost = Number(it.effectiveGold ?? d.gold_cost ?? 0);
                    const pay = it.pay;
                    const pratchettHint = (it.pratchettActive && Number(it.baseCost || 0) !== cost)
                        ? ' <span style="color:#666;">(base ' + Number(it.baseCost || 0) + ' - 1 Pratchett)</span>'
                        : '';
                    const rulesText = cardFullText(d);
                    const rulesLine = rulesText
                        ? '<div style="margin-top:3px;color:#555;white-space:pre-wrap;">' + escapeHtml(rulesText) + '</div>'
                        : '';
                    const costSummary = 'Cost: G ' + cost + ' · pay G' + pay.payGold + (pay.payMagic ? ', M' + pay.payMagic : '') + pratchettHint + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="buildDomainFromRow(this)">Build</button>' : '';
                    return '<div class="pay-row" data-domain-id="' + d.domain_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(d.name) + '</strong> (#' + d.domain_id + ')' + rulesLine + '</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-key" data-pay-key="' + key + '">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="' + G + '" value="' + pay.payGold + '"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="0" value="0" title="Domains use gold and magic only"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                const monsterHtml = listSection('Monsters (top of each stack)', affordMonsters, (it) => {
                    const mcard = it.card;
                    const key = 'm-' + mcard.monster_id;
                    const sCost = Number(mcard.strength_cost || 0);
                    const mMin = Number(mcard.magic_cost || 0);
                    const pay = it.pay;
                    const rulesText = cardFullText(mcard);
                    const rulesLine = rulesText
                        ? '<div style="margin-top:3px;color:#555;white-space:pre-wrap;">' + escapeHtml(rulesText) + '</div>'
                        : '';
                    const costSummary = 'Cost: S ' + sCost + ' + M ' + mMin + ' min · pay S' + pay.payStrength + ', M' + pay.payMagic + ' · Stack ' + it.stackSize;
                    const btn = isYou ? '<button type="button" onclick="slayMonsterFromRow(this)">Slay</button>' : '';
                    return '<div class="pay-row" data-monster-id="' + mcard.monster_id + '">' +
                        btn +
                        ' <span><strong>' + escapeHtml(mcard.name) + '</strong> (#' + mcard.monster_id + ')' + rulesLine + '</span>' +
                        ' <span class="cost-line" style="color:#555;">' +
                        '<span class="pay-cost-key" data-pay-key="' + key + '">' + costSummary + '</span>' +
                        '<div id="pay-editor-' + key + '" class="pay-controls">' +
                        '<span style="display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap;">' +
                        '<label>G <input type="number" class="pay-g" min="0" max="0" value="0" title="Monsters use strength and magic only"></label>' +
                        '<label>S <input type="number" class="pay-s" min="0" max="' + S + '" value="' + pay.payStrength + '"></label>' +
                        '<label>M <input type="number" class="pay-m" min="0" max="' + M + '" value="' + pay.payMagic + '"></label>' +
                        '</span></div></span></div>';
                });

                panel.innerHTML = `
                    <div style="padding:10px;border:1px solid #ddd;border-radius:8px;background:#eef7ff;">
                        ${header}
                        ${resourcesLine}
                        ${effectsBanner}
                        ${takeResourceRow}
                        ${citizenHtml}
                        ${domainHtml}
                        ${monsterHtml}
                    </div>
                `;
                restorePayEditorRenderState(panel, payEditorState);
            }

            async function takeResourceFromChoice(resource) {
                if (!playerId || !currentGameId) return;
                const r = (resource || '').toString().trim().toLowerCase();
                if (!['gold', 'strength', 'magic'].includes(r)) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'take_resource',
                        resource: r
                    })
                });
                getGameState(false);
            }

            async function sendBonusChoice(resource) {
                if (!playerId || !currentGameId) return;
                try {
                    await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'act_on_required_action',
                            action: resource
                        })
                    });
                    // Refresh state so UI updates immediately
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                }
            }

            async function sendHarvestCard(slotKey, options = {}) {
                if (!playerId || !currentGameId) return;
                const suppressAlert = !!(options && options.suppressAlert);
                const sk = (slotKey || '').toString().trim();
                if (!sk) return;
                try {
                    const res = await fetch(`/api/game/${currentGameId}/action`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            player_id: playerId,
                            action_type: 'harvest_card',
                            harvest_slot_key: sk
                        })
                    });
                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        if (!suppressAlert) {
                            alert(err.detail || res.statusText || 'Harvest failed');
                        }
                        return;
                    }
                    getGameState(false);
                } catch (e) {
                    console.error(e);
                    if (!suppressAlert) {
                        alert(e.message || 'Harvest failed');
                    }
                }
            }

            async function hireCitizen(citizenId, goldCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'hire_citizen',
                        citizen_id: citizenId,
                        payment: {
                            gold: Number(goldCost || 0),
                            strength: 0,
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }

            async function buildDomain(domainId, goldCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'build_domain',
                        domain_id: domainId,
                        payment: {
                            gold: Number(goldCost || 0),
                            strength: 0,
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }

            async function slayMonster(monsterId, strengthCost, magicCost) {
                if (!playerId || !currentGameId) return;
                await fetch(`/api/game/${currentGameId}/action`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        player_id: playerId,
                        action_type: 'slay_monster',
                        monster_id: monsterId,
                        payment: {
                            gold: 0,
                            strength: Number(strengthCost || 0),
                            magic: Number(magicCost || 0)
                        }
                    })
                });
                getGameState(false);
            }
            
            // Auto-refresh lobby status
            setInterval(getLobbyStatus, 2000);
