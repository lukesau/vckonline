/**
 * Rejoin URL helpers + QR display (requires qrcode.min.js).
 */
(function (global) {
  function rejoinUrl(gameId, playerId) {
    const q = new URLSearchParams({ game_id: gameId, player_id: playerId });
    return `${location.origin}/?${q}`;
  }

  async function copyText(text) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) { /* fall through */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (_) {
      return false;
    }
  }

  function qrCanvas(text, cellSize) {
    if (typeof qrcode !== 'function') return null;
    const qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    const cs = cellSize || 4;
    const canvas = document.createElement('canvas');
    canvas.width = n * cs;
    canvas.height = n * cs;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#000';
    for (let row = 0; row < n; row++) {
      for (let col = 0; col < n; col++) {
        if (qr.isDark(row, col)) ctx.fillRect(col * cs, row * cs, cs, cs);
      }
    }
    return canvas;
  }

  function closeQrModal() {
    const el = document.getElementById('vck-rejoin-qr-overlay');
    if (el) el.remove();
    document.removeEventListener('keydown', _qrKeydown);
  }

  function _qrKeydown(e) {
    if (e.key === 'Escape') closeQrModal();
  }

  function openQrModal(url, opts) {
    opts = opts || {};
    closeQrModal();
    const overlay = document.createElement('div');
    overlay.id = 'vck-rejoin-qr-overlay';
    overlay.className = 'vck-rejoin-qr-overlay';
    overlay.addEventListener('click', e => { if (e.target === overlay) closeQrModal(); });

    const panel = document.createElement('div');
    panel.className = 'vck-rejoin-qr-panel';

    const title = document.createElement('div');
    title.className = 'vck-rejoin-qr-title';
    title.textContent = opts.title || 'Scan to rejoin';
    panel.appendChild(title);

    if (opts.subtitle) {
      const sub = document.createElement('div');
      sub.className = 'vck-rejoin-qr-subtitle';
      sub.textContent = opts.subtitle;
      panel.appendChild(sub);
    }

    const canvas = qrCanvas(url, opts.cellSize || 5);
    if (canvas) {
      canvas.className = 'vck-rejoin-qr-canvas';
      panel.appendChild(canvas);
    } else {
      const err = document.createElement('p');
      err.textContent = 'QR code unavailable.';
      panel.appendChild(err);
    }

    const hint = document.createElement('div');
    hint.className = 'vck-rejoin-qr-hint';
    hint.textContent = 'Open your phone camera and scan, or copy the link below.';
    panel.appendChild(hint);

    const linkRow = document.createElement('div');
    linkRow.className = 'vck-rejoin-qr-actions';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'vck-rejoin-qr-copy';
    copyBtn.textContent = 'Copy link';
    copyBtn.addEventListener('click', async () => {
      const ok = await copyText(url);
      const prev = copyBtn.textContent;
      copyBtn.textContent = ok ? 'Copied!' : 'Copy failed';
      setTimeout(() => { copyBtn.textContent = prev; }, 1500);
    });
    linkRow.appendChild(copyBtn);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'vck-rejoin-qr-close';
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', closeQrModal);
    linkRow.appendChild(closeBtn);
    panel.appendChild(linkRow);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', _qrKeydown);
  }

  function closeRejoinPrompt() {
    const el = document.getElementById('vck-rejoin-prompt-overlay');
    if (el) el.remove();
    document.removeEventListener('keydown', _rejoinPromptKeydown);
  }

  function _rejoinPromptKeydown(e) {
    if (e.key === 'Escape') closeRejoinPrompt();
  }

  async function submitRejoinCode(gameId, code) {
    const r = await fetch(`/api/game/${encodeURIComponent(gameId)}/rejoin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rejoin_code: code }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = data.detail || data.error || `Rejoin failed (${r.status})`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  }

  function openRejoinPrompt(gameId, opts) {
    opts = opts || {};
    closeRejoinPrompt();
    const overlay = document.createElement('div');
    overlay.id = 'vck-rejoin-prompt-overlay';
    overlay.className = 'vck-rejoin-prompt-overlay';
    overlay.addEventListener('click', e => { if (e.target === overlay) closeRejoinPrompt(); });

    const panel = document.createElement('div');
    panel.className = 'vck-rejoin-prompt-panel';

    const title = document.createElement('h2');
    title.className = 'vck-rejoin-prompt-title';
    title.textContent = opts.title || 'Rejoin your seat';
    panel.appendChild(title);

    const hint = document.createElement('p');
    hint.className = 'vck-rejoin-prompt-hint';
    hint.textContent = opts.hint || 'Enter the rejoin code shown in the game menu (tap the dice).';
    panel.appendChild(hint);

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'vck-rejoin-prompt-input';
    input.placeholder = 'e.g. BLUE-FOX-42';
    input.autocomplete = 'off';
    input.spellcheck = false;
    panel.appendChild(input);

    const err = document.createElement('div');
    err.className = 'vck-rejoin-prompt-error';
    err.setAttribute('aria-live', 'polite');
    panel.appendChild(err);

    const actions = document.createElement('div');
    actions.className = 'vck-rejoin-prompt-actions';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'vck-rejoin-prompt-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', closeRejoinPrompt);
    actions.appendChild(cancelBtn);

    const goBtn = document.createElement('button');
    goBtn.type = 'button';
    goBtn.className = 'vck-rejoin-prompt-go';
    goBtn.textContent = 'Rejoin';
    actions.appendChild(goBtn);
    panel.appendChild(actions);

    async function tryRejoin() {
      const code = (input.value || '').trim();
      if (!code) {
        err.textContent = 'Enter your rejoin code.';
        return;
      }
      err.textContent = '';
      goBtn.disabled = true;
      try {
        const data = await submitRejoinCode(gameId, code);
        if (typeof VCK_CLIENT_META !== 'undefined' && VCK_CLIENT_META.patch) {
          VCK_CLIENT_META.patch({ game_id: data.game_id, player_id: data.player_id });
        }
        const q = new URLSearchParams({ game_id: data.game_id, player_id: data.player_id });
        window.location.href = `/?${q}`;
      } catch (e) {
        err.textContent = e.message || 'Rejoin failed';
        goBtn.disabled = false;
      }
    }

    goBtn.addEventListener('click', tryRejoin);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') tryRejoin(); });

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    document.addEventListener('keydown', _rejoinPromptKeydown);
    input.focus();
  }

  global.VCK_REJOIN = {
    rejoinUrl: rejoinUrl,
    copyText: copyText,
    qrCanvas: qrCanvas,
    openQrModal: openQrModal,
    closeQrModal: closeQrModal,
    openRejoinPrompt: openRejoinPrompt,
    closeRejoinPrompt: closeRejoinPrompt,
    submitRejoinCode: submitRejoinCode,
  };
})(typeof window !== 'undefined' ? window : this);
