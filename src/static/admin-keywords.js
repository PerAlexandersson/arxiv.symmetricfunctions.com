// ── Select all ────────────────────────────────────────────────────────────────
const selectAll = document.getElementById('select-all');
const selCount  = document.getElementById('sel-count');

function updateCount() {
  const n = document.querySelectorAll('input[name=ids]:checked').length;
  if (selCount) selCount.textContent = n ? n + ' selected' : '';
  document.querySelectorAll('input[name=ids]').forEach(cb =>
    cb.closest('tr').classList.toggle('selected', cb.checked)
  );
}
if (selectAll) {
  selectAll.addEventListener('change', function() {
    document.querySelectorAll('input[name=ids]').forEach(cb => cb.checked = this.checked);
    updateCount();
  });
  document.querySelectorAll('input[name=ids]').forEach(cb =>
    cb.addEventListener('change', updateCount)
  );
}

document.addEventListener('change', event => {
  const input = event.target.closest('[data-score-input]');
  if (input) setScore(Number(input.dataset.kid), input);
});

document.addEventListener('click', event => {
  const deleteAliasBtn = event.target.closest('[data-delete-alias]');
  if (deleteAliasBtn) {
    deleteAlias(Number(deleteAliasBtn.dataset.kid), Number(deleteAliasBtn.dataset.aliasId));
    return;
  }

  const showAliasBtn = event.target.closest('[data-show-alias]');
  if (showAliasBtn) {
    showAliasInput(Number(showAliasBtn.dataset.kid));
    return;
  }

  const showMergeBtn = event.target.closest('[data-show-merge]');
  if (showMergeBtn) {
    showMergeInput(Number(showMergeBtn.dataset.kid));
    return;
  }

  const retagBtn = event.target.closest('[data-retag-keyword]');
  if (retagBtn) {
    retagKeyword(Number(retagBtn.dataset.kid), retagBtn);
    return;
  }

  const deleteKeywordBtn = event.target.closest('[data-delete-keyword]');
  if (deleteKeywordBtn) {
    deleteKeyword(Number(deleteKeywordBtn.dataset.kid), deleteKeywordBtn);
    return;
  }

  if (event.target.closest('[data-bulk-delete]')) doBulkDelete();
});

document.addEventListener('keydown', event => {
  const inlineInput = event.target.closest('.kw-table .inline-edit[data-kid][data-field]');
  if (inlineInput) {
    inlineKeydown(event, inlineInput);
    return;
  }

  const aliasInput = event.target.closest('[data-alias-input]');
  if (aliasInput) {
    aliasKeydown(event, Number(aliasInput.dataset.kid));
    return;
  }

  const mergeInput = event.target.closest('[data-merge-input]');
  if (mergeInput) mergeKeydown(event, Number(mergeInput.dataset.kid));
});

document.addEventListener('input', event => {
  const aliasInput = event.target.closest('[data-alias-input]');
  if (aliasInput) aliasWarn(aliasInput, Number(aliasInput.dataset.kid));
});

document.addEventListener('focusout', event => {
  const inlineInput = event.target.closest('.kw-table .inline-edit[data-kid][data-field]');
  if (inlineInput) {
    saveInline(inlineInput);
    return;
  }

  const aliasInput = event.target.closest('[data-alias-input]');
  if (aliasInput) {
    scheduleHideAlias(Number(aliasInput.dataset.kid));
    return;
  }

  const mergeInput = event.target.closest('[data-merge-input]');
  if (mergeInput) scheduleHideMerge(Number(mergeInput.dataset.kid));
});

// ── Score ─────────────────────────────────────────────────────────────────────
async function setScore(kid, input) {
  const prev = input.defaultValue;
  const fd = new FormData(); fd.append('score', input.value);
  try {
    const res = await csrfFetch(`/admin/keywords/${kid}/score`, fd);
    if (!res.ok) throw new Error();
    input.defaultValue = input.value;
    flash(input, true);
  } catch { alert('Failed to save score'); input.value = prev; }
}

// ── Inline edit (phrase, tag_name, url) ───────────────────────────────────────
function inlineKeydown(e, input) {
  if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
  if (e.key === 'Escape') { input.value = input.defaultValue; input.blur(); }
}

