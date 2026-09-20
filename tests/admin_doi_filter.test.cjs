const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../src/static/admin-dois.js'), 'utf8');

// Execute the production script against a small DOM fixture. Saved preferences
// from the removed filter must not affect initial or AJAX-rendered candidates.
function fixture(saved = '0') {
  let rows = [{hidden: false}, {hidden: false}];
  let html = '';
  let storageReads = 0;
  const elements = {
    'doi-tabs': {dataset: {currentTab: 'pending', currentPage: '1'}},
    'tab-pending': {textContent: 'Pending (2)'},
    'tab-approved': {}, 'tab-rejected': {}, 'tab-all': {},
    'doi-pagination': {},
    'doi-tbody': {
      get innerHTML() { return html; },
      set innerHTML(value) {
        html = value;
        rows = [...value.matchAll(/<tr id="row-(\d+)"([^>]*)>/g)]
          .map(match => ({id: Number(match[1]), hidden: /\bhidden\b/.test(match[2])}));
      },
    },
  };
  const context = vm.createContext({
    document: {
      getElementById: id => elements[id],
      querySelectorAll: selector => {
        if (selector === '#doi-tabs a') return [];
        assert.equal(selector, '#doi-tbody tr.doi-row--conflict');
        return rows;
      },
      addEventListener: () => {},
      createElement: () => ({textContent: '', get innerHTML() { return this.textContent; }}),
    },
    localStorage: {
      getItem: key => {
        storageReads++;
        assert.equal(key, 'admin-dois-show-conflicts');
        return saved;
      },
      setItem: () => { throw new Error('Visibility must not depend on storage'); },
    },
    history: {replaceState: () => {}},
    console: {error: (...args) => { throw new Error(args.join(' ')); }},
  });
  vm.runInContext(source, context);
  return {elements, rows: () => rows, storageReads: () => storageReads, context};
}

function candidate(id, conflict = true) {
  return {id, status: 'pending', confidence: 0.7, doi: 'test/' + id,
    doi_conflicts: conflict ? [{arxiv_id: 'other', title: 'Other paper'}] : []};
}

test('initial rows stay visible regardless of the old saved hide preference', () => {
  for (const preference of ['0', '1', null]) {
    const f = fixture(preference);
    assert.equal(f.rows().length, 2);
    assert.ok(f.rows().every(row => !row.hidden));
    assert.equal(f.elements['tab-pending'].textContent, 'Pending (2)');
    assert.equal(f.storageReads(), 0);
  }
});

test('two conflicting pending candidates render visibly with warnings and review actions', () => {
  const f = fixture();
  f.context.candidates = [candidate(1), candidate(2)];
  vm.runInContext('renderRows(candidates)', f.context);
  assert.deepEqual(f.rows().map(row => row.id), [1, 2]);
  assert.ok(f.rows().every(row => !row.hidden));
  const html = f.elements['doi-tbody'].innerHTML;
  assert.equal((html.match(/DOI already assigned to another paper/g) || []).length, 2);
  for (const action of ['approve', 'reassign', 'reject']) {
    assert.equal((html.match(new RegExp('data-doi-action="' + action + '"', 'g')) || []).length, 2);
  }
});

test('mixed results show every candidate and only warn about actual conflicts', () => {
  const f = fixture();
  f.context.candidates = [candidate(1), candidate(2, false)];
  vm.runInContext('renderRows(candidates)', f.context);
  assert.equal(f.rows().length, 2);
  assert.ok(f.rows().every(row => !row.hidden));
  assert.equal((f.elements['doi-tbody'].innerHTML.match(/DOI already assigned/g) || []).length, 1);
});

test('an actually empty result shows the empty-state message', () => {
  const f = fixture();
  vm.runInContext('renderRows([])', f.context);
  assert.equal(f.rows().length, 0);
  assert.match(f.elements['doi-tbody'].innerHTML, /No candidates in this view/);
});

test('AJAX tab refresh keeps counts and visible candidates consistent', async () => {
  const f = fixture();
  f.context.fetchJson = async () => ({ok: true,
    counts: {pending: 2, approved: 3, rejected: 1},
    candidates: [candidate(1), candidate(2)], page: 1, total_pages: 1});
  await vm.runInContext("loadTab('pending', 1)", f.context);
  assert.equal(f.elements['tab-pending'].textContent, 'Pending (2)');
  assert.equal(f.elements['tab-all'].textContent, 'All (6)');
  assert.equal(f.rows().filter(row => !row.hidden).length, 2);
  assert.equal(f.storageReads(), 0);
});

test('removed filter cannot silently hide rows or depend on browser storage', () => {
  assert.doesNotMatch(source, /localStorage|doi-show-conflicts|doi-hidden-notice|row\.hidden/);
  const f = fixture();
  Object.defineProperty(f.context, 'localStorage', {
    get() { throw new Error('Storage unavailable'); },
  });
  f.context.candidates = [candidate(1)];
  vm.runInContext('renderRows(candidates)', f.context);
  assert.equal(f.rows()[0].hidden, false);
});
