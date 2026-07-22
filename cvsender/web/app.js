'use strict';
const $ = id => document.getElementById(id);
const items = new Map();          // item_id -> item
let mode = 'dry', runId = null, es = null;

function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hide');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add('hide'), 3500);
}
async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.status === 204 ? null : r.json();
}

// ---- mode toggle ----
$('modeSw').onclick = () => {
  mode = mode === 'dry' ? 'live' : 'dry';
  $('modeSw').classList.toggle('on', mode === 'live');
  $('modeLbl').textContent = mode === 'live' ? 'LIVE' : 'Dry run';
  $('modeLbl').classList.toggle('armed', mode === 'live');
  $('dryBanner').classList.toggle('hide', mode === 'live');
  $('liveBanner').classList.toggle('hide', mode !== 'live');
  renderReview();
};

// ---- profile ----
async function loadProfile() {
  const p = await api('GET', '/api/profile');
  $('p_full').value = p.full_name || ''; $('p_email').value = p.email || '';
  $('p_phone').value = p.phone || ''; $('p_linkedin').value = p.linkedin || '';
  $('p_github').value = p.github || ''; $('p_location').value = p.location || 'Israel';
  if (p.cv_path) $('cvStatus').innerHTML =
    `✓ ${p.cv_name || 'cv.pdf'} · ${p.cv_pages ?? '?'} pages · ${((p.cv_size||0)/1024|0)} KB`;
}
$('saveProfile').onclick = async () => {
  try {
    await api('PUT', '/api/profile', {
      full_name: $('p_full').value, email: $('p_email').value, phone: $('p_phone').value,
      linkedin: $('p_linkedin').value, github: $('p_github').value, location: $('p_location').value,
    });
    const f = $('p_cv').files[0];
    if (f) {
      const fd = new FormData(); fd.append('cv', f);
      const r = await fetch('/api/cv', { method: 'POST', body: fd });
      if (!r.ok) { toast('CV: ' + ((await r.json()).detail || r.statusText)); return; }
      const meta = await r.json();
      $('cvStatus').innerHTML = `✓ ${meta.cv_name} · ${meta.cv_pages ?? '?'} pages · ${((meta.cv_size||0)/1024|0)} KB`;
    }
    toast('Profile saved');
  } catch (e) { toast('Save failed: ' + e.message); }
};

// ---- run ----
$('prepareBtn').onclick = async () => {
  try {
    const body = { channels: ['greenhouse'], mode, cap: +$('r_cap').value,
                   geography: $('r_geo').value, strictness: $('r_strict').value };
    const r = await api('POST', '/api/runs', body);
    items.clear(); $('items').innerHTML = ''; $('review').innerHTML = '';
    $('liveCard').hidden = false;
    attach(r.run_id);
    toast('Preparing…');
  } catch (e) { toast(e.message); }
};
$('cancelBtn').onclick = async () => {
  if (!runId) return;
  $('cancelBtn').textContent = 'Cancelling…';
  try { await api('POST', `/api/runs/${runId}/cancel`); } catch (e) { toast(e.message); }
};

function attach(id) {
  runId = id;
  $('cancelBtn').classList.remove('hide');
  $('prepareBtn').disabled = true;
  if (es) es.close();
  es = new EventSource(`/api/runs/${id}/events`);
  ['item.new', 'item.state', 'item.error', 'funnel.update', 'source.health',
   'run.state', 'run.error', 'phase', 'end'].forEach(t =>
    es.addEventListener(t, ev => onEvent(t, JSON.parse(ev.data))));
  es.onerror = () => {};   // EventSource auto-reconnects with Last-Event-ID
}

function onEvent(type, payload) {
  const d = payload.data || {};
  if (type === 'phase') { $('statusLine').textContent = payload.message; }
  else if (type === 'item.new') {
    items.set(payload.item_id, { id: payload.item_id, ...d, reason: '' });
    renderItems(); renderReview();
  } else if (type === 'item.state') {
    const it = items.get(payload.item_id) || { id: payload.item_id };
    Object.assign(it, d); items.set(payload.item_id, it);
    renderItems(); renderReview();
  } else if (type === 'item.error') {
    const it = items.get(payload.item_id); if (it) { it.reason = payload.message; }
    renderItems();
  } else if (type === 'funnel.update') { renderFunnel(d); }
  else if (type === 'source.health') { renderHealth(payload.item_id, d); }
  else if (type === 'run.state' || type === 'end') {
    $('statusLine').textContent = payload.message || `status: ${d.status || payload.status || ''}`;
    renderCounts(d.counts);
    const finished = ['done', 'cancelled', 'error', 'awaiting_confirm'].includes(d.status || payload.status);
    if (['done', 'cancelled', 'error'].includes(d.status || payload.status) || type === 'end') {
      $('prepareBtn').disabled = false; $('cancelBtn').classList.add('hide');
      $('cancelBtn').textContent = 'Cancel run';
    }
    if (finished) renderReview();
  } else if (type === 'run.error') { toast(payload.message); }
}