async function saveInline(input) {
  const kid   = input.dataset.kid;
  const field = input.dataset.field;
  const value = input.value.trim();
  if (value === (input.defaultValue || '')) return;
  if (field === 'phrase' && !value) { input.value = input.defaultValue; return; }
  const fd = new FormData(); fd.append('field', field); fd.append('value', value);
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/inline`, fd);
    const data = await res.json();
    if (!data.ok) {
      if (data.error === 'duplicate') {
        const own = input.defaultValue;
        if (confirm(`«${value}» already exists as a keyword.\n\nMerge «${own}» into «${value}»?\n«${own}» will become an alias and its row will be removed.`)) {
          const mfd = new FormData(); mfd.append('into_phrase', value);
          const mres  = await csrfFetch(`/admin/keywords/${kid}/merge`, mfd);
          const mdata = await mres.json();
          if (mdata.ok) {
            document.querySelector(`tr[data-kid="${kid}"]`)?.remove();
          } else {
            alert('Merge failed: ' + (mdata.error || 'unknown'));
            flash(input, false); input.value = input.defaultValue;
          }
        } else {
          flash(input, false); input.value = input.defaultValue;
        }
      } else {
        flash(input, false); input.value = input.defaultValue;
      }
      return;
    }
    input.defaultValue = value;
    flash(input, true);
  } catch { flash(input, false); input.value = input.defaultValue; }
}

// ── Aliases ───────────────────────────────────────────────────────────────────
function showAliasInput(kid) {
  document.getElementById('alias-btn-' + kid).style.display = 'none';
  const inp = document.getElementById('alias-input-' + kid);
  inp.style.display = 'inline-block';
  inp.focus();
}

let _hideTimer = {};
function scheduleHideAlias(kid) {
  _hideTimer[kid] = setTimeout(() => hideAliasInput(kid), 150);
}
function hideAliasInput(kid) {
  const inp = document.getElementById('alias-input-' + kid);
  inp.style.display = 'none';
  inp.value = '';
  document.getElementById('alias-btn-' + kid).style.display = '';
}

function aliasKeydown(e, kid) {
  clearTimeout(_hideTimer[kid]);
  if (e.key === 'Enter')  { e.preventDefault(); addAlias(kid); }
  if (e.key === 'Escape') { hideAliasInput(kid); }
}

function makeAliasChip(kid, aliasId, aliasText) {
  const chip = document.createElement('span');
  chip.className = 'alias-chip';
  chip.id = 'alias-chip-' + aliasId;
  const label = document.createElement('span');
  label.textContent = aliasText;
  const button = document.createElement('button');
  button.type = 'button';
  button.title = 'Remove';
  button.textContent = '×';
  button.dataset.deleteAlias = '';
  button.dataset.kid = String(kid);
  button.dataset.aliasId = String(aliasId);
  chip.append(label, button);
  return chip;
}

async function addAlias(kid) {
  const inp      = document.getElementById('alias-input-' + kid);
  const alias    = inp.value.trim().toLowerCase();
  if (!alias) { hideAliasInput(kid); return; }
  const ownPhrase = document.querySelector(`tr[data-kid="${kid}"] .phrase-field`)?.value.trim().toLowerCase();
  if (alias === ownPhrase) { alert('An alias cannot be the same as the keyword itself.'); inp.select(); return; }
  const fd = new FormData(); fd.append('alias', alias);
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/aliases/add`, fd);
    const data = await res.json();
    if (!data.ok) {
      const msg = {
        duplicate: `«${alias}» is already an alias of another keyword.`,
        self:      'An alias cannot be the same as the keyword itself.',
      }[data.error] || 'Error adding alias.';
      alert(msg); inp.select(); return;
    }
    // If the alias phrase was a standalone keyword, remove its row from the table
    if (data.absorbed) {
      document.querySelectorAll('tr[data-kid]').forEach(row => {
        const phraseInput = row.querySelector('.phrase-field');
        if (phraseInput && phraseInput.value.trim().toLowerCase() === alias) row.remove();
      });
    }
    const list = document.getElementById('aliases-' + kid);
    const btn  = document.getElementById('alias-btn-' + kid);
    const chip = makeAliasChip(kid, data.id, data.alias);
    list.insertBefore(chip, btn);
    hideAliasInput(kid);
  } catch { alert('Error adding alias.'); }
}

