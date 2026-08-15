'use strict';
// Assist burst mode: one blocked application at a time, ~5s each.
// The bot already filled everything + attached the CV; the human clears the
// CAPTCHA / answers the question and confirms. No AI, no tokens.

const $ = id => document.getElementById(id);
let queue = [], idx = 0, total = 0;

function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._t); t._t = setTimeout(() => t.style.display = 'none', 2200);
}
async function api(method, url, body) {
  const o = { method, headers: {} };
  if (body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
  const r = await fetch(url, o);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}
const esc = s => (s ?? '').toString().replace(/[&<>"]/g, c =>
  ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));

async function load() {
  const d = await api('GET', '/api/assist');
  queue = d.items; total = queue.length; idx = 0;
  $('sentToday').textContent = d.sent_today;
  render();
}

function render() {
  $('bar').style.width = total ? `${(idx / total) * 100}%` : '0%';
  if (idx >= queue.length) {
    $('stage').innerHTML = `<div class="done"><h2>🎉 Queue clear</h2>
      <p>Nothing left to finish. Run a new batch to load more.</p>
      <div class="actions"><button onclick="load()">Reload queue</button></div></div>`;
    return;
  }
  const it = queue[idx];
  const qs = (it.questions || []).filter(q => q && q.label);
  $('stage').innerHTML = `
    <div class="card">
      <div class="co">${esc(it.company)}</div>
      <div class="role">${esc(it.title)}</div>
      <span class="why">${esc(it.reason || it.state)}</span>
      <div class="meta">${it.cv_attached ? '<span class="ok">✓ CV attached</span>' : '⚠ CV not attached'}
        · ${(it.filled || []).length} fields filled · ${esc(it.channel)}
        · <span class="mut">${idx + 1} of ${total}</span></div>
      ${it.screenshot ? `<img class="shot" src="/data2/${it.screenshot}" alt="filled form">` : ''}
      ${qs.length ? `<div class="meta">Answer once — reused automatically next time:</div>` : ''}
      ${qs.map((q, i) => `<div class="q">
          <label>${esc(q.label)}</label>
          <input id="q${i}" data-label="${esc(q.label)}" placeholder="your answer">
        </div>`).join('')}
      <div class="actions">
        <button onclick="takeover()" title="Re-opens the form already filled with your details + CV">🖥 Fill it for me</button>
        <a class="btn open" href="${esc(it.apply_url || it.url)}" target="_blank" rel="noopener"
           onclick="opened()">Open &amp; apply ↗</a>
        <button class="sent" onclick="markSent()">✓ I sent it</button>
        ${qs.length ? `<button onclick="saveAnswers()">Save answers</button>` : ''}
        <button class="gone" onclick="markGone()"
                title="Posting is closed — never offer it again">🚫 Not available</button>
        <button class="skip" onclick="next()" title="Come back to this later">Skip</button>
      </div>
    </div>`;
}

function opened() { toast('Opened — finish it, then hit "I sent it"'); }

// Desktop take-over: re-opens the form ALREADY FILLED (with the CV attached) in
// a visible window, so you only clear the CAPTCHA and submit. "Open & apply"
// gives you an empty form; this doesn't.
async function takeover() {
  const it = queue[idx];
  try {
    await api('POST', `/api/items/${it.id}/takeover`);
    toast('Filling it in a window — solve the CAPTCHA, submit, then "I sent it"');
  } catch (e) { toast(e.message); }
}
window.takeover = takeover;

async function markSent() {
  const it = queue[idx];
  try {
    const r = await api('POST', `/api/items/${it.id}/mark-sent`);
    $('sentToday').textContent = r.sent_today ?? $('sentToday').textContent;
    toast('Recorded ✓');
    next();
  } catch (e) { toast('Failed: ' + e.message); }
}

// The posting is gone when you click through. Different from Skip (comes back)
// and from "I sent it" (never sent — must not count). Never offered again.
async function markGone() {
  const it = queue[idx];
  try {
    await api('POST', `/api/items/${it.id}/unavailable`, { kind: 'unavailable' });
    toast('Marked gone — you won’t see it again');
    next();
  } catch (e) { toast('Failed: ' + e.message); }
}
window.markGone = markGone;

async function saveAnswers() {
  const it = queue[idx];
  const answers = {};
  document.querySelectorAll('input[data-label]').forEach(el => {
    if (el.value.trim()) answers[el.dataset.label] = el.value.trim();
  });
  if (!Object.keys(answers).length) return toast('Nothing to save');
  try {
    const r = await api('POST', `/api/items/${it.id}/answers`, { answers });
    toast(`Learned ${r.learned} answer(s) — reused from now on`);
    next();
  } catch (e) { toast('Failed: ' + e.message); }
}

function next() { idx++; render(); }
window.load = load; window.markSent = markSent; window.saveAnswers = saveAnswers;
window.next = next; window.opened = opened;

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'Enter') markSent();
  else if (e.key.toLowerCase() === 'g') markGone();
  else if (e.key.toLowerCase() === 's') next();
  else if (e.key.toLowerCase() === 'o') {
    const it = queue[idx];
    if (it) { window.open(it.apply_url || it.url, '_blank', 'noopener'); opened(); }
  }
});

load();
