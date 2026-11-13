(() => {
  const $ = id => document.getElementById(id);
  const boardEl = $('mboard'), trayEl = $('mtray'), toastEl = $('toast');
  const phaseEl = $('phase'), hitsEl = $('hits'), statText = $('stattext'), fill = $('lookfill'), lookbar = $('lookbar');
  const checkBtn = $('check'), clearBtn = $('clear'), endbox = $('endbox'), endmsg = $('endmsg');

  let state = null, placed = {}, selected = null, busy = false, timer = null, cells = [];
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  let toastTimer;
  function toast(msg, ms = 1800) {
    toastEl.textContent = msg; toastEl.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }

  function renderHits() {
    hitsEl.innerHTML = '<span>Erros</span>';
    for (let i = 0; i < state.max_errors; i++) {
      const d = document.createElement('i');
      d.className = i < state.errors ? 'on' : '';
      hitsEl.appendChild(d);
    }
  }

  function buildBoard(size) {
    boardEl.innerHTML = '';
    boardEl.style.setProperty('--n', size);
    boardEl.dataset.n = size;
    cells = [];
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++) {
      const d = document.createElement('button');
      d.type = 'button'; d.className = 'mcell';
      d.addEventListener('click', () => clickCell(r, c));
      d.addEventListener('pointerdown', ev => { const e = placed[r + ',' + c]; if (e && !selected) startDrag(e, r + ',' + c, d, ev); });
      boardEl.appendChild(d); cells.push(d);
    }
  }
  const idx = (r, c) => r * state.size + c;

  function renderCells() {
    cells.forEach(el => { el.textContent = ''; el.classList.remove('has', 'wrong'); });
    if (state.mode === 'look') {
      state.items.forEach(([e, r, c]) => { const el = cells[idx(r, c)]; el.textContent = e; el.classList.add('has', 'show'); });
      return;
    }
    cells.forEach(el => el.classList.remove('show'));
    Object.entries(placed).forEach(([k, e]) => {
      const [r, c] = k.split(',').map(Number);
      const el = cells[idx(r, c)]; el.textContent = e; el.classList.add('has');
    });
  }

  function renderTray() {
    trayEl.innerHTML = '';
    if (state.mode !== 'place') return;
    const used = new Set(Object.values(placed));
    state.tray.forEach(e => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'mitem' + (used.has(e) ? ' used' : '') + (selected === e ? ' sel' : '');
      b.textContent = e;
      b.addEventListener('pointerdown', ev => startDrag(e, null, b, ev));
      trayEl.appendChild(b);
    });
    checkBtn.disabled = Object.keys(placed).length !== state.tray.length;
  }

  function place(e, r, c, from) {
    const k = r + ',' + c;
    if (from === k) return;
    Object.keys(placed).forEach(x => { if (placed[x] === e) delete placed[x]; });
    placed[k] = e;                              // se a casa estava ocupada, o emoji antigo volta para a lista
    selected = null;
    renderCells(); renderTray();
  }

  // ---- arrastar e soltar (toque simples também funciona: escolhe o emoji e toca na casa) ----
  let drag = null;
  function cellAt(x, y) {
    const el = document.elementFromPoint(x, y);
    const i = el ? cells.indexOf(el.closest('.mcell')) : -1;
    return i < 0 ? null : [Math.floor(i / state.size), i % state.size];
  }
  function startDrag(e, fromKey, srcEl, ev) {
    if (busy || !state || state.mode !== 'place' || state.status !== 'playing' || drag) return;
    ev.preventDefault();
    drag = { e, fromKey, srcEl, x: ev.clientX, y: ev.clientY, moved: false, id: ev.pointerId, ghost: null };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  }
  function onMove(ev) {
    if (!drag || ev.pointerId !== drag.id) return;
    if (!drag.moved && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 6) return;
    if (!drag.moved) {
      drag.moved = true;
      const g = document.createElement('div');
      g.className = 'mghost'; g.textContent = drag.e;
      document.body.appendChild(g); drag.ghost = g;
      drag.srcEl.classList.add('dragging');
    }
    drag.ghost.style.left = ev.clientX + 'px';
    drag.ghost.style.top = ev.clientY + 'px';
    cells.forEach(c => c.classList.remove('over'));
    const t = cellAt(ev.clientX, ev.clientY);
    if (t) cells[idx(t[0], t[1])].classList.add('over');
  }
  function onUp(ev) {
    if (!drag || ev.pointerId !== drag.id) return;
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', onUp);
    const d = drag; drag = null;
    cells.forEach(c => c.classList.remove('over'));
    if (d.ghost) d.ghost.remove();
    d.srcEl.classList.remove('dragging');
    if (!d.moved) {                                   // toque simples
      if (d.fromKey) { delete placed[d.fromKey]; selected = null; renderCells(); renderTray(); }
      else { selected = selected === d.e ? null : d.e; renderTray(); }
      return;
    }
    if (ev.type !== 'pointerup') return;
    const t = cellAt(ev.clientX, ev.clientY);
    if (t) place(d.e, t[0], t[1], d.fromKey);
    else if (d.fromKey) { delete placed[d.fromKey]; renderCells(); renderTray(); }   // soltou fora: devolve à lista
  }

  function clickCell(r, c) {
    if (busy || !state || state.mode !== 'place' || state.status !== 'playing') return;
    if (selected) place(selected, r, c, null);
  }

  function setStat(text, look) {
    statText.textContent = text;
    lookbar.style.visibility = look ? 'visible' : 'hidden';
  }

  function runLook(remaining) {
    clearInterval(timer);
    const end = performance.now() + remaining * 1000, total = state.look_time;
    checkBtn.disabled = true; clearBtn.disabled = true;
    const tick = async () => {
      const left = Math.max(0, (end - performance.now()) / 1000);
      fill.style.width = (100 * left / total) + '%';
      setStat('Memorize! ' + Math.ceil(left) + 's', true);
      if (left <= 0) {
        clearInterval(timer);
        await sleep(350);                 // pequena folga para o relógio do servidor
        const res = await fetch('/api/memoria/hide', { method: 'POST' });
        apply(await res.json());
      }
    };
    tick(); timer = setInterval(tick, 100);
  }

  function apply(data) {
    state = data; placed = {}; selected = null; busy = false;
    clearInterval(timer);
    endbox.hidden = true;
    renderHits();
    if (data.status !== 'playing') { showEnd(); return; }
    phaseEl.innerHTML = 'Fase <b>' + (data.phase + 1) + '</b> de ' + data.phases + ' · ' + data.level;
    if (boardEl.dataset.n !== String(data.size)) buildBoard(data.size);
    clearBtn.disabled = false;
    renderCells(); renderTray();
    if (data.mode === 'look') runLook(data.remaining);
    else setStat('Coloque os ' + data.count + ' emojis onde estavam.', false);
  }

  function showEnd() {
    clearInterval(timer);
    phaseEl.textContent = state.phase >= state.phases ? 'Concluído' : 'Fase ' + (state.phase + 1) + ' de ' + state.phases;
    trayEl.innerHTML = ''; checkBtn.disabled = true; clearBtn.disabled = true;
    setStat('', false);
    endbox.hidden = false;
    endmsg.textContent = state.score
      ? 'Parabéns! Você terminou as 3 fases com ' + state.errors + (state.errors === 1 ? ' erro' : ' erros') + ' e ganhou +' + state.score + ' pontos.'
      : (state.errors >= state.max_errors ? 'Fim de jogo: ' + state.max_errors + ' erros. 0 pontos desta vez.' : 'Fim de jogo.');
  }

  checkBtn.addEventListener('click', async () => {
    if (busy || state.mode !== 'place') return;
    busy = true; checkBtn.disabled = true;
    const list = Object.entries(placed).map(([k, e]) => { const [r, c] = k.split(',').map(Number); return [e, r, c]; });
    const res = await fetch('/api/memoria/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ placed: list }) });
    const data = await res.json();
    if (!res.ok) { toast(data.error || 'Erro'); busy = false; renderTray(); return; }
    if (data.outcome === 'ok') {
      cells.forEach(el => el.classList.add('right'));
      toast(data.status === 'playing' ? 'Acertou! Próxima fase.' : 'Acertou tudo!');
    } else {
      data.wrong.forEach(([r, c]) => cells[idx(r, c)].classList.add('wrong'));
      toast(data.status === 'playing' ? 'Errou! Veja o tabuleiro de novo.' : 'Errou!');
    }
    await sleep(1300);
    apply(data);
    if (data.status !== 'playing') window.TQ.showBadges(data.new_badges);
  });
  clearBtn.addEventListener('click', () => { if (busy || state.mode !== 'place') return; placed = {}; selected = null; renderCells(); renderTray(); });
  $('again').addEventListener('click', async () => apply(await (await fetch('/api/memoria/new', { method: 'POST' })).json()));
  (async () => apply(await (await fetch('/api/memoria/state')).json()))();
})();