async function deleteAlias(kid, aid) {
  const fd = new FormData();
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/aliases/${aid}/delete`, fd);
    const data = await res.json();
    if (data.ok) document.getElementById('alias-chip-' + aid).remove();
  } catch { alert('Error removing alias.'); }
}

// ── Absorption warning ────────────────────────────────────────────────────────
// Map phrase → paper_count, built from the rendered table
const _phraseCount = {};
document.querySelectorAll('tr[data-kid]').forEach(row => {
  const phrase = row.querySelector('.phrase-field')?.value.trim().toLowerCase();
  const count  = parseInt(row.querySelector('.paper-count')?.textContent) || 0;
  if (phrase) _phraseCount[phrase] = count;
});

function aliasWarn(inp, kid) {
  const val  = inp.value.trim().toLowerCase();
  const warn = document.getElementById('alias-warn-' + kid);
  if (val && _phraseCount[val] !== undefined) {
    warn.textContent = `⚠ will absorb «${val}» (${_phraseCount[val]} papers)`;
    warn.style.display = 'inline';
  } else {
    warn.style.display = 'none';
  }
}

// ── Merge into ────────────────────────────────────────────────────────────────
const _mergeTimer = {};

function showMergeInput(kid) {
  document.getElementById('merge-btn-' + kid).style.display = 'none';
  const inp = document.getElementById('merge-input-' + kid);
  inp.style.display = 'inline-block';
  inp.focus();
}

function hideMergeInput(kid) {
  const inp = document.getElementById('merge-input-' + kid);
  inp.style.display = 'none';
  inp.value = '';
  document.getElementById('merge-btn-' + kid).style.display = '';
}

function scheduleHideMerge(kid) {
  _mergeTimer[kid] = setTimeout(() => hideMergeInput(kid), 200);
}

function mergeKeydown(e, kid) {
  clearTimeout(_mergeTimer[kid]);
  if (e.key === 'Enter')  { e.preventDefault(); doMerge(kid); }
  if (e.key === 'Escape') { hideMergeInput(kid); }
}

async function doMerge(kid) {
  const inp        = document.getElementById('merge-input-' + kid);
  const into_phrase = inp.value.trim().toLowerCase();
  if (!into_phrase) { hideMergeInput(kid); return; }
  const srcPhrase = document.querySelector(`tr[data-kid="${kid}"] .phrase-field`)?.value.trim().toLowerCase();
  if (into_phrase === srcPhrase) { alert('Cannot merge a keyword into itself.'); inp.select(); return; }
  if (!confirm(`Merge «${srcPhrase}» into «${into_phrase}»?\n«${srcPhrase}» will become an alias and its row will be removed.`)) return;
  const fd = new FormData(); fd.append('into_phrase', into_phrase);
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/merge`, fd);
    const data = await res.json();
    if (!data.ok) { alert('Merge failed: ' + (data.error || 'unknown')); inp.select(); return; }
    // Remove the merged keyword's row
    document.querySelector(`tr[data-kid="${kid}"]`)?.remove();
  } catch { alert('Error during merge.'); }
}

// ── Delete confirmation with paper count ─────────────────────────────────────
function confirmDelete(phrase, count) {
  const papers = count === 1 ? '1 paper' : `${count} papers`;
  const msg = count > 0
    ? `Delete «${phrase}»?\n\nThis keyword tags ${papers}. The papers won't be deleted, but this tag will be removed from them.`
    : `Delete «${phrase}»? (no papers tagged)`;
  return confirm(msg);
}

function confirmBulkDelete() {
  const checked = Array.from(document.querySelectorAll('input[name=ids]:checked'));
  if (!checked.length) return false;
  const kwCount = checked.length;
  const paperCount = checked.reduce((sum, cb) => {
    const row = cb.closest('tr[data-kid]');
    return sum + (parseInt(row?.dataset.papers) || 0);
  }, 0);
  const kws = kwCount === 1 ? '1 keyword' : `${kwCount} keywords`;
  const papers = paperCount === 1 ? '1 paper' : `${paperCount} papers`;
  return confirm(`Delete ${kws}?\n\nThese keywords tag ${papers}. The papers won't be deleted, but the tags will be removed.`);
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Trash SVG (same as template, avoids duplication in buildKwRow)
const _TRASH_SVG = `<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>`;

// ── AJAX delete keyword ───────────────────────────────────────────────────────
async function deleteKeyword(kid, btn) {
  const row    = btn.closest('tr[data-kid]');
  const phrase = row?.querySelector('.phrase-field')?.value || '';
  const count  = parseInt(row?.dataset.papers) || 0;
  if (!confirmDelete(phrase, count)) return;
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/delete`, new FormData());
    const data = await res.json();
    if (data.ok) {
      row.remove();
      // Keep datalist and _phraseCount in sync
      document.querySelector(`#kw-list option[value="${escHtml(phrase)}"]`)?.remove();
      delete _phraseCount[phrase];
    } else {
      alert('Delete failed.');
    }
  } catch { alert('Delete request failed.'); }
}

