/* Verified Content Engine: web UI (vanilla JS, no dependencies).
 *
 * Rules this file follows:
 * - Every piece of server text goes through esc() before it reaches innerHTML.
 * - No inline handlers (CSP): one delegated listener per event type, keyed by data-action / data-form.
 * - There is no Approve button anywhere. Approval comes from the gate or from a logged override.
 */
'use strict';
(function () {

  // =====================================================================
  // Helpers
  // =====================================================================

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const enc = encodeURIComponent;

  const ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/[&<>"'`]/g, (c) => ESC_MAP[c]);
  }

  const TAG_RE = /\[\[([A-Z][A-Z0-9]{1,15}-[0-9]{3,})\]\]/g;
  function stripTags(s) {
    return String(s || '').replace(TAG_RE, '').replace(/[ \t]+([.,;:!?])/g, '$1').replace(/[ \t]{2,}/g, ' ').trim();
  }
  function tagsIn(s) {
    const out = []; let m; const re = new RegExp(TAG_RE.source, 'g');
    while ((m = re.exec(String(s || '')))) out.push(m[1]);
    return out;
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  function fmtDay(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  }
  function fmtNum(n) {
    if (n === null || n === undefined || n === '') return '—';
    const x = Number(n);
    return isNaN(x) ? String(n) : x.toLocaleString();
  }
  function fmtPct(x) {
    if (x === null || x === undefined) return '—';
    return (Number(x) * 100).toFixed(1).replace(/\.0$/, '') + '%';
  }
  function fmtScore(x) {
    if (x === null || x === undefined) return '—';
    return typeof x === 'number' ? x.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : String(x);
  }
  function shortSha(s) { return s ? String(s).slice(0, 10) : ''; }
  function plural(n, one, many) { return `${fmtNum(n)} ${n === 1 ? one : (many || one + 's')}`; }

  const STATUS = {
    blocked: ['Blocked', 'b-red'],
    flagged: ['Flagged', 'b-amber'],
    approved: ['Approved', 'b-green'],
    'approved-override': ['Approved (override)', 'b-purple'],
    rejected: ['Rejected', 'b-dark'],
    failed: ['Failed', 'b-outline-red'],
    running: ['Running', 'b-blue'],
    verified: ['Verified', 'b-green'],
    'needs-review': ['Needs review', 'b-amber'],
    deprecated: ['Deprecated', ''],
    ready: ['Ready', 'b-green'],
    stale: ['Stale', 'b-amber'],
    incomplete: ['Incomplete', 'b-amber'],
    open: ['Open', 'b-amber'],
    resolved: ['Resolved', 'b-green'],
    active: ['Active', 'b-green'],
    removed: ['Removed', ''],
    pass: ['Pass', 'b-green'],
    block: ['Block', 'b-red'],
    flag: ['Flag', 'b-amber'],
    high: ['High', 'b-amber'],
    medium: ['Medium', ''],
    low: ['Low', ''],
    done: ['Done', 'b-green'],
    succeeded: ['Succeeded', 'b-green'],
    pending: ['Pending', ''],
    skipped: ['Skipped', ''],
    'has-claim': ['Has claim', 'b-green'],
    'needs-claim': ['Needs claim', 'b-amber'],
    confirmed: ['Confirmed', 'b-green'],
    'doc-wrong': ['Doc is wrong', 'b-red'],
    deprioritized: ['Deprioritized', ''],
    'conflict-resolved': ['Conflict ruled', 'b-accent'],
    living: ['Living page', 'b-blue'],
    changelog: ['Changelog', ''],
  };
  function badge(status, label) {
    const s = STATUS[status] || [status, ''];
    return `<span class="badge ${s[1]}">${esc(label || s[0])}</span>`;
  }
  function statusLabel(status) { return (STATUS[status] || [status])[0]; }
  function chip(t) { return `<span class="chip">${esc(t)}</span>`; }
  function chips(list) { return (list || []).map(chip).join(' '); }
  function empty(title, text, actionHtml) {
    return `<div class="empty"><strong>${esc(title)}</strong>${text ? `<p>${esc(text)}</p>` : ''}${actionHtml || ''}</div>`;
  }
  function errorBox(e) { return `<div class="error-box" role="alert">${esc(e && e.message ? e.message : e)}</div>`; }

  // Small, escaped Markdown renderer for final copy and previews.
  function inlineMd(s) {
    let out = esc(s);
    out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
    return out;
  }
  function mdToHtml(md) {
    const out = []; let para = []; let inList = false;
    const flush = () => { if (para.length) { out.push(`<p>${inlineMd(para.join(' '))}</p>`); para = []; } };
    const closeList = () => { if (inList) { out.push('</ul>'); inList = false; } };
    String(md || '').replace(/<!--[\s\S]*?-->/g, '').split('\n').forEach((line) => {
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      const li = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)$/);
      if (!line.trim()) { flush(); closeList(); return; }
      if (h) { flush(); closeList(); const n = h[1].length; out.push(`<h${n}>${inlineMd(h[2])}</h${n}>`); return; }
      if (li) { flush(); if (!inList) { out.push('<ul>'); inList = true; } out.push(`<li>${inlineMd(li[1])}</li>`); return; }
      closeList(); para.push(line.trim());
    });
    flush(); closeList();
    return out.join('\n');
  }

  // =====================================================================
  // API
  // =====================================================================

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function api(method, path, body) {
    const opts = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (method !== 'GET') {
      opts.headers['X-Requested-With'] = 'vce';
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body || {});
    }
    let res;
    try { res = await fetch(path, opts); } catch (e) { throw new ApiError(0, 'The server did not respond. Is it running?'); }
    const ctype = res.headers.get('Content-Type') || '';
    const data = ctype.includes('json') ? await res.json().catch(() => null) : await res.text();
    if (res.status === 401 && path !== '/api/login') {
      showSignin(path === '/api/me' ? '' : 'Your session ended. Sign in again.');
      throw new ApiError(401, 'Sign in required');
    }
    if (!res.ok) throw new ApiError(res.status, (data && data.error) || `Request failed (HTTP ${res.status})`);
    return data;
  }
  const GET = (p) => api('GET', p);
  const POST = (p, b) => api('POST', p, b);
  const PUT = (p, b) => api('PUT', p, b);
  const DEL = (p, b) => api('DELETE', p, b);
  const P = (pid) => `/api/products/${enc(pid)}`;

  // =====================================================================
  // State & roles
  // =====================================================================

  const S = {
    me: null,
    products: [],
    pid: localStorage.getItem('vce.pid') || null,
    contentTypes: null,
    claimFilters: { status: '', category: '', q: '' },
    queueGroups: [],
    lastDiff: null,
    rv: null,           // review state
    createResult: null,
  };

  const CATEGORIES = ['capability', 'integration', 'security', 'compliance', 'metric', 'pricing', 'competitive',
    'customer-reference', 'availability', 'deployment', 'limitation', 'market-evidence'];
  const DEFAULT_HIGH_RISK = ['compliance', 'metric', 'pricing', 'competitive', 'customer-reference', 'market-evidence'];
  const STAGES = ['unaware', 'problem-aware', 'solution-aware', 'product-aware', 'most-aware'];
  const ROLES = ['editor', 'reviewer', 'sme', 'compliance', 'admin'];
  const AUTO_CAP = 2;

  // Mirrors services/actions.py ROLE_FOR so the UI only offers what the server will allow.
  const ROLE_FOR = {
    'product.create': ['admin'], 'source.add': ['admin', 'editor', 'sme'], 'source.remove': ['admin'],
    ingest: ['admin', 'editor', 'sme'], 'claim.confirm': ['sme', 'admin'], 'claim.reject': ['sme', 'admin'],
    'claim.deprioritize': ['sme', 'admin', 'editor'], 'claim.doc-wrong': ['sme', 'admin'],
    'claim.confirm-high-risk': ['compliance', 'admin'], 'conflict.rule': ['sme', 'admin'],
    'decision.edit': ['admin', 'editor'], 'brief.create': ['editor', 'admin'], 'content.run': ['editor', 'admin'],
    'content.edit': ['editor', 'reviewer', 'admin'], 'content.direct': ['editor', 'reviewer', 'admin'],
    'content.override': ['reviewer', 'admin'], 'content.reject': ['reviewer', 'admin'],
    'content.mark-positioning': ['reviewer', 'admin'], 'content.export': ['editor', 'reviewer', 'admin'],
    'style.accept-threshold': ['admin'], 'settings.update': ['admin'], 'eval.run': ['admin', 'editor'],
    'member.manage': ['admin'], 'audit.view': ['admin', 'reviewer', 'compliance'],
  };
  function roles() { return (S.me && S.me.user && S.me.user.roles) || []; }
  function allowed(action) { return (ROLE_FOR[action] || []).some((r) => roles().includes(r)); }
  function current() { return S.products.find((p) => p.id === S.pid) || null; }

  async function loadProducts() {
    S.products = await GET('/api/products');
    if (!S.products.some((p) => p.id === S.pid)) S.pid = S.products.length ? S.products[0].id : null;
    if (S.pid) localStorage.setItem('vce.pid', S.pid); else localStorage.removeItem('vce.pid');
    syncPicker();
  }
  function setProduct(pid) {
    S.pid = pid;
    localStorage.setItem('vce.pid', pid);
    S.rv = null; S.createResult = null; S.lastDiff = null;
    syncPicker();
  }
  function syncPicker() {
    const sel = $('#product-picker');
    if (!sel) return;
    if (!S.products.length) {
      sel.innerHTML = '<option value="">No products yet</option>';
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    sel.innerHTML = S.products.map((p) =>
      `<option value="${esc(p.id)}"${p.id === S.pid ? ' selected' : ''}>${esc(p.name)} (${esc(p.claim_prefix)})</option>`).join('');
  }

  // =====================================================================
  // UI primitives: toast, modal, jobs, estimates
  // =====================================================================

  function toast(msg, kind) {
    const el = document.createElement('div');
    el.className = 'toast' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    $('#toasts').appendChild(el);
    setTimeout(() => el.remove(), kind === 'err' ? 7000 : 4000);
  }

  let modalSeq = 0;
  /**
   * modal({title, body, actions:[{label, value, kind}], wide, validate(form, value) -> error string|null})
   * Resolves {value, data} (data = FormData-derived object) or {value:null} when dismissed.
   */
  function modal(opts) {
    return new Promise((resolve) => {
      const id = 'modal-' + (++modalSeq);
      const prevFocus = document.activeElement;
      const root = $('#modal-root');
      const actions = opts.actions || [{ label: 'Cancel', value: null }, { label: 'OK', value: 'ok', kind: 'primary' }];
      root.innerHTML = `
        <div class="modal-backdrop">
          <div class="modal${opts.wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-labelledby="${id}-t">
            <div class="modal-head"><h2 id="${id}-t">${esc(opts.title)}</h2>
              <button type="button" class="btn btn-ghost btn-sm" data-mv="__close" aria-label="Close">✕</button></div>
            <form class="modal-form" novalidate>
              <div class="modal-body">${opts.body || ''}<p class="form-error" role="alert"></p></div>
              <div class="modal-foot">${actions.map((a) =>
                `<button type="${a.kind === 'primary' || a.kind === 'danger-primary' ? 'submit' : 'button'}" class="btn ${
                  a.kind === 'primary' ? 'btn-primary' : a.kind === 'danger' || a.kind === 'danger-primary' ? 'btn-danger' : a.kind === 'purple' ? 'btn-purple' : ''
                }" data-mv="${esc(a.value === null ? '__close' : a.value)}">${esc(a.label)}</button>`).join('')}</div>
            </form>
          </div>
        </div>`;
      const back = $('.modal-backdrop', root);
      const form = $('form', root);
      const errEl = $('.form-error', root);
      const close = (value, data) => {
        document.removeEventListener('keydown', onKey, true);
        root.innerHTML = '';
        if (prevFocus && prevFocus.focus) prevFocus.focus();
        resolve({ value, data });
      };
      const collect = () => {
        const fd = new FormData(form); const data = {};
        for (const [k, v] of fd.entries()) {
          if (k in data) data[k] = [].concat(data[k], v); else data[k] = v;
        }
        return data;
      };
      const finish = (value) => {
        if (value === '__close') return close(null);
        const data = collect();
        if (opts.validate) {
          const err = opts.validate(data, value, form);
          if (err) { errEl.textContent = err; return; }
        }
        close(value, data);
      };
      const onKey = (e) => {
        if (e.key === 'Escape') { e.preventDefault(); close(null); }
        if (e.key === 'Tab') { // trap focus
          const f = $$('button, input, select, textarea, a[href]', back).filter((x) => !x.disabled);
          if (!f.length) return;
          if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
          else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
        }
      };
      document.addEventListener('keydown', onKey, true);
      back.addEventListener('click', (e) => {
        const b = e.target.closest('[data-mv]');
        if (b && b.type !== 'submit') { e.preventDefault(); finish(b.getAttribute('data-mv')); }
        else if (e.target === back) close(null);
      });
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const sub = e.submitter || $('button[type=submit]', form);
        finish(sub ? sub.getAttribute('data-mv') : 'ok');
      });
      const first = $('textarea, input:not([type=hidden]), select', form) || $('button[type=submit]', form);
      if (first) first.focus();
      if (opts.onOpen) opts.onOpen(form);
    });
  }
  async function confirmDialog(title, bodyHtml, okLabel, kind) {
    const r = await modal({ title, body: bodyHtml, actions: [{ label: 'Cancel', value: null }, { label: okLabel || 'Continue', value: 'ok', kind: kind || 'primary' }] });
    return r.value === 'ok';
  }

  /** Show a token estimate before a run (PRD: anything more expensive than a quick check). */
  async function confirmEstimate(pid, kind, what) {
    let est;
    try { est = await GET(`${P(pid)}/estimate?kind=${enc(kind)}`); } catch (e) { toast(e.message, 'err'); return false; }
    return confirmDialog(`Run ${what}?`,
      `<p>Estimated cost: <strong>${fmtNum(est.tokens)} tokens</strong> with provider <code>${esc(est.provider)}</code>.</p>
       <p class="muted small">The estimate is approximate. Runs stop at the workspace's per-run budget.</p>`,
      `Run ${what}`);
  }

  function jobBox(id, title) {
    return `<div class="job" id="${esc(id)}">
      <div class="row-between"><strong>${esc(title)}</strong><span class="job-status">${badge('running')}</span></div>
      <p class="job-msg small muted" aria-live="polite">Starting…</p>
      <ul class="job-steps"></ul>
      <div class="job-result"></div>
    </div>`;
  }

  function stepsFromJob(job) {
    if (job.run && Array.isArray(job.run.steps) && job.run.steps.length) return job.run.steps;
    const map = new Map();
    (job.progress || []).forEach((p) => map.set(p.step, { name: p.step, status: p.status, attempts: null, tokens: null }));
    return Array.from(map.values());
  }

  function renderJobInto(el, job) {
    if (!el) return;
    const steps = stepsFromJob(job);
    const tokens = steps.reduce((a, s) => a + (Number(s.tokens) || 0), 0);
    const st = job.status === 'done' ? 'done' : job.status === 'failed' ? 'failed' : 'running';
    $('.job-status', el).innerHTML = badge(st === 'done' ? 'done' : st, st === 'done' ? 'Done' : null);
    const runningStep = steps.filter((s) => s.status === 'running').map((s) => s.name);
    const last = (job.progress || [])[job.progress.length - 1];
    const msg = st === 'running'
      ? (runningStep.length ? `Running: ${runningStep.join(', ')}` : last ? `${last.step}: ${last.status}` : 'Working…')
      : st === 'failed' ? `Failed: ${job.error || 'unknown error'}` : `Finished. ${plural(steps.length, 'step')}, ${fmtNum(tokens)} tokens.`;
    const m = $('.job-msg', el);
    if (m.textContent !== msg) m.textContent = msg;
    $('.job-steps', el).innerHTML = steps.map((s) => `
      <li>${s.status === 'running' ? '<span class="spinner" aria-hidden="true"></span>' : `<span class="dot ${esc(s.status)}" aria-hidden="true"></span>`}
        <span>${esc(s.name)} <span class="sr-only">${esc(s.status)}</span>${s.error ? ` <span class="small" style="color:var(--red)">${esc(s.error)}</span>` : ''}</span>
        <span class="small muted">${s.attempts ? esc(plural(s.attempts, 'attempt')) : ''}</span>
        <span class="small muted right">${s.tokens ? esc(fmtNum(s.tokens)) + ' tok' : ''}</span></li>`).join('');
  }

  /** Poll GET /api/jobs/<id> every 1.5s, rendering live progress into #elId (looked up each tick). */
  function trackJob(jobId, elId) {
    return new Promise((resolve) => {
      const tick = async () => {
        let job;
        try { job = await GET(`/api/jobs/${enc(jobId)}`); } catch (e) {
          if (e.status === 401) return resolve({ status: 'failed', error: e.message });
          setTimeout(tick, 3000); return;
        }
        renderJobInto(document.getElementById(elId), job);
        if (job.status === 'running') setTimeout(tick, 1500); else resolve(job);
      };
      tick();
    });
  }

  // =====================================================================
  // Router
  // =====================================================================

  const SCREENS = {
    products: renderProducts, sources: renderSources, claims: renderClaims, decisions: renderDecisions,
    style: renderStyle, create: renderCreate, review: renderReview, gaps: renderGaps, quality: renderQuality,
    settings: renderSettings,
  };
  let renderSeq = 0;

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, '');
    const parts = raw.split('/').filter(Boolean).map((x) => { try { return decodeURIComponent(x); } catch (e) { return x; } });
    return { name: SCREENS[parts[0]] ? parts[0] : 'products', args: parts.slice(1) };
  }

  async function route(opts) {
    if (!S.me) return;
    const { name, args } = parseHash();
    $$('.sidenav a').forEach((a) => {
      if (a.dataset.nav === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    const seq = ++renderSeq;
    const main = $('#main');
    const scroll = opts && opts.keepScroll ? window.scrollY : 0;
    if (!(opts && opts.keepScroll)) main.innerHTML = '<div class="loading">Loading…</div>';
    let html;
    try { html = await SCREENS[name](args); } catch (e) {
      if (e.status === 401) return;
      html = errorBox(e);
    }
    if (seq !== renderSeq) return;
    main.innerHTML = html;
    if (opts && opts.keepScroll) window.scrollTo(0, scroll);
    else { window.scrollTo(0, 0); }
    const after = S.after; S.after = null;
    if (after) after();
  }
  const rerender = () => route({ keepScroll: true });

  function needProduct() {
    const p = current();
    if (p) return null;
    return empty('No product selected', 'Create a product first, then add its sources.',
      '<a class="btn btn-primary" href="#/products">Go to Products</a>');
  }

  function pageHead(title, sub, right) {
    return `<div class="page-head"><div><h1>${esc(title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ''}</div>${right ? `<div class="row">${right}</div>` : ''}</div>`;
  }

  // =====================================================================
  // Sign in / boot
  // =====================================================================

  function showSignin(msg) {
    S.me = null;
    $('#app').hidden = true;
    $('#signin').hidden = false;
    $('#signin-error').textContent = msg || '';
    const em = $('#signin-form [name=email]');
    if (em) em.focus();
  }

  async function boot() {
    try {
      S.me = await GET('/api/me');
    } catch (e) {
      if (e.status !== 401) showSignin(e.message);
      return;
    }
    $('#signin').hidden = true;
    $('#app').hidden = false;
    $('#ws-name').textContent = S.me.workspace.name;
    $('#user-email').textContent = `${S.me.user.email} · ${roles().join(', ')}`;
    try { await loadProducts(); } catch (e) { toast(e.message, 'err'); }
    route();
  }

  // =====================================================================
  // 1. Products
  // =====================================================================

  async function renderProducts() {
    await loadProducts();
    const cards = S.products.map(productCard).join('');
    return `${pageHead('Products', 'Each product has its own sources, claims registry, style and positioning.')}
      ${S.products.length ? `<div class="grid-2">${cards}</div>` :
        empty('No products yet', allowed('product.create') ? 'Create your first product below, then add its documentation.' : 'Ask an admin to create a product.')}
      ${allowed('product.create') ? createProductForm() : ''}`;
  }

  function productCard(p) {
    const st = p.kb_status || {};
    const srcs = st.sources || {};
    const isCur = p.id === S.pid;
    return `<section class="panel product-card${isCur ? ' is-current' : ''}" aria-label="${esc(p.name)}">
      <div class="row-between">
        <div><h2 style="margin:0">${esc(p.name)}</h2>
          <div class="small muted">${esc(p.company || '—')} · prefix ${chip(p.claim_prefix)}</div></div>
        <div class="row">${badge(st.state || 'incomplete')}${isCur ? '<span class="badge b-accent">Current</span>' : ''}</div>
      </div>
      <div class="stat-row">
        <div class="stat"><span class="num">${fmtNum(st.verified || 0)}</span><span class="lbl">verified claims</span></div>
        <div class="stat"><span class="num">${fmtNum(st.needs_review || 0)}</span><span class="lbl">need review</span></div>
        <div class="stat"><span class="num">${fmtNum(srcs.truth || 0)}</span><span class="lbl">truth</span></div>
        <div class="stat"><span class="num">${fmtNum(srcs.style || 0)}</span><span class="lbl">style</span></div>
        <div class="stat"><span class="num">${fmtNum(srcs.positioning || 0)}</span><span class="lbl">positioning</span></div>
        <div class="stat"><span class="num">${fmtNum(srcs.evidence || 0)}</span><span class="lbl">evidence</span></div>
      </div>
      ${(st.blockers || []).length ? `<ul class="msg-list">${st.blockers.map((b) => `<li class="block">${esc(b)}</li>`).join('')}</ul>` : ''}
      ${(st.warnings || []).length ? `<ul class="msg-list">${st.warnings.map((w) => `<li class="warn">${esc(w)}</li>`).join('')}</ul>` : ''}
      <div><h4>Onboarding</h4><ul class="checklist">${(p.checklist || []).map((c) =>
        `<li><span class="check-dot${c.done ? ' done' : ''}" aria-hidden="true">${c.done ? '✓' : ''}</span>${esc(c.step)}<span class="sr-only">${c.done ? ' (done)' : ' (to do)'}</span></li>`).join('')}</ul></div>
      <div class="row">
        ${isCur ? '' : `<button type="button" class="btn btn-sm" data-action="select-product" data-pid="${esc(p.id)}">Make current</button>`}
        <button type="button" class="btn btn-sm" data-action="goto" data-pid="${esc(p.id)}" data-href="#/sources">Sources</button>
        <button type="button" class="btn btn-sm" data-action="goto" data-pid="${esc(p.id)}" data-href="#/claims">Review claims</button>
        <button type="button" class="btn btn-sm" data-action="goto" data-pid="${esc(p.id)}" data-href="#/create">Create content</button>
      </div>
    </section>`;
  }

  function createProductForm() {
    return `<section class="panel section-gap">
      <div class="panel-head"><h2>New product</h2></div>
      <form data-form="create-product" class="stack" novalidate>
        <div class="form-grid">
          <label class="field"><span>Name</span><input type="text" name="name" required placeholder="e.g. Lumen Hub"></label>
          <label class="field"><span>Claim prefix</span><input type="text" name="claim_prefix" required data-upper pattern="[A-Z][A-Z0-9]{1,15}" maxlength="16" placeholder="e.g. LUMEN">
            <span class="field-hint">Uppercase letters and digits. Claim IDs look like PREFIX-001 and are permanent.</span></label>
          <label class="field"><span>Company</span><input type="text" name="company" placeholder="optional"></label>
        </div>
        <fieldset><legend>High-risk categories</legend>
          <p class="field-hint" style="margin-top:0">Claims in these categories always enter as needs-review, need compliance sign-off, and can't be bulk-confirmed.</p>
          <div class="checks">${CATEGORIES.map((c) => `<label><input type="checkbox" name="high_risk_categories" value="${esc(c)}"${DEFAULT_HIGH_RISK.includes(c) ? ' checked' : ''}> ${esc(c)}</label>`).join('')}</div>
        </fieldset>
        <label class="field"><span>Synthetic buyer persona (optional JSON)</span>
          <textarea name="buyer_persona" class="code" style="min-height:110px" placeholder='{"name": "…", "role": "…", "priorities": ["…"], "objections": ["…"], "language": ["…"]}'></textarea>
          <span class="field-hint">Enables the synthetic-buyer checker. Leave blank to skip.</span></label>
        <p class="form-error" role="alert"></p>
        <div><button type="submit" class="btn btn-primary">Create product</button></div>
      </form>
    </section>`;
  }

  async function submitCreateProduct(form) {
    const fd = new FormData(form);
    const err = $('.form-error', form);
    const name = String(fd.get('name') || '').trim();
    const prefix = String(fd.get('claim_prefix') || '').trim().toUpperCase();
    if (!name) { err.textContent = 'Name is required.'; return; }
    if (!/^[A-Z][A-Z0-9]{1,15}$/.test(prefix)) { err.textContent = 'Claim prefix must be 2–16 uppercase letters or digits, starting with a letter.'; return; }
    let persona = null;
    const raw = String(fd.get('buyer_persona') || '').trim();
    if (raw) {
      try { persona = JSON.parse(raw); } catch (e) { err.textContent = 'Buyer persona is not valid JSON: ' + e.message; return; }
      if (!persona || typeof persona !== 'object' || Array.isArray(persona)) { err.textContent = 'Buyer persona must be a JSON object.'; return; }
    }
    const body = { name, claim_prefix: prefix, company: String(fd.get('company') || '').trim(),
      high_risk_categories: fd.getAll('high_risk_categories'), buyer_persona: persona };
    try {
      const p = await POST('/api/products', body);
      toast(`Created ${p.name}.`, 'ok');
      setProduct(p.id);
      location.hash = '#/sources';
      await loadProducts();
      route();
    } catch (e) { err.textContent = e.message; }
  }

  // =====================================================================
  // 2. Sources
  // =====================================================================

  const SOURCE_TYPES = [
    ['truth', 'Truth sources', 'Product docs, specs and release notes. The only sources that can make facts.'],
    ['style', 'Style examples', 'Example copy. Shapes voice and cadence; never a source of facts.'],
    ['positioning', 'Positioning material', 'Positioning and messaging. Shapes angle and proof points; never a source of facts.'],
    ['evidence', 'Evidence', 'Voice-of-customer data. Backs market-evidence claims only, always reviewed. Confidential.'],
  ];

  async function renderSources() {
    const np = needProduct(); if (np) return np;
    const pid = S.pid;
    const [prod, sources] = await Promise.all([GET(P(pid)), GET(`${P(pid)}/sources`)]);
    Object.assign(current(), prod);
    const st = prod.kb_status || {};
    const byId = {}; sources.forEach((s) => { byId[s.id] = s; });
    const stl = st.staleness || {};
    const staleNames = (st.stale_sources || []).map((id) => (byId[id] ? byId[id].title : id));
    const listIds = (arr) => (arr || []).map((x) => (typeof x === 'string' ? x : x.id || x.claim_id || JSON.stringify(x)));

    const kb = `<section class="panel">
      <div class="panel-head"><h2>Knowledge base ${badge(st.state || 'incomplete')}</h2>
        ${allowed('ingest') ? `<button type="button" class="btn btn-primary" data-action="ingest">Build knowledge base</button>` : ''}</div>
      <div class="stat-row">
        <div class="stat"><span class="num">${fmtNum(st.verified || 0)}</span><span class="lbl">verified claims</span></div>
        <div class="stat"><span class="num">${fmtNum(st.needs_review || 0)}</span><span class="lbl">need review</span></div>
        <div class="stat"><span class="num">${fmtDate(st.updated_at) || '—'}</span><span class="lbl">status updated</span></div>
      </div>
      ${(st.blockers || []).length ? `<div class="error-box section-gap"><strong>Blocks generation:</strong><ul class="msg-list">${st.blockers.map((b) => `<li>${esc(b)}</li>`).join('')}</ul></div>` : ''}
      ${(st.warnings || []).length ? `<div class="warn-box section-gap"><ul class="msg-list">${st.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
      ${staleNames.length ? `<div class="section-gap"><h4>Changed since the last build</h4><p>${chips(staleNames)}</p>
        <div class="grid-3 small">
          <div><strong>${fmtNum(listIds(stl.claims).length)}</strong> claims affected ${listIds(stl.claims).length ? `<div>${chips(listIds(stl.claims).slice(0, 30))}${listIds(stl.claims).length > 30 ? ' …' : ''}</div>` : ''}</div>
          <div><strong>${fmtNum(listIds(stl.content_items).length)}</strong> content items affected ${listIds(stl.content_items).map((id) => `<div><a href="#/review/${esc(enc(id))}">${esc(id)}</a></div>`).join('')}</div>
          <div><strong>${fmtNum(listIds(stl.conflicts).length)}</strong> conflicts affected</div>
        </div>
        <p class="muted small">Rebuild the knowledge base to pick up the changes. Rulings survive a rebuild.</p></div>` : ''}
      <div id="ingest-job"></div>
    </section>`;

    const addForms = allowed('source.add') ? `<div class="grid-2 section-gap">
      <section class="panel">
        <div class="panel-head"><h2>Upload files</h2></div>
        <form data-form="upload" class="stack" novalidate>
          <label class="field"><span>Source type</span>
            <select name="type">${SOURCE_TYPES.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join('')}</select></label>
          <label class="field"><span>Files</span>
            <input type="file" name="files" multiple required accept=".pdf,.docx,.pptx,.md,.markdown,.html,.htm,.txt,.json,.csv">
            <span class="field-hint">PDF, DOCX, PPTX, Markdown, HTML or plain text. Evidence: JSON or CSV.</span></label>
          <p class="form-error" role="alert"></p>
          <div><button type="submit" class="btn btn-primary">Upload</button></div>
          <div class="upload-log small"></div>
        </form>
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Import a docs site</h2></div>
        <form data-form="import" class="stack" novalidate>
          <label class="field"><span>Base URL</span><input type="url" name="base" required placeholder="https://docs.example.com"></label>
          <div class="form-grid">
            <label class="field"><span>Mode</span><select name="mode">
              <option value="llms">llms.txt</option><option value="sitemap">sitemap.xml</option><option value="prefix">URL prefix crawl</option></select></label>
            <label class="field"><span>Page limit</span><input type="number" name="limit" value="300" min="1" max="5000"></label>
          </div>
          <p class="field-hint">Imports a snapshot as truth sources with a manifest (URL, fetch time, hash). Refreshes only when you ask.</p>
          <p class="form-error" role="alert"></p>
          <div><button type="submit" class="btn btn-primary">Import snapshot</button></div>
        </form>
        <div id="import-job"></div>
      </section>
    </div>` : '';

    const tables = SOURCE_TYPES.map(([type, label, hint]) => {
      const rows = sources.filter((s) => s.type === type);
      return `<section class="panel">
        <div class="panel-head"><div><h2>${esc(label)} <span class="muted">(${rows.filter((r) => r.status === 'active').length})</span></h2>
          <p class="small muted" style="margin:0">${esc(hint)}</p></div></div>
        ${rows.length ? `<div class="table-wrap"><table class="table">
          <thead><tr><th>Title</th><th>Kind</th><th>Updated</th><th class="right">Words</th><th>Status</th><th>SHA-256</th><th>Origin</th><th></th></tr></thead>
          <tbody>${rows.map((s) => `<tr>
            <td><strong>${esc(s.title)}</strong>${(st.stale_sources || []).includes(s.id) ? ' ' + badge('stale', 'Changed') : ''}</td>
            <td>${badge(s.kind)}</td>
            <td class="nowrap">${esc(s.updated || '—')}<div class="small muted">fetched ${esc(fmtDay(s.fetched_at))}</div></td>
            <td class="right">${fmtNum(s.words)}</td>
            <td>${badge(s.status)}</td>
            <td><code title="${esc(s.sha256)}">${esc(shortSha(s.sha256))}</code></td>
            <td class="small">${s.origin && /^https?:/.test(s.origin.value || '') ? `<a href="${esc(s.origin.value)}" target="_blank" rel="noopener noreferrer">${esc(s.origin.value)}</a>` : esc(s.origin ? s.origin.value : '')}</td>
            <td class="nowrap right">
              <button type="button" class="btn btn-sm" data-action="view-source" data-sid="${esc(s.id)}">View text</button>
              ${allowed('source.remove') && s.status === 'active' ? `<button type="button" class="btn btn-sm btn-danger" data-action="remove-source" data-sid="${esc(s.id)}" data-title="${esc(s.title)}">Remove</button>` : ''}
            </td></tr>`).join('')}</tbody></table></div>`
        : `<p class="muted small" style="margin:0">None yet.${type === 'truth' ? ' Truth sources are required before any content can be generated.' : type === 'evidence' ? ' Optional.' : ' Missing sources show a warning but don’t block.'}</p>`}
      </section>`;
    }).join('');

    return `${pageHead('Sources', `${prod.name}: the material the knowledge base is built from.`)}
      ${kb}${addForms}<div class="section-gap">${tables}</div>`;
  }

  function readFileB64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => { const s = String(r.result); resolve(s.slice(s.indexOf(',') + 1)); };
      r.onerror = () => reject(new Error(`Could not read ${file.name}`));
      r.readAsDataURL(file);
    });
  }

  async function submitUpload(form) {
    const err = $('.form-error', form); err.textContent = '';
    const type = form.elements.type.value;
    const files = Array.from(form.elements.files.files || []);
    if (!files.length) { err.textContent = 'Choose at least one file.'; return; }
    const log = $('.upload-log', form);
    const btn = $('button[type=submit]', form); btn.disabled = true;
    const lines = [];
    let changedAny = false;
    for (const f of files) {
      lines.push(`<div>Uploading ${esc(f.name)}…</div>`); log.innerHTML = lines.join('');
      try {
        const content_base64 = await readFileB64(f);
        const res = await POST(`${P(S.pid)}/sources`, { type, name: f.name, content_base64 });
        changedAny = changedAny || res.changed;
        lines[lines.length - 1] = `<div>✓ ${esc(f.name)}: ${res.changed ? 'added' : 'unchanged (same content)'}${res.staleness ? `, affects ${fmtNum((res.staleness.claims || []).length)} claims and ${fmtNum((res.staleness.content_items || []).length)} content items` : ''}</div>`;
      } catch (e) {
        lines[lines.length - 1] = `<div style="color:var(--red)">✕ ${esc(f.name)}: ${esc(e.message)}</div>`;
      }
      log.innerHTML = lines.join('');
    }
    btn.disabled = false;
    if (changedAny) { toast('Sources updated. Rebuild the knowledge base to use them.', 'ok'); setTimeout(rerender, 900); }
  }

  async function submitImport(form) {
    const err = $('.form-error', form); err.textContent = '';
    const base = form.elements.base.value.trim();
    if (!/^https?:\/\//.test(base)) { err.textContent = 'Enter a full http(s) URL.'; return; }
    const limit = parseInt(form.elements.limit.value, 10) || 300;
    try {
      const { job_id } = await POST(`${P(S.pid)}/sources/import`, { base, mode: form.elements.mode.value, limit });
      $('#import-job').innerHTML = jobBox('import-job-box', `Importing ${base}`);
      const job = await trackJob(job_id, 'import-job-box');
      const box = document.getElementById('import-job-box');
      if (job.status === 'done' && job.result) {
        const r = job.result;
        if (box) $('.job-result', box).innerHTML = `<p class="small">${fmtNum(r.pages)} pages, ${fmtNum((r.changed || []).length)} changed.</p>`;
        toast(`Import finished: ${r.pages} pages.`, 'ok');
        if (parseHash().name === 'sources') setTimeout(rerender, 1200);
      } else toast(`Import failed: ${job.error || ''}`, 'err');
    } catch (e) { err.textContent = e.message; }
  }

  async function runIngest() {
    const pid = S.pid;
    if (!(await confirmEstimate(pid, 'ingest', 'knowledge base build'))) return;
    try {
      const { job_id } = await POST(`${P(pid)}/ingest`, {});
      const host = $('#ingest-job');
      if (host) host.innerHTML = jobBox('ingest-job-box', 'Building knowledge base');
      const job = await trackJob(job_id, 'ingest-job-box');
      const box = document.getElementById('ingest-job-box');
      if (job.status === 'done') {
        const r = job.result || {};
        if (box) {
          $('.job-result', box).innerHTML = `<p class="small">${fmtNum(r.claims)} claims in the registry.
            ${(r.failed_sources || []).length ? `<span style="color:var(--red)">Failed sources: ${esc((r.failed_sources || []).map((f) => f.id || f.source_id || f).join(', '))}</span>` : ''}</p>
            <a class="btn btn-sm" href="#/claims">Review claims</a>`;
        }
        toast('Knowledge base built.', 'ok');
        await loadProducts();
      } else toast(`Build failed: ${job.error || ''}`, 'err');
    } catch (e) { toast(e.message, 'err'); }
  }

  async function viewSource(sid) {
    try {
      const d = await GET(`${P(S.pid)}/sources/${enc(sid)}`);
      const s = d.source;
      await modal({
        title: s.title, wide: true,
        body: `<p class="small muted">${badge(s.type, s.type)} ${badge(s.kind)} · ${fmtNum(s.words)} words · sha <code>${esc(shortSha(s.sha256))}</code> · ${esc(s.origin ? s.origin.value : '')}</p>
          <p class="small muted">Normalized text blocks. Claim quotes and locations come from these.</p>
          <div class="blocks-view">${(d.blocks || []).map((b) => `<div class="blk"><div class="loc">${esc(b.loc)}</div>${
            b.heading_path && b.heading_path.length && b.text === b.heading_path[b.heading_path.length - 1] ? `<strong>${esc(b.text)}</strong>` : esc(b.text)}</div>`).join('') || '<p class="muted">No text blocks.</p>'}</div>`,
        actions: [{ label: 'Close', value: null }],
      });
    } catch (e) { toast(e.message, 'err'); }
  }

  async function removeSource(sid, title) {
    if (!(await confirmDialog('Remove source?', `<p>Remove <strong>${esc(title)}</strong>? Claims from it will be deprecated on the next build, and approved content citing them will be re-flagged.</p>`, 'Remove source', 'danger-primary'))) return;
    try {
      const r = await DEL(`${P(S.pid)}/sources/${enc(sid)}`, {});
      const st = r.staleness || {};
      toast(`Removed. Affects ${fmtNum((st.claims || []).length)} claims, ${fmtNum((st.content_items || []).length)} content items.`, 'ok');
      rerender();
    } catch (e) { toast(e.message, 'err'); }
  }

  // =====================================================================
  // 3. Claims
  // =====================================================================

  async function renderClaims(args) {
    const np = needProduct(); if (np) return np;
    const tab = ['queue', 'all', 'conflicts', 'rulings'].includes(args[0]) ? args[0] : 'queue';
    const tabs = [['queue', 'Review queue'], ['all', 'All claims'], ['conflicts', 'Conflicts'], ['rulings', 'Rulings log']];
    const head = `${pageHead('Claims', `${current().name}: the Source-of-Truth registry. Only verified claims can be cited.`)}
      <nav class="tabs" role="tablist">${tabs.map(([k, l]) => `<a role="tab" href="#/claims/${k}" aria-selected="${k === tab}">${esc(l)}</a>`).join('')}</nav>`;
    let body;
    if (tab === 'queue') body = await claimsQueue();
    else if (tab === 'all') body = await claimsAll();
    else if (tab === 'conflicts') body = await claimsConflicts();
    else body = await claimsRulings();
    return head + body;
  }

  async function sourceMap() {
    const sources = await GET(`${P(S.pid)}/sources`);
    const m = {}; sources.forEach((s) => { m[s.id] = s; });
    return m;
  }

  function claimSourceBlock(c, srcs) {
    const s = srcs ? srcs[c.source_id] : null;
    const title = c.source_title || (s && s.title) || c.source_id;
    const url = c.source_url || (s && s.origin && /^https?:/.test(s.origin.value || '') ? s.origin.value : null);
    return `<blockquote class="quote">${esc(c.quote)}</blockquote>
      <div class="src-meta">${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>` : esc(title)}
        · ${esc(c.location)}${s ? ` · ${esc(s.kind || '')}${s.updated ? ', updated ' + esc(s.updated) : ''}` : ''}</div>`;
  }

  async function claimsQueue() {
    const [groups, srcs] = await Promise.all([GET(`${P(S.pid)}/review-queue`), sourceMap()]);
    S.queueGroups = groups;
    if (!groups.length) return empty('Nothing to review', 'Every claim has been ruled on. New sources add claims here after the next build.');
    const highRisk = current().high_risk_categories || [];
    const total = groups.reduce((a, g) => a + g.claims.length, 0);
    return `<p class="muted">${plural(total, 'claim')} in ${plural(groups.length, 'group')}. Confirming makes a claim citable; it doesn't change the document.
      Reject and "Doc is wrong" need a note: it is stored verbatim${' '}and sent to the docs owner.</p>
      ${groups.map((g, gi) => `<section class="panel">
        <div class="group-head"><div class="row"><h3 style="margin:0">${esc(g.theme)}</h3>${badge('', g.category)}
          ${highRisk.includes(g.category) ? '<span class="badge b-red">High-risk: review one by one</span>' : ''}
          <span class="muted small">${plural(g.claims.length, 'claim')}</span></div>
          ${g.bulk_allowed && allowed('claim.confirm') && g.claims.length > 1 ? `<button type="button" class="btn btn-sm" data-action="bulk-confirm" data-g="${gi}">Confirm all ${g.claims.length}</button>` : ''}
        </div>
        ${g.claims.map((c) => claimReviewCard(c, srcs, highRisk)).join('')}
      </section>`).join('')}`;
  }

  function claimReviewCard(c, srcs, highRisk) {
    const hr = highRisk.includes(c.category);
    const canConfirm = allowed('claim.confirm') && (!hr || allowed('claim.confirm-high-risk'));
    return `<article class="claim-card" data-cid="${esc(c.id)}">
      <div class="side-by-side">
        <div>
          <div class="row" style="margin-bottom:6px">${chip(c.id)} ${badge(c.status)} ${badge('', c.category)} ${badge(c.confidence === 'low' ? 'block' : '', `${c.confidence} confidence`)}
            ${c.count !== null && c.count !== undefined ? `<span class="badge b-blue">count ${esc(c.count)}</span>` : ''}</div>
          <div>${esc(c.text)}</div>
          ${c.status_reason ? `<div class="small muted" style="margin-top:4px">${esc(c.status_reason)}</div>` : ''}
        </div>
        <div>${claimSourceBlock(c, srcs)}</div>
      </div>
      <div class="claim-actions">
        <label class="sr-only" for="note-${esc(c.id)}">Note for ${esc(c.id)}</label>
        <textarea id="note-${esc(c.id)}" name="note" placeholder="Note (required for Reject and Doc is wrong)"></textarea>
        ${canConfirm ? `<button type="button" class="btn btn-sm btn-primary" data-action="rule" data-kind="confirmed">Confirm</button>` :
          hr ? '<span class="small muted">Compliance sign-off needed to confirm</span>' : ''}
        ${allowed('claim.deprioritize') ? `<button type="button" class="btn btn-sm" data-action="rule" data-kind="deprioritized">Deprioritize</button>` : ''}
        ${allowed('claim.reject') ? `<button type="button" class="btn btn-sm btn-danger" data-action="rule" data-kind="rejected">Reject</button>` : ''}
        ${allowed('claim.doc-wrong') ? `<button type="button" class="btn btn-sm btn-danger" data-action="rule" data-kind="doc-wrong">Doc is wrong</button>` : ''}
      </div>
      <p class="form-error" role="alert"></p>
    </article>`;
  }

  async function ruleClaim(btn) {
    const card = btn.closest('[data-cid]');
    const cid = card.dataset.cid;
    const kind = btn.dataset.kind;
    const ta = $('textarea', card);
    const note = ta ? ta.value.trim() : '';
    const err = $('.form-error', card);
    if ((kind === 'rejected' || kind === 'doc-wrong') && !note) {
      err.textContent = 'Say why. The note is stored verbatim and goes to the docs owner.';
      if (ta) ta.focus();
      return;
    }
    $$('button', card).forEach((b) => { b.disabled = true; });
    try {
      const c = await POST(`${P(S.pid)}/claims/${enc(cid)}/rule`, { kind, note });
      toast(`${cid}: ${statusLabel(kind)} → ${statusLabel(c.status)}.`, 'ok');
      rerender();
      loadProducts().catch(() => {});
    } catch (e) {
      err.textContent = e.message;
      $$('button', card).forEach((b) => { b.disabled = false; });
    }
  }

  async function bulkConfirm(gi) {
    const g = S.queueGroups[gi];
    if (!g) return;
    const r = await modal({
      title: `Confirm ${g.claims.length} claims?`,
      body: `<p>Confirm every claim in <strong>${esc(g.theme)}</strong> (${esc(g.category)}). Each becomes citable.</p>
        <label class="field"><span>Note (optional)</span><textarea name="note"></textarea></label>`,
      actions: [{ label: 'Cancel', value: null }, { label: `Confirm ${g.claims.length}`, value: 'ok', kind: 'primary' }],
    });
    if (r.value !== 'ok') return;
    try {
      await POST(`${P(S.pid)}/claims/bulk-rule`, { claim_ids: g.claims.map((c) => c.id), kind: 'confirmed', note: r.data.note || '' });
      toast(`Confirmed ${g.claims.length} claims.`, 'ok');
      rerender();
      loadProducts().catch(() => {});
    } catch (e) { toast(e.message, 'err'); }
  }

  async function claimsAll() {
    const f = S.claimFilters;
    const qs = new URLSearchParams({ limit: '500' });
    if (f.status) qs.set('status', f.status);
    if (f.category) qs.set('category', f.category);
    if (f.q) qs.set('q', f.q);
    const d = await GET(`${P(S.pid)}/claims?${qs}`);
    const filters = `<form data-form="claim-filters" class="inline-form panel tight" role="search">
      <label class="field"><span>Status</span><select name="status">
        ${['', 'verified', 'needs-review', 'deprecated'].map((s) => `<option value="${s}"${f.status === s ? ' selected' : ''}>${s ? esc(statusLabel(s)) : 'Any status'}</option>`).join('')}</select></label>
      <label class="field"><span>Category</span><select name="category">
        <option value="">Any category</option>${CATEGORIES.map((c) => `<option value="${c}"${f.category === c ? ' selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
      <label class="field grow"><span>Search</span><input type="search" name="q" value="${esc(f.q)}" placeholder="Text or claim ID"></label>
      <button type="submit" class="btn btn-primary">Filter</button>
      <button type="button" class="btn" data-action="clear-claim-filters">Clear</button>
    </form>`;
    const rows = d.claims.map((c) => {
      const ud = c.user_decision;
      return `<tr>
        <td class="nowrap">${chip(c.id)}</td>
        <td>${esc(c.text)}<div class="src-meta">${esc(c.source_title)} · ${esc(c.location)}</div></td>
        <td>${esc(c.category)}</td>
        <td>${esc(c.confidence)}</td>
        <td>${badge(c.status)}${c.deprioritized ? ' ' + badge('deprioritized') : ''}</td>
        <td class="small">${ud ? `${badge(ud.kind)}<div>${esc(ud.author)}, ${esc(fmtDay(ud.at))}</div>${ud.note ? `<div class="muted">“${esc(ud.note)}”</div>` : ''}` : '<span class="muted">—</span>'}</td>
        <td class="small muted">${esc(c.status_reason || '')}</td>
      </tr>`;
    }).join('');
    return `${filters}
      <section class="panel section-gap">
        <p class="small muted">${fmtNum(d.total)} matching${d.total > d.claims.length ? `, showing the first ${fmtNum(d.claims.length)}` : ''}.</p>
        ${d.claims.length ? `<div class="table-wrap"><table class="table">
          <thead><tr><th>ID</th><th>Claim</th><th>Category</th><th>Confidence</th><th>Status</th><th>Decision</th><th>Status reason</th></tr></thead>
          <tbody>${rows}</tbody></table></div>` : empty('No claims match', 'Change the filters, or build the knowledge base from the Sources screen.')}
      </section>`;
  }

  async function claimsConflicts() {
    const list = await GET(`${P(S.pid)}/conflicts`);
    if (!list.length) return empty('No conflicts', 'When truth sources disagree, both claims show up here for a ruling.');
    const canRule = allowed('conflict.rule');
    const KIND = { contradiction: 'Contradiction', 'absolute-vs-exception': 'Absolute vs exception', 'living-vs-changelog': 'Living page vs changelog' };
    return `<p class="muted">Conflicts are never resolved silently. Until you rule, the gate uses the interim default shown below, labeled as a default.</p>
      ${list.map((c) => {
        const [a, b] = c.claims;
        const claimCol = (cl, label) => cl ? `<div class="conflict-claim${c.interim_default === cl.id ? ' is-default' : ''}">
            <div class="row" style="margin-bottom:6px"><strong>${esc(label)}</strong> ${chip(cl.id)} ${badge(cl.status)}
              ${c.interim_default === cl.id ? '<span class="badge b-blue">Interim default</span>' : ''}</div>
            <div>${esc(cl.text)}</div>
            <blockquote class="quote" style="margin-top:6px">${esc(cl.quote)}</blockquote>
            <div class="src-meta">${esc(cl.source_title)} · ${esc(cl.location)}<br>${badge(cl.source_kind)} ${cl.source_updated ? 'updated ' + esc(cl.source_updated) : 'no updated date'}</div>
          </div>` : '<div class="conflict-claim muted">Claim no longer in registry</div>';
        return `<section class="panel">
          <div class="panel-head"><div class="row"><h3 style="margin:0">${esc(KIND[c.kind] || c.kind)}</h3>${badge(c.status)}</div>
            <span class="small muted">${esc(fmtDate(c.created_at))}</span></div>
          <p>${esc(c.explanation)}</p>
          <div class="grid-2">${claimCol(a, 'A')}${claimCol(b, 'B')}</div>
          <div class="note-box section-gap"><strong>${c.interim_default ? 'Default, not a ruling:' : 'No default:'}</strong> ${esc(c.interim_label)}</div>
          ${c.status === 'open' && canRule ? `<form data-form="rule-conflict" data-id="${esc(c.id)}" class="stack section-gap" novalidate>
            <fieldset><legend>Ruling</legend><div class="checks">
              ${a ? `<label><input type="radio" name="keep" value="${esc(a.id)}"> Keep A (${esc(a.id)}): B is wrong</label>` : ''}
              ${b ? `<label><input type="radio" name="keep" value="${esc(b.id)}"> Keep B (${esc(b.id)}): A is wrong</label>` : ''}
              <label><input type="radio" name="keep" value=""> Both stand</label></div></fieldset>
            <label class="field"><span>Note (required)</span><textarea name="note" required placeholder="Why. Stored verbatim; the deprecated claim becomes a correction for the docs owner."></textarea></label>
            <p class="form-error" role="alert"></p>
            <div><button type="submit" class="btn btn-primary">Record ruling</button></div>
          </form>` : ''}
        </section>`;
      }).join('')}`;
  }

  async function submitRuleConflict(form) {
    const err = $('.form-error', form); err.textContent = '';
    const keep = form.querySelector('input[name=keep]:checked');
    const note = form.elements.note.value.trim();
    if (!keep) { err.textContent = 'Choose which claim is right, or that both stand.'; return; }
    if (!note) { err.textContent = 'A conflict ruling needs a note.'; form.elements.note.focus(); return; }
    try {
      await POST(`${P(S.pid)}/conflicts/${enc(form.dataset.id)}/rule`, { keep_claim_id: keep.value || null, note });
      toast('Ruling recorded.', 'ok');
      rerender();
    } catch (e) { err.textContent = e.message; }
  }

  async function claimsRulings() {
    const list = await GET(`${P(S.pid)}/rulings`);
    if (!list.length) return empty('No rulings yet', 'Confirmations, rejections, doc corrections and conflict rulings are logged here. Rulings outrank documents and survive rebuilds.');
    return `<section class="panel"><div class="table-wrap"><table class="table">
      <thead><tr><th>When</th><th>Target</th><th>Ruling</th><th>Note</th><th>By</th><th>Kept</th></tr></thead>
      <tbody>${list.map((r) => `<tr>
        <td class="nowrap small">${esc(fmtDate(r.created_at))}</td>
        <td><span class="small muted">${esc(r.target_kind)}</span> ${chip(r.target_id)}</td>
        <td>${badge(r.kind)}</td>
        <td>${r.note ? esc(r.note) : '<span class="muted">—</span>'}</td>
        <td class="small">${esc(r.author)}</td>
        <td>${r.target_kind === 'conflict' ? (r.keep_claim_id ? chip(r.keep_claim_id) : '<span class="small">both stand</span>') : ''}</td>
      </tr>`).join('')}</tbody></table></div></section>`;
  }

  // =====================================================================
  // 4. Decisions
  // =====================================================================

  function diffBox(diff) {
    if (!diff) return '';
    const added = diff.added || []; const removed = diff.removed || [];
    return `<section class="panel" aria-live="polite"><div class="panel-head"><h3>Guardrail changes from your last save</h3>
        <button type="button" class="btn btn-sm btn-ghost" data-action="dismiss-diff">Dismiss</button></div>
      ${!added.length && !removed.length ? '<p class="muted">No guardrails changed.</p>' : ''}
      ${added.length ? `<div class="ok-box"><strong>Added</strong><ul class="msg-list">${added.map((x) => `<li>+ ${esc(typeof x === 'string' ? x : x.rule)}</li>`).join('')}</ul></div>` : ''}
      ${removed.length ? `<div class="error-box section-gap"><strong>Removed</strong><ul class="msg-list">${removed.map((x) => `<li>− ${esc(typeof x === 'string' ? x : x.rule)}</li>`).join('')}</ul></div>` : ''}
    </section>`;
  }

  async function renderDecisions() {
    const np = needProduct(); if (np) return np;
    const list = await GET(`${P(S.pid)}/decisions`);
    const canEdit = allowed('decision.edit');
    const addForm = canEdit ? `<section class="panel">
      <div class="panel-head"><h2>Add a decision</h2></div>
      <form data-form="add-decision" class="stack" novalidate>
        <label class="field"><span>Decision, in plain language</span>
          <textarea name="text" required placeholder="e.g. Never call it 'the Lumen thermostat'. Lead with the cloud deployment."></textarea>
          <span class="field-hint">Stored verbatim. Each guardrail derived from it is listed so you can check it says what you meant.</span></label>
        <p class="form-error" role="alert"></p>
        <div><button type="submit" class="btn btn-primary">Save decision</button></div>
      </form></section>` : '';
    const cards = list.map((d) => `<section class="panel" data-did="${esc(d.id)}">
      <div class="panel-head"><div class="row">${chip(d.id)}<span class="small muted">${esc(d.author)} · ${esc(fmtDate(d.created_at))}</span></div>
        ${canEdit ? `<button type="button" class="btn btn-sm" data-action="toggle-edit-decision">Edit</button>` : ''}</div>
      <blockquote class="quote" style="font-size:14px;color:var(--text)">${esc(d.text)}</blockquote>
      <form data-form="edit-decision" data-id="${esc(d.id)}" class="stack section-gap" hidden novalidate>
        <label class="field"><span>Edit decision text</span><textarea name="text" required>${esc(d.text)}</textarea></label>
        <p class="field-hint">Saving re-derives this decision's guardrails and shows what changed.</p>
        <p class="form-error" role="alert"></p>
        <div class="row"><button type="submit" class="btn btn-primary btn-sm">Save</button><button type="button" class="btn btn-sm" data-action="toggle-edit-decision">Cancel</button></div>
      </form>
      <h4 class="section-gap">Derived guardrails</h4>
      ${(d.derived_guardrails || []).length ? `<table class="table"><thead><tr><th>Type</th><th>Terms</th><th>Rule</th></tr></thead><tbody>
        ${d.derived_guardrails.map((g) => `<tr><td>${badge('', g.type)}</td><td>${chips(g.terms)}</td><td>${esc(g.rule)}</td></tr>`).join('')}
      </tbody></table>` : '<p class="muted small">No guardrails derived.</p>'}
    </section>`).join('');
    return `${pageHead('Decisions', 'Plain-language rules from your team. They shape style and positioning. They never create product facts.')}
      ${diffBox(S.lastDiff)}${addForm}
      <div class="section-gap">${list.length ? cards : empty('No decisions yet', 'Add rules like naming conventions, banned words or what to lead with.')}</div>`;
  }

  async function submitDecision(form, id) {
    const err = $('.form-error', form); err.textContent = '';
    const text = form.elements.text.value.trim();
    if (!text) { err.textContent = 'Decision text is required.'; return; }
    try {
      const r = id ? await PUT(`${P(S.pid)}/decisions/${enc(id)}`, { text }) : await POST(`${P(S.pid)}/decisions`, { text });
      S.lastDiff = r.diff;
      toast(`Saved ${r.decision.id}.`, 'ok');
      route();
    } catch (e) { err.textContent = e.message; }
  }

  // =====================================================================
  // 5. Style & positioning
  // =====================================================================

  async function renderStyle() {
    const np = needProduct(); if (np) return np;
    const [sp, pack] = await Promise.all([GET(`${P(S.pid)}/style-profile`), GET(`${P(S.pid)}/positioning`).catch(() => null)]);
    const prof = sp.profile;
    const cal = sp.calibration;
    const head = pageHead('Style & positioning', 'Read-only rendered views. Change them through Decisions or by updating sources and rebuilding.');
    const stylePart = prof ? styleView(prof, cal, sp.threshold) : empty('No style profile yet', 'Add style examples (about 1,500 words across 3 pieces) and build the knowledge base.');
    const posPart = pack ? positioningView(pack) : empty('No positioning pack yet', 'Add positioning material and build the knowledge base.');
    return `${head}<h2>Style profile</h2>${stylePart}<h2 class="section-gap" style="margin-top:28px">Positioning pack</h2>${posPart}`;
  }

  function kvList(obj) {
    return `<dl class="kv">${Object.entries(obj || {}).map(([k, v]) => `<dt>${esc(k.replace(/_/g, ' '))}</dt><dd>${
      Array.isArray(v) ? (v.length ? esc(v.join(', ')) : '—') : v && typeof v === 'object' ? esc(JSON.stringify(v)) : esc(typeof v === 'number' ? fmtScore(v) : v)}</dd>`).join('')}</dl>`;
  }

  function styleView(p, cal, threshold) {
    const voc = p.vocabulary || {}; const nm = p.naming || {}; const fm = p.formatting || {}; const cons = p.consistency || {};
    const thr = threshold !== null && threshold !== undefined ? threshold : p.threshold;
    const calPanel = cal ? `<section class="panel">
      <div class="panel-head"><h3>Calibration</h3>${cal.meets_target ? '<span class="badge b-green">Meets AUC target</span>' : '<span class="badge b-amber">Below AUC target</span>'}</div>
      <div class="grid-4">
        <div class="kpi"><div class="num">${fmtScore(cal.auc)}</div><div class="lbl">AUC (target ${fmtScore(cal.target_auc)})</div></div>
        <div class="kpi"><div class="num">${fmtScore(cal.recommended_threshold)}</div><div class="lbl">Recommended threshold</div></div>
        <div class="kpi"><div class="num">${fmtNum(cal.on_brand)} / ${fmtNum(cal.off_brand)}</div><div class="lbl">On-brand / off-brand samples</div></div>
        <div class="kpi"><div class="num">${fmtScore(cal.on_mean)} / ${fmtScore(cal.off_mean)}</div><div class="lbl">Mean score on / off</div></div>
      </div>
      <p class="small muted section-gap">Scorer ${esc(cal.scorer || '')}, computed ${esc(fmtDate(cal.computed_at))}.
        Accepted threshold: <strong>${thr !== null && thr !== undefined ? esc(fmtScore(thr)) : 'none yet'}</strong>${current().style_threshold_accepted_by ? ` (by ${esc(current().style_threshold_accepted_by)})` : ''}.
        Until a threshold is accepted, style scores are informational.</p>
      ${allowed('style.accept-threshold') ? `<form data-form="accept-threshold" class="inline-form" novalidate>
        <label class="field"><span>Manual value (optional)</span><input type="number" name="threshold" step="0.001" min="0" max="1" placeholder="${esc(fmtScore(cal.recommended_threshold))}"></label>
        <button type="submit" class="btn btn-primary">Accept threshold</button>
        <span class="form-error" role="alert"></span></form>` : '<p class="small muted">Only an admin can accept the threshold.</p>'}
    </section>` : `<section class="panel"><p class="muted" style="margin:0">Not calibrated yet. Build the knowledge base to calibrate the style threshold.</p></section>`;
    return `<div class="grid-2">
      <section class="panel"><h3>Voice</h3><p>${esc((p.voice || {}).summary)}</p><ul>${((p.voice || {}).traits || []).map((t) => `<li>${esc(t)}</li>`).join('')}</ul></section>
      <section class="panel"><h3>Cadence</h3>${kvList(p.cadence)}</section>
      <section class="panel"><h3>Vocabulary</h3>
        <h4>Preferred</h4><p>${chips(voc.preferred) || '<span class="muted">—</span>'}</p>
        <h4>Avoid</h4><p>${chips(voc.avoid) || '<span class="muted">—</span>'}</p>
        <h4>Banned</h4><p>${(voc.banned || []).map((t) => `<span class="badge b-red">${esc(t)}</span>`).join(' ') || '<span class="muted">—</span>'}</p></section>
      <section class="panel"><h3>Naming</h3>
        <dl class="kv"><dt>Product name</dt><dd><strong>${esc(nm.product_name)}</strong></dd>
          <dt>Variants allowed</dt><dd>${chips(nm.variants_allowed) || '—'}</dd>
          <dt>Forbidden</dt><dd>${(nm.forbidden || []).map((t) => `<span class="badge b-red">${esc(t)}</span>`).join(' ') || '—'}</dd></dl>
        <h3 class="section-gap">Formatting</h3>
        <dl class="kv"><dt>Heading case</dt><dd>${esc(fm.heading_case)}</dd><dt>Lists</dt><dd>${esc(fm.list_style)}</dd></dl>
        ${(fm.notes || []).length ? `<ul class="small">${fm.notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}</section>
    </div>
    <section class="panel section-gap"><h3>Rubric</h3><table class="table"><thead><tr><th>Criterion</th><th class="right">Weight</th><th>Description</th></tr></thead>
      <tbody>${(p.rubric || []).map((r) => `<tr><td>${esc(r.criterion)}</td><td class="right">${esc(fmtScore(r.weight))}</td><td>${esc(r.description)}</td></tr>`).join('')}</tbody></table></section>
    <div class="grid-2 section-gap">
      <section class="panel"><h3>Consistency ${cons.ok ? '<span class="badge b-green">Consistent</span>' : '<span class="badge b-red">Issues</span>'}</h3>
        ${(cons.issues || []).length ? `<ul>${cons.issues.map((i) => `<li>${esc(typeof i === 'string' ? i : i.issue || JSON.stringify(i))}</li>`).join('')}</ul>` : '<p class="muted small">No consistency issues.</p>'}</section>
      <section class="panel"><h3>Corpus & decisions</h3>
        <p class="small">${fmtNum((p.corpus || {}).pieces)} pieces, ${fmtNum((p.corpus || {}).words)} words.</p>
        ${(p.derived_from_decisions || []).length ? `<ul class="small">${p.derived_from_decisions.map((d) => `<li>${chip(d.decision_id)} ${esc(d.rule)}</li>`).join('')}</ul>` : ''}</section>
    </div>
    <div class="section-gap">${calPanel}</div>`;
  }

  function positioningView(pk) {
    const themes = (pk.value_themes || []).map((t) => `<section class="panel tight">
      <h3>${esc(t.name)}</h3><p>${esc(t.message)}</p>
      <ul class="flag-list">${(t.proof_points || []).map((pp) => `<li>${badge(pp.status)}<span class="grow">${esc(pp.text)}</span>${chips(pp.claim_ids)}</li>`).join('')}</ul>
    </section>`).join('');
    return `<section class="panel">
      <h3>Positioning statement</h3><p>${esc(pk.positioning_statement)}</p>
      <dl class="kv"><dt>Category</dt><dd>${esc(pk.category)}</dd><dt>Generated</dt><dd>${esc(fmtDate(pk.generated_at))}</dd></dl>
    </section>
    <section class="panel"><h3>Competitive alternatives</h3><table class="table"><tbody>
      ${(pk.alternatives || []).map((a) => `<tr><td class="nowrap"><strong>${esc(a.name)}</strong></td><td>${esc(a.notes)}</td></tr>`).join('')}</tbody></table></section>
    <h3 class="section-gap">Value themes</h3>
    <p class="small muted">Proof points marked "needs claim" can't be used in copy until a verified claim backs them. They feed the Gaps report.</p>
    <div class="grid-2">${themes}</div>
    <h3 class="section-gap">Personas</h3>
    <div class="grid-2">${(pk.personas || []).map((p) => `<section class="panel tight">
      <div class="row-between"><h3 style="margin:0">${esc(p.name)}</h3>${p.stage ? badge('', p.stage) : ''}</div>
      <p class="small muted">${esc(p.role)}</p>
      <div class="grid-2 small"><div><h4>Pains</h4><ul>${(p.pains || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
        <div><h4>Goals</h4><ul>${(p.goals || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div></div>
    </section>`).join('')}</div>
    <div class="grid-2 section-gap">
      <section class="panel"><h3>Objections</h3><ul class="flag-list">${(pk.objections || []).map((o) => `<li><div><strong>${esc(o.text)}</strong><div class="small muted">${esc(o.response)}</div></div></li>`).join('')}</ul></section>
      <section class="panel"><h3>Awareness stages</h3><dl class="kv">${STAGES.filter((s) => (pk.stages || {})[s]).map((s) => `<dt>${esc(s)}</dt><dd>${esc(pk.stages[s])}</dd>`).join('')}</dl></section>
    </div>
    <div class="grid-2 section-gap">
      <section class="panel"><h3>Messaging</h3><dl class="kv">${Object.entries(pk.messaging || {}).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></section>
      <section class="panel"><h3>Guardrails</h3><ul class="flag-list">${(pk.guardrails || []).map((g) => `<li>${g.decision_id ? chip(g.decision_id) : ''}<div>${esc(g.rule)}${g.decision_quote ? `<div class="small muted">“${esc(g.decision_quote)}”</div>` : ''}</div></li>`).join('')}</ul></section>
    </div>`;
  }

  async function submitAcceptThreshold(form) {
    const err = $('.form-error', form); err.textContent = '';
    const raw = form.elements.threshold.value.trim();
    const body = {};
    if (raw) {
      const v = Number(raw);
      if (isNaN(v) || v < 0 || v > 1) { err.textContent = 'Threshold must be between 0 and 1.'; return; }
      body.threshold = v;
    }
    try {
      const p = await POST(`${P(S.pid)}/style/accept-threshold`, body);
      toast(`Style threshold set to ${fmtScore(p.style_threshold)}.`, 'ok');
      await loadProducts();
      rerender();
    } catch (e) { err.textContent = e.message; }
  }

  // =====================================================================
  // 6. Create
  // =====================================================================

  async function renderCreate() {
    const np = needProduct(); if (np) return np;
    const p = current();
    const [types, pack, briefs, items] = await Promise.all([
      S.contentTypes ? Promise.resolve(S.contentTypes) : GET('/api/content-types'),
      GET(`${P(S.pid)}/positioning`).catch(() => null),
      GET(`${P(S.pid)}/briefs`).catch(() => []),
      GET(`/api/content?product=${enc(S.pid)}`).catch(() => []),
    ]);
    S.contentTypes = types;
    const enabled = types.filter((t) => (p.content_types || []).includes(t.id));
    const personas = pack ? (pack.personas || []) : [];
    const st = p.kb_status || {};
    const itemByBrief = {}; items.forEach((i) => { itemByBrief[i.brief_id] = i; });
    const ready = !(st.blockers || []).length;
    const warn = !ready ? `<div class="error-box"><strong>Generation is blocked.</strong> ${esc((st.blockers || []).join(' '))} <a href="#/sources">Go to Sources</a></div>`
      : st.state !== 'ready' ? `<div class="warn-box">The knowledge base is ${esc(st.state)}. ${esc((st.warnings || []).join(' '))}</div>` : '';

    const form = `<section class="panel">
      <div class="panel-head"><h2>New brief</h2></div>
      <form data-form="brief" class="stack" novalidate>
        <div class="form-grid">
          <label class="field"><span>Content type</span><select name="content_type" required>
            ${enabled.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}${t.length_words ? ` (${esc(t.length_words.join('–'))} words)` : ''}</option>`).join('')}</select></label>
          <label class="field"><span>Title</span><input type="text" name="title" required placeholder="e.g. Lumen Hub for clinics"></label>
          <label class="field"><span>Audience</span><input type="text" name="audience" required list="personas-dl" placeholder="Pick a persona or type one">
            <datalist id="personas-dl">${personas.map((x) => `<option value="${esc(x.name)}">${esc(x.role || '')}</option>`).join('')}</datalist></label>
          <label class="field"><span>Awareness stage</span><select name="stage" required>
            ${STAGES.map((s) => `<option value="${s}"${s === 'problem-aware' ? ' selected' : ''}>${esc(s)}</option>`).join('')}</select></label>
          <label class="field span-2"><span>Goal</span><input type="text" name="goal" required placeholder="e.g. Book a walkthrough"></label>
          <label class="field span-2"><span>Notes</span><textarea name="notes" placeholder="Context for the strategist. Notes are not a source of facts."></textarea></label>
        </div>
        <fieldset><legend>Mandated wording (optional)</legend>
          <div id="mandated-rows" class="stack-sm"></div>
          <div class="row" style="margin-top:8px"><button type="button" class="btn btn-sm" data-action="add-mandated">Add wording</button></div>
          <p class="field-hint" style="margin-bottom:0">Checked by the gate like any other copy.</p>
        </fieldset>
        <p class="form-error" role="alert"></p>
        <div class="row"><button type="submit" class="btn btn-primary"${ready && allowed('brief.create') ? '' : ' disabled'}>Create brief and run</button>
          ${allowed('brief.create') ? '' : '<span class="small muted">Editors and admins can create briefs.</span>'}</div>
      </form>
      <div id="create-job"></div>
    </section>`;

    const quick = `<section class="panel">
      <div class="panel-head"><h2>Quick check</h2></div>
      <p class="small muted">Paste copy (with or without claim tags) to run it through the gate. No drafting, no revisions.</p>
      <form data-form="quick-check" class="stack" novalidate>
        <label class="field"><span class="sr-only">Copy to check</span><textarea name="draft" class="code" style="min-height:160px" placeholder="Paste Markdown copy here…"></textarea></label>
        <p class="form-error" role="alert"></p>
        <div><button type="submit" class="btn"${allowed('content.run') ? '' : ' disabled'}>Run quick check</button></div>
      </form>
      <div id="quick-result" aria-live="polite"></div>
    </section>`;

    const recent = briefs.length ? `<section class="panel section-gap"><div class="panel-head"><h2>Recent briefs</h2></div>
      <table class="table"><thead><tr><th>Title</th><th>Type</th><th>Audience</th><th>Stage</th><th>Created</th><th>Status</th><th></th></tr></thead><tbody>
      ${briefs.slice(0, 15).map((b) => { const it = itemByBrief[b.id]; return `<tr><td>${esc(b.title)}</td><td>${esc(b.content_type)}</td><td>${esc(b.audience)}</td><td>${esc(b.stage)}</td>
        <td class="small nowrap">${esc(fmtDate(b.created_at))}</td><td>${it ? badge(it.status) : '<span class="muted small">not run</span>'}</td>
        <td class="right">${it ? `<a class="btn btn-sm" href="#/review/${esc(enc(it.id))}">Review</a>` : allowed('content.run') ? `<button type="button" class="btn btn-sm" data-action="run-brief" data-bid="${esc(b.id)}">Run</button>` : ''}</td></tr>`; }).join('')}
      </tbody></table></section>` : '';

    S.after = () => { addMandatedRow(); };
    return `${pageHead('Create', `${p.name}: write a brief. The strategist plans, the copywriter drafts, and the gate checks every sentence.`)}
      ${warn ? warn + '<div class="section-gap"></div>' : ''}
      <div class="grid-2">${form}${quick}</div>${recent}`;
  }

  let mandatedSeq = 0;
  function addMandatedRow() {
    const host = $('#mandated-rows'); if (!host) return;
    const i = ++mandatedSeq;
    const row = document.createElement('div');
    row.className = 'row mandated-row';
    row.innerHTML = `<label class="field" style="flex:0 0 160px"><span>Where</span><input type="text" name="mw_where_${i}" data-mw="where" placeholder="headline, CTA…"></label>
      <label class="field grow"><span>Exact text</span><input type="text" name="mw_text_${i}" data-mw="text"></label>
      <button type="button" class="btn btn-sm btn-ghost" data-action="remove-mandated" aria-label="Remove this wording" style="align-self:flex-end">Remove</button>`;
    host.appendChild(row);
  }

  async function submitBrief(form) {
    const err = $('.form-error', form); err.textContent = '';
    const v = (n) => String(form.elements[n].value || '').trim();
    const body = { content_type: v('content_type'), title: v('title'), audience: v('audience'), goal: v('goal'), stage: v('stage'), notes: v('notes') };
    const missing = ['content_type', 'title', 'audience', 'goal', 'stage'].filter((k) => !body[k]);
    if (missing.length) { err.textContent = `Fill in: ${missing.join(', ').replace(/_/g, ' ')}.`; return; }
    body.mandated_wording = $$('.mandated-row', form).map((r) => ({
      where: $('[data-mw=where]', r).value.trim(), text: $('[data-mw=text]', r).value.trim() })).filter((m) => m.text);
    if (body.mandated_wording.some((m) => !m.where)) { err.textContent = 'Say where each mandated wording goes.'; return; }
    let brief;
    try { brief = await POST(`${P(S.pid)}/briefs`, body); } catch (e) { err.textContent = e.message; return; }
    toast('Brief saved.', 'ok');
    await runBrief(brief.id, '#create-job');
  }

  async function runBrief(bid, hostSel) {
    const pid = S.pid;
    if (!(await confirmEstimate(pid, 'content', 'content generation'))) {
      const host = $(hostSel || '#create-job');
      if (host) host.innerHTML = `<div class="note-box section-gap">Brief saved but not run. Run it from Recent briefs when you're ready.</div>`;
      return;
    }
    try {
      const { job_id } = await POST(`/api/briefs/${enc(bid)}/run`, {});
      let host = $(hostSel || '#create-job');
      if (!host) { host = $('#create-job'); }
      if (host) host.innerHTML = jobBox('content-job-box', 'Generating and verifying');
      const job = await trackJob(job_id, 'content-job-box');
      const box = document.getElementById('content-job-box');
      let itemId = bid;
      try {
        const items = await GET(`/api/content?product=${enc(pid)}`);
        const it = items.find((i) => i.brief_id === bid);
        if (it) itemId = it.id;
      } catch (e) { /* fall back to brief id */ }
      if (job.status === 'done') {
        const r = job.result || {};
        if (box) $('.job-result', box).innerHTML = `<div class="row section-gap">${badge(r.status)} <span class="small">${plural(r.rounds || 0, 'round')}</span>
          <a class="btn btn-primary btn-sm" href="#/review/${esc(enc(itemId))}">Open in Review</a></div>`;
        toast(`Run finished: ${statusLabel(r.status)}.`, r.status === 'blocked' ? '' : 'ok');
      } else {
        if (box) $('.job-result', box).innerHTML = `<div class="row section-gap"><a class="btn btn-sm" href="#/review/${esc(enc(itemId))}">Open in Review</a></div>`;
        toast(`Run failed: ${job.error || ''}`, 'err');
      }
    } catch (e) { toast(e.message, 'err'); }
  }

  async function submitQuickCheck(form) {
    const err = $('.form-error', form); err.textContent = '';
    const draft = form.elements.draft.value;
    if (!draft.trim()) { err.textContent = 'Paste some copy first.'; return; }
    const out = $('#quick-result');
    out.innerHTML = '<p class="loading">Checking…</p>';
    const btn = $('button[type=submit]', form); btn.disabled = true;
    try {
      const r = await POST(`${P(S.pid)}/quick-check`, { draft });
      const rep = r.report || {};
      out.innerHTML = `<div class="row section-gap">${badge(rep.status)} <span class="small muted">${plural(rep.block_count || 0, 'block')}, ${plural(rep.high_count || 0, 'high flag')}</span></div>
        <ul class="flag-list">${(r.verdicts || []).map((u) => `<li>${badge(u.verdict)}<div class="grow">
          <div>${esc(stripTags(u.text))} ${(u.cited_ids || []).map(chip).join(' ')}</div>
          ${u.verdict !== 'pass' ? `<div class="small"><strong>${esc(u.reason || '')}</strong> ${esc(u.explanation || '')}</div>
            ${u.suggested_fix ? `<div class="small muted">Fix: ${esc(u.suggested_fix)}</div>` : ''}` : `<div class="small muted">${esc(u.classification)}</div>`}
        </div></li>`).join('')}</ul>`;
    } catch (e) { out.innerHTML = errorBox(e); }
    btn.disabled = false;
  }

  // =====================================================================
  // 7. Review
  // =====================================================================

  async function renderReview(args) {
    const np = needProduct(); if (np) return np;
    const items = await GET(`/api/content?product=${enc(S.pid)}`);
    if (!items.length) {
      return `${pageHead('Review', 'Every draft and its gate verdicts.')}
        ${empty('Nothing to review yet', 'Create a brief and run it. Drafts appear here with every sentence checked.', '<a class="btn btn-primary" href="#/create">Create content</a>')}`;
    }
    let id = args[0];
    if (!id || !items.some((i) => i.id === id)) id = items[0].id;
    const data = await GET(`/api/content/${enc(id)}`);
    const keep = S.rv && S.rv.id === id;
    S.rv = {
      id, data,
      round: keep && S.rv.round <= data.rounds.length ? S.rv.round : data.rounds.length,
      unit: keep ? S.rv.unit : null,
      compare: keep ? S.rv.compare : null,
    };
    const list = `<ul class="item-list" aria-label="Content items">${items.map((i) => `<li><a href="#/review/${esc(enc(i.id))}"${i.id === id ? ' aria-current="true"' : ''}>
      <span class="item-title">${esc(i.brief ? i.brief.title : i.id)}</span>
      <span class="row">${badge(i.status)}<span class="small muted">${plural(i.rounds.length, 'round')}</span>${(i.reflags || []).some((r) => !r.cleared) ? '<span class="badge b-red">Re-flagged</span>' : ''}</span>
      <span class="small muted">${esc(i.brief ? i.brief.content_type : '')} · ${esc(fmtDate(i.updated_at))}</span></a></li>`).join('')}</ul>`;
    return `${pageHead('Review', 'Every sentence is checked against the claims registry. Approval comes only from the gate or a logged override.')}
      <div class="review-layout">${list}<div id="review-detail">${reviewDetail()}</div></div>`;
  }

  function redrawReview() {
    const host = $('#review-detail');
    if (host) host.innerHTML = reviewDetail();
  }

  function norm(s) { return stripTags(s).replace(/[*_`#]/g, '').replace(/\s+/g, ' ').trim().toLowerCase(); }

  /** Split draft Markdown into display blocks (headings, list items, paragraphs, table rows). */
  function draftBlocks(md) {
    const blocks = []; let para = [];
    const flush = () => { if (para.length) { blocks.push({ type: 'p', raw: para.join(' ') }); para = []; } };
    String(md || '').replace(/<!--[\s\S]*?-->/g, '').split('\n').forEach((line) => {
      if (!line.trim()) { flush(); return; }
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) { flush(); blocks.push({ type: 'h', level: h[1].length, raw: h[2] }); return; }
      const li = line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)$/);
      if (li) { flush(); blocks.push({ type: 'li', raw: li[1] }); return; }
      if (/^\s*(\||---|```)/.test(line)) { flush(); blocks.push({ type: 'table', raw: line }); return; }
      para.push(line.trim());
    });
    flush();
    blocks.forEach((b) => { b.norm = norm(b.raw); b.units = []; });
    return blocks;
  }

  /** Attach each gate unit to the draft block it came from, in order. */
  function placeUnits(blocks, units) {
    let ptr = 0; const orphans = [];
    units.forEach((u) => {
      const nu = norm(u.text);
      const isHead = nu === norm(u.section || '') && nu !== '';
      let j = ptr;
      while (j < blocks.length && !((blocks[j].type === 'h') === isHead && (nu === '' || blocks[j].norm.includes(nu)))) j++;
      if (j < blocks.length) { ptr = j; blocks[j].units.push(u); } else orphans.push(u);
    });
    return orphans;
  }

  function unitSpan(u, sel) {
    const cls = u.verdict === 'block' ? 'u-block' : u.verdict === 'flag' ? 'u-flag' : 'u-pass';
    const label = u.verdict === 'block' ? 'blocked' : u.verdict === 'flag' ? 'flagged' : 'passes';
    return `<span class="u ${cls}${sel === u.index ? ' u-sel' : ''}" role="button" tabindex="0" data-action="unit" data-i="${esc(u.index)}"
      aria-pressed="${sel === u.index}" title="${esc(statusLabel(u.verdict))}${u.reason ? ': ' + esc(u.reason) : ''}">${esc(stripTags(u.text))}${
      (u.cited_ids || []).map((c) => `<span class="cid">${esc(c)}</span>`).join('')}${u.verdict !== 'pass' ? `<span class="sr-only"> (${label}${u.reason ? ': ' + esc(u.reason) : ''})</span>` : ''}</span>`;
  }

  function renderDraft(md, verdicts, sel) {
    if (!verdicts) return `<div class="note-box">No gate verdicts for this round.</div><div class="draft section-gap">${mdToHtml(md)}</div>`;
    const blocks = draftBlocks(md);
    const orphans = placeUnits(blocks, verdicts);
    const out = []; let inList = false;
    blocks.forEach((b) => {
      if (!b.units.length) return;
      const inner = b.units.map((u) => unitSpan(u, sel)).join(' ');
      if (b.type !== 'li' && inList) { out.push('</ul>'); inList = false; }
      if (b.type === 'h') out.push(`<h${b.level}>${inner}</h${b.level}>`);
      else if (b.type === 'li') { if (!inList) { out.push('<ul>'); inList = true; } out.push(`<li>${inner}</li>`); }
      else if (b.type === 'table') out.push(`<div class="d-table">${inner}</div>`);
      else out.push(`<p>${inner}</p>`);
    });
    if (inList) out.push('</ul>');
    if (orphans.length) out.push(`<p>${orphans.map((u) => unitSpan(u, sel)).join(' ')}</p>`);
    return `<div class="draft">${out.join('\n')}</div>`;
  }

  function reviewDetail() {
    const rv = S.rv; if (!rv) return '';
    const { item, brief, rounds, plan, final, can_export: canExport } = rv.data;
    const r = rounds[rv.round - 1];
    const latest = rv.round === rounds.length;
    const verdicts = r ? r.verdicts : null;
    const rep = r ? r.report : null;
    const closed = ['approved', 'approved-override', 'rejected'].includes(item.status) && item.review_state === 'closed';
    const lv = item.live_version;
    const openReflags = (item.reflags || []).filter((x) => !x.cleared);

    const header = `<section class="panel">
      <div class="row-between"><div><h2 style="margin:0">${esc(brief ? brief.title : item.id)}</h2>
        <div class="small muted">${esc(brief ? `${brief.content_type} · ${brief.audience} · ${brief.stage} · goal: ${brief.goal}` : '')}</div></div>
        <div class="row">${badge(item.status)}<span class="badge">${esc(item.review_state || '')}</span>
          <button type="button" class="btn btn-sm btn-ghost" data-action="refresh-review">Refresh</button></div></div>
      <div class="status-strip section-gap">
        <span><span class="k">Live version</span>${lv ? `round ${esc(lv.round)} ${badge(lv.status)}` : '<span class="muted">none (nothing approved yet)</span>'}</span>
        <span><span class="k">Auto revisions</span>${esc(item.auto_revisions_used)} / ${AUTO_CAP}</span>
        <span><span class="k">Human rounds</span>${esc(item.human_rounds)}</span>
        <span><span class="k">Positioning marks</span>${(item.positioning_marks || []).length}</span>
      </div>
      ${item.status === 'running' ? '<div class="note-box section-gap">A run is in progress. Refresh to see new rounds.</div>' : ''}
      ${item.override ? `<div class="purple-box section-gap"><strong>Approved (override)</strong> by ${esc(item.override.by)}, ${esc(fmtDate(item.override.at))}: “${esc(item.override.reason)}”</div>` : ''}
      ${openReflags.length ? `<div class="error-box section-gap"><strong>Re-flagged:</strong> a claim this content cites changed after approval.
        <ul class="msg-list">${openReflags.map((x) => `<li>${chip(x.claim_id)} ${esc(x.reason)} <span class="muted">(${esc(fmtDate(x.at))})</span></li>`).join('')}</ul></div>` : ''}
      ${item.auto_revisions_used >= AUTO_CAP && !closed && ['blocked', 'flagged'].includes(item.status) ? '<div class="warn-box section-gap">The automatic revision cap is used up. A person needs to edit, direct a revision, override or reject.</div>' : ''}
    </section>`;

    const roundSel = `<div class="row section-gap" role="group" aria-label="Rounds">${rounds.map((x) =>
      `<button type="button" class="btn btn-sm${x.round === rv.round ? ' btn-primary' : ''}" data-action="pick-round" data-round="${esc(x.round)}" aria-pressed="${x.round === rv.round}">
        Round ${esc(x.round)} · ${esc(x.kind)}</button> ${badge(x.status)}`).join(' ')}</div>`;

    const draftPanel = r ? `<section class="panel section-gap">
      <div class="panel-head"><h3>Draft, round ${esc(r.round)} <span class="muted small">${esc(r.kind)} by ${esc(r.by)} · ${esc(fmtDate(r.created_at))}</span></h3>
        <div class="legend" aria-hidden="true"><span><i class="sw sw-block"></i>Blocked</span><span><i class="sw sw-flag"></i>Flagged</span><span><i class="sw sw-pass"></i>Passes</span></div></div>
      ${verdicts ? `<p class="small muted">${plural(verdicts.filter((u) => u.verdict === 'block').length, 'block')}, ${plural(verdicts.filter((u) => u.verdict === 'flag').length, 'flag')}. Select any sentence to see why.</p>` : ''}
      ${renderDraft(r.draft, verdicts, rv.unit)}
    </section>` : '';

    const flagsPanel = rep ? flagsView(rep) : '';
    const comparePanel = rounds.length > 1 ? compareView(rounds) : '';
    const planPanel = plan ? planView(plan) : '';
    const finalPanel = final ? `<section class="panel section-gap"><div class="panel-head"><h3>Final copy ${lv ? badge(lv.status) : ''}</h3>
        <span class="small muted">round ${esc(lv ? lv.round : '')}, approved ${esc(fmtDate(lv ? lv.approved_at : ''))}</span></div>
      <div class="final-copy draft">${mdToHtml(final)}</div></section>` : '';
    const exportPanel = canExport && allowed('content.export') ? `<section class="panel section-gap"><h3>Export</h3>
      <p class="small muted">Claim tags are stripped. Citation exports are for internal review only: each sentence is followed by its claim and source quote.</p>
      <div class="row">${['md', 'html', 'docx'].map((f) => `<a class="btn btn-sm" href="/api/content/${esc(enc(item.id))}/export?fmt=${f}&amp;citations=0" download>${f.toUpperCase()}</a>`).join('')}
        <span class="muted small" style="margin-left:8px">With citations (internal):</span>
        ${['md', 'html', 'docx'].map((f) => `<a class="btn btn-sm" href="/api/content/${esc(enc(item.id))}/export?fmt=${f}&amp;citations=1" download>${f.toUpperCase()}</a>`).join('')}</div></section>` : '';

    const side = `<div class="sticky-side">
      <section class="panel" id="inspector">${inspector()}</section>
      <section class="panel">${actionsPanel(item, latest, closed)}<div id="direct-job"></div></section>
    </div>`;

    return `${header}${roundSel}
      <div class="detail-grid section-gap"><div>${draftPanel}${flagsPanel}${finalPanel}${exportPanel}${comparePanel}${planPanel}</div>${side}</div>`;
  }

  function inspector() {
    const rv = S.rv;
    const r = rv.data.rounds[rv.round - 1];
    const u = r && r.verdicts && rv.unit !== null ? r.verdicts.find((x) => x.index === rv.unit) : null;
    if (!u) return `<h3>Sentence</h3><p class="muted small" style="margin:0">Select a sentence in the draft to see its verdict, the cited claim and quote, and the suggested fix.</p>`;
    const claims = rv.data.claims || {};
    const latest = rv.round === rv.data.rounds.length;
    const canMark = latest && u.verdict === 'block' && u.reason === 'untagged' && !(u.cited_ids || []).length && allowed('content.mark-positioning')
      && !['approved', 'approved-override', 'rejected'].includes(rv.data.item.status);
    return `<div class="row-between"><h3 style="margin:0">Sentence ${esc(u.index + 1)}</h3>${badge(u.verdict)}</div>
      <blockquote class="quote section-gap" style="color:var(--text)">${esc(stripTags(u.text))}</blockquote>
      <dl class="kv section-gap"><dt>Section</dt><dd>${esc(u.section || '—')}</dd><dt>Classified as</dt><dd>${esc(u.classification)}</dd>
        ${u.reason ? `<dt>Reason</dt><dd><strong>${esc(u.reason)}</strong></dd>` : ''}</dl>
      ${u.explanation ? `<p class="section-gap">${esc(u.explanation)}</p>` : ''}
      ${u.suggested_fix ? `<div class="note-box"><strong>Suggested fix:</strong> ${esc(u.suggested_fix)}</div>` : ''}
      ${(u.cited_ids || []).length ? `<h4 class="section-gap">Cited claims</h4>${u.cited_ids.map((id) => {
        const c = claims[id];
        if (!c) return `<div class="claim-card">${chip(id)} <span class="badge b-red">Not in registry</span></div>`;
        return `<div class="claim-card"><div class="row">${chip(c.id)} ${badge(c.status)} <span class="small muted">${esc(c.category)}</span></div>
          <p class="small" style="margin:6px 0">${esc(c.text)}</p><blockquote class="quote">${esc(c.quote)}</blockquote>
          <div class="src-meta">${esc(c.source_title || c.source_id)} · ${esc(c.location)}</div></div>`;
      }).join('')}` : ''}
      ${(u.relevant_ids || []).filter((x) => !(u.cited_ids || []).includes(x)).length ? `<p class="small muted section-gap">Related claims: ${chips(u.relevant_ids.filter((x) => !(u.cited_ids || []).includes(x)))}</p>` : ''}
      ${canMark ? `<div class="section-gap"><button type="button" class="btn btn-sm" data-action="mark-positioning" data-i="${esc(u.index)}">Mark as positioning</button>
        <p class="field-hint">Use only when the line makes no checkable claim. Logged with your name.</p></div>` : ''}`;
  }

  function actionsPanel(item, latest, closed) {
    const st = item.status;
    const reviewable = ['blocked', 'flagged'].includes(st) || (item.review_state === 'open' && st !== 'running');
    const btns = [];
    if (allowed('content.edit') && st !== 'running') btns.push('<button type="button" class="btn btn-block" data-action="edit-draft">Edit copy</button>');
    if (allowed('content.direct') && st !== 'running') btns.push('<button type="button" class="btn btn-block" data-action="direct-revision">Direct a revision</button>');
    btns.push('<a class="btn btn-block" href="#/sources">Add a source</a>');
    if (allowed('content.override') && ['blocked', 'flagged'].includes(st)) btns.push('<button type="button" class="btn btn-block btn-purple" data-action="override">Override…</button>');
    if (allowed('content.reject') && reviewable && st !== 'rejected') btns.push('<button type="button" class="btn btn-block btn-danger" data-action="reject">Reject</button>');
    return `<h3>Actions</h3>
      ${closed ? `<p class="small muted">This item is ${esc(statusLabel(st))}. Editing creates a new round; the approved version stays live unless the new round passes.</p>` : ''}
      <div class="stack-sm">${btns.join('')}</div>
      <p class="field-hint section-gap">Adding a source never clears a block by itself: the new claim enters as needs-review until someone confirms it.</p>
      ${!latest ? '<p class="field-hint">You are viewing an older round. Actions apply to the latest round.</p>' : ''}`;
  }

  function flagsView(rep) {
    const ORDER = ['gate', 'style-checker', 'best-practice-auditor', 'synthetic-buyer'];
    const SEV = { block: 0, high: 1, medium: 2, low: 3 };
    const groups = {};
    (rep.flags || []).forEach((f) => { (groups[f.source] = groups[f.source] || []).push(f); });
    const keys = Object.keys(groups).sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
    const scores = rep.checker_scores || {};
    return `<section class="panel section-gap">
      <div class="panel-head"><h3>Verification report ${badge(rep.status)}</h3>
        <span class="small muted">${plural(rep.block_count || 0, 'block')} · ${plural(rep.high_count || 0, 'high flag')} · ${plural(rep.low_count || 0, 'low flag')}</span></div>
      ${Object.keys(scores).length ? `<div class="row">${Object.entries(scores).map(([k, v]) => `<span class="badge">${esc(k)}: ${esc(fmtScore(v))}</span>`).join('')}</div>` : ''}
      ${(rep.checkers_missing || []).length ? `<div class="warn-box section-gap">Checkers missing: ${esc(rep.checkers_missing.join(', '))}</div>` : ''}
      ${rep.override ? `<div class="purple-box section-gap">Override by ${esc(rep.override.by)}, ${esc(fmtDate(rep.override.at))}: “${esc(rep.override.reason)}”</div>` : ''}
      ${keys.length ? keys.map((k) => `<h4 class="section-gap">${esc(k)}</h4><ul class="flag-list">${groups[k].sort((a, b) => (SEV[a.severity] ?? 9) - (SEV[b.severity] ?? 9)).map((f) =>
        `<li>${badge(f.severity)}<div class="grow">${f.sentence ? `<div><em>“${esc(stripTags(f.sentence))}”</em></div>` : ''}<div class="small">${esc(f.issue)}</div></div>${f.reason ? chip(f.reason) : ''}</li>`).join('')}</ul>`).join('')
        : '<p class="muted small">No flags.</p>'}
    </section>`;
  }

  function compareView(rounds) {
    const rv = S.rv; const c = rv.compare;
    const n = rounds.length;
    const a = c ? c.a : Math.max(1, n - 1); const b = c ? c.b : n;
    const opts = (sel) => rounds.map((x) => `<option value="${esc(x.round)}"${x.round === sel ? ' selected' : ''}>Round ${esc(x.round)} (${esc(x.kind)})</option>`).join('');
    const list = (title, arr, cls) => `<div><h4>${esc(title)} (${arr.length})</h4>${arr.length ? `<ul class="flag-list">${arr.map((f) =>
      `<li><span class="badge ${cls}">${esc(f.reason || f.severity)}</span><span class="small">${esc(stripTags(f.sentence || f.issue))}</span></li>`).join('')}</ul>` : '<p class="small muted">None</p>'}</div>`;
    return `<section class="panel section-gap"><div class="panel-head"><h3>Compare rounds</h3></div>
      <form data-form="compare" class="inline-form" novalidate>
        <label class="field"><span>Round A</span><select name="a">${opts(a)}</select></label>
        <label class="field"><span>Round B</span><select name="b">${opts(b)}</select></label>
        <button type="submit" class="btn">Compare</button></form>
      ${c ? `<div class="section-gap"><div class="row">Round ${esc(c.a)} ${badge(c.status.a)} → Round ${esc(c.b)} ${badge(c.status.b)}</div>
        <div class="grid-3 section-gap">${list('Fixed', c.fixed, 'b-green')}${list('New', c.new, 'b-red')}${list('Still blocked', c.still, 'b-amber')}</div>
        <h4 class="section-gap">Draft diff</h4>
        <div class="diff" role="region" aria-label="Unified diff">${c.diff.length ? c.diff.map((l) => {
          const cls = l.startsWith('+++') || l.startsWith('---') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : l.startsWith('@@') ? 'hunk' : '';
          return `<span class="${cls}">${esc(l) || ' '}</span>`; }).join('') : '<span>No text changes.</span>'}</div></div>` : ''}
    </section>`;
  }

  function planView(plan) {
    return `<details class="panel section-gap"><summary>Content plan</summary>
      <dl class="kv"><dt>Framework</dt><dd>${esc(plan.framework)}</dd><dt>Persona</dt><dd>${esc(plan.persona)}</dd><dt>Stage</dt><dd>${esc(plan.stage)}</dd><dt>Angle</dt><dd>${esc(plan.angle)}</dd></dl>
      <h4 class="section-gap">Sections</h4>
      <table class="table"><thead><tr><th>Section</th><th>Purpose</th><th>Claims</th><th>Notes</th></tr></thead><tbody>
        ${(plan.sections || []).map((s) => `<tr><td class="nowrap">${esc(s.name)}</td><td>${esc(s.purpose)}</td><td>${chips(s.claim_ids) || '<span class="muted">—</span>'}</td><td class="small muted">${esc(s.notes)}</td></tr>`).join('')}
      </tbody></table>
      ${(plan.proof_gaps || []).length ? `<h4 class="section-gap">Proof gaps (the writer must not fill these)</h4><ul class="flag-list">${plan.proof_gaps.map((g) =>
        `<li><span class="badge b-amber">gap</span><div><div>${esc(g.need)}</div><div class="small muted">${esc(g.reason)}</div></div></li>`).join('')}</ul>` : ''}
      ${(plan.mandated_wording_notes || []).length ? `<h4 class="section-gap">Mandated wording</h4><ul class="small">${plan.mandated_wording_notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}
      ${(plan.style_notes || []).length ? `<h4 class="section-gap">Style notes</h4><ul class="small">${plan.style_notes.map((n) => `<li>${esc(typeof n === 'string' ? n : JSON.stringify(n))}</li>`).join('')}</ul>` : ''}
    </details>`;
  }

  async function reloadReview() {
    if (!S.rv) return rerender();
    const id = S.rv.id;
    try {
      const data = await GET(`/api/content/${enc(id)}`);
      S.rv.data = data;
      S.rv.round = data.rounds.length;
      S.rv.unit = null; S.rv.compare = null;
      rerender();
    } catch (e) { toast(e.message, 'err'); }
  }

  function selectUnit(i) {
    S.rv.unit = i;
    $$('.draft .u').forEach((el) => {
      const on = Number(el.dataset.i) === i;
      el.classList.toggle('u-sel', on);
      el.setAttribute('aria-pressed', String(on));
    });
    const insp = $('#inspector');
    if (insp) insp.innerHTML = inspector();
  }

  async function editDraft() {
    const rounds = S.rv.data.rounds;
    const md = rounds[rounds.length - 1].draft;
    const r = await modal({
      title: 'Edit copy', wide: true,
      body: `<p class="small muted">Edit the latest draft, including claim tags like <code>[[PREFIX-001]]</code>. Saving creates a new human round that the gate re-verifies.</p>
        <label class="field"><span class="sr-only">Draft Markdown</span><textarea name="draft" class="code">${esc(md)}</textarea></label>`,
      actions: [{ label: 'Cancel', value: null }, { label: 'Save and re-verify', value: 'ok', kind: 'primary' }],
      validate: (d) => (!String(d.draft || '').trim() ? 'The draft cannot be empty.' : null),
    });
    if (r.value !== 'ok') return;
    toast('Re-verifying…');
    try {
      const rep = await POST(`/api/content/${enc(S.rv.id)}/edit`, { draft: r.data.draft });
      toast(`Re-verified: ${statusLabel(rep && rep.status ? rep.status : 'done')}.`, 'ok');
      reloadReview();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function directRevision() {
    const r = await modal({
      title: 'Direct a revision',
      body: `<p class="small muted">Tell the copywriter what to change. This is logged as human-directed and doesn't count against the automatic cap. The result goes through the gate.</p>
        <label class="field"><span>Instructions</span><textarea name="instructions" style="min-height:120px" required></textarea></label>`,
      actions: [{ label: 'Cancel', value: null }, { label: 'Start revision', value: 'ok', kind: 'primary' }],
      validate: (d) => (!String(d.instructions || '').trim() ? 'Instructions are required.' : null),
    });
    if (r.value !== 'ok') return;
    try {
      const { job_id } = await POST(`/api/content/${enc(S.rv.id)}/direct`, { instructions: r.data.instructions.trim() });
      const host = $('#direct-job');
      if (host) host.innerHTML = jobBox('direct-job-box', 'Directed revision');
      const job = await trackJob(job_id, 'direct-job-box');
      if (job.status === 'done') { toast('Revision verified.', 'ok'); reloadReview(); } else toast(`Revision failed: ${job.error || ''}`, 'err');
    } catch (e) { toast(e.message, 'err'); }
  }

  async function overrideItem() {
    const r = await modal({
      title: 'Override the gate',
      body: `<div class="purple-box"><strong>The status becomes “Approved (override)”, never Approved.</strong>
          The override is logged with your name, the time and your reason, and appears in the verification report and the audit log.</div>
        <label class="field section-gap"><span>Reason (required)</span><textarea name="reason" style="min-height:110px" required placeholder="Why this copy should ship despite the gate result."></textarea></label>`,
      actions: [{ label: 'Cancel', value: null }, { label: 'Approve with override', value: 'ok', kind: 'purple' }],
      validate: (d) => (!String(d.reason || '').trim() ? 'A written reason is required.' : null),
    });
    if (r.value !== 'ok') return;
    try {
      await POST(`/api/content/${enc(S.rv.id)}/override`, { reason: r.data.reason.trim() });
      toast('Override logged. Status: Approved (override).', 'ok');
      reloadReview();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function rejectItem() {
    const r = await modal({
      title: 'Reject this draft?',
      body: `<label class="field"><span>Reason (optional)</span><textarea name="reason"></textarea></label>`,
      actions: [{ label: 'Cancel', value: null }, { label: 'Reject draft', value: 'ok', kind: 'danger-primary' }],
    });
    if (r.value !== 'ok') return;
    try {
      await POST(`/api/content/${enc(S.rv.id)}/reject`, { reason: (r.data.reason || '').trim() });
      toast('Draft rejected.', 'ok');
      reloadReview();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function markPositioning(i) {
    const rounds = S.rv.data.rounds;
    const u = (rounds[rounds.length - 1].verdicts || []).find((x) => x.index === i);
    if (!u) return;
    const ok = await confirmDialog('Mark as positioning?',
      `<blockquote class="quote">${esc(stripTags(u.text))}</blockquote>
       <p class="section-gap">Positioning lines (tone, framing, questions) aren't gated. Only do this if the line makes no checkable claim. The mark is logged with your name.</p>`, 'Mark as positioning');
    if (!ok) return;
    try {
      const rep = await POST(`/api/content/${enc(S.rv.id)}/mark-positioning`, { sentence: u.text });
      toast(`Marked. Status: ${statusLabel(rep && rep.status ? rep.status : '')}.`, 'ok');
      reloadReview();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function submitCompare(form) {
    const a = Number(form.elements.a.value); const b = Number(form.elements.b.value);
    try {
      S.rv.compare = await GET(`/api/content/${enc(S.rv.id)}/compare?a=${a}&b=${b}`);
      redrawReview();
    } catch (e) { toast(e.message, 'err'); }
  }

  // =====================================================================
  // 8. Gaps
  // =====================================================================

  async function renderGaps() {
    const np = needProduct(); if (np) return np;
    const g = await GET(`${P(S.pid)}/gaps`);
    const kpis = `<div class="grid-4">
      <a class="kpi" href="#/claims/queue"><div class="num">${fmtNum(g.claims_needing_review)}</div><div class="lbl">Claims needing review</div></a>
      <div class="kpi"><div class="num">${fmtNum(g.proof_points_without_claims.length)}</div><div class="lbl">Proof points without claims</div></div>
      <div class="kpi"><div class="num">${fmtNum(g.topics_without_docs.length)}</div><div class="lbl">Topics with no docs</div></div>
      <a class="kpi" href="#/claims/conflicts"><div class="num">${fmtNum(g.open_conflicts.length)}</div><div class="lbl">Open conflicts</div></a>
    </div>`;
    return `${pageHead('Gaps', 'What the docs owner needs to add or fix so marketing can say more. Share this with product owners.')}
      ${kpis}
      <div class="grid-2 section-gap">
        <section class="panel"><h3>Proof points without claims</h3>
          ${g.proof_points_without_claims.length ? `<table class="table"><thead><tr><th>Theme</th><th>Proof point</th></tr></thead><tbody>
            ${g.proof_points_without_claims.map((p) => `<tr><td class="nowrap">${esc(p.theme)}</td><td>${esc(p.proof)}</td></tr>`).join('')}</tbody></table>`
            : '<p class="muted small">Every proof point has a verified claim.</p>'}</section>
        <section class="panel"><h3>Topic coverage</h3>
          <table class="table"><thead><tr><th>Topic</th><th>Category</th><th class="right">Claims</th></tr></thead><tbody>
            ${(g.coverage || []).map((c) => `<tr><td>${esc(c.topic)}</td><td>${esc(c.category)}</td><td class="right">${c.claims ? fmtNum(c.claims) : '<span class="badge b-red">no docs</span>'}</td></tr>`).join('')}
          </tbody></table></section>
      </div>
      <section class="panel section-gap"><h3>Doc corrections</h3>
        <p class="small muted">Claims ruled "doc is wrong". The ruling stands over the document until the docs are fixed.</p>
        ${g.doc_corrections.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Claim</th><th>Source</th><th>Doc says</th><th>Ruling</th><th>By</th><th>At</th></tr></thead><tbody>
          ${g.doc_corrections.map((d) => `<tr><td>${chip(d.claim_id)}</td>
            <td>${d.url ? `<a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.source)}</a>` : esc(d.source)}<div class="small muted">${esc(d.location)}</div></td>
            <td><blockquote class="quote">${esc(d.doc_says)}</blockquote></td><td>${esc(d.ruling)}</td><td class="small">${esc(d.by)}</td><td class="small nowrap">${esc(fmtDate(d.at))}</td></tr>`).join('')}
          </tbody></table></div>` : '<p class="muted small">No corrections yet.</p>'}</section>
      <div class="grid-2 section-gap">
        <section class="panel"><h3>Claims needing review</h3>
          ${g.review_queue.length ? `<table class="table"><thead><tr><th>Category</th><th>Theme</th><th class="right">Claims</th></tr></thead><tbody>
            ${g.review_queue.map((q) => `<tr><td>${esc(q.category)}</td><td>${esc(q.theme)}</td><td class="right">${fmtNum(q.count)}</td></tr>`).join('')}</tbody></table>
            <p class="section-gap"><a class="btn btn-sm" href="#/claims/queue">Open review queue</a></p>` : '<p class="muted small">Nothing waiting.</p>'}</section>
        <section class="panel"><h3>Open conflicts</h3>
          ${g.open_conflicts.length ? `<ul class="flag-list">${g.open_conflicts.map((c) => `<li>${badge('open', c.kind)}<div><div>${esc(c.explanation)}</div><div class="small">${chips(c.claim_ids)}</div></div></li>`).join('')}</ul>
            <p class="section-gap"><a class="btn btn-sm" href="#/claims/conflicts">Rule on conflicts</a></p>` : '<p class="muted small">No open conflicts.</p>'}</section>
      </div>
      <section class="panel section-gap"><h3>Buyer objections the docs can't answer</h3>
        ${g.unanswerable_objections.length ? `<ul>${g.unanswerable_objections.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>` : '<p class="muted small">None found.</p>'}</section>`;
  }

  // =====================================================================
  // 9. Quality & cost
  // =====================================================================

  function bars(entries, max, fmt, clsFn) {
    if (!entries.length) return '<p class="muted small">No data yet.</p>';
    const m = max || Math.max(...entries.map((e) => e[1]), 1);
    return `<ul class="bars">${entries.map(([k, v]) => `<li><span title="${esc(k)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(k)}</span>
      <span class="bar${clsFn ? ' ' + clsFn(v) : ''}" role="img" aria-label="${esc(k)}: ${esc(fmt ? fmt(v) : v)}"><i style="width:${Math.max(1, Math.min(100, (v / m) * 100)).toFixed(1)}%"></i></span>
      <span class="right small">${esc(fmt ? fmt(v) : fmtNum(v))}</span></li>`).join('')}</ul>`;
  }

  function targetOk(target, value) {
    const m = String(target || '').match(/^\s*(>=|<=|>|<)\s*([\d.]+)/);
    if (!m || value === null || value === undefined) return null;
    const t = Number(m[2]);
    return m[1] === '>=' ? value >= t : m[1] === '<=' ? value <= t : m[1] === '>' ? value > t : value < t;
  }

  async function renderQuality() {
    const np = needProduct(); if (np) return np;
    const [q, cost] = await Promise.all([GET(`/api/quality?product=${enc(S.pid)}`), GET('/api/cost')]);
    const prodName = (id) => { const p = S.products.find((x) => x.id === id); return p ? p.name : id; };
    const evals = (q.evals || []).slice().reverse();
    const threshold = current().style_threshold;
    const kpis = `<div class="grid-4">
      <div class="kpi"><div class="num">${fmtNum(q.items)}</div><div class="lbl">Content items (${fmtNum(q.approved)} approved)</div></div>
      <div class="kpi"><div class="num">${fmtPct(q.override_rate)}</div><div class="lbl">Override rate</div></div>
      <div class="kpi"><div class="num">${q.avg_rounds === null ? '—' : esc(q.avg_rounds)}</div><div class="lbl">Average rounds</div></div>
      <div class="kpi"><div class="num">${fmtNum(q.approved_within_auto_cap)}</div><div class="lbl">Approved within the auto cap</div></div>
    </div>`;
    const evalTable = evals.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Run</th>${Object.keys(evals[0].metrics || {}).map((k) => `<th>${esc(k.replace(/_/g, ' '))}</th>`).join('')}<th>Result</th><th class="right">Tokens</th></tr></thead><tbody>
      ${evals.map((e) => `<tr><td class="small nowrap">${esc(fmtDate(e.computed_at))}<div class="muted">${esc(e.provider || '')}</div></td>
        ${Object.entries(e.metrics || {}).map(([k, v]) => { const ok = (e.passed || {})[k] ?? targetOk((e.targets || {})[k], v);
          return `<td><span class="${ok === true ? 'target-ok' : ok === false ? 'target-miss' : ''}">${esc(fmtPct(v))}</span><div class="small muted">target ${esc((e.targets || {})[k] || '—')}</div></td>`; }).join('')}
        <td>${e.all_passed ? '<span class="badge b-green">All targets met</span>' : '<span class="badge b-red">Below target</span>'}</td>
        <td class="right small">${fmtNum(e.tokens)}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="muted small">No gate evals yet. Run one after any model or prompt change.</p>';
    const scores = (q.style_scores || []).slice(-20);
    const budgetPct = cost.workspace_budget ? cost.workspace_tokens / cost.workspace_budget : null;
    return `${pageHead('Quality & cost', `Quality for ${current().name}. Cost is workspace-wide.`)}
      ${kpis}
      <div class="grid-2 section-gap">
        <section class="panel"><h3>Blocks by reason</h3>${bars(Object.entries(q.blocks_by_reason || {}))}</section>
        <section class="panel"><h3>Style scores</h3>
          <p class="small muted">Latest ${scores.length}. Accepted threshold: ${threshold !== null && threshold !== undefined ? esc(fmtScore(threshold)) : 'none'}.</p>
          ${bars(scores.map((s) => [fmtDate(s.at), s.score]), 1, fmtScore, (v) => (threshold !== null && threshold !== undefined && v < threshold ? 'warn' : ''))}</section>
      </div>
      <section class="panel section-gap">
        <div class="panel-head"><h3>Gate evals</h3>${allowed('eval.run') ? '<button type="button" class="btn btn-primary btn-sm" data-action="run-eval">Run gate eval</button>' : ''}</div>
        ${evalTable}<div id="eval-job"></div></section>
      <h2 class="section-gap" style="margin-top:28px">Cost</h2>
      <section class="panel">
        <div class="row-between"><h3 style="margin:0">Workspace tokens</h3><span class="small">${fmtNum(cost.workspace_tokens)} of ${fmtNum(cost.workspace_budget)} (${fmtPct(budgetPct)})</span></div>
        <div class="bar section-gap${budgetPct > 1 ? ' over' : budgetPct > 0.8 ? ' warn' : ''}" role="img" aria-label="Budget used ${esc(fmtPct(budgetPct))}"><i style="width:${Math.min(100, (budgetPct || 0) * 100).toFixed(1)}%"></i></div>
        <p class="small muted section-gap">Per-run budget: ${fmtNum(cost.run_budget)} tokens.</p>
      </section>
      <div class="grid-2 section-gap">
        <section class="panel"><h3>By product</h3>${bars(Object.entries(cost.by_product || {}).map(([k, v]) => [prodName(k), v]))}</section>
        <section class="panel"><h3>By kind</h3>${bars(Object.entries(cost.by_kind || {}))}</section>
      </div>
      <section class="panel section-gap"><h3>Recent runs</h3>
        ${(cost.runs || []).length ? `<div class="table-wrap"><table class="table"><thead><tr><th>When</th><th>Run</th><th>Product</th><th>Kind</th><th>Status</th><th class="right">Tokens</th></tr></thead><tbody>
          ${cost.runs.map((r) => `<tr><td class="small nowrap">${esc(fmtDate(r.created_at))}</td><td><code>${esc(r.id)}</code></td><td>${esc(prodName(r.product_id))}</td><td>${esc(r.kind)}</td><td>${badge(r.status)}</td><td class="right">${fmtNum(r.tokens)}</td></tr>`).join('')}
          </tbody></table></div>` : '<p class="muted small">No runs yet.</p>'}</section>`;
  }

  async function runEval() {
    let last = null;
    try { const ev = await GET(`${P(S.pid)}/evals`); last = ev[0]; } catch (e) { /* ignore */ }
    const ok = await confirmDialog('Run gate eval?',
      `<p>Runs the seeded gate eval set for ${esc(current().name)} (true, false, overstated, partial, untagged, not-citable and positioning sentences).</p>
       <p>${last && last.tokens ? `The last run used <strong>${fmtNum(last.tokens)} tokens</strong>.` : 'No previous run to estimate from.'}</p>`, 'Run eval');
    if (!ok) return;
    try {
      const { job_id } = await POST(`${P(S.pid)}/evals/gate`, {});
      const host = $('#eval-job'); if (host) host.innerHTML = jobBox('eval-job-box', 'Gate eval');
      const job = await trackJob(job_id, 'eval-job-box');
      if (job.status === 'done') {
        toast(job.result && job.result.all_passed ? 'Gate eval: all targets met.' : 'Gate eval finished: below target.', job.result && job.result.all_passed ? 'ok' : 'err');
        if (parseHash().name === 'quality') rerender();
      } else toast(`Eval failed: ${job.error || ''}`, 'err');
    } catch (e) { toast(e.message, 'err'); }
  }

  // =====================================================================
  // 10. Settings
  // =====================================================================

  async function renderSettings() {
    const s = await GET('/api/settings');
    let audit = null; let auditErr = null;
    if (allowed('audit.view')) { try { audit = await GET('/api/audit?limit=200'); } catch (e) { auditErr = e; } }
    const ws = s.workspace; const st = ws.settings || {};
    const admin = allowed('settings.update');
    const dis = admin ? '' : ' disabled';
    const encOk = s.evidence_encryption === 'fernet';
    return `${pageHead('Settings', `Workspace ${ws.name} (${ws.id})`)}
      <div class="grid-2">
        <section class="panel"><div class="panel-head"><h2>Workspace</h2></div>
          <form data-form="settings" class="stack" novalidate>
            <label class="field"><span>Name</span><input type="text" name="name" value="${esc(ws.name)}"${dis}></label>
            <div class="form-grid">
              <label class="field"><span>Retention (days)</span><input type="number" name="retention_days" min="1" value="${esc(st.retention_days ?? '')}" placeholder="keep forever"${dis}></label>
              <label class="field"><span>Run budget (tokens)</span><input type="number" name="run_budget_tokens" min="0" value="${esc(st.run_budget_tokens ?? '')}"${dis}></label>
              <label class="field"><span>Workspace budget (tokens)</span><input type="number" name="workspace_budget_tokens" min="0" value="${esc(st.workspace_budget_tokens ?? '')}"${dis}></label>
            </div>
            <div class="checks"><label><input type="checkbox" name="evidence_enabled"${st.evidence_enabled ? ' checked' : ''}${dis}> Evidence (voice-of-customer) sources enabled</label></div>
            <p class="form-error" role="alert"></p>
            ${admin ? '<div><button type="submit" class="btn btn-primary">Save settings</button></div>' : '<p class="small muted">Only admins can change settings.</p>'}
          </form></section>
        <section class="panel"><div class="panel-head"><h2>Environment</h2></div>
          <dl class="kv"><dt>Data directory</dt><dd><code>${esc(s.data_dir)}</code></dd>
            <dt>Model provider</dt><dd><code>${esc(s.provider)}</code></dd>
            <dt>Evidence encryption</dt><dd>${encOk ? '<span class="badge b-green">fernet</span>' : `<span class="badge b-amber">${esc(s.evidence_encryption)}</span>`}</dd></dl>
          <div class="note-box section-gap">These are set when the server starts and are read-only here. Choose the data path deliberately:
            it holds confidential sources and evidence, so keep it out of cloud-synced folders (Desktop, Documents, Drive, Dropbox, iCloud).</div>
          ${!encOk ? '<div class="warn-box section-gap">Evidence is not encrypted at rest. Use plaintext only with fixture data.</div>' : ''}
        </section>
      </div>
      <section class="panel section-gap"><div class="panel-head"><h2>Members</h2></div>
        <table class="table"><thead><tr><th>Email</th><th>Name</th><th>Roles</th></tr></thead><tbody>
          ${(s.members || []).map((m) => `<tr><td>${esc(m.email)}</td><td>${esc(m.name || '—')}</td><td>${(m.roles || []).map((r) => badge('', r)).join(' ')}</td></tr>`).join('')}</tbody></table>
        ${allowed('member.manage') ? `<form data-form="member" class="stack section-gap" novalidate>
          <h3>Add or update a member</h3>
          <div class="form-grid">
            <label class="field"><span>Email</span><input type="email" name="email" required autocomplete="off"></label>
            <label class="field"><span>Name</span><input type="text" name="name" autocomplete="off"></label>
            <label class="field"><span>Password (new users only)</span><input type="password" name="password" autocomplete="new-password" minlength="10">
              <span class="field-hint">At least 10 characters. Ignored if the user already exists.</span></label>
          </div>
          <fieldset><legend>Roles</legend><div class="checks">${ROLES.map((r) => `<label><input type="checkbox" name="roles" value="${r}"${r === 'editor' ? ' checked' : ''}> ${r}</label>`).join('')}</div></fieldset>
          <p class="form-error" role="alert"></p>
          <div><button type="submit" class="btn btn-primary">Save member</button></div>
        </form>` : ''}
      </section>
      <section class="panel section-gap"><div class="panel-head"><h2>Audit log</h2>
        ${audit ? '<a class="btn btn-sm" href="/api/audit?format=csv" download>Export CSV</a>' : ''}</div>
        ${audit ? (audit.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>Reason / detail</th></tr></thead><tbody>
          ${audit.map((e) => `<tr><td class="small nowrap">${esc(fmtDate(e.created_at))}</td><td class="small">${esc(e.actor)}</td><td><code>${esc(e.action)}</code></td><td class="small"><code>${esc(e.target)}</code></td><td class="small">${esc(e.reason || '')}</td></tr>`).join('')}
          </tbody></table></div>` : '<p class="muted small">No events yet.</p>')
          : auditErr ? errorBox(auditErr) : '<p class="muted small">Admins, reviewers and compliance can view the audit log.</p>'}
      </section>`;
  }

  async function submitSettings(form) {
    const err = $('.form-error', form); err.textContent = '';
    const num = (n) => { const v = form.elements[n].value.trim(); return v === '' ? null : Number(v); };
    const body = { name: form.elements.name.value.trim(), retention_days: num('retention_days'), run_budget_tokens: num('run_budget_tokens'),
      workspace_budget_tokens: num('workspace_budget_tokens'), evidence_enabled: form.elements.evidence_enabled.checked };
    if (!body.name) { err.textContent = 'Workspace name is required.'; return; }
    if (['retention_days', 'run_budget_tokens', 'workspace_budget_tokens'].some((k) => body[k] !== null && (isNaN(body[k]) || body[k] < 0))) {
      err.textContent = 'Numbers must be zero or more.'; return;
    }
    try {
      const ws = await PUT('/api/settings', body);
      $('#ws-name').textContent = ws.name;
      toast('Settings saved.', 'ok');
      rerender();
    } catch (e) { err.textContent = e.message; }
  }

  async function submitMember(form) {
    const err = $('.form-error', form); err.textContent = '';
    const fd = new FormData(form);
    const body = { email: String(fd.get('email') || '').trim(), name: String(fd.get('name') || '').trim(), roles: fd.getAll('roles') };
    const pw = String(fd.get('password') || '');
    if (pw) body.password = pw;
    if (!body.email) { err.textContent = 'Email is required.'; return; }
    if (!body.roles.length) { err.textContent = 'Pick at least one role.'; return; }
    if (pw && pw.length < 10) { err.textContent = 'Password must be at least 10 characters.'; return; }
    try {
      await POST('/api/members', body);
      toast(`Saved ${body.email}.`, 'ok');
      rerender();
    } catch (e) { err.textContent = e.message; }
  }

  // =====================================================================
  // Event wiring (delegated; no inline handlers)
  // =====================================================================

  const ACTIONS = {
    logout: async () => { try { await POST('/api/logout', {}); } catch (e) { /* ignore */ } showSignin(); },
    'select-product': (el) => { setProduct(el.dataset.pid); rerender(); },
    goto: (el) => { setProduct(el.dataset.pid); location.hash = el.dataset.href; },
    ingest: () => runIngest(),
    'view-source': (el) => viewSource(el.dataset.sid),
    'remove-source': (el) => removeSource(el.dataset.sid, el.dataset.title),
    rule: (el) => ruleClaim(el),
    'bulk-confirm': (el) => bulkConfirm(Number(el.dataset.g)),
    'clear-claim-filters': () => { S.claimFilters = { status: '', category: '', q: '' }; rerender(); },
    'toggle-edit-decision': (el) => {
      const card = el.closest('[data-did]'); const f = $('form', card);
      f.hidden = !f.hidden; if (!f.hidden) $('textarea', f).focus();
    },
    'dismiss-diff': () => { S.lastDiff = null; rerender(); },
    'add-mandated': () => addMandatedRow(),
    'remove-mandated': (el) => el.closest('.mandated-row').remove(),
    'run-brief': (el) => {
      const row = el.closest('tr');
      const holder = document.createElement('tr');
      holder.innerHTML = '<td colspan="7" id="brief-run-host"></td>';
      const old = document.getElementById('brief-run-host'); if (old) old.closest('tr').remove();
      row.after(holder);
      runBrief(el.dataset.bid, '#brief-run-host');
    },
    unit: (el) => selectUnit(Number(el.dataset.i)),
    'pick-round': (el) => { S.rv.round = Number(el.dataset.round); S.rv.unit = null; redrawReview(); },
    'refresh-review': () => reloadReview(),
    'edit-draft': () => editDraft(),
    'direct-revision': () => directRevision(),
    override: () => overrideItem(),
    reject: () => rejectItem(),
    'mark-positioning': (el) => markPositioning(Number(el.dataset.i)),
    'run-eval': () => runEval(),
  };

  const FORMS = {
    'create-product': submitCreateProduct,
    upload: submitUpload,
    import: submitImport,
    'claim-filters': (f) => {
      S.claimFilters = { status: f.elements.status.value, category: f.elements.category.value, q: f.elements.q.value.trim() };
      rerender();
    },
    'rule-conflict': submitRuleConflict,
    'add-decision': (f) => submitDecision(f, null),
    'edit-decision': (f) => submitDecision(f, f.dataset.id),
    'accept-threshold': submitAcceptThreshold,
    brief: submitBrief,
    'quick-check': submitQuickCheck,
    compare: submitCompare,
    settings: submitSettings,
    member: submitMember,
  };

  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el || el.closest('#modal-root')) return;
    const fn = ACTIONS[el.dataset.action];
    if (!fn) return;
    e.preventDefault();
    Promise.resolve(fn(el, e)).catch((err) => toast(err.message || String(err), 'err'));
  });

  document.addEventListener('keydown', (e) => {
    const el = e.target;
    if (el && el.classList && el.classList.contains('u') && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      el.click();
    }
  });

  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (form.id === 'signin-form') return;
    const fn = FORMS[form.dataset.form];
    if (!fn) return;
    e.preventDefault();
    const btn = $('button[type=submit]', form);
    if (btn && btn.disabled) return;
    if (btn) btn.disabled = true;
    Promise.resolve(fn(form, e)).catch((err) => toast(err.message || String(err), 'err'))
      .finally(() => { if (btn && document.body.contains(btn)) btn.disabled = false; });
  });

  document.addEventListener('input', (e) => {
    if (e.target.hasAttribute && e.target.hasAttribute('data-upper')) {
      const pos = e.target.selectionStart;
      e.target.value = e.target.value.toUpperCase();
      try { e.target.setSelectionRange(pos, pos); } catch (err) { /* ignore */ }
    }
  });

  $('#signin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target;
    const body = { email: f.elements.email.value.trim(), password: f.elements.password.value };
    const wsid = f.elements.workspace_id.value.trim();
    if (wsid) body.workspace_id = wsid;
    $('#signin-error').textContent = '';
    if (!body.email || !body.password) { $('#signin-error').textContent = 'Enter your email and password.'; return; }
    const btn = $('button[type=submit]', f); btn.disabled = true;
    try {
      await POST('/api/login', body);
      f.elements.password.value = '';
      await boot();
    } catch (err) { $('#signin-error').textContent = err.message; }
    btn.disabled = false;
  });

  $('#product-picker').addEventListener('change', (e) => {
    setProduct(e.target.value);
    const { name } = parseHash();
    if (name === 'review') location.hash = '#/review';
    route();
  });

  window.addEventListener('hashchange', () => route());

  boot();
})();
