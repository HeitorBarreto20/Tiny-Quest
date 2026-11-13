(() => {
  const N = 8;
  const $ = id => document.getElementById(id);
  const boardEl = $('board'), trayEl = $('tray'), toastEl = $('toast');
  const pointsEl = $('points'), linesEl = $('lines'), tierEl = $('tier');
  const timeEl = $('time'), tbarEl = $('tbar'), timerEl = $('timer');
  const endbox = $('endbox'), endmsg = $('endmsg');
  const TIERS = [[10000, 10], [20000, 25], [30000, 50], [40000, 75], [50000, 100]];

  let state = null, busy = false, drag = null;
  let cells = [], slots = [];
  let deadline = 0, limit = 300, timerId = null, finalizing = false, shownPoints = 0;

  const fmtN = v => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const fmt = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  let toastTimer;
  function toast(msg, ms = 1600) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }

  // ---- montagem ----
  for (let i = 0; i < N * N; i++) {
    const d = document.createElement('div');
    d.className = 'tcell';
    boardEl.appendChild(d);
    cells.push(d);
  }
  for (let i = 0; i < 3; i++) {
    const s = document.createElement('div');
    s.className = 'slot empty';
    s.addEventListener('pointerdown', e => startDrag(i, s, e));
    trayEl.appendChild(s);
    slots.push(s);
  }

  // ---- renderização ----
  function renderBoard(board) {
    for (let i = 0; i < N * N; i++) {
      const ch = board[i];
      cells[i].className = 'tcell' + (ch !== '.' ? ' f c' + ch : '');
    }
  }

  function pieceEl(p, cls, cellCls) {
    const el = document.createElement('div');
    el.className = cls;
    el.style.gridTemplateColumns = 'repeat(' + p.w + ', auto)';
    const on = new Set(p.cells.map(c => c[0] * p.w + c[1]));
    for (let k = 0; k < p.w * p.h; k++) {
      const c = document.createElement('div');
      c.className = cellCls + (on.has(k) ? ' c' + p.color : ' e');
      el.appendChild(c);
    }
    return el;
  }

  function renderTray() {
    state.tray.forEach((p, i) => {
      const s = slots[i];
      s.innerHTML = '';
      s.classList.toggle('empty', !p);
      s.classList.remove('dragging');
      if (p) s.appendChild(pieceEl(p, 'tpiece', 'pcell'));
    });
  }

  function tierText(points) {
    let cur = 0, next = null;
    for (const [need, pts] of TIERS) { if (points >= need) cur = pts; else if (next === null) next = [need, pts]; }
    const a = cur ? 'Vale ' + cur + ' pts no ranking' : 'Ainda 0 pts no ranking';
    return next ? a + ' · próxima meta ' + fmtN(next[0]) : a + ' · meta máxima!';
  }

  function setPoints(v, animate) {
    const from = shownPoints;
    shownPoints = v;
    tierEl.textContent = tierText(v);
    if (!animate || v === from) { pointsEl.textContent = fmtN(v); return; }
    const t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / 450);
      pointsEl.textContent = fmtN(Math.round(from + (v - from) * k));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ---- regras (só para pré-visualização; o servidor valida tudo) ----
  function fits(board, p, r, c) {
    return p.cells.every(([dr, dc]) => {
      const rr = r + dr, cc = c + dc;
      return rr >= 0 && rr < N && cc >= 0 && cc < N && board[rr * N + cc] === '.';
    });
  }
  function completed(board, p, r, c) {
    const b = board.split('');
    p.cells.forEach(([dr, dc]) => { b[(r + dr) * N + c + dc] = 'x'; });
    const out = new Set();
    for (let i = 0; i < N; i++) {
      if (b.slice(i * N, i * N + N).every(ch => ch !== '.')) for (let j = 0; j < N; j++) out.add(i * N + j);
      if (Array.from({ length: N }, (_, k) => b[k * N + i]).every(ch => ch !== '.')) for (let k = 0; k < N; k++) out.add(k * N + i);
    }
    return out;
  }

  // ---- arrastar e soltar ----
  function clearPreview() { cells.forEach(c => c.classList.remove('hint', 'pre')); }

  function anchorFor(e) {
    const rect = boardEl.getBoundingClientRect();
    const cs = rect.width / N;
    const p = drag.piece;
    const left = e.clientX - (p.w * cs) / 2;
    const top = e.clientY - (p.h * cs) / 2 - drag.lift;
    drag.ghost.style.left = left + 'px';
    drag.ghost.style.top = top + 'px';
    return { r: Math.round((top - rect.top) / cs), c: Math.round((left - rect.left) / cs) };
  }

  function onMove(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const a = anchorFor(e);
    clearPreview();
    drag.anchor = null;
    if (fits(state.board, drag.piece, a.r, a.c)) {
      drag.anchor = a;
      drag.piece.cells.forEach(([dr, dc]) => cells[(a.r + dr) * N + a.c + dc].classList.add('hint'));
      completed(state.board, drag.piece, a.r, a.c).forEach(i => cells[i].classList.add('pre'));
    }
  }

  function startDrag(idx, slotEl, e) {
    const p = state && state.tray[idx];
    if (!p || busy || state.status !== 'playing' || drag) return;
    e.preventDefault();
    const rect = boardEl.getBoundingClientRect();
    const cs = rect.width / N;
    const ghost = pieceEl(p, 'ghost', 'gcell');
    ghost.style.setProperty('--gs', cs + 'px');
    ghost.querySelectorAll('.gcell').forEach(c => { c.style.width = (cs - 3) + 'px'; c.style.height = (cs - 3) + 'px'; });
    document.body.appendChild(ghost);
    drag = { idx, piece: p, ghost, id: e.pointerId, slot: slotEl, anchor: null, lift: e.pointerType === 'touch' ? cs * 1.7 : 0 };
    slotEl.classList.add('dragging');
    try { slotEl.setPointerCapture(e.pointerId); } catch (_) { /* ignora */ }
    anchorFor(e);
    onMove(e);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }

  function endDrag() {
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    clearPreview();
    if (drag) { drag.ghost.remove(); drag.slot.classList.remove('dragging'); }
  }

  function onUp(e) {
    if (!drag || e.pointerId !== drag.id) return;
    const d = drag;
    endDrag();
    drag = null;
    if (e.type === 'pointerup' && d.anchor) submit(d.idx, d.anchor);
  }

  // ---- jogada ----
  async function submit(idx, a) {
    busy = true;
    const piece = state.tray[idx];
    slots[idx].classList.add('empty');
    slots[idx].innerHTML = '';
    let data;
    try {
      const res = await fetch('/api/tetris/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ piece: idx, r: a.r, c: a.c }),
      });
      data = await res.json();
      if (!res.ok) { toast(data.error || 'Jogada inválida'); renderTray(); busy = false; if (res.status === 409) load(); return; }
    } catch (err) {
      toast('Sem conexão com o servidor');
      renderTray(); busy = false; return;
    }

    if (data.ok) {
      // 1) mostra a peça encaixando
      data.placed.forEach(([r, c]) => { cells[r * N + c].className = 'tcell f c' + piece.color + ' pop'; });
      // 2) linhas completas estouram
      const burst = new Set();
      data.cleared.rows.forEach(r => { for (let j = 0; j < N; j++) burst.add(r * N + j); });
      data.cleared.cols.forEach(c => { for (let i = 0; i < N; i++) burst.add(i * N + c); });
      if (burst.size) {
        await sleep(160);
        burst.forEach(i => { cells[i].classList.add('burst'); });
        floatText('+' + fmtN(data.gained));
        await sleep(430);
      }
      state = data;
      renderBoard(data.board);
      renderTray();
      linesEl.textContent = data.lines;
      setPoints(data.points, true);
    } else {
      state = data;
    }

    if (data.status !== 'playing') { await sleep(250); showEnd(); window.TQ.showBadges(data.new_badges); }
    busy = false;
  }

  function floatText(t) {
    const f = document.createElement('div');
    f.className = 'tfloat';
    f.textContent = t;
    boardEl.parentElement.appendChild(f);
    setTimeout(() => f.remove(), 1100);
  }

  // ---- tempo ----
  function tick() {
    if (!state || state.status !== 'playing') return;
    const rem = Math.max(0, (deadline - performance.now()) / 1000);
    timeEl.textContent = fmt(Math.ceil(rem));
    tbarEl.style.width = (100 * rem / limit) + '%';
    timerEl.classList.toggle('low', rem <= 30);
    if (rem <= 0 && !finalizing && !busy) { finalizing = true; load('/api/tetris/state'); }
  }

  // ---- fim ----
  function showEnd() {
    clearInterval(timerId);
    boardEl.classList.add('off');
    slots.forEach(s => s.classList.add('empty'));
    endbox.hidden = false;
    const why = state.reason === 'sem_jogadas' ? 'Sem jogadas possíveis!' : 'Tempo esgotado!';
    const pts = state.score
      ? ' Você ganhou +' + state.score + ' pontos no ranking.'
      : ' Menos de 10.000 pontos: 0 pontos no ranking.';
    endmsg.textContent = why + ' Você fez ' + fmtN(state.points) + ' pontos.' + pts;
    timeEl.textContent = state.reason === 'sem_jogadas' ? timeEl.textContent : '0:00';
  }

  function apply(data) {
    state = data;
    limit = data.limit;
    finalizing = false;
    endbox.hidden = true;
    boardEl.classList.remove('off');
    renderBoard(data.board);
    renderTray();
    linesEl.textContent = data.lines;
    shownPoints = data.points;
    setPoints(data.points, false);
    clearInterval(timerId);
    if (data.status === 'playing') {
      deadline = performance.now() + data.remaining * 1000;
      tick();
      timerId = setInterval(tick, 250);
    } else {
      showEnd();
    }
  }

  async function load(url = '/api/tetris/state', opts) {
    apply(await (await fetch(url, opts)).json());
  }
  $('again').addEventListener('click', () => load('/api/tetris/new', { method: 'POST' }));
  load();
})();
