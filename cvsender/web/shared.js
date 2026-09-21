/* The helpers every page reimplemented: one copy now. */
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

async function api(method, url, body) {
  const o = { method, headers: {} };
  if (body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(body); }
  const r = await fetch(url, o);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}

function toast(message) {
  let t = $('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; t.className = 'toast hide'; document.body.appendChild(t); }
  t.textContent = message; t.classList.remove('hide');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.add('hide'), 3000);
}

/* Same header everywhere, current page marked. */
function navBar(current) {
  const pages = [['/today','Today'],['/assist','Queue'],['/answers','Answers'],['/settings','Settings']];
  return `<a class="brand" href="/today">⚡ CV Sender</a>
    <nav>${pages.filter(([h]) => h !== current)
      .map(([h, label]) => `<a href="${h}">${label}</a>`).join('')}</nav>`;
}
