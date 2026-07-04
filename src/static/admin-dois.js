const doiTabs = document.getElementById('doi-tabs');
let currentTab = doiTabs?.dataset.currentTab || 'pending';
let currentPage = parseInt(doiTabs?.dataset.currentPage || '1', 10);
const conflictToggleKey = 'admin-dois-show-conflicts';

/* ── Helpers ── */
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div'); d.textContent = s; return d.innerHTML;
}

function truncateText(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? text.slice(0, maxLen) + '\u2026' : text;
}

function renderConflictWarning(c) {
  if (!c.doi_conflicts || !c.doi_conflicts.length) return '';
  const conflicts = c.doi_conflicts.map(conflict => {
    const status = conflict.doi_status ? ' (' + esc(conflict.doi_status) + ')' : '';
    const title = truncateText(conflict.title_display || conflict.title || '', 90);
    const titleHtml = title ? '<span class="doi-warning-title">' + esc(title) + '</span>' : '';
    return '<a class="doi-warning-link" href="/paper/' + encodeURIComponent(conflict.arxiv_id) +
      '" target="_blank">arXiv: ' + esc(conflict.arxiv_id) + '</a>' + status + titleHtml;
  }).join('</div><div class="doi-warning-conflict">');
  const tooltip = c.doi_conflict_tooltip ? ' title="' + esc(c.doi_conflict_tooltip) + '"' : '';
  return '<div class="doi-warning"' + tooltip + '><strong>Already assigned</strong>' +
    '<div class="doi-warning-conflicts"><div class="doi-warning-conflict">' + conflicts +
    '</div></div></div>';
}

function shouldShowConflicts() {
  const toggle = document.getElementById('doi-show-conflicts');
  return !toggle || toggle.checked;
}

function applyConflictVisibility() {
  const showConflicts = shouldShowConflicts();
  document.querySelectorAll('#doi-tbody tr.doi-row--conflict').forEach(row => {
    row.hidden = !showConflicts;
  });
}

function setupConflictToggle() {
  const toggle = document.getElementById('doi-show-conflicts');
  if (!toggle) return;
  const saved = localStorage.getItem(conflictToggleKey);
  if (saved !== null) toggle.checked = saved === '1';
  toggle.addEventListener('change', () => {
    localStorage.setItem(conflictToggleKey, toggle.checked ? '1' : '0');
    applyConflictVisibility();
  });
  applyConflictVisibility();
}

/* ── Advanced toggle ── */
function toggleAdvanced(btn) {
  const div = document.getElementById('advanced-options');
  if (getComputedStyle(div).display === 'none') {
    div.style.display = 'flex';
    btn.innerHTML = '&#x25be; Date range';
  } else {
    div.style.display = 'none';
    btn.innerHTML = '&#x25b8; Date range';
  }
}

/* ── Tab counts ── */
function updateCounts(counts) {
  document.getElementById('tab-pending').textContent  = 'Pending (' + (counts.pending || 0) + ')';
  document.getElementById('tab-approved').textContent = 'Approved (' + (counts.approved || 0) + ')';
  document.getElementById('tab-rejected').textContent = 'Rejected (' + (counts.rejected || 0) + ')';
  const total = (counts.pending || 0) + (counts.approved || 0) + (counts.rejected || 0);
  document.getElementById('tab-all').textContent = 'All (' + total + ')';
}

