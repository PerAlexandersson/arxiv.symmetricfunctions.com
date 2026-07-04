async function deleteUser(uid, name, btn) {
  const label = name || ('user #' + uid);
  if (!confirm(`Delete ${label}?\n\nThis will permanently remove the account and all their watched keywords, watched authors, and saved lists. This cannot be undone.`)) return;
  try {
    const data = await csrfJsonFetch(`/admin/users/${uid}/delete`, {});
    if (data.ok) {
      btn.closest('tr').remove();
    } else {
      alert('Delete failed.');
    }
  } catch (err) {
    if (err.message !== 'AUTH_REQUIRED') alert('Delete request failed.');
  }
}

document.addEventListener('click', event => {
  const btn = event.target.closest('[data-delete-user]');
  if (!btn) return;
  deleteUser(btn.dataset.userId, btn.dataset.userName, btn);
});
