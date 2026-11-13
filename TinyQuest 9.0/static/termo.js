(() => {
  const ROWS = 6, COLS = 5;
  const boardEl = document.getElementById('board');
  const kbEl = document.getElementById('keyboard');
  const toastEl = document.getElementById('toast');
  const endbox = document.getElementById('endbox');
  const endmsg = document.getElementById('endmsg');
  const againBtn = document.getElementById('again');

  let rows = [], row = 0, current = '', status = 'playing', busy = false;
  const keyState = {};
  const rank = { a: 1, p: 2, c: 3 };

  // ---- Monta tabuleiro e teclado ----
  for (let r = 0; r < ROWS; r++) {
    const rowEl = document.createElement('div');
    rowEl.className = 'row-t';
    const tiles = [];
    for (let c = 0; c < COLS; c++) {
      const t = document.createElement('div');
      t.className = 'tile';
      rowEl.appendChild(t);
      tiles.push(t);
    }
    boardEl.appendChild(rowEl);
    rows.push({ el: rowEl, tiles });
  }

  const layout = ['qwertyuiop', 'asdfghjkl', '+zxcvbnm-'];
  const keyEls = {};
  layout.forEach(line => {
    const l = document.createElement('div');
    l.className = 'krow';
    [...line].forEach(ch => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'key';
      if (ch === '+') { b.textContent = 'Enter'; b.classList.add('wide'); b.dataset.k = 'enter'; }
      else if (ch === '-') { b.textContent = '⌫'; b.classList.add('wide'); b.dataset.k = 'back'; }
      else { b.textContent = ch; b.dataset.k = ch; keyEls[ch] = b; }
      b.addEventListener('click', () => press(b.dataset.k));
      l.appendChild(b);
    });
    kbEl.appendChild(l);
  });

  // ---- Utilidades ----
  let toastTimer;
  function toast(msg, ms = 1800) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  function paintKey(letter, res) {
    const k = letter.toLowerCase();
    if ((rank[res] || 0) > (rank[keyState[k]] || 0)) {
      keyState[k] = res;
      keyEls[k].classList.remove('a', 'p', 'c');
      keyEls[k].classList.add(res);
    }
  }

  function renderCurrent() {
    const t = rows[row].tiles;
    for (let i = 0; i < COLS; i++) {
      t[i].textContent = current[i] || '';
      t[i].classList.toggle('filled', !!current[i]);
    }
  }

  function setRowResult(r, word, result, animate) {
    const tiles = rows[r].tiles;
    return (async () => {
      for (let i = 0; i < COLS; i++) {
        tiles[i].textContent = word[i];
        tiles[i].classList.add('filled');
        if (animate) {
          tiles[i].classList.add('flip');
          await sleep(250);
        }
        tiles[i].classList.add(result[i]);
        paintKey(word[i], result[i]);
        if (animate) await sleep(250);
      }
    })();
  }

  function showEnd(st, answer, score) {
    status = st;
    endbox.hidden = false;
    const pts = ' (+' + (score || 0) + ' pontos)';
    endmsg.textContent = st === 'won'
      ? 'Você acertou! 🎉 A palavra era ' + answer.toUpperCase() + '.' + pts
      : 'Fim de jogo. A palavra era ' + answer.toUpperCase() + '.' + pts;
  }

  // ---- Entrada ----
  function press(k) {
    if (status !== 'playing' || busy) return;
    if (k === 'enter') return submit();
    if (k === 'back') { current = current.slice(0, -1); return renderCurrent(); }
    if (current.length < COLS) { current += k; renderCurrent(); }
  }

  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Enter') { if (document.activeElement.tagName === 'BUTTON') return; e.preventDefault(); return press('enter'); }
    if (e.key === 'Backspace') return press('back');
    const base = e.key.normalize('NFD').replace(/[̀-ͯ]/g, '');
    if (/^[a-zA-Z]$/.test(base)) press(base.toLowerCase());
  });

  async function submit() {
    if (current.length < COLS) {
      rows[row].el.classList.add('shake');
      setTimeout(() => rows[row].el.classList.remove('shake'), 400);
      return toast('Faltam letras');
    }
    busy = true;
    try {
      const res = await fetch('/api/termo/guess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word: current }),
      });
      const data = await res.json();
      if (!res.ok) {
        rows[row].el.classList.add('shake');
        setTimeout(() => rows[row].el.classList.remove('shake'), 400);
        toast(data.error || 'Erro ao enviar');
        if (res.status === 409) setTimeout(() => load(), 800);
        return;
      }
      await setRowResult(row, current, data.result, true);
      row++; current = '';
      if (data.status !== 'playing') {
        showEnd(data.status, data.answer, data.score);
        window.TQ.showBadges(data.new_badges);
      }
    } catch (err) {
      toast('Sem conexão com o servidor');
    } finally {
      busy = false;
    }
  }

  // ---- Estado inicial / nova partida ----
  function reset() {
    rows.forEach(r => r.tiles.forEach(t => { t.className = 'tile'; t.textContent = ''; }));
    Object.keys(keyState).forEach(k => { delete keyState[k]; keyEls[k].classList.remove('a', 'p', 'c'); });
    row = 0; current = ''; status = 'playing'; endbox.hidden = true;
  }

  async function load(url = '/api/termo/state', opts) {
    const data = await (await fetch(url, opts)).json();
    reset();
    for (let i = 0; i < data.guesses.length; i++) {
      await setRowResult(i, data.guesses[i].word, data.guesses[i].result, false);
    }
    row = data.guesses.length;
    if (data.status !== 'playing') { row = Math.min(row, ROWS - 1); showEnd(data.status, data.answer, data.score); }
  }

  againBtn.addEventListener('click', () => load('/api/termo/new', { method: 'POST' }));
  load();
})();
