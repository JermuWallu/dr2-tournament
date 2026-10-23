'''
Small web leaderboard reading tournament.db. Started by the tournament program, or on its own:

    python -m timerecorder.leaderboard [path/to/tournament.db] [port]
'''
import logging
import os
import sys

from flask import Flask, jsonify, request, Response

from .tournamentDatabase import TournamentDatabase, formatTime, DNF

def _cell(value):
    if value is None:
        return {'text': '', 'kind': 'empty'}
    if value == DNF:
        return {'text': 'DNF', 'kind': 'dnf'}
    return {'text': formatTime(value), 'kind': 'time'}

def formatGap(gap):
    if gap is None or gap <= 0:
        return ''
    return f'+{gap:.3f}' if gap < 60 else '+' + formatTime(gap)

def standingsPayload(database, track=None, car=None):
    combos = database.combos()
    if not combos:
        return {'combos': [], 'track': None, 'car': None, 'rows': [], 'max_attempts': database.max_attempts}

    selected = next((c for c in combos if c['track'] == track and c['car'] == car), combos[0])
    rows = []
    for entry in database.standings(selected['track'], selected['car']):
        rows.append({
            'position': entry['position'],
            'name': entry['name'],
            'best': formatTime(entry['best']) if entry['best'] is not None else 'DNF',
            'gap': formatGap(entry['gap']),
            'attempts': [_cell(a) for a in entry['attempts']],
            'used': entry['used'],
        })

    return {
        'combos': [{'track': c['track'], 'car': c['car'], 'players': c['players']} for c in combos],
        'track': selected['track'],
        'car': selected['car'],
        'rows': rows,
        'max_attempts': database.max_attempts,
    }

def createApp(database):
    app = Flask(__name__)

    @app.get('/')
    def index():
        return Response(PAGE, mimetype='text/html')

    @app.get('/api/standings')
    def standings():
        return jsonify(standingsPayload(database, request.args.get('track'), request.args.get('car')))

    return app

def serve(database, host='0.0.0.0', port=5000):
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    createApp(database).run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DR2 Tournament Leaderboard</title>
<style>
:root {
  --bg: #101216; --panel: #181b21; --row: #1d2129; --line: #2a2f39;
  --text: #f2f4f8; --muted: #8b93a3; --accent: #ffb000; --dnf: #ff6b5b;
  --gold: #ffcf40; --silver: #c9d1dc; --bronze: #d9915a;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.4 "Segoe UI", system-ui, -apple-system, sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 16px 48px; }
.kicker { color: var(--accent); font-weight: 700; letter-spacing: .14em; font-size: 13px; }
h1 { margin: 6px 0 2px; font-size: clamp(28px, 5vw, 48px); line-height: 1.1; }
.car { color: var(--muted); font-size: clamp(16px, 2.4vw, 22px); }
.bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; margin: 20px 0 14px; }
select { background: var(--panel); color: var(--text); border: 1px solid var(--line); border-radius: 6px;
  padding: 6px 10px; font: inherit; max-width: 100%; }
.updated { color: var(--muted); font-size: 13px; }
table { width: 100%; border-collapse: separate; border-spacing: 0 6px; }
th { text-align: left; color: var(--muted); font-weight: 600; font-size: 13px; text-transform: uppercase;
  letter-spacing: .08em; padding: 0 14px; }
td { background: var(--row); padding: 14px; font-size: clamp(16px, 2.2vw, 22px); }
td:first-child { border-radius: 8px 0 0 8px; } td:last-child { border-radius: 0 8px 8px 0; }
.pos { width: 64px; font-weight: 800; color: var(--muted); text-align: center; }
tr.p1 .pos { color: var(--gold); } tr.p2 .pos { color: var(--silver); } tr.p3 .pos { color: var(--bronze); }
tr.p1 td { background: #262214; }
.name { font-weight: 700; }
.best { font-weight: 800; font-variant-numeric: tabular-nums; }
.gap, .att { font-variant-numeric: tabular-nums; color: var(--muted); }
.att.best-att { color: var(--text); }
.dnf { color: var(--dnf); font-weight: 700; }
.empty-msg { color: var(--muted); text-align: center; padding: 60px 0; font-size: 20px; }
@media (max-width: 640px) { .gap, th.gap { display: none; } td { padding: 10px 6px; font-size: 14px; } th { padding: 0 6px; font-size: 11px; } .pos { width: 32px; } }
</style>
</head>
<body>
<main>
  <div class="kicker">DIRT RALLY 2.0 · LAN TOURNAMENT</div>
  <h1 id="track">Waiting for the first run</h1>
  <div class="car" id="car"></div>
  <div class="bar">
    <select id="combo" hidden></select>
    <span class="updated" id="updated"></span>
  </div>
  <table>
    <thead><tr id="head"></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="empty-msg" id="empty" hidden>No results yet.</div>
</main>
<script>
const params = new URLSearchParams(location.search);
let selected = params.has('track') ? {track: params.get('track'), car: params.get('car')} : null;
const el = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

el('combo').addEventListener('change', e => {
  selected = JSON.parse(e.target.value);
  const q = new URLSearchParams(selected);
  history.replaceState(null, '', '?' + q);
  load();
});

function render(data) {
  el('track').textContent = data.track || 'Waiting for the first run';
  el('car').textContent = data.car || '';
  const combo = el('combo');
  combo.hidden = data.combos.length < 2;
  combo.innerHTML = data.combos.map(c => {
    const v = esc(JSON.stringify({track: c.track, car: c.car}));
    const sel = c.track === data.track && c.car === data.car ? ' selected' : '';
    return `<option value="${v}"${sel}>${esc(c.track)} · ${esc(c.car)} (${c.players})</option>`;
  }).join('');

  let head = '<th>Pos</th><th>Driver</th><th>Best</th><th class="gap">Gap</th>';
  for (let i = 1; i <= data.max_attempts; i++) head += `<th>Run ${i}</th>`;
  el('head').innerHTML = head;

  el('rows').innerHTML = data.rows.map(r => {
    const cls = r.position && r.position <= 3 ? `p${r.position}` : '';
    const atts = r.attempts.map(a => {
      const isBest = a.kind === 'time' && a.text === r.best;
      return `<td class="att ${a.kind === 'dnf' ? 'dnf' : ''} ${isBest ? 'best-att' : ''}">${esc(a.text || '–')}</td>`;
    }).join('');
    const best = r.best === 'DNF' ? '<span class="dnf">DNF</span>' : esc(r.best);
    return `<tr class="${cls}"><td class="pos">${r.position ?? '–'}</td><td class="name">${esc(r.name)}</td>` +
           `<td class="best">${best}</td><td class="gap">${esc(r.gap)}</td>${atts}</tr>`;
  }).join('');
  el('empty').hidden = data.rows.length > 0;
  el('updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
}

async function load() {
  try {
    const q = selected ? '?' + new URLSearchParams(selected) : '';
    const res = await fetch('api/standings' + q, {cache: 'no-store'});
    render(await res.json());
  } catch (e) {
    el('updated').textContent = 'Connection lost, retrying…';
  }
}
load();
setInterval(load, 3000);
</script>
</body>
</html>
'''

if __name__ == '__main__':
    dbPath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'tournament.db')
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    print(f'Leaderboard for {dbPath} on http://localhost:{port}')
    serve(TournamentDatabase(dbPath), port=port)