/* ── Render table rows from JSON ── */
function renderRows(candidates) {
  const tbody = document.getElementById('doi-tbody');
  if (!candidates.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="doi-empty">No candidates in this view.</td></tr>';
    return;
  }
  tbody.innerHTML = candidates.map(c => {
    const confClass = c.confidence >= 0.90 ? 'doi-conf-high' : c.confidence >= 0.75 ? 'doi-conf-med' : 'doi-conf-low';
    const confPct = Math.round(c.confidence * 100);
    const pTitle = truncateText(c.paper_title_display || '', 80);
    const crTitle = truncateText(c.crossref_title_display || '', 80);
    const paperYear = c.paper_year ? ' (' + c.paper_year + ')' : '';
    const yrSuffix = c.crossref_year ? ' (' + c.crossref_year + ')' : '';

    let actionHtml = '<div class="doi-actions-inner"><span class="doi-conf ' + confClass + '">' + confPct + '%</span>';
    if (c.status === 'pending') {
      actionHtml += '<div class="doi-action-buttons">' +
        '<button class="approve-btn" data-doi-action="approve" data-candidate-id="' + c.id + '" title="Approve — assign this DOI to the paper"' +
          (c.doi_conflict_summary ? ' data-conflict-summary="' + esc(c.doi_conflict_summary) + '"' : '') +
          '>&#x2713;</button>' +
        (c.doi_conflicts && c.doi_conflicts.length
          ? '<button class="reassign-btn" data-doi-action="reassign" data-candidate-id="' + c.id + '" title="Reassign — clear this DOI from the already assigned paper(s), then assign it here"' +
            (c.doi_conflict_summary ? ' data-conflict-summary="' + esc(c.doi_conflict_summary) + '"' : '') +
            '>move</button>'
          : '') +
        '<button class="reject-btn" data-doi-action="reject" data-candidate-id="' + c.id + '" title="Reject — wrong match, discard">&#x1f5d1;&#xfe0e;</button>' +
        '</div>';
    } else if (c.status === 'approved') {
      actionHtml += '<span class="doi-done doi-done-ok">&#x2713; approved</span>';
    } else {
      actionHtml += '<span class="doi-done doi-done-no">&#x2717; rejected</span>';
    }
    actionHtml += '</div>';

    const conflictAttrs = c.doi_conflicts && c.doi_conflicts.length
      ? ' class="doi-row--conflict" data-has-conflict="1"'
      : '';
    return '<tr id="row-' + c.id + '"' + conflictAttrs + '>' +
      '<td><span class="doi-title" title="' + esc(c.paper_title) + '">' + esc(pTitle) + '</span><br>' +
        '<a class="doi-meta-link" href="/paper/' + esc(c.arxiv_id) + '" target="_blank">arXiv: ' + esc(c.arxiv_id) + '</a><br>' +
        '<span class="doi-authors"' + (c.paper_authors_full ? ' title="' + esc(c.paper_authors_full) + '"' : '') + '>' +
          esc(c.paper_authors_display || '') + paperYear +
        '</span></td>' +
      '<td><span class="doi-title" title="' + esc(c.crossref_title || '') + '">' + esc(crTitle) + '</span><br>' +
        '<a class="doi-link" href="https://doi.org/' + encodeURI(c.doi) + '" target="_blank" rel="noopener">' + esc(c.doi) + '</a>' +
        renderConflictWarning(c) +
        '<span class="doi-authors"' + (c.crossref_authors_full ? ' title="' + esc(c.crossref_authors_full) + '"' : '') + '>' +
          esc(c.crossref_authors_display || '') + yrSuffix +
        '</span></td>' +
      '<td class="doi-actions" id="act-' + c.id + '">' + actionHtml + '</td>' +
      '</tr>';
  }).join('');
  applyConflictVisibility();
}

/* ── Render pagination ── */
function renderPagination(page, totalPages, tab) {
  const div = document.getElementById('doi-pagination');
  if (totalPages <= 1) { div.innerHTML = ''; return; }
  let html = '<div class="pagination">';
  if (page > 1) html += '<a href="#" data-doi-tab="' + tab + '" data-doi-page="' + (page - 1) + '">&larr; Prev</a>';
  const lo = Math.max(1, page - 2), hi = Math.min(totalPages, page + 2);
  for (let p = lo; p <= hi; p++) {
    if (p === page) html += '<span class="current">' + p + '</span>';
    else html += '<a href="#" data-doi-tab="' + tab + '" data-doi-page="' + p + '">' + p + '</a>';
  }
  if (page < totalPages) html += '<a href="#" data-doi-tab="' + tab + '" data-doi-page="' + (page + 1) + '">Next &rarr;</a>';
  html += '</div>';
  div.innerHTML = html;
}

