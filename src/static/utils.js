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

/**
 * Copy textContent from an element.
 * @param {string} elementId - Element whose textContent should be copied
 * @param {string} [successMessage='Copied to clipboard!'] - Message shown on success
 */
async function copyElementText(elementId, successMessage = 'Copied to clipboard!') {
    const el = document.getElementById(elementId);
    if (!el) {
        alert('Nothing to copy.');
        return;
    }
    const text = el.textContent || '';
    try {
        await copyToClipboard(text);
        alert(successMessage);
    } catch (err) {
        alert('Failed to copy: ' + err);
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
    const target = document.getElementById(elementId);
    if (!target) return;
    try {
        const response = await fetch(`${apiPath}${arxivId}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const bibtex = await response.text();
        target.textContent = bibtex;
    } catch (error) {
        target.textContent = 'Error loading BibTeX';
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

let activeDialog = null;
let dialogReturnFocus = null;

function focusableElements(container) {
    return Array.from(container.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), ' +
        'input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(el => el.offsetParent !== null || el === document.activeElement);
}

function openDialogElement(dialog, display = 'block') {
    if (!dialog) return;
    dialogReturnFocus = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    activeDialog = dialog;
    dialog.hidden = false;
    dialog.style.display = display;
    dialog.setAttribute('aria-modal', 'true');
    if (!dialog.hasAttribute('role')) dialog.setAttribute('role', 'dialog');
    if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
}

function focusDialog(dialog, preferredSelector) {
    const preferred = preferredSelector ? dialog.querySelector(preferredSelector) : null;
    const focusables = focusableElements(dialog);
    const target = preferred || focusables[0] || dialog;
    target.focus({ preventScroll: true });
}

function closeDialogElement(dialog) {
    if (!dialog) return;
    const wasActive = activeDialog === dialog;
    dialog.style.display = 'none';
    dialog.hidden = true;
    if (wasActive) activeDialog = null;
    if (wasActive && dialogReturnFocus && document.contains(dialogReturnFocus)) {
        dialogReturnFocus.focus({ preventScroll: true });
        dialogReturnFocus = null;
    }
}

function trapDialogFocus(event) {
    if (event.key !== 'Tab' || !activeDialog) return;
    const focusables = focusableElements(activeDialog);
    if (!focusables.length) {
        event.preventDefault();
        activeDialog.focus({ preventScroll: true });
        return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
    }
}

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

    if (!modal || !titleEl || !textarea || !status) {
        return fetchAndCopy(url, 'BibTeX copied to clipboard!', 'Failed to load BibTeX');
    }

    titleEl.textContent  = title ? `BibTeX \u2014 ${title}` : 'BibTeX';
    textarea.value       = 'Loading\u2026';
    status.textContent   = '';
    openDialogElement(modal, 'flex');
    document.body.classList.add('modal-open');
    focusDialog(modal, '#bib-modal-text');

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
        closeDialogElement(modal);
        document.body.classList.remove('modal-open');
    }
}

async function copyBibtexModal() {
    const textarea = document.getElementById('bib-modal-text');
    const status   = document.getElementById('bib-modal-status');
    if (!textarea || !status) return;
    try {
        await copyToClipboard(textarea.value);
        status.textContent = 'Copied!';
        setTimeout(() => { status.textContent = ''; }, 2000);
    } catch (err) {
        status.textContent = 'Copy failed';
    }
}

// ============================================================================
// ADMIN HELP POPUPS
// ============================================================================

/**
 * Show an admin help popup. Pages with one popup can use the default ID.
 * @param {string} [id='help-popup'] - Popup element ID
 */
function openHelp(id = 'help-popup') {
    closeHelp();
    const overlay = document.getElementById('help-overlay');
    const popup = document.getElementById(id);
    if (overlay) overlay.style.display = 'block';
    if (popup) {
        openDialogElement(popup, 'block');
        focusDialog(popup, '.help-close-btn');
    }
}

function closeHelp() {
    const overlay = document.getElementById('help-overlay');
    if (overlay) overlay.style.display = 'none';
    document.querySelectorAll('.help-popup').forEach(popup => {
        closeDialogElement(popup);
    });
}

// Close modals/popups on backdrop click or Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeBibtexModal();
        closeHelp();
    }
    trapDialogFocus(e);
});
document.addEventListener('click', (e) => {
    const modal = document.getElementById('bibtex-modal');
    if (modal && e.target === modal) closeBibtexModal();
});

// ============================================================================
// DECLARATIVE ACTION HANDLERS
// ============================================================================

function initDelegatedActions() {
    document.addEventListener('click', (event) => {
        const el = event.target.closest('[data-action]');
        if (!el) return;

        const action = el.dataset.action;
        const arxivId = el.dataset.arxivId;

        if ([
            'copy-share-link',
            'copy-bibtex',
            'copy-doi-bibtex',
            'show-bibtex-modal',
            'copy-author-bibtex',
            'show-tab',
            'copy-element-text',
        ].includes(action)) {
            event.preventDefault();
        }

        switch (action) {
            case 'toggle-dark-mode':
                toggleDarkMode();
                break;
            case 'toggle-compact-papers':
                toggleCompactPapers();
                break;
            case 'close-bibtex-modal':
                closeBibtexModal();
                break;
            case 'copy-bibtex-modal':
                copyBibtexModal();
                break;
            case 'open-help':
                openHelp(el.dataset.helpId || 'help-popup');
                break;
            case 'close-help':
                closeHelp();
                break;
            case 'copy-share-link':
                copyShareLink(arxivId);
                break;
            case 'copy-bibtex':
                copyBibtex(arxivId);
                break;
            case 'copy-doi-bibtex':
                copyDoiBibtex(arxivId);
                break;
            case 'show-bibtex-modal':
                showBibtexModal(el.dataset.bibtexUrl, el.dataset.bibtexTitle || '');
                break;
            case 'copy-author-bibtex':
                copyAuthorBibtex(el.dataset.authorSlug, el.dataset.authorName || el.dataset.authorSlug);
                break;
            case 'toggle-watch':
                toggleWatch(el.dataset.watchKind, Number(el.dataset.watchId), el);
                break;
            case 'toggle-star':
                toggleStar(el, arxivId);
                break;
            case 'remove-paper-from-list':
                removePaperFromList(el, arxivId, Number(el.dataset.listCatId));
                break;
            case 'show-save-menu':
                showSaveMenu(el, arxivId);
                break;
            case 'refetch-paper':
                if (typeof refetchPaper === 'function') refetchPaper(arxivId);
                break;
            case 'show-tab':
                showTab(el.dataset.tabId);
                break;
            case 'copy-element-text':
                copyElementText(el.dataset.elementId);
                break;
            case 'skip-doi':
                if (typeof toggleSkipDoi === 'function') toggleSkipDoi(Number(el.dataset.paperId));
                break;
            case 'create-list':
                createListPrompt();
                break;
            case 'rename-list':
                renameListPrompt(Number(el.dataset.catId), el.dataset.listName || '');
                break;
            case 'delete-list':
                deleteListConfirm(Number(el.dataset.catId), el.dataset.listName || '');
                break;
            case 'unwatch':
                unwatch(el.dataset.watchKind, Number(el.dataset.watchId), el.dataset.pillId);
                break;
            default:
                break;
        }
    });

    document.addEventListener('change', (event) => {
        const el = event.target.closest('[data-action="browse-year"]');
        if (!el) return;
        window.location.href = `/browse?year=${encodeURIComponent(el.value)}`;
    });
}

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

function getStoredPreference(key) {
    try {
        return localStorage.getItem(key);
    } catch (err) {
        return null;
    }
}

function setStoredPreference(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (err) {}
}

/**
 * Toggle dark mode and persist preference
 */
function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark');
    setStoredPreference('dark-mode', isDark ? 'on' : 'off');
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
    const saved = getStoredPreference('dark-mode');
    if (saved === 'on') {
        document.documentElement.classList.add('dark');
    }
    updateDarkModeLabel();
}

// ============================================================================
// UI FEATURES - Compact Paper List
// ============================================================================

/**
 * Toggle compact paper list mode and persist preference.
 */
function toggleCompactPapers() {
    const isCompact = document.documentElement.classList.toggle('compact-papers');
    setStoredPreference('compact-paper-list', isCompact ? 'on' : 'off');
    updateCompactPaperLabel();
}

/**
 * Update compact-mode toggle state.
 */
function updateCompactPaperLabel() {
    const toggle = document.getElementById('compact-paper-toggle');
    if (!toggle) return;
    const isCompact = document.documentElement.classList.contains('compact-papers');
    toggle.setAttribute('aria-label', isCompact ? 'Use relaxed paper list' : 'Use compact paper list');
    toggle.setAttribute('title', isCompact ? 'Use relaxed paper list' : 'Use compact paper list');
    toggle.classList.toggle('nav-icon-active', isCompact);
}

/**
 * Initialize compact paper list mode from saved preference.
 */
function initCompactPapers() {
    if (getStoredPreference('compact-paper-list') === 'on') {
        document.documentElement.classList.add('compact-papers');
    }
    updateCompactPaperLabel();
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
        btn.classList.remove('active');
    });
    const tab = document.getElementById(tabId);
    if (tab) {
        tab.style.display = 'block';
    }
    const btn = document.getElementById(tabId + '-btn');
    if (btn) {
        btn.classList.add('active');
    }
}

/**
 * Toggle a submit button into or out of its running state.
 * @param {HTMLButtonElement|undefined|null} btn
 * @param {boolean} isRunning
 * @param {string} fallbackRunningLabel
 */
function setButtonRunning(btn, isRunning, fallbackRunningLabel = 'Running\u2026') {
    if (!btn) return;
    if (isRunning) {
        btn.dataset.originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = btn.dataset.runningLabel || fallbackRunningLabel;
        return;
    }
    btn.disabled = false;
    btn.textContent = btn.dataset.originalText || btn.textContent;
    delete btn.dataset.originalText;
}

/**
 * Show a result box and reset/apply ok/err state classes.
 * @param {HTMLElement|undefined|null} box
 * @param {'ok'|'err'|''} state
 */
function setResultBoxState(box, state = '') {
    if (!box) return;
    box.style.display = 'block';
    box.classList.remove('ok', 'err');
    if (state) box.classList.add(state);
}

/**
 * Toggle an author or keyword watch subscription.
 * @param {'author'|'keyword'} type
 * @param {number} id
 * @param {HTMLElement} btn
 */
async function toggleWatch(type, id, btn) {
    btn.disabled = true;
    try {
        const data = await csrfJsonFetch('/api/watch/' + type + '/' + id, {});
        if (data.watching) {
            btn.textContent = 'Watching';
            btn.classList.add('watching');
        } else {
            btn.textContent = 'Watch';
            btn.classList.remove('watching');
        }
    } catch (e) {
        if (e.message !== 'AUTH_REQUIRED') console.error('toggleWatch failed', e);
    } finally {
        btn.disabled = false;
    }
}

// ============================================================================
// MY LISTS — STAR / SAVE / REMOVE
// ============================================================================

function listDetailTitle(name) {
    return `${name} \u2014 My Lists \u2014 arXiv Combinatorics`;
}

function updateListNameInPage(catId, name) {
    const cardName = document.getElementById(`list-name-${catId}`);
    if (cardName) cardName.textContent = name;

    const pageTitle = document.getElementById('list-page-title');
    if (pageTitle) {
        pageTitle.textContent = name;
        document.title = listDetailTitle(name);
    }
}

function removeEmptyWatchGroup(container) {
    if (!container || container.querySelector('.watch-pill')) return;
    const title = container.previousElementSibling;
    if (title && title.classList.contains('watch-section-title')) title.remove();
    const section = container.closest('.watch-section');
    container.remove();
    if (section && !section.querySelector('.watch-pill')) section.remove();
}

/**
 * Remove a watched author or keyword from the current user's watch list.
 * @param {'author'|'keyword'} type
 * @param {number} id
 * @param {string} pillId
 */
async function unwatch(type, id, pillId) {
    try {
        const data = await csrfJsonFetch('/api/watch/' + type + '/' + id, {});
        if (!data.watching) {
            const el = document.getElementById(pillId);
            const container = el ? el.closest('.watch-pills') : null;
            if (el) el.remove();
            removeEmptyWatchGroup(container);
        }
    } catch (e) {
        if (e.message !== 'AUTH_REQUIRED') console.error('unwatch failed', e);
    }
}

async function createListPrompt() {
    const name = prompt('New list name:');
    if (!name || !name.trim()) return;
    try {
        const data = await csrfJsonFetch('/api/lists/categories/new', { name: name.trim() });
        if (data.error) {
            alert(data.error);
            return;
        }
        location.reload();
    } catch (e) {
        if (e.message !== 'AUTH_REQUIRED') alert('Failed to create list.');
    }
}

async function renameListPrompt(catId, currentName) {
    const name = prompt('Rename list:', currentName);
    if (!name || !name.trim() || name.trim() === currentName) return;
    try {
        const data = await csrfJsonFetch(`/api/lists/categories/${catId}/rename`, { name: name.trim() });
        if (data.error) {
            alert(data.error);
            return;
        }
        updateListNameInPage(catId, data.name || name.trim());
    } catch (e) {
        if (e.message !== 'AUTH_REQUIRED') alert('Failed to rename list.');
    }
}

async function deleteListConfirm(catId, name) {
    if (!confirm(`Delete list "${name}" and all its saved papers?`)) return;
    try {
        const data = await csrfJsonFetch(`/api/lists/categories/${catId}/delete`, {});
        if (data.error) {
            alert(data.error);
            return;
        }
        const card = document.getElementById(`list-card-${catId}`);
        if (card) {
            card.remove();
            return;
        }
        window.location.href = '/lists';
    } catch (e) {
        if (e.message !== 'AUTH_REQUIRED') alert('Failed to delete list.');
    }
}

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
        if (!data.has('csrf_token')) data.append('csrf_token', getCsrfToken());
        body = data;
    } else {
        const fd = new FormData();
        fd.append('csrf_token', getCsrfToken());
        for (const [k, v] of Object.entries(data || {})) fd.append(k, v);
        body = fd;
    }
    return fetch(url, {
        method: 'POST',
        body,
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });
}

/**
 * Parse a JSON response, redirecting to login if the session has expired.
 * @param {Response} response
 * @returns {Promise<object>}
 */
async function fetchResponseJson(response) {
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    const redirectedUrl = response.url ? new URL(response.url, window.location.origin) : null;
    const redirectedToLogin = redirectedUrl && /\/(?:admin\/)?login\/?$/.test(redirectedUrl.pathname);

    if ((response.status === 401 || response.status === 403) ||
        (response.redirected && redirectedToLogin && contentType.includes('text/html'))) {
        window.location.href = redirectedUrl ? redirectedUrl.toString() : '/login';
        throw new Error('AUTH_REQUIRED');
    }

    if (!contentType.includes('application/json')) {
        throw new Error(`Expected JSON response, got ${contentType || 'unknown content type'}`);
    }

    return response.json();
}

/**
 * GET/POST helper for JSON endpoints that may redirect to login.
 * @param {string} url
 * @param {RequestInit} options
 * @returns {Promise<object>}
 */
async function fetchJson(url, options) {
    const opts = { ...(options || {}) };
    const headers = new Headers(opts.headers || {});
    if (!headers.has('Accept')) headers.set('Accept', 'application/json');
    if (!headers.has('X-Requested-With')) headers.set('X-Requested-With', 'XMLHttpRequest');
    opts.headers = headers;
    const response = await fetch(url, opts);
    return fetchResponseJson(response);
}

/**
 * CSRF-protected POST helper that expects a JSON response.
 * @param {string} url
 * @param {FormData|object} data
 * @returns {Promise<object>}
 */
async function csrfJsonFetch(url, data) {
    const response = await csrfFetch(url, data);
    return fetchResponseJson(response);
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize all UI features on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    initDarkMode();
    initCompactPapers();
    initDelegatedActions();
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