// ---- rendering ----
const ORDER = ['sending','preparing','queued','ready','needs_input','sent','sent_unverified','failed','skipped','cancelled'];
function renderItems() {
  const rows = [...items.values()].sort((a, b) =>
    ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || (b.score||0) - (a.score||0));
  $('items').innerHTML = rows.map(it => `<tr>
    <td>${esc(it.company)}</td><td>${esc(it.title)}</td>
    <td class="mono">${it.score != null ? (+it.score).toFixed(0) : ''}</td>
    <td><span class="pill ${it.state}">${it.state}</span></td>
    <td class="mut">${esc(it.reason || '')} ${it.screenshot ? `· <a class=link target=_blank href="/data2/${it.screenshot}">shot</a>`:''}</td>
  </tr>`).join('');
}
function renderReview() {
  const rev = [...items.values()].filter(i => i.state === 'ready' || i.state === 'needs_input');
  $('reviewCard').hidden = rev.length === 0;
  $('reviewCount').textContent = rev.length ? `(${rev.length})` : '';
  const ready = rev.filter(i => i.state === 'ready').length;
  $('reviewBar').innerHTML = (mode === 'live' && ready)
    ? `<button class="ok" id="sendAll">Send all ready (${ready})</button>`
    : (ready ? `<span class="mut">${ready} ready — switch to LIVE to send</span>` : '');
  if ($('sendAll')) $('sendAll').onclick = confirmAll;
  $('review').innerHTML = rev.map(it => `
    <div class="revcard ${it.state}">
      <div style="display:flex;gap:10px;align-items:center">
        <b>${esc(it.company)}</b><span class="mut" style="flex:1">${esc(it.title)}</span>
        <span class="pill ${it.state}">${it.state}</span>
      </div>
      <div class="kv">${esc(it.reason || '')}</div>
      ${it.screenshot ? `<div class="kv"><a class=link target=_blank href="/data2/${it.screenshot}">view filled-form screenshot</a></div>`:''}
      <div style="margin-top:8px;display:flex;gap:8px">
        ${it.state === 'ready' && mode === 'live'
          ? `<button class="ok" onclick="sendItem(${it.id})">Send</button>`
          : it.state === 'ready' ? `<button disabled>Send (LIVE only)</button>` : ''}
        <button class="ghost" onclick="skipItem(${it.id})">Skip</button>
      </div>
    </div>`).join('');
}
function renderCounts(c) {
  if (!c) return;
  $('counts').innerHTML = Object.entries(c).map(([k, v]) =>
    `<span class="pill ${k}">${k} ${v}</span>`).join('');
}
function renderFunnel(f) {
  $('funnel').innerHTML = ['fetched','role','geography','score','deduped','kept']
    .map(k => `<span>${k}: <b>${f[k] ?? 0}</b></span>`).join('');
}
const health = new Map();
function renderHealth(key, d) {
  health.set(d.key || key, d);
  $('health').innerHTML = [...health.values()].map(h =>
    `<div>${esc(h.key)} — status ${h.status} · ${h.jobs} jobs</div>`).join('');
}

window.sendItem = async id => {
  try { await api('POST', `/api/runs/${runId}/items/${id}/confirm`); toast('Sending…'); }
  catch (e) { toast(e.message); }
};
window.skipItem = async id => {
  try { await api('POST', `/api/runs/${runId}/items/${id}/skip`); } catch (e) { toast(e.message); }
};
async function confirmAll() {
  if (!confirm('Send all ready applications for real?')) return;
  try { const r = await api('POST', `/api/runs/${runId}/confirm-all`); toast(`Sending ${r.confirmed}…`); }
  catch (e) { toast(e.message); }
}
function esc(s) { return (s ?? '').toString().replace(/[&<>"]/g, c =>
  ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c])); }

// ---- boot: hydrate any active run ----
(async () => {
  await loadProfile();
  try {
    const a = await api('GET', '/api/runs/active');
    if (a && a.id) {
      const snap = await api('GET', `/api/runs/${a.id}`);
      snap.items.forEach(it => items.set(it.id, {
        id: it.id, company: it.company, title: it.title, channel: it.channel,
        score: it.score, state: it.state, reason: it.reason,
        screenshot: it.screenshot_prepare }));
      $('liveCard').hidden = false;
      renderItems(); renderReview(); renderCounts(snap.counts);
      $('statusLine').textContent = snap.run.message || snap.run.status;
      attach(a.id);
    }
  } catch {}
})();
