async function scRefresh(btn) {
  btn.disabled = true; btn.textContent = 'Refreshing...';
  try {
    const data = await csrfJsonFetch(btn.dataset.refreshUrl || '/admin/symcat/refresh', {});
    if (data.ok) {
      document.getElementById('sc-count').textContent = data.count + ' labels cached';
      btn.textContent = 'Refreshed!';
      setTimeout(() => location.reload(), 600);
    } else {
      btn.textContent = 'Error: ' + (data.error || 'unknown');
    }
  } catch(e) {
    if (e.message !== 'AUTH_REQUIRED') btn.textContent = 'Fetch failed';
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = 'Refresh labels'; }, 3000);
}

function scFilter(q) {
  q = q.toLowerCase();
  document.querySelectorAll('#sc-tbody tr').forEach(tr => {
    tr.style.display = tr.dataset.phrase.includes(q) || tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}

let _activeTab = 'all';
function scShowTab(tab, btn) {
  _activeTab = tab;
  document.querySelectorAll('.sc-tabs button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#sc-tbody tr').forEach(tr => {
    tr.style.display = (tab === 'all' || tr.dataset.tab === tab) ? '' : 'none';
  });
}

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
  const refreshBtn = event.target.closest('[data-sc-refresh]');
  if (refreshBtn) {
    scRefresh(refreshBtn);
    return;
  }

  const tabBtn = event.target.closest('[data-sc-tab]');
  if (tabBtn) {
    scShowTab(tabBtn.dataset.scTab, tabBtn);
    return;
  }

  const applyBtn = event.target.closest('[data-sc-apply]');
  if (applyBtn) {
    scApply(Number(applyBtn.dataset.kid), applyBtn.dataset.anchor, applyBtn);
  }
});

document.querySelector('[data-sc-filter]')?.addEventListener('input', event => {
  scFilter(event.target.value);
});
