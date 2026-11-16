import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

let source = '';
try {
  source = await readFile(new URL('../services/control/static/app.js', import.meta.url), 'utf8');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
const ui = source ? await import('../services/control/static/app.js') : {};
const html = await readFile(new URL('../services/control/static/index.html', import.meta.url), 'utf8');

test('authentication cannot submit credentials in a URL before JavaScript initializes', () => {
  const forms = [...html.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/g)];
  assert.equal(forms.length, 2);
  for (const [, attributes, content] of forms) {
    assert.match(attributes, /\bmethod="post"/);
    assert.match(content, /<button\b[^>]*\btype="submit"[^>]*\bdisabled\b/);
  }
  assert.match(html, /<noscript>[\s\S]*JavaScript/);
});

test('API client exists for the real same-origin interface', () => {
  assert.equal(typeof ui.createApi, 'function');
});

test('mutations send session CSRF and the supplied idempotency key, never credentials upstream', { skip: !source }, async () => {
  let sent;
  const api = ui.createApi({ fetcher: async (url, options) => {
    sent = { url, ...options };
    return new Response(JSON.stringify({ operationId: 'op-1', state: 'accepted' }), { status: 202 });
  }});
  api.setCsrf('session-csrf');
  const result = await api.request('/vms/101/resources', { method: 'PATCH', body: { cores: 2 }, key: 'same-intent-123456' });
  assert.equal(sent.url, '/api/v1/vms/101/resources');
  assert.equal(sent.credentials, 'same-origin');
  assert.equal(sent.headers['X-CSRF-Token'], 'session-csrf');
  assert.equal(sent.headers['Idempotency-Key'], 'same-intent-123456');
  assert.equal(sent.headers.Authorization, undefined);
  assert.equal(ui.operationTerminal(result.data.state), false);
});

test('upstream loss after submission is ambiguous and never retried automatically', { skip: !source }, async () => {
  let calls = 0;
  const api = ui.createApi({ fetcher: async () => { calls += 1; throw new TypeError('offline'); } });
  await assert.rejects(api.request('/vms', { method: 'POST', body: {}, key: 'same-intent-123456' }), error => error.uncertain === true);
  assert.equal(calls, 1);
});

test('403 and 409 remain concrete errors; 401 invalidates only the portal session', { skip: !source }, async () => {
  let expired = 0;
  const api = ui.createApi({ onUnauthorized: () => expired++, fetcher: async () => new Response(JSON.stringify({ error: { code: 'expired', message: 'Sessão encerrada', requestId: 'r-1' } }), { status: 401 }) });
  await assert.rejects(api.request('/vms'), error => error.status === 401 && error.requestId === 'r-1');
  assert.equal(expired, 1);
  for (const status of [403, 409]) {
    const failed = ui.createApi({ fetcher: async () => new Response(JSON.stringify({ error: { code: 'denied', message: 'Operação recusada' } }), { status }) });
    await assert.rejects(failed.request('/vms/101', { method: 'DELETE', body: {} }), error => error.status === status && !error.uncertain);
  }
});

test('only explicit successful or failed operations finish polling', { skip: !source }, () => {
  for (const value of ['accepted', 'submitted', 'running', 'reconciling', undefined, 'unknown']) assert.equal(ui.operationTerminal(value), false);
  assert.equal(ui.operationTerminal('succeeded'), true);
  assert.equal(ui.operationTerminal('failed'), true);
});

test('a non-JSON 401 still invalidates the session and is not an ambiguous mutation', { skip: !source }, async () => {
  let invalidated = false;
  const api = ui.createApi({ onUnauthorized: () => { invalidated = true; }, fetcher: async () => new Response('Unauthorized', { status: 401 }) });
  await assert.rejects(api.request('/vms/901/actions', { method: 'POST', body: { action: 'start' } }), error => error.status === 401 && !error.uncertain);
  assert.equal(invalidated, true);
});

test('destruction needs an allowed unexpired preview and the exact current name', { skip: !source }, () => {
  const preview = { allowed: true, name: 'mediaserver-test', expiresAt: '2030-01-01T00:00:00Z', intentId: 'i-1' };
  assert.equal(ui.canDelete(preview, 'mediaserver-test', 1000), true);
  assert.equal(ui.canDelete(preview, ' mediaserver-test', 1000), false);
  assert.equal(ui.canDelete({ ...preview, allowed: false }, preview.name, 1000), false);
  assert.equal(ui.canDelete(preview, preview.name, Date.parse('2031-01-01')), false);
});

test('console links cannot inject script, credentials, query tokens or non HTTPS protocols', { skip: !source }, () => {
  assert.equal(ui.safeConsoleUrl('https://console.example.test/#v1:0'), 'https://console.example.test/#v1:0');
  for (const url of ['javascript:alert(1)', 'http://console.example.test', 'https://user:secret@console.example.test', 'https://console.example.test/?ticket=secret']) assert.equal(ui.safeConsoleUrl(url), null);
});

test('ACL mutation is limited to explicit user or group entries', { skip: !source }, () => {
  assert.equal(typeof ui.canEditAclEntry, 'function');
  assert.equal(ui.canEditAclEntry({ principalType: 'user', inherited: false }), true);
  assert.equal(ui.canEditAclEntry({ principalType: 'group', inherited: false }), true);
  assert.equal(ui.canEditAclEntry({ principalType: 'group', inherited: true }), false);
  assert.equal(ui.canEditAclEntry({ principalType: 'token', inherited: false }), false);
  assert.equal(ui.canEditAclEntry({ principalType: 'unrecognized', inherited: false }), false);
});

test('memory overview distinguishes host accounting, active limits and guest residency', () => {
  const result = ui.memorySummary({ totalMemoryMiB: 16000, usedMemoryMiB: 12000 }, [
    { status: 'running', memoryMiB: 2048, memoryUsedMiB: 1800 },
    { status: 'stopped', memoryMiB: 4096, memoryUsedMiB: 0 },
  ]);
  assert.deepEqual(result, { remainingMiB: 4000, activeConfiguredMiB: 2048, residentMiB: 1800, activeCount: 1 });
  assert.equal(ui.memorySummary({}, [{ status: 'running', memoryMiB: 2048 }]).residentMiB, null);
  assert.equal(ui.memorySummary({}, []).remainingMiB, null);
  assert.equal(ui.memorySummary({}, []).activeConfiguredMiB, 0);
});

test('service controls require a fresh revision and the exact allowed action', () => {
  const service = { id: 'radarr', revision: 'fresh-revision', actions: ['stop', 'restart'] };
  assert.equal(ui.serviceActionAllowed(service, 'restart', 'fresh'), true);
  assert.equal(ui.serviceActionAllowed(service, 'start', 'fresh'), false);
  assert.equal(ui.serviceActionAllowed(service, 'restart', 'stale'), false);
  assert.equal(ui.serviceActionAllowed({ ...service, revision: null }, 'restart', 'fresh'), false);
  assert.equal(ui.serviceActionAllowed({ ...service, actions: [] }, 'stop', 'fresh'), false);
  assert.equal(ui.serviceActionAllowed({ ...service, actions: ['delete'] }, 'delete', 'fresh'), false);
});
