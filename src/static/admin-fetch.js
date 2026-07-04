const fetchForm = document.getElementById('fetch-form');
const fetchResult = document.getElementById('fetch-result');
const fetchResultLog = document.getElementById('fetch-result-log');

fetchForm?.addEventListener('submit', async function(e) {
  e.preventDefault();
  const btn = e.submitter;
  setButtonRunning(btn, true, 'Fetching…');
  setResultBoxState(fetchResult);
  if (fetchResultLog) fetchResultLog.textContent = 'Running fetch…';
  try {
    const fd = new FormData(fetchForm);
    if (btn?.name && !fd.has(btn.name)) fd.append(btn.name, btn.value);
    const data = await csrfJsonFetch(fetchForm.action || window.location.pathname, fd);
    setResultBoxState(fetchResult, data.ok ? 'ok' : 'err');
    const label = fetchResult?.querySelector('strong');
    if (label) label.textContent = data.ok ? 'Done' : 'Error';
    if (fetchResultLog) fetchResultLog.textContent = data.log || data.error || '';
  } catch (err) {
    if (err.message !== 'AUTH_REQUIRED') {
      setResultBoxState(fetchResult, 'err');
      const label = fetchResult?.querySelector('strong');
      if (label) label.textContent = 'Error';
      if (fetchResultLog) fetchResultLog.textContent = 'Request failed.';
    }
  } finally {
    setButtonRunning(btn, false);
  }
});
