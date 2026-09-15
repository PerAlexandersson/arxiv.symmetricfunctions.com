(function () {
  'use strict';

  const container = document.getElementById('admin-attention');
  if (!container) return;

  const endpoint = container.dataset.endpoint;
  if (!endpoint) return;

  fetch(endpoint, {headers: {'Accept': 'application/json'}})
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (!data.ok || !Array.isArray(data.items) || data.items.length === 0) return;

      data.items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'admin-attention-item';
        if (item.level === 'danger') {
          row.classList.add('admin-attention-item--danger');
        }

        const message = document.createElement('span');
        message.textContent = item.message;
        row.appendChild(message);

        const link = document.createElement('a');
        link.className = 'admin-attention-link';
        link.href = item.href;
        link.textContent = item.label;
        row.appendChild(link);
        container.appendChild(row);
      });
      container.hidden = false;
    })
    .catch(() => {
      // A transient banner request should not interfere with the admin page.
    });
}());
