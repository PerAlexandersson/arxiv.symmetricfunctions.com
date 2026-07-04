const retagForm = document.getElementById('retag-form');
const retagResult = document.getElementById('retag-result');
const retagResultText = document.getElementById('retag-result-text');

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
