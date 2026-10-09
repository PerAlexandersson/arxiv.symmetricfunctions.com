const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../src/static/utils.js'), 'utf8');
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: {'Content-Type': 'application/json'},
});
const expired = () => json({code: 'csrf_failed', csrf_token: 'fresh', error: 'Reload the page'}, 400);
function fixture(responses) {
  let token = 'old';
  const inputs = [{value: 'old'}];
  const calls = [];
  const context = vm.createContext({
    FormData, Headers, URL, console,
    window: {location: {origin: 'https://example.test'}},
    document: {
      addEventListener() {},
      querySelector: () => ({getAttribute: () => token, setAttribute: (_, value) => {token = value;}}),
      querySelectorAll: () => inputs,
    },
    fetch: async (url, options) => {
      calls.push({url, data: Object.fromEntries(options.body)});
      const response = responses.shift();
      if (response instanceof Error) throw response;
      assert.ok(response, 'Unexpected extra request');
      return response;
    },
  });
  vm.runInContext(source, context);
  return {context, calls, inputs, token: () => token};
}

test('expired token refreshes and saves once, preserving bookmark fields', async () => {
  for (const asForm of [false, true]) {
    const f = fixture([expired(), json({saved: true})]);
    let data = {arxiv_id: '2401.00001', category_id: '4'};
    if (asForm) {
      const form = new FormData();
      Object.entries(data).forEach(([k,v]) => form.append(k,v));
      form.append('csrf_token', 'old-form-token');
      data = form;
    }
    assert.equal((await f.context.csrfJsonFetch('/api/lists/save', data)).saved, true);
    assert.equal(f.calls.length, 2);
    assert.equal(f.calls[0].data.csrf_token, 'old');
    assert.deepEqual(f.calls[1], {url: '/api/lists/save', data: {
      arxiv_id: '2401.00001', category_id: '4', csrf_token: 'fresh',
    }});
    assert.equal(f.token(), 'fresh');
    assert.equal(f.inputs[0].value, 'fresh');
  }
});

test('a second CSRF failure stops rather than looping', async () => {
  const f = fixture([expired(), expired()]);
  await assert.rejects(f.context.csrfJsonFetch('/api/lists/save', {}), /Reload the page/);
  assert.equal(f.calls.length, 2);
});

test('network, validation and server errors never trigger another write', async () => {
  for (const response of [new Error('offline'), json({error: 'Invalid list'}, 400),
    new Response('<h1>Error</h1>', {status: 500, headers: {'Content-Type': 'text/html'}})]) {
    const f = fixture([response]);
    await assert.rejects(f.context.csrfJsonFetch('/api/lists/save', {}));
    assert.equal(f.calls.length, 1);
  }
});

test('expired login redirects without retrying the bookmark', async () => {
  const f = fixture([new Response('Login', {status: 401})]);
  await assert.rejects(f.context.csrfJsonFetch('/api/lists/save', {}), /AUTH_REQUIRED/);
  assert.equal(f.context.window.location.href, '/login');
  assert.equal(f.calls.length, 1);
});