// ── AJAX bulk delete ──────────────────────────────────────────────────────────
async function doBulkDelete() {
  const checked = Array.from(document.querySelectorAll('input[name=ids]:checked'));
  if (!checked.length) return;
  if (!confirmBulkDelete()) return;
  const fd = new FormData();
  checked.forEach(cb => fd.append('ids', cb.value));
  try {
    const res  = await csrfFetch('/admin/keywords/bulk_delete', fd);
    const data = await res.json();
    if (data.ok) {
      checked.forEach(cb => {
        const row = cb.closest('tr[data-kid]');
        const phrase = row?.querySelector('.phrase-field')?.value || '';
        document.querySelector(`#kw-list option[value="${escHtml(phrase)}"]`)?.remove();
        delete _phraseCount[phrase];
        row?.remove();
      });
      updateCount();
    } else {
      alert('Bulk delete failed.');
    }
  } catch { alert('Bulk delete request failed.'); }
}

// ── AJAX add keyword ──────────────────────────────────────────────────────────
function buildKwRow(kid, phrase) {
  const tr = document.createElement('tr');
  tr.dataset.kid    = kid;
  tr.dataset.papers = '0';
  tr.innerHTML = `
    <td><input type="checkbox" name="ids" value="${kid}" form="bulk-form"></td>
    <td>
      <input type="number" value="5" min="1" max="10" class="kw-score-input"
             data-score-input data-kid="${kid}">
    </td>
    <td>
      <input type="text" class="inline-edit phrase-field" data-kid="${kid}" data-field="phrase"
             value="${escHtml(phrase)}" title="Click to rename">
    </td>
    <td>
      <div class="alias-list" id="aliases-${kid}">
        <button type="button" class="alias-add-btn" id="alias-btn-${kid}"
                data-show-alias data-kid="${kid}">+ alias</button>
        <button type="button" class="alias-add-btn merge-btn" id="merge-btn-${kid}"
                data-show-merge data-kid="${kid}" title="Merge this keyword into another">⇒ merge into…</button>
        <input type="text" class="alias-add-input" id="alias-input-${kid}"
               placeholder="synonym…" list="kw-list"
               data-alias-input data-kid="${kid}">
        <span class="alias-warn" id="alias-warn-${kid}"></span>
        <input type="text" class="alias-add-input" id="merge-input-${kid}"
               placeholder="merge into…" list="kw-list"
               data-merge-input data-kid="${kid}">
      </div>
    </td>
    <td>
      <input type="text" class="inline-edit" data-kid="${kid}" data-field="url"
             value="" placeholder="https://…" title="Definition URL (optional)">
    </td>
    <td class="paper-count">0</td>
    <td>
      <button type="button" class="btn-retag" title="Re-tag all papers for this keyword"
              data-retag-keyword data-kid="${kid}">↺</button>
      <button type="button" class="btn-trash" title="Delete keyword"
              data-delete-keyword data-kid="${kid}">${_TRASH_SVG}</button>
    </td>`;
  // Wire up the new checkbox so the selection counter works
  tr.querySelector('input[name=ids]').addEventListener('change', updateCount);
  return tr;
}

function insertRowSorted(tr, phrase) {
  const tbody = document.querySelector('table.kw-table tbody');
  if (!tbody) return;
  const rows = Array.from(tbody.querySelectorAll('tr[data-kid]'));
  const after = rows.find(r => (r.querySelector('.phrase-field')?.value || '').localeCompare(phrase) > 0);
  if (after) tbody.insertBefore(tr, after);
  else        tbody.appendChild(tr);
}

