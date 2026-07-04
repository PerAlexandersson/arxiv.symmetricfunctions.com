async function scApply(kid, anchor, btn) {
  const fd = new FormData();
  fd.append('field', 'url');
  fd.append('value', anchor);
  try {
    const data = await csrfJsonFetch(`/admin/keywords/${kid}/inline`, fd);
    if (data.ok) {
      const container = document.getElementById('sug-' + kid);
      container.textContent = '';
      const applied = document.createElement('span');
      applied.className = 'sc-sug-applied';
      applied.textContent = '\u2713 ' + anchor;
      container.appendChild(applied);
    } else {
      btn.textContent = 'Error';
    }
  } catch(e) {
    if (e.message !== 'AUTH_REQUIRED') btn.textContent = 'Failed';
  }
}

document.addEventListener('click', event => {
  const btn = event.target.closest('[data-sc-apply]');
  if (!btn) return;
  scApply(Number(btn.dataset.kid), btn.dataset.anchor, btn);
});