/* ── Load tab via AJAX ── */
async function loadTab(tab, page) {
  page = page || 1;
  currentTab = tab;
  currentPage = page;
  // Update active tab styling
  document.querySelectorAll('#doi-tabs a').forEach(a => {
    a.classList.toggle('active', a.dataset.tab === tab);
  });
  try {
    const data = await fetchJson('/admin/dois/tab?show=' + tab + '&page=' + page, {
      headers: {'Accept': 'application/json'}
    });
    if (!data.ok) return;
    updateCounts(data.counts);
    renderRows(data.candidates);
    renderPagination(data.page, data.total_pages, tab);
    history.replaceState(null, '', '?show=' + tab + '&page=' + page);
  } catch (e) {
    console.error('loadTab failed', e);
  }
}

/* ── Delegated click handlers ── */
document.addEventListener('click', event => {
  const tab = event.target.closest('#doi-tabs a[data-tab]');
  if (tab) {
    event.preventDefault();
    loadTab(tab.dataset.tab, 1);
    return;
  }

  const pageLink = event.target.closest('[data-doi-page]');
  if (pageLink) {
    event.preventDefault();
    loadTab(pageLink.dataset.doiTab, Number(pageLink.dataset.doiPage) || 1);
    return;
  }

  const actionBtn = event.target.closest('[data-doi-action]');
  if (actionBtn) {
    doiAction(Number(actionBtn.dataset.candidateId), actionBtn.dataset.doiAction, actionBtn);
    return;
  }

  const runBtn = event.target.closest('[data-doi-run]');
  if (runBtn) {
    runLookup(runBtn, runBtn.dataset.withDates === '1');
    return;
  }

  const advancedBtn = event.target.closest('[data-doi-toggle-advanced]');
  if (advancedBtn) toggleAdvanced(advancedBtn);
});

/* ── Approve / reject (AJAX) ── */
async function doiAction(cid, action, btn) {
  const container = document.getElementById('act-' + cid);
  const conflictSummary = btn && btn.dataset ? btn.dataset.conflictSummary : '';
  if (action === 'approve' && conflictSummary) {
    const ok = window.confirm(
      'This DOI is already assigned to ' + conflictSummary + '. Approve anyway?'
    );
    if (!ok) return;
  }
  if (action === 'reassign') {
    const ok = window.confirm(
      'Move this DOI from ' + (conflictSummary || 'the already assigned paper(s)') +
      ' to this paper? The old paper(s) will have this DOI cleared.'
    );
    if (!ok) return;
  }
  try {
    const data = await csrfJsonFetch('/admin/dois/' + cid + '/' + action, {});
    if (data.ok) {
      if (data.counts) updateCounts(data.counts);
      await loadTab(currentTab, currentPage);
      return;
    } else {
      btn.textContent = 'Error';
    }
  } catch(e) {
    if (e.message !== 'AUTH_REQUIRED') btn.textContent = 'Failed';
  }
}

/* ── Run DOI lookup ── */
async function runLookup(btn, withDates) {
  btn.disabled = true;
  btn.textContent = 'Running\u2026';
  const logDiv = document.getElementById('run-log');
  logDiv.style.display = 'block';
  logDiv.innerHTML = '<div class="doi-log">Looking up DOIs via Crossref\u2026</div>';
  try {
    const fd = new FormData();
    if (withDates) {
      const fromDate = document.getElementById('doi-from').value;
      const toDate = document.getElementById('doi-to').value;
      if (fromDate) fd.append('from_date', fromDate);
      if (toDate) fd.append('to_date', toDate);
    }
    const data = await csrfJsonFetch('/admin/dois/run', fd);
    logDiv.innerHTML = '<div class="doi-log">' +
      (data.log || data.error || 'Done').replace(/</g, '&lt;') + '</div>';
    if (data.ok) {
      btn.textContent = 'Done!';
      loadTab('pending', 1);
    } else {
      btn.textContent = 'Error — see log';
    }
  } catch(e) {
    if (e.message !== 'AUTH_REQUIRED') {
      logDiv.innerHTML = '<div class="doi-log">Request failed: ' + e.message + '</div>';
      btn.textContent = 'Failed';
    }
  }
  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = withDates ? 'Run with date range' : 'Fetch next 20';
  }, 3000);
}

setupConflictToggle();
