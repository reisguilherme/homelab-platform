const API = '/api/v1';
const labels = { running: 'Em execução', stopped: 'Desligada', paused: 'Pausada', accepted: 'Solicitação aceita', submitted: 'Enviada ao Proxmox', succeeded: 'Concluída', failed: 'Falhou', reconciling: 'Conferindo resultado', unknown: 'Desconhecido', healthy: 'Dados disponíveis', fresh: 'Dados atuais', live: 'Dados atuais', ok: 'Dados atuais', stale: 'Dados desatualizados', unavailable: 'Sem dados', online: 'Online', offline: 'Offline' };
const actions = { start: 'Iniciar', shutdown: 'Desligar com segurança', reboot: 'Reiniciar', stop: 'Forçar parada', create: 'Criar VM', resources: 'Alterar recursos', delete: 'Excluir VM', acl: 'Alterar acesso' };

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'network', requestId = '', uncertain = false } = {}) {
    super(message); Object.assign(this, { status, code, requestId, uncertain });
  }
}

export function createApi({ fetcher = globalThis.fetch.bind(globalThis), onUnauthorized = () => {}, timeoutMs = 15000 } = {}) {
  let csrf = '';
  return {
    setCsrf(value) { csrf = typeof value === 'string' ? value : ''; },
    async request(path, { method = 'GET', body, key } = {}) {
      if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) throw new ApiError('Destino de API inválido.');
      const mutation = method !== 'GET';
      const headers = { Accept: 'application/json' };
      if (body !== undefined) headers['Content-Type'] = 'application/json';
      if (mutation && csrf) headers['X-CSRF-Token'] = csrf;
      if (mutation && key) headers['Idempotency-Key'] = key;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetcher(API + path, { method, headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
        if (response.status === 401) { csrf = ''; onUnauthorized(); }
        let data = null;
        if (response.status !== 204) {
          try { data = await response.json(); }
          catch { throw new ApiError(response.status === 401 ? 'A sessão terminou. Entre novamente.' : 'A resposta não pôde ser confirmada. Consulte o estado antes de repetir.', { status: response.status, uncertain: mutation && (response.ok || response.status >= 500) }); }
        }
        if (!response.ok) {
          const fallback = { 401: 'A sessão terminou. Entre novamente.', 403: 'Sua identidade não tem acesso a esta ação.', 409: 'O estado mudou. Releia os dados antes de confirmar.', 422: 'Revise os campos informados.', 503: 'A origem está indisponível. O resultado ainda pode ser desconhecido.' };
          throw new ApiError(data?.error?.message || fallback[response.status] || 'A solicitação não foi concluída.', { status: response.status, code: data?.error?.code, requestId: data?.error?.requestId, uncertain: mutation && response.status >= 500 });
        }
        return { status: response.status, data };
      } catch (error) {
        if (error instanceof ApiError) throw error;
        throw new ApiError('Não foi possível confirmar a resposta. Verifique a conexão e o estado da operação.', { uncertain: mutation });
      } finally { clearTimeout(timer); }
    },
  };
}

export function operationTerminal(state) { return state === 'succeeded' || state === 'failed'; }
export function canEditAclEntry(entry) { return entry?.inherited === false && ['user', 'group'].includes(entry.principalType); }
export function canDelete(preview, confirmation, now = Date.now()) {
  return !!(preview?.allowed === true && preview.intentId && preview.name && confirmation === preview.name && Date.parse(preview.expiresAt) > now);
}
export function safeConsoleUrl(value) {
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password && !url.search ? url.href : null; }
  catch { return null; }
}

const finite = value => typeof value === 'number' && Number.isFinite(value);
const number = value => finite(value) ? new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 }).format(value) : '—';
const memory = value => finite(value) ? `${number(value / 1024)} GiB` : '—';
const date = value => value && Number.isFinite(Date.parse(value)) ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value)) : 'Sem leitura';
const list = value => Array.isArray(value) ? value : [];
const text = value => value == null ? '—' : String(value);
const allowed = (vm, capability) => vm?.capabilities?.[capability] === true;

