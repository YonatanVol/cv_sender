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
  const pages = [['/today', 'Today'], ['/assist', 'Queue'], ['/answers', 'Answers'],
                 ['/applications', 'Sent'], ['/status', 'System'], ['/settings', 'Settings']];
  return `<a class="brand" href="/today"><i>⚡</i> CV Sender</a>
    <nav>${pages.map(([href, label]) =>
      `<a href="${href}"${href === current ? ' class="on" aria-current="page"' : ''}>${label}</a>`
    ).join('')}</nav>`;
}

/* A score and how good it is, as one object. */
function scoreBadge(score, band) {
  const word = (band || '').split(' ')[0] || '';
  return `<div class="score ${word}"><b>${score ?? '–'}</b><span>${esc(word)}</span></div>`;
}

/* "3 days ago" reads better than a timestamp nobody converts in their head. */
function ago(days) {
  if (days == null) return '';
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.round(days / 7)} weeks ago`;
  return `${Math.round(days / 30)} months ago`;
}
