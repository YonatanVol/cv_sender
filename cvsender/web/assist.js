'use strict';
// Assist burst mode: one blocked application at a time, ~5s each.
// The bot already filled everything + attached the CV; the human clears the
// CAPTCHA / answers the question and confirms. No AI, no tokens.

// $, esc, api, toast, navBar and scoreBadge come from shared.js.
let queue = [], idx = 0, total = 0, sentToday = 0;

document.getElementById('hdr').innerHTML = navBar('/assist');

async function load() {
  const d = await api('GET', '/api/assist');
  queue = d.items; total = queue.length; idx = 0;
  sentToday = d.sent_today;
  render();
}

function render() {
  $('bar').style.width = total ? `${(idx / total) * 100}%` : '0%';
  if (idx >= queue.length) {
    $('stage').innerHTML = `<div class="card"><div class="empty">
      <h3>Queue clear</h3>
      <p class="sub">Nothing left to finish — ${sentToday} sent today.</p>
      <div class="row" style="justify-content:center;margin-top:16px">
        <button onclick="load()">Reload queue</button>
        <a class="btn ghost" href="/today">Back to Today</a></div></div></div>`;
    return;
  }
  const it = queue[idx];
  const qs = (it.questions || []).filter(q => q && q.label);
  $('stage').innerHTML = `
    <div class="card">
      <div class="headrow">
        ${scoreBadge(it.score, it.band)}
        <div><div class="co">${esc(it.company)}</div>
          <div class="role">${esc(it.title)}</div></div>
      </div>
      <span class="pill warn">${esc(it.reason || it.state)}</span>
      <div class="sub" style="margin-top:9px">
        ${it.cv_attached ? '<span style="color:var(--ok)">CV attached</span>'
                         : '<span style="color:var(--warn)">CV not attached</span>'}
        · ${(it.filled || []).length} fields filled · ${esc(it.channel)}
        · <span class="dim">${idx + 1} of ${total}</span>
        · <span class="dim">${sentToday} sent today</span></div>
      ${it.screenshot ? `<img class="shot" src="/data2/${it.screenshot}" alt="the filled form">` : ''}
      ${qs.length ? '<p class="sub" style="margin-top:12px">Answer once — reused automatically next time:</p>' : ''}
      ${qs.map((q, i) => {
        const opts = (q.options || []).filter(o => o && !/^select an option$/i.test(o));
        const field = opts.length
          ? `<select id="q${i}" data-label="${esc(q.label)}">
               <option value="">choose…</option>
               ${opts.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}
             </select>`
          : `<input id="q${i}" data-label="${esc(q.label)}" placeholder="your answer">`;
        return `<div class="q"><label>${esc(q.label)}</label>${field}</div>`;
      }).join('')}
      <div class="actions">
        <a class="btn" href="${esc(it.apply_url || it.url)}" target="_blank" rel="noopener"
           onclick="opened()">Open &amp; apply ↗</a>
        <button class="sent" onclick="markSent()">I sent it</button>
        ${qs.length ? '<button class="ghost" onclick="saveAnswers()">Save answers</button>' : ''}
        <button class="ghost" onclick="takeover()"
                title="Re-opens the form already filled with your details and CV">Fill it for me</button>
        <button class="ghost gone" onclick="markGone()"
                title="Posting is closed — never offer it again">Not available</button>
        <button class="quiet" onclick="next()" title="Come back to this later">Skip</button>
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
    if (r.sent_today != null) sentToday = r.sent_today;
    toast('Recorded');
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
  document.querySelectorAll('[data-label]').forEach(el => {
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
