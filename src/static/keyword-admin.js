(() => {
const keywordAdmin = document.querySelector('.admin-kw-strip[data-keyword-id]');
if (!keywordAdmin) return;
const _kid = Number(keywordAdmin.dataset.keywordId);
const keywordPhrase = keywordAdmin.dataset.keywordPhrase || '';
const keywordPaperCount = Number(keywordAdmin.dataset.paperCount || '0');

function keywordReferenceHref(value) {
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  return 'https://www.symmetricfunctions.com#' + encodeURIComponent(value);
}

function updateKeywordReferenceLink(value) {
  const link = document.getElementById('kw-reference-link');
  if (!link) return;
  if (value) {
    link.href = keywordReferenceHref(value);
    link.style.display = '';
  } else {
    link.removeAttribute('href');
    link.style.display = 'none';
  }
}

function makeAliasChip(aliasId, aliasText) {
  const chip = document.createElement('span');
  chip.className = 'alias-chip';
  chip.id = 'alias-chip-' + aliasId;
  const label = document.createElement('span');
  label.textContent = aliasText;
  const button = document.createElement('button');
  button.type = 'button';
  button.title = 'Remove';
  button.textContent = '×';
  button.dataset.akwDeleteAlias = '';
  button.dataset.aliasId = String(aliasId);
  chip.append(label, button);
  return chip;
}

async function akwSetScore(input) {
  const prev = input.defaultValue;
  const fd = new FormData(); fd.append('score', input.value);
  try {
    const res = await csrfFetch(`/admin/keywords/${_kid}/score`, fd);
    if (!res.ok) throw new Error();
    input.defaultValue = input.value;
    akwFlash(input, true);
  } catch { alert('Failed to save score'); input.value = prev; }
}

async function akwSaveUrl(inp) {
  const value = inp.value.trim();
  if (value === (inp.defaultValue || '')) return;
  const fd = new FormData(); fd.append('field', 'url'); fd.append('value', value);
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/inline`, fd);
    const data = await res.json();
    if (data.ok) {
      inp.value = data.value || '';
      inp.defaultValue = data.value || '';
      updateKeywordReferenceLink(data.value || '');
      akwFlash(inp, true);
    }
    else { akwFlash(inp, false); inp.value = inp.defaultValue; }
  } catch { akwFlash(inp, false); inp.value = inp.defaultValue; }
}

let _aliasHideTimer, _mergeHideTimer;

function akwShowAliasInput() {
  document.getElementById('akw-alias-btn').style.display = 'none';
  const inp = document.getElementById('akw-alias-input');
  inp.style.display = 'inline-block'; inp.focus();
}
function akwHideAliasInput() {
  document.getElementById('akw-alias-input').style.display = 'none';
  document.getElementById('akw-alias-input').value = '';
  document.getElementById('akw-alias-btn').style.display = '';
}
function akwScheduleHideAlias() { _aliasHideTimer = setTimeout(akwHideAliasInput, 150); }
function akwAliasKeydown(e) {
  clearTimeout(_aliasHideTimer);
  if (e.key === 'Enter')  { e.preventDefault(); akwAddAlias(); }
  if (e.key === 'Escape') { akwHideAliasInput(); }
}

async function akwAddAlias() {
  const inp   = document.getElementById('akw-alias-input');
  const alias = inp.value.trim().toLowerCase();
  if (!alias) { akwHideAliasInput(); return; }
  const fd = new FormData(); fd.append('alias', alias);
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/aliases/add`, fd);
    const data = await res.json();
    if (!data.ok) {
      alert({ duplicate: `«${alias}» is already an alias of another keyword.`,
              self: 'An alias cannot be the same as the keyword itself.' }[data.error]
            || 'Error adding alias.');
      inp.select(); return;
    }
    const list = document.getElementById('akw-alias-list');
    const btn  = document.getElementById('akw-alias-btn');
    const chip = makeAliasChip(data.id, data.alias);
    list.insertBefore(chip, btn);
    akwHideAliasInput();
  } catch { alert('Error adding alias.'); }
}

async function akwDelAlias(aid) {
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/aliases/${aid}/delete`, new FormData());
    const data = await res.json();
    if (data.ok) document.getElementById('alias-chip-' + aid).remove();
    else alert('Failed to remove alias.');
  } catch { alert('Error removing alias.'); }
}

function akwShowMergeInput() {
  document.getElementById('akw-merge-btn').style.display = 'none';
  const inp = document.getElementById('akw-merge-input');
  inp.style.display = 'inline-block'; inp.focus();
}
function akwHideMergeInput() {
  document.getElementById('akw-merge-input').style.display = 'none';
  document.getElementById('akw-merge-input').value = '';
  document.getElementById('akw-merge-btn').style.display = '';
}
function akwScheduleHideMerge() { _mergeHideTimer = setTimeout(akwHideMergeInput, 200); }
function akwMergeKeydown(e) {
  clearTimeout(_mergeHideTimer);
  if (e.key === 'Enter')  { e.preventDefault(); akwDoMerge(); }
  if (e.key === 'Escape') { akwHideMergeInput(); }
}

async function akwDoMerge() {
  const inp         = document.getElementById('akw-merge-input');
  const into_phrase = inp.value.trim().toLowerCase();
  if (!into_phrase) { akwHideMergeInput(); return; }
  const srcPhrase = keywordPhrase;
  if (into_phrase === srcPhrase) { alert('Cannot merge a keyword into itself.'); inp.select(); return; }
  if (!confirm(`Merge «${srcPhrase}» into «${into_phrase}»?\n«${srcPhrase}» will become an alias and you will be redirected to «${into_phrase}».`)) return;
  const fd = new FormData(); fd.append('into_phrase', into_phrase);
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/merge`, fd);
    const data = await res.json();
    if (data.ok) location.href = '/keyword/' + encodeURIComponent(into_phrase);
    else alert('Merge failed: ' + (data.error || 'unknown'));
  } catch { alert('Error during merge.'); }
}

