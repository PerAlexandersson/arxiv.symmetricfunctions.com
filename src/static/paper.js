(() => {
const paperView = document.querySelector('.paper[data-arxiv-id]');
if (!paperView) return;
const PAPER_ARXIV_ID = paperView.dataset.arxivId;
const PAPER_ID = Number(paperView.dataset.paperId || '0');

function setPublishedBibtexAvailable(available, endpoint) {
  const tabs = document.getElementById('tabs');
  if (!tabs) return;
  if (available) {
    tabs.style.display = '';
    if (endpoint) fetchBibtex(PAPER_ARXIV_ID, 'published-bibtex', endpoint);
  } else {
    tabs.style.display = 'none';
    showTab('arxiv-tab');
    const published = document.getElementById('published-bibtex');
    if (published) published.textContent = '';
  }
}

function updateSkipDoiButton(data) {
  const btn = document.getElementById('skip-doi-btn');
  if (!btn) return;
  if (data.doi) {
    btn.style.display = 'none';
    return;
  }
  btn.style.display = '';
  const skipped = ['known_no_doi', 'arxiv_only'].includes(data.publication_status);
  btn.classList.toggle('skip-doi-active', skipped);
  if (skipped) {
    btn.innerHTML = '&#x2717; No DOI';
    btn.title = 'Paper marked as unlikely to get a DOI \u2014 click to undo';
  } else {
    btn.textContent = 'No DOI';
    btn.title = 'Mark as unlikely to ever get a DOI (skips future lookups)';
  }
}

function updatePublicationDisplay(data) {
  const meta = document.getElementById('publication-meta');
  const label = document.getElementById('publication-label');
  const display = document.getElementById('publication-display');
  if (!meta || !label || !display) return;

  display.textContent = '';
  if (data.doi) {
    label.textContent = 'DOI:';
    const link = document.createElement('a');
    link.href = 'https://doi.org/' + data.doi;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = data.doi;
    display.appendChild(link);
    meta.style.display = '';
    setPublishedBibtexAvailable(true, '/api/doi-bibtex/');
  } else if (data.publication_url) {
    label.textContent = 'Publication:';
    const link = document.createElement('a');
    link.href = data.publication_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = data.publication_venue_label || 'View publication';
    display.appendChild(link);
    meta.style.display = '';
    setPublishedBibtexAvailable(true, '/api/publication-bibtex/');
  } else if (data.publication_status === 'arxiv_only') {
    label.textContent = 'Publication:';
    display.textContent = 'arXiv only';
    meta.style.display = '';
    setPublishedBibtexAvailable(false);
  } else {
    meta.style.display = 'none';
    setPublishedBibtexAvailable(false);
  }
  updateSkipDoiButton(data);
}

async function setPublication(e) {
  e.preventDefault();
  const mode = document.getElementById('publication-mode').value;
  const val = document.getElementById('publication-value').value.trim();
  const status = document.getElementById('publication-status');
  const saveBtn = document.getElementById('publication-save-btn');
  if (!val && mode !== 'arxiv_only') { status.textContent = 'empty'; return false; }
  status.textContent = 'Saving…';
  status.style.color = 'var(--c-text-sub)';
  saveBtn.disabled = true;
  const fd = new FormData();
  fd.append('publication_mode', mode);
  fd.append('publication_value', val);
  try {
    const data = await csrfJsonFetch(`/admin/papers/${PAPER_ID}/publication`, fd);
    if (data.ok) {
      status.textContent = '\u2713 saved';
      status.style.color = 'green';
      document.getElementById('publication-value').value = data.doi || data.publication_url || '';
      updatePublicationDisplay(data);
      saveBtn.disabled = false;
    } else {
      status.textContent = data.error || 'Error';
      status.style.color = 'red';
      saveBtn.disabled = false;
    }
  } catch (e2) {
    if (e2.message !== 'AUTH_REQUIRED') {
      status.textContent = 'Failed';
      status.style.color = 'red';
    }
    saveBtn.disabled = false;
  }
  return false;
}

async function setEditorNote(e) {
  e.preventDefault();
  const status = document.getElementById('editor-note-status');
  const saveBtn = document.getElementById('editor-note-save-btn');
  const fd = new FormData();
  fd.append('editor_note', document.getElementById('editor-note-input').value.trim());
  status.textContent = 'Saving…';
  status.style.color = 'var(--c-text-sub)';
  saveBtn.disabled = true;
  try {
    const data = await csrfJsonFetch(`/admin/papers/${PAPER_ID}/editor-note`, fd);
    if (data.ok) {
      status.textContent = '\u2713 saved';
      status.style.color = 'green';
      const note = data.editor_note || '';
      const noteMeta = document.getElementById('editor-note-meta');
      const noteText = document.getElementById('editor-note-text');
      if (noteText) noteText.textContent = note;
      if (noteMeta) noteMeta.style.display = note ? '' : 'none';
      saveBtn.disabled = false;
    } else {
      status.textContent = data.error || 'Error';
      status.style.color = 'red';
      saveBtn.disabled = false;
    }
  } catch (e2) {
    if (e2.message !== 'AUTH_REQUIRED') {
      status.textContent = 'Failed';
      status.style.color = 'red';
    }
    saveBtn.disabled = false;
  }
  return false;
}

async function toggleSkipDoi(paperId) {
  const btn = document.getElementById('skip-doi-btn');
  const isSkipped = btn.classList.contains('skip-doi-active');
  const action = isSkipped ? 'unskip' : 'skip';
  try {
    const data = await csrfJsonFetch('/admin/dois/' + paperId + '/' + action, {});
    if (data.ok) {
      if (action === 'skip') {
        btn.classList.add('skip-doi-active');
        btn.innerHTML = '&#x2717; No DOI';
        btn.title = 'Paper marked as unlikely to get a DOI \u2014 click to undo';
      } else {
        btn.classList.remove('skip-doi-active');
        btn.textContent = 'No DOI';
        btn.title = 'Mark as unlikely to ever get a DOI (skips future lookups)';
      }
    }
  } catch (e2) {
    if (e2.message !== 'AUTH_REQUIRED') {
      console.error('toggleSkipDoi failed', e2);
    }
  }
}

async function refetchPaper(arxivId) {
  const btn = document.getElementById('refetch-btn');
  const status = document.getElementById('refetch-status');
  btn.disabled = true;
  status.textContent = 'Fetching…';
  status.style.color = 'var(--c-text-sub)';
  try {
    const data = await csrfJsonFetch('/admin/paper/' + arxivId + '/refetch', {});
    if (data.ok) {
      status.textContent = 'Done. Reload to view latest metadata.';
      status.style.color = 'green';
      btn.disabled = false;
    } else {
      status.textContent = 'Error: ' + (data.error || 'unknown');
      status.style.color = 'red';
      btn.disabled = false;
    }
  } catch (e2) {
    if (e2.message !== 'AUTH_REQUIRED') {
      status.textContent = 'Request failed.';
      status.style.color = 'red';
      btn.disabled = false;
    }
  }
}
window.toggleSkipDoi = toggleSkipDoi;
window.refetchPaper = refetchPaper;

document.querySelector('[data-publication-form]')?.addEventListener('submit', setPublication);
document.querySelector('[data-editor-note-form]')?.addEventListener('submit', setEditorNote);

// Fetch BibTeX on page load using utils.js fetchBibtex().
fetchBibtex(PAPER_ARXIV_ID, 'arxiv-bibtex');
const publishedBibtexEndpoint = paperView.dataset.publishedBibtexEndpoint;
if (publishedBibtexEndpoint) {
  fetchBibtex(PAPER_ARXIV_ID, 'published-bibtex', publishedBibtexEndpoint);
}
})();
