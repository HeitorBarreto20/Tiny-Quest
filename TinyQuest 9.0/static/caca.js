(() => {
  const N = 8;
  const $ = id => document.getElementById(id);
  const gridEl = $('grid'), wordsEl = $('words'), countEl = $('count'), toastEl = $('toast');
  const timeEl = $('time'), tbarEl = $('tbar'), timerEl = $('timer');
  const endbox = $('endbox'), endmsg = $('endmsg');
  const checkBtn = $('check'), clearBtn = $('clear');

  let state = null, sel = new Set(), cells = [];
  let deadline = 0, limit = 120, timerId = null, finalizing = false;

  // ---- tabuleiro ----
  for (let i = 0; i < N * N; i++) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'cell'; b.dataset.i = i;
    b.addEventListener('keydown', e => {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(i); }
    });
    gridEl.appendChild(b);
    cells.push(b);
  }

  let toastTimer;
  function toast(msg, ms = 1800) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }
  function shake() {
    gridEl.classList.add('shake');
    setTimeout(() => gridEl.classList.remove('shake'), 400);
  }

  function foundCells() {
    const s = new Set();
    state.found.forEach(f => f.cells.forEach(c => s.add(c)));
    return s;
  }

  function paint() {
    const fc = state ? foundCells() : new Set();
    cells.forEach((c, i) => {
      c.classList.toggle('found', fc.has(i));
      c.classList.toggle('sel', sel.has(i));
    });
  }

  function renderWords() {
    const done = new Set(state.found.map(f => f.word));
    wordsEl.innerHTML = '';
    state.words.forEach(w => {
      const li = document.createElement('li');
      li.textContent = w;
      if (done.has(w)) li.className = 'done';
      wordsEl.appendChild(li);
    });
    countEl.textContent = state.found.length + '/' + state.words.length;
  }

  // ---- seleção (clique ou arrastar) ----
  function toggle(i) {
    if (!state || state.status !== 'playing') return;
    sel.has(i) ? sel.delete(i) : sel.add(i);
    paint();
  }

  function lineBetween(a, b) {
    const r1 = Math.floor(a / N), c1 = a % N, r2 = Math.floor(b / N), c2 = b % N;
    const dr = r2 - r1, dc = c2 - c1;
    if (!(dr === 0 || dc === 0 || Math.abs(dr) === Math.abs(dc))) return null;
    const len = Math.max(Math.abs(dr), Math.abs(dc));
    const sr = Math.sign(dr), sc = Math.sign(dc);
    const out = [];
    for (let k = 0; k <= len; k++) out.push((r1 + sr * k) * N + (c1 + sc * k));
    return out;
  }

  let dragStart = null, dragging = false, moved = false;
  gridEl.addEventListener('pointerdown', e => {
    const c = e.target.closest('.cell');
    if (!c || !state || state.status !== 'playing') return;
    dragStart = +c.dataset.i; dragging = true; moved = false;
    gridEl.setPointerCapture(e.pointerId);
    e.preventDefault();
  });
  gridEl.addEventListener('pointermove', e => {
    if (!dragging) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const c = el && el.closest && el.closest('.cell');
    if (!c) return;
    const j = +c.dataset.i;
    if (j === dragStart && !moved) return;
    const line = lineBetween(dragStart, j);
    if (line) { moved = true; sel = new Set(line); paint(); }
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    if (!moved) toggle(dragStart);
  };
  gridEl.addEventListener('pointerup', endDrag);
  gridEl.addEventListener('pointercancel', () => { dragging = false; });

  clearBtn.addEventListener('click', () => { sel.clear(); paint(); });

  // ---- tempo ----
  const fmt = s => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');

  function tick() {
    if (!state || state.status !== 'playing') return;
    const rem = Math.max(0, (deadline - performance.now()) / 1000);
    timeEl.textContent = fmt(Math.ceil(rem));
    tbarEl.style.width = (100 * rem / limit) + '%';
    timerEl.classList.toggle('low', rem <= 15);
    if (rem <= 0 && !finalizing) {
      finalizing = true;
      load('/api/caca/state');
    }
  }

  // ---- fim de jogo ----
  function showEnd() {
    clearInterval(timerId);
    endbox.hidden = false;
    const pts = ' (+' + (state.score || 0) + ' pontos)';
    if (state.status === 'won') {
      endmsg.textContent = 'Você achou todas as palavras em ' + state.elapsed.toFixed(1).replace('.', ',') + 's! 🎉' + pts;
    } else {
      endmsg.textContent = 'Tempo esgotado! Faltaram: ' + state.missing.join(', ') + '.' + pts;
    }
    timeEl.textContent = state.status === 'won' ? fmt(Math.round(state.elapsed)) : '0:00';
    timerEl.classList.toggle('low', state.status !== 'won');
    checkBtn.disabled = clearBtn.disabled = true;
    gridEl.classList.add('off');
  }

  function apply(data) {
    state = data;
    limit = data.limit;
    sel.clear();
    finalizing = false;
    for (let i = 0; i < cells.length; i++) cells[i].textContent = data.grid[i];
    renderWords();
    paint();
    endbox.hidden = true;
    clearInterval(timerId);
    if (data.status === 'playing') {
      deadline = performance.now() + data.remaining * 1000;
      checkBtn.disabled = clearBtn.disabled = false;
      gridEl.classList.remove('off');
      tick();
      timerId = setInterval(tick, 200);
    } else {
      showEnd();
    }
  }

  async function load(url = '/api/caca/state', opts) {
    apply(await (await fetch(url, opts)).json());
  }

  checkBtn.addEventListener('click', async () => {
    if (!state || state.status !== 'playing') return;
    if (sel.size < 2) { shake(); return toast('Selecione as letras da palavra'); }
    checkBtn.disabled = true;
    try {
      const res = await fetch('/api/caca/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cells: [...sel] }),
      });
      const data = await res.json();
      if (!res.ok) { shake(); toast(data.error || 'Erro ao enviar'); return; }
      if (data.ok) {
        const wasPlaying = true;
        apply(data);
        toast('Achou: ' + data.word + '!');
        window.TQ.showBadges(data.new_badges);
      } else if (data.status !== 'playing') {
        apply(data);
      } else {
        sel.clear(); paint(); shake();
        toast(data.reason === 'repetida' ? 'Você já achou essa palavra' : 'Essa não é uma das palavras');
        state.found = data.found;
      }
    } catch (err) {
      toast('Sem conexão com o servidor');
    } finally {
      if (state && state.status === 'playing') checkBtn.disabled = false;
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.activeElement.tagName !== 'BUTTON') checkBtn.click();
  });

  $('again').addEventListener('click', () => load('/api/caca/new', { method: 'POST' }));
  load();
})();
