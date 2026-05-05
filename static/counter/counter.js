(function () {
  const ICONS = {
    gold: '/images/gold_icon.jpg',
    magic: '/images/magic_icon.png',
    strength: '/images/strength_icon.png',
    victory: '/images/vp_icon.png',
  };

  const IS_COARSE_POINTER =
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(pointer: coarse)').matches;

  const INITIAL = {
    gold: 2,
    strength: 0,
    magic: 1,
    victory: 0,
  };

  /** @type {{ key: string, label: string, kind: string }[]} */
  const ROWS = [
    { key: 'gold', label: 'Gold', kind: 'resource' },
    { key: 'strength', label: 'Strength', kind: 'resource' },
    { key: 'magic', label: 'Magic', kind: 'resource' },
    { key: 'victory', label: 'Victory points', kind: 'vp' },
  ];

  /** Remove whitespace for parsing only */
  function stripSpaces(s) {
    return String(s).replace(/\s+/g, '');
  }

  /**
   * Parse simple integer expressions: unary +/- on each operand, chain with + or -.
   * Examples: "7", "-3", "7+14", "12 - 4 + 1", "5+-2"
   * @returns {number|null}
   */
  function parseCounterExpression(raw) {
    const s = stripSpaces(raw);
    if (!s) return null;

    let i = 0;

    function readSignedInt() {
      let sign = 1;
      if (i < s.length && s[i] === '+') i++;
      else if (i < s.length && s[i] === '-') {
        sign = -1;
        i++;
      }
      if (i >= s.length || s[i] < '0' || s[i] > '9') return null;
      let n = 0;
      while (i < s.length && s[i] >= '0' && s[i] <= '9') {
        n = n * 10 + (s[i].charCodeAt(0) - 48);
        i++;
      }
      return sign * n;
    }

    const first = readSignedInt();
    if (first === null) return null;
    let sum = first;
    while (i < s.length) {
      const op = s[i];
      if (op !== '+' && op !== '-') return null;
      i++;
      const next = readSignedInt();
      if (next === null) return null;
      sum += op === '+' ? next : -next;
    }
    if (!Number.isFinite(sum)) return null;
    return Math.trunc(sum);
  }

  /** Commit string: integer or expression; invalid → null */
  function commitEdit(str, fallback) {
    const trimmed = String(str).trim();
    if (trimmed === '') return fallback;
    const n = parseCounterExpression(trimmed);
    return n === null ? null : n;
  }

  function mk(tag, cls) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    return el;
  }

  function clamp(n, min, max) {
    return Math.max(min, Math.min(max, n));
  }

  function insertAtCursor(input, text) {
    const value = String(input.value);
    const start = input.selectionStart == null ? value.length : input.selectionStart;
    const end = input.selectionEnd == null ? value.length : input.selectionEnd;
    const next = value.slice(0, start) + text + value.slice(end);
    input.value = next;
    const caret = start + text.length;
    input.setSelectionRange(caret, caret);
  }

  function deleteBeforeCursor(input) {
    const value = String(input.value);
    const start = input.selectionStart == null ? value.length : input.selectionStart;
    const end = input.selectionEnd == null ? value.length : input.selectionEnd;
    if (start !== end) {
      input.value = value.slice(0, start) + value.slice(end);
      input.setSelectionRange(start, start);
      return;
    }
    if (start <= 0) return;
    input.value = value.slice(0, start - 1) + value.slice(end);
    input.setSelectionRange(start - 1, start - 1);
  }

  function createKeypad() {
    const pad = mk('div', 'counter-keypad is-hidden');
    pad.setAttribute('role', 'group');
    pad.setAttribute('aria-label', 'Counter keypad');

    const row1 = mk('div', 'counter-keypad-row');
    const row2 = mk('div', 'counter-keypad-row');
    const row3 = mk('div', 'counter-keypad-row');
    const row4 = mk('div', 'counter-keypad-row');

    function key(label, action) {
      const b = mk('button', 'counter-keypad-key');
      b.type = 'button';
      b.textContent = label;
      b.dataset.action = action;
      return b;
    }

    row1.appendChild(key('7', 'ins:7'));
    row1.appendChild(key('8', 'ins:8'));
    row1.appendChild(key('9', 'ins:9'));
    row1.appendChild(key('+', 'ins:+'));

    row2.appendChild(key('4', 'ins:4'));
    row2.appendChild(key('5', 'ins:5'));
    row2.appendChild(key('6', 'ins:6'));
    row2.appendChild(key('-', 'ins:-'));

    row3.appendChild(key('1', 'ins:1'));
    row3.appendChild(key('2', 'ins:2'));
    row3.appendChild(key('3', 'ins:3'));
    row3.appendChild(key('⌫', 'bksp'));

    row4.appendChild(key('0', 'ins:0'));
    row4.appendChild(key('Clear', 'clear'));
    row4.appendChild(key('Done', 'done'));

    pad.appendChild(row1);
    pad.appendChild(row2);
    pad.appendChild(row3);
    pad.appendChild(row4);

    return pad;
  }

  const keypad = createKeypad();
  document.body.appendChild(keypad);
  let activeInput = null;
  let activeCommit = null;
  let activeExit = null;

  function showKeypad(input, commitFn, exitFn) {
    activeInput = input;
    activeCommit = commitFn;
    activeExit = exitFn;
    keypad.classList.remove('is-hidden');
  }

  function hideKeypad() {
    activeInput = null;
    activeCommit = null;
    activeExit = null;
    keypad.classList.add('is-hidden');
  }

  keypad.addEventListener('pointerdown', (e) => {
    if (!activeInput) return;
    const btn = e.target && e.target.closest ? e.target.closest('button') : null;
    if (!btn) return;
    e.preventDefault();
    activeInput.focus();

    const action = btn.dataset.action || '';
    if (action.startsWith('ins:')) {
      const ch = action.slice(4);
      insertAtCursor(activeInput, ch);
      return;
    }
    if (action === 'bksp') {
      deleteBeforeCursor(activeInput);
      return;
    }
    if (action === 'clear') {
      activeInput.value = '';
      const at = clamp(activeInput.value.length, 0, activeInput.value.length);
      activeInput.setSelectionRange(at, at);
      return;
    }
    if (action === 'done') {
      if (typeof activeCommit === 'function') activeCommit();
      hideKeypad();
    }
  });

  function renderDisplay(rowEl, key, kind, value) {
    const cell = rowEl.querySelector('.counter-display');
    cell.innerHTML = '';
    cell.title = rowEl._fullLabel + ': ' + value;
    cell.setAttribute('aria-label', rowEl._fullLabel + ', ' + value);

    const num = mk('span', 'counter-value-num');
    num.textContent = String(value);
    cell.appendChild(num);
    cell.appendChild(document.createTextNode(' \u00D7 '));
    const img = document.createElement('img');
    img.className = 'score-pill-resource-icon';
    img.alt = '';
    img.src = ICONS[key];
    cell.appendChild(img);
  }

  function setupRow(container, spec, values, rowClass) {
    const row = mk('div', 'counter-row ' + rowClass);
    row._fullLabel = spec.label;

    const minus = mk('button', 'counter-step counter-step--minus');
    minus.type = 'button';
    minus.setAttribute('aria-label', 'Decrease ' + spec.label);
    minus.textContent = '-';

    const plus = mk('button', 'counter-step counter-step--plus');
    plus.type = 'button';
    plus.setAttribute('aria-label', 'Increase ' + spec.label);
    plus.textContent = '+';

    const mid = mk('div', 'counter-cell');
    const display = mk('div', 'counter-display');
    display.setAttribute('tabindex', '0');
    display.setAttribute('role', 'button');

    const input = mk('input', 'counter-input is-hidden');
    input.setAttribute('aria-label', spec.label + ' value');
    input.setAttribute('inputmode', 'numeric');
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('spellcheck', 'false');
    input.setAttribute('autocapitalize', 'off');

    mid.appendChild(display);
    mid.appendChild(input);

    row.appendChild(minus);
    row.appendChild(mid);
    row.appendChild(plus);

    let snapshot = values[spec.key];

    function refreshView() {
      renderDisplay(row, spec.key, spec.kind, values[spec.key]);
    }

    function exitEdit(revert) {
      input.classList.add('is-hidden');
      display.classList.remove('is-hidden');
      if (revert) {
        values[spec.key] = snapshot;
        refreshView();
      }
      snapshot = values[spec.key];
      if (activeInput === input) hideKeypad();
    }

    function commitFromInput() {
      const committed = commitEdit(input.value, snapshot);
      if (committed === null || committed < 0) {
        input.value = String(snapshot);
        exitEdit(true);
        return;
      }
      values[spec.key] = committed;
      refreshView();
      exitEdit(false);
    }

    minus.addEventListener('click', () => {
      values[spec.key] = Math.max(0, values[spec.key] - 1);
      snapshot = values[spec.key];
      refreshView();
    });
    plus.addEventListener('click', () => {
      values[spec.key] += 1;
      snapshot = values[spec.key];
      refreshView();
    });

    function enterEdit() {
      snapshot = values[spec.key];
      display.classList.add('is-hidden');
      input.classList.remove('is-hidden');
      input.value = String(snapshot);
      input.focus();
      input.select();
      if (IS_COARSE_POINTER) showKeypad(input, commitFromInput, exitEdit);
    }

    display.addEventListener('click', enterEdit);
    display.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        enterEdit();
      }
    });

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        commitFromInput();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        exitEdit(true);
      }
    });

    input.addEventListener('blur', () => {
      if (!input.classList.contains('is-hidden')) commitFromInput();
    });

    container.appendChild(row);
    refreshView();
  }

  const root = document.getElementById('counter-rows');
  const values = { ...INITIAL };

  ROWS.forEach((spec) => {
    const cls =
      spec.key === 'gold'
        ? 'counter-row--gold'
        : spec.key === 'strength'
          ? 'counter-row--strength'
          : spec.key === 'magic'
            ? 'counter-row--magic'
            : 'counter-row--victory';
    setupRow(root, spec, values, cls);
  });
})();
