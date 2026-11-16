function render(d) {
  const set = (id, txt) => { const e = document.getElementById(id); if (e) e.textContent = txt; };
  set('tt-l-ns', 'NS tricks');
  set('rt-l-ns', 'pts to ' + side);
  const rows = [];
  const add = (k, v) => { if (v != null) rows.push(`<div><span>${escHtml(k)}:</span> ${escHtml(String(v))}</div>`); };
  add('exit code', d.exit_code);
  add('stop reason', d.stop_reason);
  function warn(msg) { banner.innerText = msg; }
  warn('Browser engines are not built; using the server.');
  const log = (m) => console.log(m);
  log('debug only message here');
  const byId = (id) => document.getElementById(id);
  byId('tt-l-ew');
  set('tt-l-ew', i18n.t('table.ew'));
}
function card() {
  const chip = (label, value, color) => `<span class="chip" style="color:${color}">${label}: ${value}</span>`;
  out += chip('VRAM', '0.0 GiB', 'var(--fail)');
  out += chip('Peak memory', '1.2 GiB', '#a855f7');
  const log = (level, msg) => { panel.innerHTML += `<div class="${level}">${msg}</div>`; };
  log('info', 'Starting native bench…');
}
