/**
 * Utility functions for arXiv Combinatorics Frontend
 * Organized into sections: Core Utilities, BibTeX Functions, UI Features
 */

// ============================================================================
// CORE UTILITIES
// ============================================================================

/**
 * Copy text to clipboard with fallback for non-secure contexts
 * @param {string} text - The text to copy
 * @returns {Promise} - Resolves when copy succeeds, rejects on error
 */
function copyToClipboard(text) {
    // Try modern Clipboard API first (requires HTTPS or localhost)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
    }

    // Fallback for older browsers or non-secure contexts
    return new Promise((resolve, reject) => {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();

        try {
            const successful = document.execCommand('copy');
            document.body.removeChild(textarea);
            if (successful) {
                resolve();
            } else {
                reject(new Error('execCommand failed'));
            }
        } catch (err) {
            document.body.removeChild(textarea);
            reject(err);
        }
    });
}

/**
 * Generic fetch and copy utility
 * @param {string} url - API endpoint to fetch from
 * @param {string} successMessage - Message to show on success
 * @param {string} errorPrefix - Prefix for error messages
 * @returns {Promise}
 */
async function fetchAndCopy(url, successMessage, errorPrefix = 'Failed to copy') {
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const text = await response.text();
        await copyToClipboard(text);
        alert(successMessage);
    } catch (err) {
        alert(`${errorPrefix}: ${err}`);
        throw err;
    }
}

// ============================================================================
// BIBTEX FUNCTIONS
// ============================================================================

/**
 * Fetch and copy arXiv BibTeX citation
 * @param {string} arxivId - The arXiv paper ID
 */
async function copyBibtex(arxivId) {
    showBibtexModal(`/api/bibtex/${arxivId}`, `arXiv:${arxivId}`);
}

/**
 * Fetch and show DOI BibTeX citation in modal
 * @param {string} arxivId - The arXiv paper ID
 */
async function copyDoiBibtex(arxivId) {
    showBibtexModal(`/api/doi-bibtex/${arxivId}`, `DOI \u2014 arXiv:${arxivId}`);
}

/**
 * Fetch BibTeX and display in element
 * @param {string} arxivId - The arXiv paper ID
 * @param {string} elementId - Target element ID for display
 * @param {string} [apiPath='/api/bibtex/'] - API endpoint prefix (override for DOI bibtex)
 */
async function fetchBibtex(arxivId, elementId, apiPath = '/api/bibtex/') {
    try {
        const response = await fetch(`${apiPath}${arxivId}`);
        const bibtex = await response.text();
        document.getElementById(elementId).textContent = bibtex;
    } catch (error) {
        document.getElementById(elementId).textContent = 'Error loading BibTeX';
    }
}

// ============================================================================
// BULK BIBTEX FUNCTIONS
// ============================================================================

/**
 * Fetch and copy all BibTeX entries for an author
 * @param {string} authorName - The author's name
 */
async function copyAuthorBibtex(authorSlug, authorName) {
    showBibtexModal(`/api/author-bibtex/${authorSlug}`, authorName || authorSlug);
}

// ============================================================================
// BIBTEX MODAL
// ============================================================================

/**
 * Fetch plain-text BibTeX from url and display it in the shared modal.
 * @param {string} url   - Endpoint returning plain-text BibTeX
 * @param {string} title - Title shown in the modal header
 */
async function showBibtexModal(url, title) {
    const modal    = document.getElementById('bibtex-modal');
    const titleEl  = document.getElementById('bib-modal-title');
    const textarea = document.getElementById('bib-modal-text');
    const status   = document.getElementById('bib-modal-status');

    titleEl.textContent  = title ? `BibTeX \u2014 ${title}` : 'BibTeX';
    textarea.value       = 'Loading\u2026';
    status.textContent   = '';
    modal.style.display  = 'flex';
    document.body.classList.add('modal-open');

    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        textarea.value = await resp.text();
    } catch (err) {
        textarea.value = `Error loading BibTeX: ${err}`;
    }
}

function closeBibtexModal() {
    const modal = document.getElementById('bibtex-modal');
    if (modal) {
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    }
}

async function copyBibtexModal() {
    const textarea = document.getElementById('bib-modal-text');
    const status   = document.getElementById('bib-modal-status');
    try {
        await copyToClipboard(textarea.value);
        status.textContent = 'Copied!';
        setTimeout(() => { status.textContent = ''; }, 2000);
    } catch (err) {
        status.textContent = 'Copy failed';
    }
}

// Close modal on backdrop click or Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeBibtexModal();
});
document.addEventListener('click', (e) => {
    const modal = document.getElementById('bibtex-modal');
    if (modal && e.target === modal) closeBibtexModal();
});

// ============================================================================
// SHARING FUNCTIONS
// ============================================================================

/**
 * Copy shareable link to clipboard
 * @param {string} arxivId - The arXiv paper ID
 */
