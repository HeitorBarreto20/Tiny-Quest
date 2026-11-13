(() => {
  const $ = id => document.getElementById(id);
  const boardEl = $('rboard'), programEl = $('program'), toastEl = $('toast');
  const phaseEl = $('phase'), hitsEl = $('hits'), facingEl = $('facing');
  const ftext = $('ftext'), farrow = $('farrow');
  const runBtn = $('run'), eraseBtn = $('erase');
  const endbox = $('endbox'), endmsg = $('endmsg');
  const cmdBtns = document.querySelectorAll('.cmd');

  const MAX_CMDS = 60;
  const DIR_TEXT = ['para cima', 'para a direita', 'para baixo', 'para a esquerda'];
  const DIR_VEC = [[-1, 0], [0, 1], [1, 0], [0, -1]];
  const CMD_ICON = { E: '#i-left', D: '#i-right', A: '#i-go' };
  const CMD_NAME = { E: 'Esquerda', D: 'Direita', A: 'Andar' };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const svgUse = (id, cls) =>
    '<svg viewBox="' + (id.startsWith('#i-') ? '0 0 24 24' : '0 0 100 100') + '"' + (cls ? ' class="' + cls + '"' : '') +
    ' aria-hidden="true"><use href="' + id + '"/></svg>';

  let state = null, program = [], busy = false;
  let robotEl = null, bodyEl = null, angle = 0, n = 4;

  let toastTimer;
  function toast(msg, ms = 1800) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }

  // Bandeira quadriculada ondulada, com mastro, bola dourada e base
  function flagSvg() {
    const cloth = 'M38.5 17 C48 11 58 24 69 18 C78 13 87 15 93 19 L93 53 C87 49 78 47 69 52 C58 58 48 45 38.5 51 Z';
    let checks = '';
    for (let r = 0; r < 5; r++) {
      for (let c = 0; c < 6; c++) {
        if ((r + c) % 2 === 0) checks += '<rect x="' + (38.5 + c * 9.4) + '" y="' + (8 + r * 11) + '" width="9.6" height="11.1" fill="#14090d"/>';
      }
    }
    return '<svg viewBox="0 0 100 100" aria-hidden="true">' +
      '<defs>' +
      '<linearGradient id="fpole" x1="0" x2="1"><stop offset="0" stop-color="#f4ece4"/><stop offset=".55" stop-color="#b9aea3"/><stop offset="1" stop-color="#7d726a"/></linearGradient>' +
      '<radialGradient id="fball" cx=".35" cy=".3"><stop offset="0" stop-color="#fff4b8"/><stop offset="1" stop-color="#d49a12"/></radialGradient>' +
      '<linearGradient id="fbase" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6b5a60"/><stop offset="1" stop-color="#2b2024"/></linearGradient>' +
      '<linearGradient id="ffold" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity=".3"/><stop offset=".18" stop-color="#000" stop-opacity=".22"/>' +
      '<stop offset=".36" stop-color="#fff" stop-opacity=".24"/><stop offset=".56" stop-color="#000" stop-opacity=".22"/>' +
      '<stop offset=".78" stop-color="#fff" stop-opacity=".2"/><stop offset="1" stop-color="#000" stop-opacity=".28"/></linearGradient>' +
      '<clipPath id="fcloth"><path d="' + cloth + '"/></clipPath>' +
      '</defs>' +
      '<ellipse cx="50" cy="90" rx="30" ry="6" fill="#000" opacity=".4"/>' +
      '<rect x="27" y="83" width="44" height="8" rx="3.5" fill="url(#fbase)" stroke="#8a747c" stroke-width="1"/>' +
      '<rect x="33.5" y="14" width="5" height="71" rx="2.5" fill="url(#fpole)"/>' +
      '<circle cx="36" cy="12.5" r="5.2" fill="url(#fball)" stroke="#a87408" stroke-width=".8"/>' +
      '<g class="fwave"><g clip-path="url(#fcloth)"><rect x="38" y="6" width="60" height="60" fill="#fff"/>' + checks +
      '<rect x="38" y="6" width="60" height="60" fill="url(#ffold)"/></g>' +
      '<path d="' + cloth + '" fill="none" stroke="#14090d" stroke-width="1.6" stroke-linejoin="round"/></g></svg>';
  }

  // ---- tabuleiro ----
  function buildBoard(data) {
    n = data.size;
    boardEl.innerHTML = '';
    boardEl.style.setProperty('--n', n);
    data.grid.forEach((row, r) => {
      [...row].forEach((ch, c) => {
        const cell = document.createElement('div');
        cell.className = 'rcell';
        const inner = document.createElement('div');
        inner.className = 'tile' + (ch === 'W' ? ' wall' : '');
        if (ch === 'W') inner.innerHTML = svgUse('#brick');
        if (r === data.flag.r && c === data.flag.c) { inner.classList.add('goal'); inner.innerHTML = flagSvg(); }
        if (r === data.start.r && c === data.start.c) inner.classList.add('start');
        cell.appendChild(inner);
        boardEl.appendChild(cell);
      });
    });
    robotEl = document.createElement('div');
    robotEl.className = 'robot';
    robotEl.style.width = robotEl.style.height = (100 / n) + '%';
    bodyEl = document.createElement('div');
    bodyEl.className = 'rbody';
    bodyEl.innerHTML = svgUse('#robot');
    robotEl.appendChild(bodyEl);
    boardEl.appendChild(robotEl);
  }

  function place(r, c, dx = 0, dy = 0) {
    robotEl.style.left = ((c + dx) * 100 / n) + '%';
    robotEl.style.top = ((r + dy) * 100 / n) + '%';
  }
  function setDir(d, instant) {
    const target = d * 90;
    const delta = ((target - angle + 540) % 360) - 180;
    angle += delta;
    if (instant) bodyEl.style.transition = 'none';
    bodyEl.style.transform = 'rotate(' + angle + 'deg)';
    if (instant) { void bodyEl.offsetWidth; bodyEl.style.transition = ''; }
  }
  function resetRobot() {
    robotEl.classList.add('snap');
    place(state.start.r, state.start.c);
    setDir(state.dir, true);
    void robotEl.offsetWidth;
    robotEl.classList.remove('snap');
  }

  // ---- interface ----
  function renderHits() {
    hitsEl.innerHTML = '<span>Batidas</span>';
    for (let i = 0; i < state.max_crashes; i++) {
      const d = document.createElement('i');
      if (i < state.crashes) d.className = 'on';
      hitsEl.appendChild(d);
    }
  }

  function renderProgram(activeIdx = -1) {
    programEl.innerHTML = '';
    if (!program.length) {
      const hint = document.createElement('span');
      hint.className = 'phint';
      hint.textContent = 'Seus comandos aparecem aqui';
      programEl.appendChild(hint);
    }
    program.forEach((c, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'chip' + (c === 'A' ? ' go' : '') + (i === activeIdx ? ' run' : '');
      b.title = CMD_NAME[c] + ' (clique para remover)';
      b.innerHTML = '<small>' + (i + 1) + '</small>' + svgUse(CMD_ICON[c]);
      b.addEventListener('click', () => { if (!busy) { program.splice(i, 1); renderProgram(); } });
      programEl.appendChild(b);
    });
  }

  function showFacing() {
    ftext.innerHTML = 'O robô está virado <b>' + DIR_TEXT[state.dir] + '</b>';
    farrow.style.transform = 'rotate(' + (state.dir * 90) + 'deg)';
    facingEl.classList.remove('flash');
    void facingEl.offsetWidth;
    facingEl.classList.add('flash');
  }

  function setBusy(b) {
    busy = b;
    runBtn.disabled = eraseBtn.disabled = b;
    cmdBtns.forEach(x => x.disabled = b);
  }

  function applyState(data, keepProgram = false) {
    state = data;
    endbox.hidden = true;
    if (data.status !== 'playing') return showEnd();
    if (!keepProgram) program = [];
    buildBoard(data);
    place(data.start.r, data.start.c);
    setDir(data.dir, true);
    phaseEl.innerHTML = 'Fase <b>' + (data.phase + 1) + '</b> de ' + data.phases + ' &middot; ' + data.level;
    renderHits();
    renderProgram();
    showFacing();
    setBusy(false);
  }

  function showEnd() {
    setBusy(true);
    endbox.hidden = false;
    const pts = ' (+' + (state.score || 0) + ' pontos)';
    endmsg.textContent = state.status === 'won'
      ? 'Você completou as ' + state.phases + ' fases! 🎉 Batidas: ' + state.crashes + pts
      : 'O robô bateu ' + state.crashes + ' vezes. Fim de jogo.' + pts;
    renderHits();
  }

  // ---- comandos ----
  function add(c) {
    if (busy || !state || state.status !== 'playing') return;
    if (program.length >= MAX_CMDS) return toast('Limite de ' + MAX_CMDS + ' comandos');
    program.push(c);
    renderProgram();
    programEl.scrollTop = programEl.scrollHeight;
  }
  cmdBtns.forEach(b => b.addEventListener('click', () => add(b.dataset.c)));
  eraseBtn.addEventListener('click', () => { if (!busy) { program = []; renderProgram(); } });

  document.addEventListener('keydown', e => {
    if (e.ctrlKey || e.metaKey || e.altKey || busy) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); add('E'); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); add('D'); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); add('A'); }
    else if (e.key === 'Backspace') { program.pop(); renderProgram(); }
    else if (e.key === 'Enter' && document.activeElement.tagName !== 'BUTTON') { run(); }
  });

  // ---- execução (o servidor valida e conta as batidas) ----
  async function run() {
    if (busy || !state || state.status !== 'playing') return;
    if (!program.length) return toast('Adicione comandos primeiro');
    setBusy(true);
    let data;
    try {
      const res = await fetch('/api/robo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ program: program.join('') }),
      });
      data = await res.json();
      if (!res.ok) { toast(data.error || 'Erro ao enviar'); setBusy(false); if (res.status === 409) load(); return; }
    } catch (err) {
      toast('Sem conexão com o servidor');
      return setBusy(false);
    }

    resetRobot();
    await sleep(200);
    for (let i = 0; i < data.steps.length; i++) {
      const s = data.steps[i];
      renderProgram(i);
      setDir(s.d);
      place(s.r, s.c);
      await sleep(s.cmd === 'A' ? 420 : 320);
    }

    if (data.outcome === 'crash') {
      const idx = data.steps.length;
      renderProgram(idx);
      const last = data.steps.length ? data.steps[data.steps.length - 1] : { r: state.start.r, c: state.start.c };
      const v = DIR_VEC[data.crash_dir];
      place(last.r, last.c, v[1] * 0.35, v[0] * 0.35);
      boardEl.classList.add('crash');
      await sleep(220);
      place(last.r, last.c);
      await sleep(260);
      boardEl.classList.remove('crash');
      state.crashes = data.crashes;
      renderHits();
      toast('Bateu! ' + data.crashes + ' de ' + data.max_crashes + ' batidas', 2200);
      await sleep(800);
      renderProgram();
      if (data.status === 'lost') { state = data; showEnd(); window.TQ.showBadges(data.new_badges); return; }
      resetRobot();
      setBusy(false);
    } else if (data.outcome === 'goal') {
      renderProgram();
      boardEl.classList.add('win');
      toast(data.status === 'playing' ? 'Fase concluída! 🏁' : 'Chegou! 🏁', 2000);
      await sleep(1300);
      boardEl.classList.remove('win');
      if (data.status === 'playing') {
        applyState(data);
      } else {
        state = data; showEnd(); window.TQ.showBadges(data.new_badges);
      }
    } else {
      renderProgram();
      toast('O robô parou antes da bandeira. Ajuste os comandos.', 2400);
      await sleep(900);
      resetRobot();
      setBusy(false);
    }
  }
  runBtn.addEventListener('click', run);

  async function load(url = '/api/robo/state', opts) {
    applyState(await (await fetch(url, opts)).json());
  }
  $('again').addEventListener('click', () => load('/api/robo/new', { method: 'POST' }));
  load();
})();
