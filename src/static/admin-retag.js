const retagForm = document.getElementById('retag-form');
const retagResult = document.getElementById('retag-result');
const retagResultText = document.getElementById('retag-result-text');
const fetchKeywordsButton = document.getElementById('fetch-keywords');
const keywordFetchResult = document.getElementById('keyword-fetch-result');

fetchKeywordsButton?.addEventListener('click', async function() {
  setButtonRunning(fetchKeywordsButton, true, 'Fetching…');
  setResultBoxState(keywordFetchResult);
  keywordFetchResult.textContent = 'Fetching keywords from SymCat…';
  try {
    const data = await csrfJsonFetch(fetchKeywordsButton.dataset.fetchUrl, {});
    setResultBoxState(keywordFetchResult, data.ok ? 'ok' : 'err');
    keywordFetchResult.textContent = data.ok
      ? `Fetched ${data.total} keywords: ${data.added} added, ${data.existing} already present, ${data.excluded} excluded. Run retag below to apply them to papers.`
      : data.error || 'Keyword fetch failed.';
  } catch (err) {
    if (err.message !== 'AUTH_REQUIRED') {
      setResultBoxState(keywordFetchResult, 'err');
      keywordFetchResult.textContent = 'Keyword fetch failed. Please try again.';
    }
  } finally {
    setButtonRunning(fetchKeywordsButton, false);
  }
});

retagForm?.addEventListener('submit', async function(e) {
  e.preventDefault();
  const btn = e.submitter || document.getElementById('retag-submit');
  setButtonRunning(btn, true, 'Tagging…');
  setResultBoxState(retagResult);
  if (retagResultText) retagResultText.textContent = 'Running retag…';
  try {
    const data = await csrfJsonFetch(retagForm.action || window.location.pathname, new FormData(retagForm));
    if (data.ok) {
      setResultBoxState(retagResult, 'ok');
      if (retagResultText) retagResultText.innerHTML = `Done. Tagged <strong>${data.papers}</strong> paper${data.papers === 1 ? '' : 's'} (${data.from} → ${data.to}) — <strong>${data.tags}</strong> keyword tag${data.tags === 1 ? '' : 's'} applied.`;
    } else {
      setResultBoxState(retagResult, 'err');
      if (retagResultText) retagResultText.textContent = data.error || 'Retag failed.';
    }
  } catch (err) {
    if (err.message !== 'AUTH_REQUIRED') {
      setResultBoxState(retagResult, 'err');
      if (retagResultText) retagResultText.textContent = 'Retag request failed.';
    }
  } finally {
    setButtonRunning(btn, false);
  }
});