async function copyShareLink(arxivId) {
    const url = `${window.location.origin}/paper/${arxivId}`;
    try {
        await copyToClipboard(url);
        alert('Link copied to clipboard!');
    } catch (err) {
        alert('Failed to copy link: ' + err);
    }
}

// ============================================================================
// UI FEATURES - Abstract Persistence
// ============================================================================

/**
 * Initialize persistent abstract state using localStorage
 * Remembers which abstracts are expanded across page loads
 */
function initAbstractPersistence() {
    const details = document.querySelectorAll('.abstract-details');

    // Restore state from localStorage
    details.forEach(detail => {
        const arxivId = detail.getAttribute('data-arxiv-id');
        if (arxivId) {
            const isOpen = localStorage.getItem(`abstract-${arxivId}`) === 'open';
            if (isOpen) {
                detail.open = true;
            }
        }
    });

    // Save state on toggle
    details.forEach(detail => {
        detail.addEventListener('toggle', function() {
            const arxivId = this.getAttribute('data-arxiv-id');
            if (arxivId) {
                localStorage.setItem(`abstract-${arxivId}`, this.open ? 'open' : 'closed');
            }
        });
    });
}

// ============================================================================
// UI FEATURES - Keyboard Shortcuts
// ============================================================================

/**
 * Initialize keyboard shortcuts for paper navigation
 * j/k - Navigate between papers
 * Enter - Toggle abstract
 */
function initKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Ignore if user is typing in an input/textarea
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return;
        }

        const papers = Array.from(document.querySelectorAll('.paper'));
        if (papers.length === 0) return;

        let currentIndex = -1;
        const focused = document.activeElement;

        // Find current paper
        if (focused && focused.classList.contains('paper-title')) {
            const paper = focused.closest('.paper');
            currentIndex = papers.indexOf(paper);
        }

        if (e.key === 'j') {
            // Next paper
            e.preventDefault();
            const nextIndex = currentIndex + 1;
            if (nextIndex < papers.length) {
                const summary = papers[nextIndex].querySelector('.paper-title');
                if (summary) {
                    summary.focus();
                    summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        } else if (e.key === 'k') {
            // Previous paper
            e.preventDefault();
            const prevIndex = currentIndex - 1;
            if (prevIndex >= 0) {
                const summary = papers[prevIndex].querySelector('.paper-title');
                if (summary) {
                    summary.focus();
                    summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            } else if (currentIndex === -1 && papers.length > 0) {
                // If nothing focused, focus first paper
                const summary = papers[0].querySelector('.paper-title');
                if (summary) {
                    summary.focus();
                    summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        } else if (e.key === 'Enter') {
            // Toggle current paper's abstract
            if (focused && focused.classList.contains('paper-title')) {
                e.preventDefault();
                focused.click();
            }
        }
    });
}

// ============================================================================
// UI FEATURES - Dark Mode
// ============================================================================

/**
 * Toggle dark mode and persist preference
 */
function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark');
    localStorage.setItem('dark-mode', isDark ? 'on' : 'off');
    updateDarkModeLabel();
}

/**
 * Update the dark-mode toggle button aria-label (icons handled via CSS)
 */
function updateDarkModeLabel() {
    const toggle = document.getElementById('dark-mode-toggle');
    if (toggle) {
        const isDark = document.documentElement.classList.contains('dark');
        toggle.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
        toggle.setAttribute('title',      isDark ? 'Switch to light mode' : 'Switch to dark mode');
    }
}

/**
 * Initialize dark mode from saved preference
 */
function initDarkMode() {
    const saved = localStorage.getItem('dark-mode');
    if (saved === 'on') {
        document.documentElement.classList.add('dark');
    }
    updateDarkModeLabel();
}

// ============================================================================
// UI FEATURES - Tab Switching
// ============================================================================

/**
 * Switch between tab panels (shared by tools.html and paper.html)
 * Tab content IDs must match button IDs as "<tabId>-btn"
 * @param {string} tabId - ID of the tab content panel to show
 */
function showTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.style.borderBottomColor = 'transparent';
        btn.style.color = 'var(--c-text-sub)';
        btn.style.fontWeight = 'normal';
    });
    document.getElementById(tabId).style.display = 'block';
    const btn = document.getElementById(tabId + '-btn');
    if (btn) {
        btn.style.borderBottomColor = 'var(--c-link)';
        btn.style.color = 'var(--c-link)';
        btn.style.fontWeight = '600';
    }
}

// ============================================================================
// MY LISTS — STAR / SAVE / REMOVE
// ============================================================================

/**
 * Toggle the Starred status of a paper.
 * @param {HTMLElement} btn
 * @param {string} arxivId
 */
