// Synthetic, loopback-only browser fixture. Never connects to Proxmox or real data.
// Run: node tests/control_ui_fixture.mjs; open http://127.0.0.1:8765.
// Login: any synthetic identity/password; TOTP: 123456. Ctrl+C stops the server.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const now = () => new Date().toISOString();
let authenticated = false, nextOperation = 1, fault = '', completed = false, mutationDelay = 0;
const requests = [], operations = new Map();
const vm = { vmid: 901, node: 'lab-fixture', name: 'mediaserver-fixture', project: 'media', pool: 'media', tags: ['fixture'], status: 'stopped', cores: 2, memoryMiB: 2048, memoryUsedMiB: 1800, cpu: .12, diskGiB: 24, digest: 'fixture-digest', pending: [], dependencies: [], capabilities: { resources: true, start: true, shutdown: true, reboot: true, stop: true, delete: true, acl: true }, collectedAt: now() };
const session = () => ({ authenticated: true, user: 'operador@pve', csrfToken: 'synthetic-csrf-only' });
const reply = (res, status, value) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(value === undefined ? undefined : JSON.stringify(value)); };
const error = (res, status, message) => reply(res, status, { error: { code: 'fixture', message, requestId: 'synthetic-request' } });
const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname === '/__fixture' && req.method === 'POST') {
      let raw = ''; for await (const chunk of req) raw += chunk;
      const control = JSON.parse(raw || '{}');
      fault = control.fault || ''; completed = control.completed === true;
      mutationDelay = Math.min(2000, Math.max(0, Number(control.mutationDelay) || 0));
      if (['running', 'stopped'].includes(control.vmStatus)) vm.status = control.vmStatus;
      if (control.reset) { authenticated = false; operations.clear(); requests.length = 0; }
      return reply(res, 200, { ok: true });
    }
    if (url.pathname === '/__fixture') return reply(res, 200, { requests, operations: [...operations.values()] });
    if (url.pathname === '/__browser-test.js') { res.writeHead(200, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' }); return res.end(await readFile(new URL('./control_ui_browser.mjs', import.meta.url))); }
    if (!url.pathname.startsWith('/api/v1/')) {
      const files = { '/': ['index.html', 'text/html'], '/static/app.js': ['app.js', 'text/javascript'], '/static/style.css': ['style.css', 'text/css'] };
      const file = files[url.pathname]; if (!file) return reply(res, 404, {});
      const body = await readFile(new URL(`../services/control/static/${file[0]}`, import.meta.url));
      res.writeHead(200, { 'Content-Type': `${file[1]}; charset=utf-8`, 'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'", 'Cache-Control': 'no-store' }); return res.end(body);
    }
    const path = url.pathname.slice('/api/v1'.length);
    let raw = ''; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    // Do not record even synthetic password or second-factor values.
    if (!path.startsWith('/session')) requests.push({ method: req.method, path, body, key: req.headers['idempotency-key'], csrf: !!req.headers['x-csrf-token'] });
    if (path === '/session' && req.method === 'GET') return reply(res, 200, authenticated ? session() : { authenticated: false });
    if (path === '/session' && req.method === 'POST') return reply(res, 200, { challenge: { kind: 'totp', id: 'fixture-challenge', expiresAt: new Date(Date.now() + 300000).toISOString() } });
    if (path === '/session/tfa' && req.method === 'POST') { if (!['123456','12345678'].includes(body.code)) return error(res, 403, 'Código sintético incorreto.'); authenticated = true; return reply(res, 200, session()); }
    if (!authenticated) return error(res, 401, 'Sessão necessária.');
    if (path === '/session' && req.method === 'DELETE') { authenticated = false; return reply(res, 204); }
    if (fault === 'unavailable' && path === '/overview') return error(res, 503, 'Coleta sintética indisponível.');
    if (path === '/overview') return reply(res, 200, { collectedAt: now(), sourceState: 'fresh', nodes: [{ name: 'lab-fixture', status: 'online', cpu: .17, memoryMiB: 5324, maxMemoryMiB: 15862 }], capacity: { totalMemoryMiB: 15862, usedMemoryMiB: 5324, allocatedMemoryMiB: 11264, freeStorageGiB: 125.7 }, alerts: [{ level: 'warning', message: 'Fixture: restauração de aplicações ainda pendente.' }, { level: 'info', message: 'Fixture: inventário limitado à identidade autenticada.' }], consoleLinks: [{ label: 'Proxmox', url: 'https://console.example.test' }, { label: 'Grafana', url: 'https://metrics.example.test' }] });
    if (path === '/profiles') return reply(res, 200, { collectedAt: now(), items: [{ id: 'small', label: 'Linux · pequeno', readiness: 'hardware-only', limits: { minCores: 1, maxCores: 4, minMemoryMiB: 512, maxMemoryMiB: 4096, minDiskGiB: 8, maxDiskGiB: 32 }, projects: ['sandbox', 'media'] }] });
    if (path === '/vms' && req.method === 'GET') return reply(res, 200, { sourceState: 'fresh', collectedAt: now(), items: [vm] });
    if (path === '/vms/901' && req.method === 'GET') return reply(res, 200, vm);
    if (path === '/storage') {
      if (fault === 'storage-unavailable') return error(res, 503, 'Origem de discos indisponível.');
      return reply(res, 200, { collectedAt: now(), sourceState: fault === 'storage-partial' ? 'partial' : 'fresh', sources: [{ scope: 'pve', node: 'lab-fixture', state: 'fresh', collectedAt: now(), reason: null }, { scope: 'core', node: 'lab-fixture', state: fault === 'storage-partial' ? 'unknown' : 'fresh', collectedAt: fault === 'storage-partial' ? null : now() }], disks: [
        { id: 'pve:fixture:sda', scope: 'pve', node: 'lab-fixture', owner: 'host', device: 'sda', model: 'SSD de sistema · fixture', kind: 'ssd', capacityBytes: 512000000000, health: 'unknown', readOnly: null, mounted: true, mounts: [], partitions: [{ device: 'sda1', capacityBytes: 511000000000, filesystem: 'LVM', mounted: true }] },
        { id: 'core:fixture:sdb', scope: 'core', node: 'lab-fixture', owner: 'vm-901', device: 'sdb', model: 'HD do acervo · fixture', kind: 'hdd', capacityBytes: 18000000000000, health: 'passed', readOnly: false, mounted: true, partitions: [], mounts: [{ device: 'sdb1', path: '/srv/media-fixture', filesystem: 'ext4', readOnly: false, sizeBytes: 17000000000000, usedBytes: 6000000000000, availableBytes: 10000000000000 }] },
      ] });
    }
    if (path === '/vms/901/services' && req.method === 'GET') {
      if (fault === 'services-unavailable') return error(res, 503, 'Serviços indisponíveis na fixture.');
      if (vm.status === 'stopped') return reply(res, 200, { collectedAt: now(), sourceState: 'stopped', items: [], memory: {} });
      return reply(res, 200, { collectedAt: now(), sourceState: fault === 'services-stale' ? 'stale' : 'fresh', memory: { totalBytes: 2147483648, availableBytes: 1073741824 }, items: [
        { id: 'radarr', label: 'Radarr', url: 'https://radarr.example.test/radarr/', project: 'media-fixture', state: 'running', health: 'healthy', image: 'fixture:local', memoryBytes: 268435456, revision: 'fixture-runtime-revision', actions: ['stop', 'restart'], reason: null },
        { id: 'control', label: 'Controle protegido', url: 'javascript:alert(1)', project: 'control-fixture', state: 'created', health: 'none', image: 'fixture:local', memoryBytes: 0, revision: 'fixture-control-revision', actions: [], reason: 'Protegido contra interrupção do próprio controle.' },
      ] });
    }
    if (path === '/vms/901/acl' && req.method === 'GET') return reply(res, 200, { items: [{ principalType: 'group', principal: 'operators', role: 'PVEVMAdmin', propagate: true, inherited: true, origin: '/pool/media' }, { principalType: 'user', principal: 'viewer@pve', role: 'PVEAuditor', propagate: false, inherited: false, origin: '/vms/901' }, { principalType: 'token', principal: 'collector@pve!metrics', role: 'PVEAuditor', propagate: false, inherited: false, origin: '/vms/901' }], completeness: 'partial', digest: 'acl-fixture', users: [{ id: 'viewer@pve', label: 'viewer@pve' }], groups: [{ id: 'operators', label: 'Operators' }], roles: [{ id: 'PVEAuditor', label: 'PVEAuditor' }] });
    if (path === '/vms/901/deletion-preview') return reply(res, 200, { intentId: 'preview-fixture', expiresAt: new Date(Date.now() + 300000).toISOString(), name: vm.name, digest: vm.digest, allowed: true, impact: ['VM desligada de fixture', 'Disco virtual de 24 GiB'], blockers: [] });
    if (path.startsWith('/operations/')) { const op = operations.get(path.split('/').at(-1)); return op ? reply(res, 200, { ...op, state: completed ? 'succeeded' : 'running', updatedAt: now() }) : error(res, 403, 'Operação não autorizada.'); }
    if (path === '/audit') return reply(res, 200, { items: [...operations.values()].map(op => ({ id: `event-${op.operationId}`, createdAt: op.createdAt, actor: 'operador@pve', action: op.action, target: op.target, outcome: op.state, operationId: op.operationId })), nextCursor: null });
    if (req.method !== 'GET') {
      if (req.headers['x-csrf-token'] !== 'synthetic-csrf-only') return error(res, 403, 'CSRF ausente.');
      if (fault === 'denied') return error(res, 403, 'Sua permissão foi revogada.');
      if (fault === 'conflict') return error(res, 409, 'A configuração mudou. Releia os dados.');
      const prior = [...operations.values()].find(op => op.key === req.headers['idempotency-key']);
      const op = prior || { operationId: `fixture-${nextOperation++}`, state: 'accepted', action: path.endsWith('/actions') ? body.action : 'resources', target: 'VM 901', createdAt: now(), updatedAt: now(), key: req.headers['idempotency-key'] };
      operations.set(op.operationId, op);
      if (mutationDelay) await new Promise(resolve => setTimeout(resolve, mutationDelay));
      if (fault === 'ambiguous') return error(res, 503, 'A origem não confirmou a resposta.');
      const { key, ...dto } = op; return reply(res, 202, dto);
    }
    return reply(res, 404, {});
  } catch { return error(res, 500, 'Falha da fixture.'); }
});
server.listen(8765, '127.0.0.1', () => console.log('Synthetic control UI fixture: http://127.0.0.1:8765'));