function element(tag, properties = {}, ...children) {
  const node = document.createElement(tag);
  if (tag === 'form') node.method = 'post';
  for (const [key, value] of Object.entries(properties)) {
    if (key === 'className') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (['disabled', 'hidden', 'checked', 'required', 'readOnly'].includes(key)) node[key] = value;
    else if (value !== undefined && value !== null) node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}
const h = element;
const byId = id => document.getElementById(id);
const replace = (id, ...nodes) => byId(id).replaceChildren(...nodes);
const button = (label, handler, className = 'button quiet', disabled = false) => h('button', { type: 'button', className, text: label, onclick: handler, disabled });
const empty = (title, detail = '') => h('div', { className: 'empty-state' }, h('strong', { text: title }), detail);
const loading = () => h('div', { className: 'loading', role: 'status', text: 'Consultando a origem…' });
const badge = (state, custom) => h('span', { className: `badge ${['running', 'succeeded', 'online', 'healthy', 'fresh', 'live', 'ok'].includes(state) ? 'good' : ['failed', 'offline'].includes(state) ? 'bad' : ['reconciling', 'stale', 'unavailable', 'unknown'].includes(state) ? 'warn' : 'neutral'}`, text: custom || labels[state] || 'Desconhecido' });
const errorText = error => `${error.message}${error.requestId ? `\nReferência: ${error.requestId}` : ''}`;
const dataList = entries => entries.length ? h('ul', { className: 'plain-list' }, entries.map(value => h('li', { text: typeof value === 'string' ? value : value?.message || value?.label || 'Informação indisponível' }))) : h('p', { className: 'muted', text: 'Nenhum item informado.' });

function boot() {
  const state = { session: null, challenge: null, overview: null, vms: [], profiles: [], vm: null, view: 'overview', detailTab: 'summary', operations: new Map(), audit: [], cursor: null, sessionEpoch: 0 };
  let operationTimer = null, toastTimer = null, dialogBusy = false, polling = false, dialogGeneration = 0, detailGeneration = 0;
  const api = createApi({ onUnauthorized: () => showLogin('A sessão terminou. Entre novamente para continuar.') });

  function notice(message = '', kind = '') {
    const box = byId('global-notice'); box.textContent = message; box.hidden = !message; box.className = `notice ${kind}`;
  }
  function toast(message) { clearTimeout(toastTimer); byId('toast').textContent = message; byId('toast').hidden = false; toastTimer = setTimeout(() => { byId('toast').hidden = true; }, 6500); }
  function showLogin(message = '') {
    state.session = null; state.sessionEpoch++; state.challenge = null; api.setCsrf('');
    dialogGeneration++; detailGeneration++; dialogBusy = false;
    clearTimeout(operationTimer); state.operations.clear(); state.audit = []; state.vms = []; state.vm = null; state.overview = null; state.profiles = [];
    if (byId('action-dialog').open) byId('action-dialog').close();
    byId('workspace').hidden = true; byId('login-screen').hidden = false;
    byId('login-form').hidden = false; byId('totp-form').hidden = true;
    byId('password').value = ''; byId('totp').value = ''; byId('login-error').textContent = message; byId('login-error').hidden = !message;
    byId('toast').hidden = true; byId('username').focus();
  }
  async function signedIn(payload) {
    if (payload?.challenge) {
      if (payload.challenge.kind !== 'totp') throw new ApiError('Este segundo fator exige o console nativo do Proxmox.');
      state.challenge = payload.challenge; byId('password').value = ''; byId('login-form').hidden = true; byId('totp-form').hidden = false; byId('totp').focus(); return;
    }
    if (payload?.authenticated !== true || !payload.csrfToken) throw new ApiError('O servidor não confirmou uma sessão completa.');
    state.session = payload; state.challenge = null; state.sessionEpoch++; api.setCsrf(payload.csrfToken);
    byId('password').value = ''; byId('totp').value = ''; byId('login-screen').hidden = true; byId('workspace').hidden = false;
    byId('session-user').textContent = typeof payload.user === 'string' ? payload.user : payload.user?.username || payload.user?.name || 'Operador';
    navigate('overview'); byId('main').focus(); await refresh();
  }
  async function authentication(form, path, body) {
    const submit = form.querySelector('button[type=submit]'); submit.disabled = true; byId('login-error').hidden = true;
    try { await signedIn((await api.request(path, { method: 'POST', body })).data); }
    catch (error) { byId('login-error').textContent = errorText(error); byId('login-error').hidden = false; }
    finally { submit.disabled = false; byId('password').value = ''; byId('totp').value = ''; }
  }
  byId('login-form').addEventListener('submit', event => { event.preventDefault(); authentication(event.currentTarget, '/session', { username: byId('username').value.trim(), password: byId('password').value }); });
  byId('totp-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!state.challenge || Date.parse(state.challenge.expiresAt) <= Date.now()) { showLogin('O desafio expirou. Entre novamente.'); return; }
    authentication(event.currentTarget, '/session/tfa', { challengeId: state.challenge.id, code: byId('totp').value.trim() });
  });
  byId('back-login').addEventListener('click', () => showLogin());
  byId('logout').addEventListener('click', async () => {
    byId('logout').disabled = true;
    try { await api.request('/session', { method: 'DELETE' }); showLogin(); }
    catch (error) { notice('Não foi possível confirmar o encerramento da sessão. Tente novamente.\n' + errorText(error), 'error'); }
    finally { byId('logout').disabled = false; }
  });

  function navigate(view) {
    state.view = view; notice();
    for (const node of document.querySelectorAll('.page-view')) node.hidden = node.id !== `view-${view}`;
    for (const node of document.querySelectorAll('[data-view]')) { const active = node.dataset.view === (view === 'detail' ? 'vms' : view); node.classList.toggle('active', active); if (active) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current'); }
    byId('breadcrumb-current').textContent = { overview: 'Visão geral', vms: 'Máquinas virtuais', detail: 'Detalhe da máquina', activity: 'Atividades' }[view];
    if (view === 'vms') renderVms();
    if (view === 'activity') { renderOperations(); loadAudit(); }
  }
  for (const node of document.querySelectorAll('[data-view]')) node.addEventListener('click', () => navigate(node.dataset.view));
  byId('back-vms').addEventListener('click', () => navigate('vms'));
  byId('vm-search').addEventListener('input', renderVms); byId('vm-filter').addEventListener('change', renderVms);
  byId('refresh').addEventListener('click', refresh);
  for (const node of document.querySelectorAll('[data-create]')) node.addEventListener('click', createVm);

  async function refresh() {
    if (!state.session) return;
    const epoch = state.sessionEpoch; byId('refresh').disabled = true;
    if (!state.overview) replace('overview-content', loading());
    const results = await Promise.allSettled([api.request('/overview'), api.request('/vms'), api.request('/profiles')]);
    if (!state.session || epoch !== state.sessionEpoch) { byId('refresh').disabled = false; return; }
    const errors = [];
    if (results[0].status === 'fulfilled') { state.overview = results[0].value.data; renderOverview(); }
    else { state.overview = null; replace('overview-content', empty('A coleta está indisponível', errorText(results[0].reason))); byId('source-badge').replaceWith(Object.assign(badge('unavailable'), { id: 'source-badge' })); errors.push(results[0].reason); }
    if (results[1].status === 'fulfilled') { state.vms = list(results[1].value.data?.items); renderVms(); }
    else { state.vms = []; replace('vms-content', empty('Inventário indisponível', errorText(results[1].reason))); errors.push(results[1].reason); }
    if (results[2].status === 'fulfilled') state.profiles = list(results[2].value.data?.items);
    else state.profiles = [];
    if (errors.length) notice(errors.map(errorText).join('\n'), 'error');
    if (state.view === 'detail' && state.vm) await loadVm(state.vm.vmid, false);
    if (state.view === 'activity') await loadAudit();
    byId('refresh').disabled = false;
  }

  function metric(label, value, foot, percent) {
    return h('article', { className: 'metric' }, h('p', { className: 'metric-label', text: label }), h('p', { className: 'metric-value', text: value }), finite(percent) ? h('progress', { className: 'meter', 'aria-label': label, max: 100, value: Math.min(100, Math.max(0, percent)) }) : null, h('p', { className: 'metric-foot', text: foot }));
  }
  function renderOverview() {
    const data = state.overview || {}, cap = data.capacity || {}, nodes = list(data.nodes), alerts = list(data.alerts);
    const unknown = !['healthy', 'fresh', 'live', 'ok', 'available'].includes(data.sourceState);
    byId('source-badge').replaceWith(Object.assign(badge(unknown ? 'unknown' : 'healthy', unknown ? (labels[data.sourceState] || 'Estado desconhecido') : 'Coleta disponível'), { id: 'source-badge' }));
    byId('last-update').textContent = `Leitura: ${date(data.collectedAt)}`;
    const cpu = nodes.filter(node => finite(node.cpu));
    const percent = cpu.length && !unknown ? cpu.reduce((sum, node) => sum + node.cpu * 100, 0) / cpu.length : null;
    const metrics = h('div', { className: 'metrics' }, metric('Nós visíveis', unknown ? '—' : String(nodes.length), 'Filtrados pela sua identidade'), metric('CPU média', finite(percent) ? `${number(percent)}%` : '—', 'Utilização dos nós com leitura', percent), metric('Memória em uso', unknown ? '—' : memory(cap.usedMemoryMiB), `${memory(cap.totalMemoryMiB)} de capacidade`, finite(cap.totalMemoryMiB) && cap.totalMemoryMiB > 0 && !unknown ? cap.usedMemoryMiB / cap.totalMemoryMiB * 100 : null), metric('Storage livre', unknown ? '—' : finite(cap.freeStorageGiB) ? `${number(cap.freeStorageGiB)} GiB` : '—', 'Capacidade física informada'));
    const nodePanel = h('article', { className: 'panel' }, h('div', { className: 'panel-header' }, h('h2', { text: 'Nós da plataforma' }), h('span', { className: 'muted', text: `${nodes.length} ${nodes.length === 1 ? 'visível' : 'visíveis'}` })), nodes.length ? nodes.map(node => h('div', { className: 'node-row' }, h('span', { className: 'node-icon', 'aria-hidden': true, text: '▤' }), h('div', { className: 'node-info' }, h('strong', { text: text(node.name) }), h('p', { text: `${memory(node.memoryMiB)} / ${memory(node.maxMemoryMiB)} RAM` })), h('div', { className: 'node-cpu' }, badge(node.status), h('p', { className: 'cell-sub', text: finite(node.cpu) ? `CPU ${number(node.cpu * 100)}%` : 'CPU desconhecida' })))) : empty('Nenhum nó disponível', 'Sem leitura, não há saúde confirmada.'));
    const alertPanel = h('article', { className: 'panel' }, h('div', { className: 'panel-header' }, h('h2', { text: 'Sinais de atenção' }), badge(alerts.length ? 'stale' : 'neutral', `${alerts.length} alertas`)), unknown ? empty('Estado da coleta desconhecido', 'Ausência de alertas não comprova saúde.') : alerts.length ? alerts.map(alert => h('div', { className: 'alert-row' }, h('span', { className: 'alert-symbol', 'aria-hidden': true, text: '!' }), h('div', {}, h('p', { text: text(alert.message) }), h('span', { className: 'cell-sub', text: ({ critical: 'Crítico', warning: 'Atenção', info: 'Informação' })[alert.level] || 'Sinal da plataforma' })))) : empty('Nenhum alerta informado', 'Continue acompanhando a idade da coleta.'));
    replace('overview-content', metrics, h('div', { className: 'overview-grid' }, nodePanel, alertPanel), h('div', { className: 'section-heading' }, h('h2', { text: 'Operar com contexto' })), h('div', { className: 'panel panel-body' }, h('p', { className: 'muted', text: `Memória alocada informada: ${memory(cap.allocatedMemoryMiB)}. Perfis e capacidade são validados novamente pelo servidor antes de criar uma máquina.` }), button('Ver máquinas →', () => navigate('vms'), 'button quiet')));
    const links = list(data.consoleLinks).map(link => { const url = safeConsoleUrl(link.url); return url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, text(link.label), h('span', { 'aria-hidden': true, text: '↗' })) : null; }).filter(Boolean);
    if (links.length) byId('overview-content').append(h('div', { className: 'console-shortcuts' }, h('span', { className: 'muted', text: 'Consoles autorizados' }), links.map(link => link.cloneNode(true))));
    replace('console-links', ...(links.length ? links : [h('span', { className: 'muted', text: 'Nenhum console autorizado' })]));
  }

  function table(headers, rows) { return h('div', { className: 'panel table-scroll' }, h('table', { className: 'data-table' }, h('thead', {}, h('tr', {}, headers.map(label => h('th', { scope: 'col', text: label })))), h('tbody', {}, rows))); }
  function renderVms() {
    const query = byId('vm-search').value.toLocaleLowerCase('pt-BR'), filter = byId('vm-filter').value;
    const items = state.vms.filter(vm => `${vm.name} ${vm.project || ''} ${vm.vmid}`.toLocaleLowerCase('pt-BR').includes(query) && (filter === 'all' || vm.status === filter));
    byId('vm-count').textContent = `${items.length} máquina${items.length === 1 ? '' : 's'}`;
    if (!items.length) { replace('vms-content', empty('Nenhuma máquina nesta seleção', 'A lista mostra somente objetos autorizados para sua identidade.')); return; }
    replace('vms-content', table(['Máquina', 'Estado', 'Projeto', 'CPU / RAM', 'Disco', 'Nó'], items.map(vm => h('tr', {}, h('td', {}, button(text(vm.name), () => loadVm(vm.vmid), 'cell-name'), h('span', { className: 'cell-sub mono', text: `VM ${vm.vmid}` })), h('td', {}, badge(vm.status)), h('td', { text: vm.project || 'Não classificado' }), h('td', {}, `${number(vm.cores)} vCPU`, h('span', { className: 'cell-sub', text: memory(vm.memoryMiB) })), h('td', { text: finite(vm.diskGiB) ? `${number(vm.diskGiB)} GiB` : '—' }), h('td', { className: 'mono', text: text(vm.node) })))));
  }
  async function loadVm(vmid, changeView = true) {
    if (changeView) { state.vm = null; state.detailTab = 'summary'; navigate('detail'); replace('detail-content', loading()); }
    const epoch = state.sessionEpoch, generation = ++detailGeneration;
    try { const { data } = await api.request(`/vms/${encodeURIComponent(vmid)}`); if (!state.session || epoch !== state.sessionEpoch || generation !== detailGeneration) return; state.vm = data; if (state.view === 'detail') renderDetail(); }
    catch (error) { if (state.session && epoch === state.sessionEpoch && generation === detailGeneration) { state.vm = null; replace('detail-content', empty('Não foi possível ler a máquina', errorText(error))); notice(errorText(error), 'error'); } }
  }
  function renderDetail() {
    const vm = state.vm; if (!vm) return;
    const tabs = h('div', { className: 'detail-tabs', role: 'tablist', 'aria-label': 'Detalhes da máquina' }, [['summary', 'Resumo'], ['resources', 'Recursos'], ['acl', 'Acessos']].map(([id, label], index) => button(label, () => { state.detailTab = id; renderDetail(); byId(`detail-tab-${index}`).focus(); }, `tab ${state.detailTab === id ? 'active' : ''}`)));
    [...tabs.children].forEach((tab, index) => { tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(tab.classList.contains('active'))); tab.tabIndex = tab.classList.contains('active') ? 0 : -1; tab.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const target = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3; tabs.children[target].click(); document.querySelectorAll('.detail-tabs .tab')[target].focus(); } }); });
    const heading = h('div', { className: 'detail-heading' }, h('div', {}, h('p', { className: 'eyebrow', text: `MÁQUINA VIRTUAL · ${vm.vmid}` }), h('h1', { id: 'detail-title', text: text(vm.name) }), h('div', { className: 'detail-meta' }, badge(vm.status), `${vm.node || 'Nó desconhecido'} · ${vm.project || 'Sem projeto'}`)), h('div', { className: 'actions' }, button('Iniciar', () => power('start'), 'button primary', !allowed(vm, 'start')), button('Desligar', () => power('shutdown'), 'button quiet', !allowed(vm, 'shutdown')), button('Reiniciar', () => power('reboot'), 'button quiet', !allowed(vm, 'reboot'))));
    [...tabs.children].forEach((tab, index) => { tab.id = `detail-tab-${index}`; tab.setAttribute('aria-controls', 'detail-tab-content'); });
    const content = h('div', { id: 'detail-tab-content', role: 'tabpanel', 'aria-labelledby': tabs.querySelector('[aria-selected="true"]').id });
    replace('detail-content', heading, tabs, content);
    if (state.detailTab === 'summary') {
      const facts = [['CPU', `${number(vm.cores)} vCPU`], ['Memória', memory(vm.memoryMiB)], ['Discos virtuais', finite(vm.diskGiB) ? `${number(vm.diskGiB)} GiB` : '—'], ['Pool', vm.pool || 'Não informado'], ['Tags', list(vm.tags).join(', ') || 'Nenhuma'], ['Última leitura', date(vm.collectedAt)]];
      content.append(h('div', { className: 'detail-grid' }, h('article', { className: 'panel' }, h('div', { className: 'panel-header' }, h('h2', { text: 'Configuração' })), h('div', { className: 'panel-body' }, h('dl', { className: 'facts' }, facts.map(([label, value]) => h('div', {}, h('dt', { text: label }), h('dd', { text: value })))))), h('div', {}, h('article', { className: 'panel' }, h('div', { className: 'panel-header' }, h('h2', { text: 'Dependências protegidas' })), h('div', { className: 'panel-body' }, dataList(list(vm.dependencies)))), h('div', { className: 'section-heading' }, h('h2', { text: 'Mudanças pendentes' })), dataList(list(vm.pending)))));
      content.append(h('div', { className: 'section-heading' }, h('h2', { text: 'Ações que exigem atenção' })), h('div', { className: 'panel panel-body' }, h('p', { className: 'field-help', text: 'A parada forçada não oferece desligamento limpo ao sistema convidado. A exclusão exige prévia e confirmação do nome.' }), h('div', { className: 'form-actions' }, button('Forçar parada', () => power('stop'), 'button danger', !allowed(vm, 'stop')), button('Revisar exclusão', previewDelete, 'button danger', !allowed(vm, 'delete')))));
    } else if (state.detailTab === 'resources') renderResources(content, vm);
    else loadAcl(content, vm);
  }

  function field(label, name, { type = 'text', value = '', min, max, required = true, options, help, disabled = false } = {}) {
    const id = `field-${name}`;
    const control = options ? h('select', { id, name, required, disabled }, options.map(option => h('option', { value: option.value, text: option.label }))) : h('input', { id, name, type, value, min, max, required, disabled, ...(type === 'number' ? { step: 1 } : {}) });
    if (options && value !== '') control.value = value;
    const wrapper = h('div', {}, h('label', { for: id, text: label }), control, help ? h('p', { className: 'field-help', id: `${id}-help`, text: help }) : null);
    if (help) control.setAttribute('aria-describedby', `${id}-help`);
    return { wrapper, control };
  }
  function formError(form, error) { let node = form.querySelector('[data-error]'); if (!node) { node = h('p', { className: 'form-error', role: 'alert', 'data-error': true }); form.append(node); } node.textContent = errorText(error); node.hidden = false; }
  function setBusy(form, busy) { for (const node of form.querySelectorAll('button,input,select')) { if (busy) { node.dataset.wasDisabled = String(node.disabled); node.disabled = true; } else { node.disabled = node.dataset.wasDisabled === 'true'; delete node.dataset.wasDisabled; } } }
  function renderResources(content, vm) {
    const form = h('form', { className: 'panel panel-body resource-form' });
    const cores = field('vCPU', 'cores', { type: 'number', min: 1, max: 128, value: vm.cores, help: 'O limite da plataforma e a capacidade disponível são validados ao salvar.', disabled: !allowed(vm, 'resources') });
    const ram = field('Memória (MiB)', 'memoryMiB', { type: 'number', min: 128, value: vm.memoryMiB, help: '1 GiB = 1024 MiB. A capacidade será conferida pelo servidor.', disabled: !allowed(vm, 'resources') });
    form.append(h('h2', { text: 'CPU e memória' }), h('p', { className: 'field-help', text: 'A alteração usa a configuração lida agora. Mudanças concorrentes exigem nova leitura; nem toda alteração se aplica imediatamente ao guest.' }), h('div', { className: 'form-grid' }, cores.wrapper, ram.wrapper), h('div', { className: 'form-actions' }, h('button', { type: 'submit', className: 'button primary', text: 'Salvar recursos', disabled: !allowed(vm, 'resources') })));
    form.addEventListener('submit', async event => { event.preventDefault(); await submitForm(form, 'PATCH', `/vms/${vm.vmid}/resources`, { cores: Number(cores.control.value), memoryMiB: Number(ram.control.value), expectedDigest: vm.digest }, `Recursos · ${vm.name}`); }); content.append(form);
  }

  function openDialog(title, eyebrow = 'OPERAÇÃO') { if (dialogBusy) return null; dialogGeneration++; byId('dialog-title').textContent = title; byId('dialog-eyebrow').textContent = eyebrow; replace('dialog-body'); const dialog = byId('action-dialog'); if (!dialog.open) dialog.showModal(); return byId('dialog-body'); }
  byId('dialog-close').addEventListener('click', () => { if (!dialogBusy) byId('action-dialog').close(); });
  byId('action-dialog').addEventListener('cancel', event => { if (dialogBusy) event.preventDefault(); });
  function cancelButton() { return button('Cancelar', () => byId('action-dialog').close()); }

  async function createVm() {
    const body = openDialog('Criar máquina virtual', 'NOVO RECURSO'); if (!body) return; body.append(loading());
    const generation = dialogGeneration;
    try { state.profiles = list((await api.request('/profiles')).data?.items); }
    catch (error) { if (generation === dialogGeneration) body.replaceChildren(empty('Perfis indisponíveis', errorText(error))); return; }
    if (!state.session || !byId('action-dialog').open || generation !== dialogGeneration) return;
    if (!state.profiles.length) { body.replaceChildren(empty('Nenhum perfil autorizado', 'Nenhuma máquina pode ser criada com a sua identidade neste momento.')); return; }
    const profile = field('Perfil aprovado', 'profileId', { options: state.profiles.map(item => ({ value: item.id, label: item.label })) });
    const name = field('Nome da máquina', 'name', { help: 'Identifique o projeto e a função. O nome será validado pelo servidor.' }); name.control.maxLength = 63;
    const project = field('Projeto', 'project', { options: [] });
    const cores = field('vCPU', 'create-cores', { type: 'number' });
    const ram = field('Memória (MiB)', 'create-memory', { type: 'number' });
    const disk = field('Disco virtual (GiB)', 'create-disk', { type: 'number' });
    const summary = h('div', { className: 'profile-summary', role: 'status' });
    const form = h('form', {}, profile.wrapper, summary, name.wrapper, project.wrapper, h('div', { className: 'form-grid' }, cores.wrapper, ram.wrapper, disk.wrapper), h('div', { className: 'form-actions' }, cancelButton(), h('button', { type: 'submit', className: 'button primary', text: 'Solicitar criação' })));
    function selectProfile() {
      const selected = state.profiles.find(item => item.id === profile.control.value), limits = selected?.limits || {};
      project.control.replaceChildren(...list(selected?.projects).map(value => h('option', { value, text: value })));
      for (const [input, min, max] of [[cores.control, limits.minCores, limits.maxCores], [ram.control, limits.minMemoryMiB, limits.maxMemoryMiB], [disk.control, limits.minDiskGiB, limits.maxDiskGiB]]) { if (finite(min)) { input.min = min; input.value = min; } if (finite(max)) input.max = max; }
      summary.textContent = selected?.readiness === 'hardware-only' ? 'Hardware preparado, VM desligada e sem interface de rede. O sistema operacional, a rede e as aplicações ainda precisam ser configurados no console Proxmox.' : 'O servidor define a preparação deste perfil. A criação não comprova que aplicações estejam prontas.';
    }
    profile.control.addEventListener('change', selectProfile); selectProfile();
    form.addEventListener('submit', async event => { event.preventDefault(); await submitForm(form, 'POST', '/vms', { name: name.control.value.trim(), project: project.control.value, profileId: profile.control.value, cores: Number(cores.control.value), memoryMiB: Number(ram.control.value), diskGiB: Number(disk.control.value) }, `Criação · ${name.control.value.trim()}`, true); });
    body.replaceChildren(form); profile.control.focus();
  }

  function power(action) {
    const vm = state.vm; if (!allowed(vm, action)) return;
    const body = openDialog(`${actions[action]} · ${vm.name}`, action === 'stop' ? 'PARADA FORÇADA' : 'ENERGIA'); if (!body) return;
    const form = h('form', {}, h('p', { className: action === 'stop' ? 'notice error' : 'muted', text: action === 'stop' ? 'Esta ação corta a execução da VM. Escritas em andamento podem ser perdidas. Confirme o nome exato para continuar.' : `A solicitação será enviada ao Proxmox e acompanhada até o resultado. Alvo: VM ${vm.vmid}.` }));
    const confirmation = action === 'stop' ? field('Digite o nome exato da VM', 'power-confirmation', { help: vm.name }) : null;
    if (confirmation) form.append(confirmation.wrapper);
    const submit = h('button', { type: 'submit', className: `button ${action === 'stop' ? 'danger' : 'primary'}`, text: actions[action], disabled: !!confirmation });
    confirmation?.control.addEventListener('input', () => { submit.disabled = confirmation.control.value !== vm.name; });
    form.append(h('div', { className: 'form-actions' }, cancelButton(), submit));
    form.addEventListener('submit', async event => { event.preventDefault(); if (confirmation && confirmation.control.value !== vm.name) return; await submitForm(form, 'POST', `/vms/${vm.vmid}/actions`, { action, expectedDigest: vm.digest, ...(confirmation ? { confirmation: confirmation.control.value } : {}) }, `${actions[action]} · ${vm.name}`, true); }); body.append(form);
  }
  async function previewDelete() {
    const vm = state.vm; if (!allowed(vm, 'delete')) return;
    const body = openDialog(`Excluir ${vm.name}`, 'PRÉVIA DE EXCLUSÃO'); if (!body) return; body.append(loading());
    const generation = dialogGeneration;
    try {
      const { data: preview } = await api.request(`/vms/${vm.vmid}/deletion-preview`, { method: 'POST', body: {}, key: crypto.randomUUID() });
      if (!byId('action-dialog').open || !state.session || generation !== dialogGeneration) return;
      const form = h('form', {}, h('p', { className: 'notice error', text: 'Exclusão permanente dos recursos descritos nesta prévia. Discos físicos e recursos externos não devem ser removidos por esta operação.' }), h('h3', { text: 'Impacto informado pelo servidor' }), dataList(list(preview.impact)), h('p', { className: 'field-help', text: `Prévia válida até ${date(preview.expiresAt)}. Mudanças de configuração exigem outra prévia.` }));
      if (preview.allowed !== true) { form.append(h('h3', { text: 'Operação bloqueada' }), dataList(list(preview.blockers)), h('div', { className: 'form-actions' }, cancelButton())); body.replaceChildren(form); return; }
      const confirmation = field('Confirme o nome exato', 'delete-confirmation', { help: preview.name });
      const submit = h('button', { type: 'submit', className: 'button danger', text: 'Excluir permanentemente', disabled: true });
      confirmation.control.addEventListener('input', () => { submit.disabled = !canDelete(preview, confirmation.control.value); });
      form.append(confirmation.wrapper, h('div', { className: 'form-actions' }, cancelButton(), submit));
      form.addEventListener('submit', async event => { event.preventDefault(); if (!canDelete(preview, confirmation.control.value)) { formError(form, new ApiError('Prévia expirada ou confirmação divergente. Feche e gere uma nova prévia.')); return; } await submitForm(form, 'DELETE', `/vms/${vm.vmid}`, { intentId: preview.intentId, confirmationName: confirmation.control.value }, `Exclusão · ${vm.name}`, true); }); body.replaceChildren(form); confirmation.control.focus();
    } catch (error) { if (generation === dialogGeneration) body.replaceChildren(empty('Não foi possível preparar a exclusão', errorText(error))); if (error.status === 409) loadVm(vm.vmid, false); }
  }

  async function loadAcl(content, vm) {
    const epoch = state.sessionEpoch;
    content.replaceChildren(loading());
    try {
      const { data } = await api.request(`/vms/${vm.vmid}/acl`);
      if (state.vm?.vmid !== vm.vmid || state.detailTab !== 'acl' || !state.session || epoch !== state.sessionEpoch || !content.isConnected) return;
      const entries = list(data.items);
      const rows = entries.map(entry => h('tr', {}, h('td', {}, text(entry.principal), h('span', { className: 'cell-sub', text: ({ group: 'Grupo', user: 'Usuário', token: 'Token de API' })[entry.principalType] || 'Identidade não suportada' })), h('td', { text: text(entry.role) }), h('td', {}, badge('neutral', entry.inherited ? 'Herdado' : 'Explícito'), h('span', { className: 'cell-sub mono', text: text(entry.origin) })), h('td', { text: entry.propagate ? 'Sim' : 'Não' }), h('td', {}, button('Revogar', () => revokeAcl(vm, data, entry), 'button small danger', !canEditAclEntry(entry) || !allowed(vm, 'acl')))));
      content.replaceChildren(h('div', { className: 'section-heading' }, h('h2', { text: 'Acesso à máquina' }), button('＋ Conceder acesso', () => grantAcl(vm, data), 'button primary', !allowed(vm, 'acl'))), h('p', { className: 'notice info', text: 'Estas permissões controlam a VM no Proxmox. Elas não criam usuários Linux ou contas nos aplicativos. Acessos herdados e tokens devem ser administrados no console de origem.' }), ...(data.completeness === 'complete' ? [] : [h('p', { className: 'notice', text: 'Lista parcial de permissões: sua identidade não pode confirmar toda a herança de acesso. Outras permissões podem continuar válidas.' })]), rows.length ? table(['Identidade', 'Papel', 'Origem', 'Propagar', 'Ação'], rows) : empty('Nenhuma ACL informada'));
    } catch (error) { if (epoch === state.sessionEpoch) content.replaceChildren(empty('Acessos indisponíveis', errorText(error))); }
  }
  function grantAcl(vm, acl) {
    const body = openDialog('Conceder acesso', `VM ${vm.vmid}`); if (!body) return;
    const kind = field('Tipo de identidade', 'principalType', { options: [{ value: 'user', label: 'Usuário' }, { value: 'group', label: 'Grupo' }] });
    const principal = field('Identidade existente', 'principal', { options: [] });
    const role = field('Papel existente', 'role', { options: list(acl.roles).map(item => ({ value: item.id, label: item.label || item.id })) });
    const propagate = h('input', { type: 'checkbox', id: 'acl-propagate' });
    const choose = () => principal.control.replaceChildren(...list(kind.control.value === 'group' ? acl.groups : acl.users).map(item => h('option', { value: item.id, text: item.label || item.id })));
    kind.control.addEventListener('change', choose); choose();
    const form = h('form', {}, kind.wrapper, principal.wrapper, role.wrapper, h('label', { className: 'checkbox-label', for: 'acl-propagate' }, propagate, 'Propagar para os objetos subordinados'), h('p', { className: 'field-help', text: 'Somente esta entrada será alterada. Suas permissões e a versão da ACL são conferidas novamente ao confirmar.' }), h('div', { className: 'form-actions' }, cancelButton(), h('button', { type: 'submit', className: 'button primary', text: 'Conceder acesso' })));
    form.addEventListener('submit', async event => { event.preventDefault(); await submitForm(form, 'PUT', `/vms/${vm.vmid}/acl`, { principalType: kind.control.value, principal: principal.control.value, role: role.control.value, propagate: propagate.checked, expectedAclDigest: acl.digest }, `Acesso · ${vm.name}`, true); }); body.append(form);
  }
  function revokeAcl(vm, acl, entry) {
    if (!canEditAclEntry(entry) || !allowed(vm, 'acl')) return;
    const body = openDialog('Revogar acesso explícito', `VM ${vm.vmid}`); if (!body) return;
    const form = h('form', {}, h('p', { text: `${entry.principal} perderá a entrada explícita do papel ${entry.role} nesta VM.` }), h('p', { className: 'field-help', text: 'Outras permissões, inclusive as herdadas ou concedidas por grupos, podem continuar válidas.' }), h('div', { className: 'form-actions' }, cancelButton(), h('button', { type: 'submit', className: 'button danger', text: 'Revogar entrada' })));
    form.addEventListener('submit', async event => { event.preventDefault(); await submitForm(form, 'DELETE', `/vms/${vm.vmid}/acl`, { principalType: entry.principalType, principal: entry.principal, role: entry.role, expectedAclDigest: acl.digest }, `Revogar acesso · ${vm.name}`, true); }); body.append(form);
  }

  async function submitForm(form, method, path, payload, label, dialog = false) {
    if (form.dataset.busy === 'true') return;
    if ([...state.operations.values()].some(op => !operationTerminal(op.state) && (op.intent || op.submission)?.path === path && (op.intent || op.submission)?.method === method)) {
      formError(form, new ApiError('Já existe uma solicitação pendente para esta ação. Acompanhe ou reconcilie a mesma intenção em Atividades.')); return;
    }
    form.dataset.busy = 'true'; setBusy(form, true); if (dialog) dialogBusy = true;
    const epoch = state.sessionEpoch;
    const intent = { method, path, body: payload, key: crypto.randomUUID(), label };
    try {
      const { data } = await api.request(path, intent);
      if (!state.session || epoch !== state.sessionEpoch) return;
      if (!data?.operationId) throw new ApiError('A solicitação não retornou uma operação rastreável. O resultado é desconhecido.', { uncertain: true });
      trackOperation(data, label, intent);
      if (dialog) byId('action-dialog').close();
      toast('Solicitação registrada. Acompanhe o resultado em Atividades.');
    } catch (error) {
      if (!state.session || epoch !== state.sessionEpoch) return;
      if (error.uncertain) {
        state.operations.set(intent.key, { state: 'unknown', label, intent, createdAt: new Date().toISOString(), pollError: error.message });
        renderOperations(); notice('O resultado da solicitação é desconhecido. Não crie outra intenção; confira ou reconcilie a mesma em Atividades.', 'error');
        if (dialog) byId('action-dialog').close();
      } else { formError(form, error); if (error.status === 409) { notice('O estado mudou. Dados atualizados; revise a operação antes de tentar novamente.', 'error'); await refresh(); } }
    } finally { form.dataset.busy = 'false'; setBusy(form, false); if (epoch === state.sessionEpoch) dialogBusy = false; }
  }
  function trackOperation(operation, label, submission) {
    const old = state.operations.get(operation.operationId);
    state.operations.set(operation.operationId, { ...old, ...operation, ...(submission ? { submission } : {}), label: label || old?.label || actions[operation.action] || 'Operação da plataforma', pollError: null });
    renderOperations(); if (!operationTerminal(operation.state)) schedulePoll();
    else if (operation.state === 'succeeded') refresh();
  }
  function schedulePoll() { clearTimeout(operationTimer); if (state.session) operationTimer = setTimeout(pollOperations, 2500); }
  async function pollOperations() {
    if (polling || !state.session) return; polling = true;
    const epoch = state.sessionEpoch;
    const pending = [...state.operations.values()].filter(op => op.operationId && !operationTerminal(op.state));
    await Promise.allSettled(pending.map(async operation => {
      try {
        const { data } = await api.request(`/operations/${encodeURIComponent(operation.operationId)}`);
        if (!state.session || epoch !== state.sessionEpoch) return;
        state.operations.set(operation.operationId, { ...operation, ...data, pollError: null });
        if (operationTerminal(data.state)) { if (data.state === 'succeeded') toast(`${operation.label}: resultado confirmado.`); await refresh(); }
      } catch (error) {
        if (state.session && epoch === state.sessionEpoch) {
          if (error.status === 403) { state.operations.delete(operation.operationId); notice('O acesso a uma operação foi revogado. Seu resultado não pôde ser confirmado.', 'error'); }
          else state.operations.set(operation.operationId, { ...operation, pollError: error.message });
        }
      }
    }));
    polling = false; renderOperations();
    if ([...state.operations.values()].some(op => op.operationId && !operationTerminal(op.state))) schedulePoll();
  }
  async function reconcileUnknown(operation, target) {
    const epoch = state.sessionEpoch;
    target.disabled = true;
    try {
      const { data } = await api.request(operation.intent.path, operation.intent);
      if (!state.session || epoch !== state.sessionEpoch) return;
      if (!data?.operationId) throw new ApiError('Ainda não há resultado rastreável. Não gere uma nova intenção.');
      state.operations.delete(operation.intent.key); trackOperation(data, operation.label, operation.intent);
    } catch (error) { if (epoch === state.sessionEpoch) { operation.pollError = error.message; renderOperations(); } }
    finally { target.disabled = false; }
  }
  function renderOperations() {
    const operations = [...state.operations.values()].reverse(), active = operations.filter(op => !operationTerminal(op.state)).length;
    byId('task-count').textContent = String(active); byId('task-count').hidden = active === 0;
    replace('operations-content', ...(operations.length ? operations.map(op => {
      const details = h('div', {}, h('h3', { text: op.label }), h('p', { text: `${date(op.updatedAt || op.createdAt)}${op.target ? ` · ${text(op.target)}` : ''}` }), op.operationId ? h('p', { className: 'mono', text: `Operação ${op.operationId}` }) : null, op.task ? h('p', { className: 'mono', text: `Tarefa ${op.task.node || ''} · ${op.task.upid || ''}` }) : null, op.error || op.pollError ? h('p', { className: 'task-error', text: op.error?.message || op.pollError }) : null);
      if (op.intent) details.append(button('Conferir / reconciliar a mesma intenção', event => reconcileUnknown(op, event.currentTarget), 'button small quiet'));
      return h('article', { className: 'task-card' }, details, badge(op.state, op.state === 'running' ? 'Tarefa em execução' : undefined));
    }) : [empty('Nenhuma tarefa acompanhada', 'Operações ficam registradas no servidor. A auditoria mostra os eventos que sua identidade pode consultar.')]));
  }
  async function loadAudit(more = false) {
    if (!state.session) return;
    const epoch = state.sessionEpoch;
    if (!more) replace('audit-content', loading());
    byId('audit-more').disabled = true;
    try {
      const { data } = await api.request(`/audit${more && state.cursor !== null ? `?cursor=${encodeURIComponent(state.cursor)}` : ''}`);
      if (!state.session || epoch !== state.sessionEpoch) return;
      state.audit = more ? [...state.audit, ...list(data.items)] : list(data.items); state.cursor = data.nextCursor ?? null;
      replace('audit-content', state.audit.length ? table(['Quando', 'Identidade', 'Ação', 'Alvo', 'Resultado'], state.audit.map(item => h('tr', {}, h('td', { text: date(item.createdAt) }), h('td', { text: text(item.actor) }), h('td', {}, text(actions[item.action] || item.action), item.operationId ? h('div', {}, h('span', { className: 'cell-sub mono', text: item.operationId }), button('Acompanhar operação', () => recoverOperation(item.operationId), 'button small quiet')) : null), h('td', { text: text(item.target) }), h('td', {}, badge(item.outcome, labels[item.outcome] || text(item.outcome)))))) : empty('Nenhum evento visível', 'A auditoria respeita suas permissões atuais.'));
      byId('audit-more').hidden = state.cursor === null;
    } catch (error) { replace('audit-content', empty('Auditoria indisponível', errorText(error))); byId('audit-more').hidden = true; }
    finally { byId('audit-more').disabled = false; }
  }
  async function recoverOperation(id) {
    const epoch = state.sessionEpoch;
    try { const { data } = await api.request(`/operations/${encodeURIComponent(id)}`); if (state.session && epoch === state.sessionEpoch && data?.operationId) trackOperation(data); }
    catch (error) { if (epoch === state.sessionEpoch) notice(errorText(error), 'error'); }
  }
  byId('audit-more').addEventListener('click', () => loadAudit(true));
  document.querySelector('.sidebar > .brand').addEventListener('click', event => { event.preventDefault(); navigate('overview'); });
  setInterval(() => { if (state.session && document.visibilityState === 'visible' && state.view === 'overview' && !byId('action-dialog').open && !byId('refresh').disabled) refresh(); }, 30000);
  api.request('/session').then(({ data }) => data?.authenticated ? signedIn(data) : showLogin()).catch(error => showLogin(error.status === 401 ? '' : errorText(error))).finally(() => {
    for (const form of [byId('login-form'), byId('totp-form')]) form.querySelector('button[type=submit]').disabled = false;
    document.documentElement.dataset.controlReady = 'true';
  });
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true }); else boot();
}
