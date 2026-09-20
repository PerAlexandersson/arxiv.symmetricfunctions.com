const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../src/static/admin-dois.js'), 'utf8');

// Minimal DOM fixture: execute the production script, including its initial
// setup and delegated click/change handlers. No network or database access.
function fixture(saved = '0', initialConflicts = 2) {
  const handlers = {};
  const storage = new Map(saved === null ? [] : [['admin-dois-show-conflicts', saved]]);
  let rows = Array.from({length: initialConflicts}, () => ({hidden: false}));
  const toggleHandlers = {};
  const toggle = {
    checked: true,
    addEventListener: (name, fn) => { toggleHandlers[name] = fn; },
    dispatchEvent: event => toggleHandlers[event.type]?.(event),
  };
  const elements = {
    'doi-tabs': {dataset: {currentTab: 'pending', currentPage: '1'}},
    'doi-show-conflicts': toggle,
    'doi-hidden-notice': {hidden: true},
    'doi-hidden-message': {textContent: ''},
    'tab-pending': {textContent: 'Pending (2)'},
    'tab-approved': {}, 'tab-rejected': {}, 'tab-all': {},
    'doi-tbody': {
      set innerHTML(value) {
        rows = [...value.matchAll(/<tr id="row-\d+" class="doi-row--conflict"/g)]
          .map(() => ({hidden: false}));
      },
    },
  };
  const context = vm.createContext({
    document: {
      getElementById: id => elements[id],
      querySelectorAll: selector => {
        assert.equal(selector, '#doi-tbody tr.doi-row--conflict');
        return rows;
      },
      addEventListener: (name, fn) => { handlers[name] = fn; },
      createElement: () => ({textContent: '', get innerHTML() { return this.textContent; }}),
    },
    localStorage: {getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value)},
    Event: class { constructor(type) { this.type = type; } },
  });
  vm.runInContext(source, context);
  return {elements, toggle, storage, rows: () => rows, context,
    reveal: () => handlers.click({target: {
      closest: selector => selector === '[data-doi-show-hidden]' ? {} : null,
    }}),
  };
}

test('saved hide preference explains two real pending entries without changing totals', () => {
  const f = fixture();
  assert.ok(f.rows().every(row => row.hidden));
  assert.equal(f.elements['doi-hidden-notice'].hidden, false);
  assert.match(f.elements['doi-hidden-message'].textContent, /^2 entries on this page are hidden/);
  assert.match(f.elements['doi-hidden-message'].textContent, /counts include hidden entries/);
  assert.equal(f.elements['tab-pending'].textContent, 'Pending (2)');
});

test('reveal button checks the filter, persists it and reveals rows without reviewing them', () => {
  const f = fixture();
  f.reveal();
  assert.equal(f.toggle.checked, true);
  assert.equal(f.storage.get('admin-dois-show-conflicts'), '1');
  assert.ok(f.rows().every(row => !row.hidden));
  assert.equal(f.elements['doi-hidden-notice'].hidden, true);
  assert.equal(f.elements['doi-hidden-message'].textContent, '');
  assert.equal(f.elements['tab-pending'].textContent, 'Pending (2)');
});

test('fresh browsers and saved show preference do not show a misleading notice', () => {
  for (const preference of [null, '1']) {
    const f = fixture(preference);
    assert.equal(f.elements['doi-hidden-notice'].hidden, true);
    assert.ok(f.rows().every(row => !row.hidden));
  }
});

test('checkbox changes update singular notice and persistence', () => {
  const f = fixture('1', 1);
  f.toggle.checked = false;
  f.toggle.dispatchEvent({type: 'change'});
  assert.match(f.elements['doi-hidden-message'].textContent, /^1 entry on this page is hidden/);
  assert.equal(f.storage.get('admin-dois-show-conflicts'), '0');
});

test('AJAX empty-page rendering clears the old notice', () => {
  const f = fixture();
  vm.runInContext('renderRows([])', f.context);
  assert.equal(f.elements['doi-hidden-notice'].hidden, true);
  assert.equal(f.elements['doi-hidden-message'].textContent, '');
});

test('AJAX mixed-page rendering counts only hidden rows on this page', () => {
  const f = fixture();
  f.context.candidates = [
    {id: 1, status: 'pending', confidence: 0.7, doi: 'test/1',
      doi_conflicts: [{arxiv_id: 'test', title: 'Other paper'}]},
    {id: 2, status: 'pending', confidence: 0.6, doi: 'test/2'},
  ];
  vm.runInContext('renderRows(candidates)', f.context);
  assert.equal(f.rows().length, 1);
  assert.equal(f.rows()[0].hidden, true);
  assert.match(f.elements['doi-hidden-message'].textContent, /^1 entry on this page is hidden/);
});
