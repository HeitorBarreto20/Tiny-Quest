// Utilidades compartilhadas: tutoriais (modais) e aviso de emblemas conquistados.
(() => {
  const STAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l2.9 6.3 6.9.8-5.1 4.7 1.4 6.8L12 17.3 5.9 20.6l1.4-6.8L2.2 9.1l6.9-.8z"/></svg>';

  // Botões [data-open="id"] abrem o <dialog> correspondente
  document.querySelectorAll('[data-open]').forEach(btn => {
    btn.addEventListener('click', () => {
      const d = document.getElementById(btn.dataset.open);
      if (d && d.showModal) d.showModal();
    });
  });
  document.querySelectorAll('dialog.modal').forEach(d => {
    d.addEventListener('click', e => { if (e.target === d) d.close(); });
  });

  let box;
  function showBadges(list) {
    if (!list || !list.length) return;
    if (!box) {
      box = document.createElement('div');
      box.className = 'badge-pops';
      document.body.appendChild(box);
    }
    list.forEach((b, i) => {
      setTimeout(() => {
        const el = document.createElement('div');
        el.className = 'badge-pop';
        el.innerHTML = '<div class="medal t' + b.tier + '"><span class="mi">' + (b.icon || STAR) + '</span><span class="pips">' +
          '<i></i>'.repeat(b.tier) + '</span></div>' +
          '<div><small>Emblema conquistado!</small><b></b><span></span></div>';
        el.querySelector('b').textContent = b.name;
        el.querySelector('span').textContent = b.desc;
        box.appendChild(el);
        setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 400); }, 6500);
      }, i * 700);
    });
  }

  window.TQ = { showBadges };
})();