document.getElementById('add-kw-form')?.addEventListener('submit', async function(e) {
  e.preventDefault();
  const inp   = this.querySelector('input[name=phrase]');
  const phrase = inp.value.trim().toLowerCase();
  if (!phrase) return;
  try {
    const fd = new FormData(this);
    const res  = await csrfFetch(this.action, fd);
    const data = await res.json();
    if (!data.ok) {
      alert(data.error === 'duplicate' ? `«${phrase}» already exists.` : 'Could not add keyword.');
      return;
    }
    const row = buildKwRow(data.id, data.phrase);
    insertRowSorted(row, data.phrase);
    // Add to datalist and phrase-count map
    const opt = document.createElement('option');
    opt.value = data.phrase;
    document.getElementById('kw-list')?.appendChild(opt);
    _phraseCount[data.phrase] = 0;
    inp.value = '';
    inp.focus();
  } catch { alert('Failed to add keyword.'); }
});

// ── Retag single keyword ──────────────────────────────────────────────────────
async function retagKeyword(kid, btn) {
  if (!confirm('Re-tag all papers for this keyword?\nThis scans all papers and may take ~10 seconds.')) return;
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const res  = await csrfFetch(`/admin/keywords/${kid}/retag`, new FormData());
    const data = await res.json();
    if (data.ok) {
      // Update the paper count cell in this row
      const row = btn.closest('tr[data-kid]');
      row.dataset.papers = data.count;
      row.querySelector('.paper-count').textContent = data.count;
      btn.textContent = '✓';
      setTimeout(() => { btn.textContent = '↺'; btn.disabled = false; }, 1500);
    } else {
      alert('Retag failed: ' + (data.error || 'unknown'));
      btn.textContent = '↺'; btn.disabled = false;
    }
  } catch {
    alert('Retag request failed.');
    btn.textContent = '↺'; btn.disabled = false;
  }
}

// ── Visual feedback ───────────────────────────────────────────────────────────
function flash(el, ok) {
  el.classList.add(ok ? 'saved' : 'error');
  setTimeout(() => el.classList.remove('saved', 'error'), 800);
}

// ── Column resize with drag handles + localStorage persistence ────────────────
(function() {
  const STORE_KEY = 'kw-table-col-widths';
  const FIXED    = new Set([0, 1, 5, 6]); // check, score, count, del
  const DEFAULTS = { 2: '18%', 3: '24%', 4: '7%' }; // phrase, aliases, url
  const cols  = Array.from(document.querySelectorAll('table.kw-table col'));
  const ths   = Array.from(document.querySelectorAll('table.kw-table thead th'));

  // Apply widths from localStorage, falling back to defaults — always via inline
  // style so there's no CSS→px jump on load.
  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    const valid = saved && saved.length === cols.length;
    cols.forEach((col, i) => {
      if (FIXED.has(i)) return;
      const w = (valid && saved[i]) ? saved[i] : DEFAULTS[i];
      if (w) col.style.width = w;
    });
  } catch(e) {
    cols.forEach((col, i) => { if (!FIXED.has(i) && DEFAULTS[i]) col.style.width = DEFAULTS[i]; });
  }

  function saveWidths() {
    const widths = cols.map((c, i) => FIXED.has(i) ? null : (c.style.width || c.offsetWidth + 'px'));
    try { localStorage.setItem(STORE_KEY, JSON.stringify(widths)); } catch(e) {}
  }

  // Add handle between each pair of adjacent resizable columns
  ths.forEach((th, i) => {
    if (FIXED.has(i)) return;         // this col is fixed
    if (FIXED.has(i + 1)) return;     // next col is fixed (or out of bounds)
    if (i + 1 >= ths.length) return;

    const handle = document.createElement('div');
    handle.className = 'col-resize-handle';
    th.appendChild(handle);

    handle.addEventListener('mousedown', function(e) {
      e.preventDefault();
      handle.classList.add('dragging');
      document.body.style.cursor = 'col-resize';

      const startX    = e.clientX;
      const startW    = th.offsetWidth;
      const nextTh    = ths[i + 1];
      const nextStartW = nextTh.offsetWidth;
      const MIN = 40;

      function onMove(e) {
        const delta   = e.clientX - startX;
        const newW    = Math.max(MIN, startW + delta);
        const newNextW = Math.max(MIN, nextStartW - delta);
        // Only allow if both stay above minimum
        if (startW + delta >= MIN && nextStartW - delta >= MIN) {
          cols[i].style.width     = newW + 'px';
          cols[i + 1].style.width = newNextW + 'px';
        }
      }
      function onUp() {
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        saveWidths();
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  });
})();
