(() => {
  const TOTAL = 5;
  const $ = id => document.getElementById(id);
  const hintsEl = $('hints'), progressEl = $('progress'), wrongEl = $('wrong');
  const form = $('form'), input = $('guess'), catEl = $('category');
  const endbox = $('endbox'), endmsg = $('endmsg'), answerEl = $('answer'), toastEl = $('toast');

  let shown = 0, busy = false, status = 'playing';

  let toastTimer;
  function toast(msg, ms = 1800) {
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('show'), ms);
  }
  function shake() {
    form.classList.add('shake');
    setTimeout(() => form.classList.remove('shake'), 400);
  }

  function render(data, animate) {
    const prev = shown;
    shown = data.hints.length;
    status = data.status;
    catEl.textContent = data.category || '';

    progressEl.innerHTML = '';
    for (let i = 0; i < TOTAL; i++) {
      const d = document.createElement('i');
      if (i < shown) d.className = 'on';
      progressEl.appendChild(d);
    }

    hintsEl.innerHTML = '';
    for (let i = 0; i < TOTAL; i++) {
      const li = document.createElement('li');
      const n = document.createElement('span'); n.className = 'n'; n.textContent = i + 1;
      const t = document.createElement('span'); t.className = 't';
      if (i < shown) {
        t.textContent = data.hints[i];
        if (animate && i >= prev && i === shown - 1 && shown > 1) li.classList.add('new');
      } else {
        li.classList.add('locked');
        t.textContent = 'Dica bloqueada';
      }
      li.append(n, t);
      hintsEl.appendChild(li);
    }

    wrongEl.innerHTML = '';
    data.wrong.forEach(w => {
      const s = document.createElement('span'); s.textContent = w; wrongEl.appendChild(s);
    });

    const over = data.status !== 'playing';
    form.classList.toggle('off', over);
    input.disabled = over;
    endbox.hidden = !over;
    if (over) {
      answerEl.textContent = data.answer;
      const pts = ' (+' + (data.score || 0) + ' pontos)';
      endmsg.textContent = data.status === 'won'
        ? (shown === 1 ? 'Incrível! Você acertou na primeira dica! 🎉' : 'Você acertou na dica ' + shown + '! 🎉') + pts
        : 'Fim de jogo. Era:' + pts;
    } else {
      input.focus();
    }
  }

  async function load(url = '/api/quem/state', opts) {
    const data = await (await fetch(url, opts)).json();
    shown = 0;
    render(data, false);
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (busy || status !== 'playing') return;
    const guess = input.value.trim();
    if (!guess) { shake(); return toast('Digite um nome'); }
    busy = true;
    try {
      const res = await fetch('/api/quem/guess', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guess }),
      });
      const data = await res.json();
      if (!res.ok) { shake(); toast(data.error || 'Erro ao enviar'); return; }
      input.value = '';
      if (!data.correct && data.status === 'playing') { shake(); toast('Não é essa pessoa. Nova dica!'); }
      render(data, true);
      window.TQ.showBadges(data.new_badges);
    } catch (err) {
      toast('Sem conexão com o servidor');
    } finally {
      busy = false;
    }
  });

  $('again').addEventListener('click', () => load('/api/quem/new', { method: 'POST' }));
  load();
})();