async function akwRetag(btn) {
  if (!confirm('Re-tag all papers for this keyword?\nThis may take ~10 seconds.')) return;
  btn.disabled = true; btn.textContent = '…';
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/retag`, new FormData());
    const data = await res.json();
    btn.disabled = false;
    if (data.ok) { btn.textContent = '✓'; setTimeout(() => { btn.textContent = '↺'; }, 1500); }
    else { btn.textContent = '↺'; alert('Retag failed: ' + (data.error || 'unknown')); }
  } catch { btn.disabled = false; btn.textContent = '↺'; alert('Retag request failed.'); }
}

async function akwDelete() {
  const phrase = keywordPhrase;
  const count = keywordPaperCount;
  const papers = count === 1 ? '1 paper' : `${count} papers`;
  const msg = count > 0
    ? `Delete «${phrase}»?\n\nThis keyword tags ${papers}. The papers won't be deleted, but this tag will be removed from them.`
    : `Delete «${phrase}»? (no papers tagged)`;
  if (!confirm(msg)) return;
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/delete`, new FormData());
    const data = await res.json();
    if (data.ok) location.href = '/keywords';
    else alert('Delete failed.');
  } catch { alert('Delete request failed.'); }
}

function akwFlash(el, ok) {
  el.classList.add(ok ? 'saved' : 'error');
  setTimeout(() => el.classList.remove('saved', 'error'), 800);
}

async function akwApplySug(anchor, btn) {
  const fd = new FormData();
  fd.append('field', 'url');
  fd.append('value', anchor);
  try {
    const res  = await csrfFetch(`/admin/keywords/${_kid}/inline`, fd);
    const data = await res.json();
    if (data.ok) {
      document.getElementById('akw-url').value = anchor;
      document.getElementById('akw-url').defaultValue = anchor;
      updateKeywordReferenceLink(data.value || anchor);
      const sug = document.getElementById('akw-url-sug');
      sug.textContent = '';
      const applied = document.createElement('span');
      applied.className = 'sc-sug-applied';
      applied.textContent = '\u2713 ' + anchor;
      sug.appendChild(applied);
    } else { btn.textContent = 'Error'; }
  } catch { btn.textContent = 'Failed'; }
}

document.addEventListener('change', event => {
  const input = event.target.closest('[data-akw-score]');
  if (input) akwSetScore(input);
});

document.addEventListener('keydown', event => {
  if (event.target.closest('[data-akw-alias-input]')) {
    akwAliasKeydown(event);
    return;
  }

  if (event.target.closest('[data-akw-merge-input]')) {
    akwMergeKeydown(event);
    return;
  }

  const urlInput = event.target.closest('[data-akw-url]');
  if (urlInput) {
    if (event.key === 'Enter') {
      event.preventDefault();
      urlInput.blur();
    }
    if (event.key === 'Escape') {
      urlInput.value = urlInput.defaultValue;
      urlInput.blur();
    }
  }
});

document.addEventListener('focusout', event => {
  if (event.target.closest('[data-akw-alias-input]')) {
    akwScheduleHideAlias();
    return;
  }

  if (event.target.closest('[data-akw-merge-input]')) {
    akwScheduleHideMerge();
    return;
  }

  const urlInput = event.target.closest('[data-akw-url]');
  if (urlInput) akwSaveUrl(urlInput);
});

document.addEventListener('click', event => {
  const deleteAliasBtn = event.target.closest('[data-akw-delete-alias]');
  if (deleteAliasBtn) {
    akwDelAlias(Number(deleteAliasBtn.dataset.aliasId));
    return;
  }

  if (event.target.closest('[data-akw-show-alias]')) {
    akwShowAliasInput();
    return;
  }

  if (event.target.closest('[data-akw-show-merge]')) {
    akwShowMergeInput();
    return;
  }

  const applyBtn = event.target.closest('[data-akw-apply-sug]');
  if (applyBtn) {
    akwApplySug(applyBtn.dataset.anchor, applyBtn);
    return;
  }

  const retagBtn = event.target.closest('[data-akw-retag]');
  if (retagBtn) {
    akwRetag(retagBtn);
    return;
  }

  if (event.target.closest('[data-akw-delete]')) akwDelete();
});
})();
