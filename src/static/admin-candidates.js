const candidatesTable = document.querySelector('table.candidates');
const markCandidateUrl = candidatesTable?.dataset.markCandidateUrl || '/admin/candidates/mark';
const adminKeywordsUrl = candidatesTable?.dataset.keywordsUrl || '/admin/keywords';

function htmlEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

function hiddenInput(name, value) {
  return `<input type="hidden" name="${htmlEscape(name)}" value="${htmlEscape(value)}">`;
}

function statusBadgeHtml(status, aliasOf) {
  if (status === 'useful') return '<span class="badge badge-useful">useful</span>';
  if (status === 'math') return '<span class="badge badge-math">math</span>';
  if (status === 'ignore') return '<span class="badge badge-ignore">ignore</span>';
  if (status === 'alias') {
    const alias = htmlEscape(aliasOf || '');
    return `<span class="badge badge-alias" title="alias of: ${alias}">alias → ${alias}</span>`;
  }
  return '';
}

function markFormHtml(fields, buttonHtml, extraClass = '') {
  const inputs = Object.entries(fields).map(([name, value]) => hiddenInput(name, value)).join('');
  const className = ['candidate-action-form', extraClass].filter(Boolean).join(' ');
  return `<form method="post" action="${markCandidateUrl}" class="${className}">
    ${inputs}${buttonHtml}
  </form>`;
}

function unreviewedActionsHtml(row) {
  const phrase = row.dataset.orig || '';
  const edited = row.querySelector('.phrase-edit')?.value.trim() || phrase;
  return `
    ${markFormHtml(
      {phrase, keyword_phrase: edited, status: 'useful'},
      '<button type="submit" class="btn-useful">Useful</button>',
      'useful-form'
    )}
    <button type="button" class="btn-alias btn-edit" data-candidate-show-alias>Alias →</button>
    ${markFormHtml(
      {phrase, status: 'alias', keyword_phrase: edited},
      `<input type="text" name="alias_of" placeholder="canonical keyword…" list="kw-list" class="alias-input">
       <button type="submit" class="btn-useful btn-nowrap">Add ✓</button>
       <button type="button" class="btn-undo" data-candidate-hide-alias>✕</button>`,
      'alias-form'
    )}
    ${markFormHtml(
      {phrase, status: 'math'},
      '<button type="submit" class="btn-math">Math</button>'
    )}
    ${markFormHtml(
      {phrase, status: 'ignore'},
      '<button type="submit" class="btn-ignore">Ignore</button>'
    )}
  `;
}

function processedActionsHtml(status, phrase) {
  let html = '';
  if (status === 'useful') {
    html += `<a href="${adminKeywordsUrl}" class="btn-edit candidate-edit-link">Edit ↗</a>`;
  }
  html += markFormHtml(
    {phrase, status: 'unreviewed'},
    '<button type="submit" class="btn-undo">✕ unmark</button>'
  );
  return html;
}

function updateCandidateCounts(data) {
  const useful = document.getElementById('useful-count');
  const math = document.getElementById('math-count');
  const ignored = document.getElementById('ignored-count');
  if (useful && data.useful_count !== undefined) useful.textContent = data.useful_count;
  if (math && data.math_count !== undefined) math.textContent = data.math_count;
  if (ignored && data.ignored_count !== undefined) ignored.textContent = data.ignored_count;
}

function updateCandidateRow(row, data) {
  const status = data.status || 'unreviewed';
  const effectivePhrase = data.keyword_phrase || data.phrase || row.dataset.orig || '';
  const unmarkPhrase = (status === 'useful' || status === 'alias')
    ? effectivePhrase
    : (data.phrase || row.dataset.orig || effectivePhrase);

  row.dataset.status = status;
  row.dataset.currentPhrase = effectivePhrase;
  row.classList.remove(
    'candidate-row--processed',
    'candidate-row--useful',
    'candidate-row--math',
    'candidate-row--ignore',
    'candidate-row--alias',
    'candidate-row--error'
  );
  if (status !== 'unreviewed') {
    row.classList.add('candidate-row--processed', `candidate-row--${status}`);
  }

  const phraseInput = row.querySelector('.phrase-edit');
  if (phraseInput && (status === 'useful' || status === 'alias')) {
    phraseInput.value = effectivePhrase;
  }

  const statusCell = row.querySelector('.status-cell');
  if (statusCell) statusCell.innerHTML = statusBadgeHtml(status, data.alias_of);

  const actions = row.querySelector('.actions-cell .action-btns');
  if (actions) {
    actions.innerHTML = status === 'unreviewed'
      ? unreviewedActionsHtml(row)
      : processedActionsHtml(status, unmarkPhrase);
  }
}

// Keep keyword_phrase in sync with the editable phrase cell
document.querySelectorAll('tr[data-orig]').forEach(row => {
  const phraseInput = row.querySelector('.phrase-edit');
  if (!phraseInput) return;
  const syncPhrase = () => {
    const val = phraseInput.value.trim();
    row.querySelectorAll('input[name=keyword_phrase]').forEach(h => h.value = val);
  };
  phraseInput.addEventListener('input', syncPhrase);
  phraseInput.addEventListener('change', syncPhrase);
});

function showAliasEdit(btn) {
  const cell = btn.closest('td');
  const form = cell.querySelector('.alias-form');
  const row  = btn.closest('tr');
  // Sync current phrase into keyword_phrase before showing
  const phrase = row.querySelector('.phrase-edit').value.trim();
  form.querySelector('input[name=keyword_phrase]').value = phrase;
  btn.style.display = 'none';
  form.style.display = 'flex';
  form.querySelector('input[name=alias_of]').focus();
}

function hideAliasEdit(btn) {
  const cell = btn.closest('td');
  cell.querySelector('.alias-form').style.display = 'none';
  cell.querySelector('.btn-alias').style.display = '';
}

document.querySelector('table.candidates')?.addEventListener('click', event => {
  const showBtn = event.target.closest('[data-candidate-show-alias]');
  if (showBtn) {
    showAliasEdit(showBtn);
    return;
  }
  const hideBtn = event.target.closest('[data-candidate-hide-alias]');
  if (hideBtn) hideAliasEdit(hideBtn);
});

document.querySelector('table.candidates')?.addEventListener('submit', async event => {
  const form = event.target;
  if (!form.action.endsWith(markCandidateUrl)) return;

  event.preventDefault();
  const row = form.closest('tr[data-orig]');
  if (!row) return;

  const fd = new FormData(form);
  const phraseInput = row.querySelector('.phrase-edit');
  if (phraseInput && (form.classList.contains('useful-form') || form.classList.contains('alias-form'))) {
    fd.set('keyword_phrase', phraseInput.value.trim());
  }
  if (form.classList.contains('alias-form') && !(fd.get('alias_of') || '').trim()) {
    form.querySelector('input[name=alias_of]')?.focus();
    return;
  }

  row.classList.add('candidate-row--saving');
  row.querySelectorAll('button').forEach(btn => { btn.disabled = true; });

  try {
    const data = await csrfJsonFetch(form.action, fd);
    if (!data.ok) throw new Error(data.error || 'Request failed');
    updateCandidateCounts(data);
    updateCandidateRow(row, data);
  } catch (err) {
    if (err.message !== 'AUTH_REQUIRED') {
      row.classList.add('candidate-row--error');
      alert(err.message || 'Could not update candidate.');
    }
  } finally {
    row.classList.remove('candidate-row--saving');
    row.querySelectorAll('button').forEach(btn => { btn.disabled = false; });
  }
});