async function toggleStar(btn, arxivId) {
    try {
        const resp = await csrfFetch(`/api/lists/star/${arxivId}`, {});
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = '/login'; return; }
            throw new Error(`HTTP ${resp.status}`);
        }
        const data = await resp.json();
        btn.classList.toggle('starred', data.starred);
        btn.title = data.starred ? 'Remove from Starred' : 'Star this paper';
        btn.setAttribute('aria-label', btn.title);
    } catch (err) {
        console.error('toggleStar failed:', err);
    }
}

/**
 * Show a save-to-list dropdown near the clicked button.
 * @param {HTMLElement} btn
 * @param {string} arxivId
 */
async function showSaveMenu(btn, arxivId) {
    document.querySelectorAll('.save-dropdown').forEach(d => d.remove());

    let categories;
    try {
        const resp = await fetch('/api/lists/categories');
        if (!resp.ok) {
            if (resp.status === 401) { window.location.href = '/login'; return; }
            throw new Error(`HTTP ${resp.status}`);
        }
        categories = await resp.json();
    } catch (err) {
        console.error('showSaveMenu failed:', err);
        return;
    }

    const dropdown = document.createElement('div');
    dropdown.className = 'save-dropdown';

    if (categories.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'save-dropdown-item save-dropdown-empty';
        empty.textContent = 'No lists yet';
        dropdown.appendChild(empty);
    } else {
        categories.forEach(cat => {
            const item = document.createElement('div');
            item.className = 'save-dropdown-item';
            item.textContent = cat.name;
            item.addEventListener('click', async () => {
                dropdown.remove();
                const r = await csrfFetch('/api/lists/save', { arxiv_id: arxivId, category_id: cat.id });
                if (r.ok) {
                    btn.classList.add('saved');
                    btn.title = `Saved to ${cat.name}`;
                } else {
                    const d = await r.json();
                    alert(d.error || 'Failed to save.');
                }
            });
            dropdown.appendChild(item);
        });
    }

    const newItem = document.createElement('div');
    newItem.className = 'save-dropdown-item save-dropdown-new';
    newItem.textContent = '+ New list\u2026';
    newItem.addEventListener('click', async () => {
        dropdown.remove();
        const name = prompt('New list name:');
        if (!name || !name.trim()) return;
        const r = await csrfFetch('/api/lists/save', { arxiv_id: arxivId, new_name: name.trim() });
        if (r.ok) {
            const d = await r.json();
            btn.classList.add('saved');
            btn.title = `Saved to ${d.category_name}`;
        } else {
            const d = await r.json();
            alert(d.error || 'Failed to save.');
        }
    });
    dropdown.appendChild(newItem);

    document.body.appendChild(dropdown);
    const rect = btn.getBoundingClientRect();
    const ddW  = dropdown.offsetWidth;
    let left   = rect.left + window.scrollX;
    if (left + ddW > window.innerWidth - 8) left = window.innerWidth - ddW - 8;
    dropdown.style.top  = (rect.bottom + window.scrollY + 4) + 'px';
    dropdown.style.left = Math.max(4, left) + 'px';

    const closeDropdown = (e) => {
        if (!dropdown.contains(e.target) && e.target !== btn) {
            dropdown.remove();
            document.removeEventListener('click', closeDropdown, true);
        }
    };
    setTimeout(() => document.addEventListener('click', closeDropdown, true), 0);
}

/**
 * Remove a paper from the current list and hide its row.
 * @param {HTMLElement} btn
 * @param {string} arxivId
 * @param {number} catId
 */
async function removePaperFromList(btn, arxivId, catId) {
    try {
        const resp = await csrfFetch('/api/lists/remove', { arxiv_id: arxivId, category_id: catId });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const row = document.getElementById(`list-row-${arxivId}`);
        if (row) row.remove();
    } catch (err) {
        alert('Failed to remove paper: ' + err);
    }
}

// ============================================================================
// CSRF HELPERS
// ============================================================================

/**
 * Get the CSRF token from the meta tag injected by Flask-WTF.
 * @returns {string}
 */
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

/**
 * POST helper that automatically includes the CSRF token.
 * @param {string} url
 * @param {FormData|object} data - FormData instance or plain object
 * @returns {Promise<Response>}
 */
function csrfFetch(url, data) {
    let body;
    if (data instanceof FormData) {
        data.append('csrf_token', getCsrfToken());
        body = data;
    } else {
        const fd = new FormData();
        fd.append('csrf_token', getCsrfToken());
        for (const [k, v] of Object.entries(data || {})) fd.append(k, v);
        body = fd;
    }
    return fetch(url, { method: 'POST', body });
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize all UI features on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    initDarkMode();
    initAbstractPersistence();
    initKeyboardShortcuts();

    // Inject CSRF token into all POST forms automatically
    const token = getCsrfToken();
    if (token) {
        document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(form => {
            if (!form.querySelector('input[name="csrf_token"]')) {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrf_token';
                input.value = token;
                form.appendChild(input);
            }
        });
    }
});
