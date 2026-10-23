'''
Password-protected web admin for tournament.db: edit or delete runs, add runs by hand,
rename or remove players, clear a track/car combination and download a backup.

Started by the tournament program on port 6969 (or the next free port), or on its own:

    python -m timerecorder.adminPortal [path/to/tournament.db] [port] [passcode]
'''
import hmac
import io
import logging
import os
import secrets
import socket
import sys
import tempfile
import time
from datetime import datetime
from functools import wraps

from flask import Flask, abort, flash, redirect, render_template_string, request, send_file, session, url_for

from .tournamentDatabase import TournamentDatabase, AttemptsExhausted, FINISHED, DNF, formatTime, parseTime

DEFAULT_PORT = 6969

def findFreePort(host, start=DEFAULT_PORT, tries=50):
    '''First port from start upwards that can be bound on host.'''
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue
    raise OSError(f'No free port between {start} and {start + tries - 1}')

def createApp(database, passcode):  #pylint: disable=too-many-locals,too-many-statements
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)  # new on every start, which logs everyone out
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict')

    def loggedIn(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get('admin'):
                return redirect(url_for('login'))
            if request.method == 'POST' and not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', '')):
                abort(400)
            return view(*args, **kwargs)
        return wrapper

    def backTo(track, car):
        return redirect(url_for('index', track=track, car=car) if track is not None else url_for('index'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        error = None
        if request.method == 'POST':
            if hmac.compare_digest(request.form.get('passcode', '').encode(), passcode.encode()):
                session.clear()
                session['admin'] = True
                session['csrf'] = secrets.token_hex(16)
                return redirect(url_for('index'))
            time.sleep(1)  # slow down guessing
            error = 'Wrong passcode'
        return render_template_string(LOGIN_PAGE, error=error, css=CSS)

    @app.post('/logout')
    @loggedIn
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @loggedIn
    def index():
        combos = database.combos()
        track, car = request.args.get('track'), request.args.get('car')
        selected = next((c for c in combos if c['track'] == track and c['car'] == car), combos[0] if combos else None)
        runs = database.runs(selected['track'], selected['car']) if selected else []
        for run in runs:
            run['time_text'] = formatTime(run['time']) if run['time'] is not None else ''
            run['recorded_text'] = datetime.fromtimestamp(run['recorded_at']).strftime('%d.%m. %H:%M:%S')
        return render_template_string(MAIN_PAGE, css=CSS, combos=combos, selected=selected, runs=runs,
                                      players=database.players(), max_attempts=database.max_attempts,
                                      csrf=session['csrf'], FINISHED=FINISHED, DNF=DNF)

    @app.post('/runs/<int:runId>/update')
    @loggedIn
    def updateRun(runId):
        form = request.form
        try:
            status = form.get('status')
            laptime = parseTime(form.get('time')) if status == FINISHED else None
            database.updateRun(runId, laptime, status, form.get('note', '').strip())
            flash('Run saved', 'ok')
        except ValueError as exc:
            flash(str(exc), 'error')
        return backTo(form.get('track'), form.get('car'))

    @app.post('/runs/<int:runId>/delete')
    @loggedIn
    def deleteRun(runId):
        if database.deleteRun(runId):
            flash('Run deleted, the player can drive that attempt again', 'ok')
        return backTo(request.form.get('track'), request.form.get('car'))

    @app.post('/runs/add')
    @loggedIn
    def addRun():
        form = request.form
        track, car = form.get('track'), form.get('car')
        try:
            status = form.get('status')
            laptime = parseTime(form.get('time')) if status == FINISHED else None
            attempt = database.recordResult(form.get('name', ''), track, car, laptime, status,
                                            form.get('note', '').strip() or 'added by admin')
            flash(f'Added attempt {attempt}', 'ok')
        except (ValueError, AttemptsExhausted) as exc:
            flash(str(exc), 'error')
        return backTo(track, car)

    @app.post('/players/<int:playerId>/rename')
    @loggedIn
    def renamePlayer(playerId):
        try:
            database.renamePlayer(playerId, request.form.get('name', ''))
            flash('Player renamed', 'ok')
        except ValueError as exc:
            flash(str(exc), 'error')
        return backTo(request.form.get('track'), request.form.get('car'))

    @app.post('/players/<int:playerId>/delete')
    @loggedIn
    def deletePlayer(playerId):
        database.deletePlayer(playerId)
        flash('Player and all their runs deleted', 'ok')
        return backTo(request.form.get('track'), request.form.get('car'))

    @app.post('/combo/delete')
    @loggedIn
    def deleteCombo():
        count = database.deleteCombo(request.form.get('track'), request.form.get('car'))
        flash(f'Deleted {count} runs', 'ok')
        return redirect(url_for('index'))

    @app.get('/backup')
    @loggedIn
    def backup():
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'backup.db')
            database.backup(path)
            with open(path, 'rb') as file:
                data = io.BytesIO(file.read())

        name = datetime.now().strftime('tournament-backup-%Y%m%d-%H%M%S.db')
        return send_file(data, as_attachment=True, download_name=name, mimetype='application/vnd.sqlite3')

    return app

def serve(database, passcode, host='0.0.0.0', port=DEFAULT_PORT):
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    createApp(database, passcode).run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

CSS = '''
:root { --bg:#101216; --panel:#181b21; --row:#1d2129; --line:#2a2f39; --text:#f2f4f8; --muted:#8b93a3;
  --accent:#ffb000; --danger:#ff6b5b; --ok:#5fd18b; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.45 "Segoe UI", system-ui, sans-serif; }
main { max-width:1100px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:26px; margin:4px 0 0; } h2 { font-size:18px; margin:32px 0 10px; }
.kicker { color:var(--accent); font-weight:700; letter-spacing:.14em; font-size:12px; }
.muted { color:var(--muted); }
.top { display:flex; flex-wrap:wrap; gap:12px; justify-content:space-between; align-items:flex-end; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; }
th { text-align:left; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em;
  padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:middle; white-space:nowrap; }
input, select { background:var(--row); color:var(--text); border:1px solid var(--line); border-radius:6px;
  padding:6px 8px; font:inherit; }
input:focus, select:focus { outline:2px solid var(--accent); outline-offset:0; }
input.time { width:110px; font-variant-numeric:tabular-nums; } input.note { width:180px; }
button, .button { background:var(--accent); color:#16181d; border:0; border-radius:6px; padding:7px 12px;
  font:inherit; font-weight:700; cursor:pointer; text-decoration:none; display:inline-block; }
button.ghost, .button.ghost { background:transparent; color:var(--text); border:1px solid var(--line); font-weight:600; }
button.danger { background:transparent; color:var(--danger); border:1px solid var(--danger); }
form.inline { display:inline; margin:0; }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.combos a { color:var(--text); text-decoration:none; padding:6px 10px; border:1px solid var(--line); border-radius:6px; }
.combos a.active { border-color:var(--accent); color:var(--accent); }
.flash { padding:10px 14px; border-radius:8px; margin:12px 0; }
.flash.ok { background:#18301f; color:var(--ok); } .flash.error { background:#3a1b18; color:var(--danger); }
.dnf { color:var(--danger); font-weight:700; }
.login { max-width:340px; margin:18vh auto 0; }
.login input { width:100%; font-size:18px; padding:10px; margin:12px 0; }
.login button { width:100%; font-size:16px; padding:10px; }
'''

LOGIN_PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tournament Admin</title><style>{{ css }}</style></head>
<body><main><form class="card login" method="post">
  <div class="kicker">DR2 TOURNAMENT</div><h1>Admin</h1>
  {% if error %}<div class="flash error">{{ error }}</div>{% endif %}
  <input type="password" name="passcode" placeholder="Passcode" autofocus autocomplete="current-password">
  <button type="submit">Log in</button>
</form></main></body></html>'''

MAIN_PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tournament Admin</title><style>{{ css }}</style></head>
<body><main>
<div class="top">
  <div><div class="kicker">DR2 TOURNAMENT · ADMIN</div>
    <h1>{{ selected.track if selected else 'No runs yet' }}</h1>
    <div class="muted">{{ selected.car if selected else '' }}</div></div>
  <div class="row">
    <a class="button ghost" href="{{ url_for('backup') }}">Download backup</a>
    <form class="inline" method="post" action="{{ url_for('logout') }}"><input type="hidden" name="csrf" value="{{ csrf }}">
      <button class="ghost">Log out</button></form>
  </div>
</div>

{% for category, message in get_flashed_messages(with_categories=true) %}
  <div class="flash {{ category }}">{{ message }}</div>
{% endfor %}

{% if combos|length > 1 %}
<h2>Track &amp; car</h2>
<div class="row combos">
  {% for c in combos %}
  <a class="{{ 'active' if selected and c.track == selected.track and c.car == selected.car else '' }}"
     href="{{ url_for('index', track=c.track, car=c.car) }}">{{ c.track }} · {{ c.car }} ({{ c.players }})</a>
  {% endfor %}
</div>
{% endif %}

{% if selected %}
<h2>Runs</h2>
<div class="card scroll"><table>
  <tr><th>Player</th><th>Attempt</th><th>Status</th><th>Time</th><th>Note</th><th>Recorded</th><th></th></tr>
  {% for r in runs %}
  <tr>
    <td><strong>{{ r.name }}</strong></td>
    <td>{{ r.attempt }}/{{ max_attempts }}</td>
    <td><select name="status" form="run{{ r.id }}">
      <option value="{{ FINISHED }}" {{ 'selected' if r.status == FINISHED else '' }}>Finished</option>
      <option value="{{ DNF }}" {{ 'selected' if r.status == DNF else '' }}>DNF</option></select></td>
    <td><input class="time" name="time" form="run{{ r.id }}" value="{{ r.time_text }}" placeholder="m:ss.mmm"></td>
    <td><input class="note" name="note" form="run{{ r.id }}" value="{{ r.note or '' }}"></td>
    <td class="muted">{{ r.recorded_text }}</td>
    <td>
      <form class="inline" id="run{{ r.id }}" method="post" action="{{ url_for('updateRun', runId=r.id) }}">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">
        <button>Save</button></form>
      <form class="inline" method="post" action="{{ url_for('deleteRun', runId=r.id) }}"
            onsubmit='return confirm({{ ("Delete attempt " ~ r.attempt ~ " of " ~ r.name ~ "? They can drive it again.")|tojson }})'>
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">
        <button class="danger">Delete</button></form>
    </td>
  </tr>
  {% endfor %}
</table></div>

<h2>Add a run by hand</h2>
<form class="card row" method="post" action="{{ url_for('addRun') }}">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">
  <input name="name" list="names" placeholder="Nickname" required>
  <datalist id="names">{% for p in players %}<option value="{{ p.name }}">{% endfor %}</datalist>
  <select name="status"><option value="{{ FINISHED }}">Finished</option><option value="{{ DNF }}">DNF</option></select>
  <input class="time" name="time" placeholder="m:ss.mmm">
  <input class="note" name="note" placeholder="Note (optional)">
  <button>Add</button>
  <span class="muted">Counts as the player's next attempt on this track and car.</span>
</form>
{% endif %}

<h2>Players</h2>
<div class="card scroll"><table>
  <tr><th>Nickname</th><th>Runs (all tracks)</th><th></th></tr>
  {% for p in players %}
  <tr>
    <td><input name="name" form="player{{ p.id }}" value="{{ p.name }}"></td>
    <td>{{ p.runs }}</td>
    <td>
      <form class="inline" id="player{{ p.id }}" method="post" action="{{ url_for('renamePlayer', playerId=p.id) }}">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        {% if selected %}<input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">{% endif %}
        <button class="ghost">Rename</button></form>
      <form class="inline" method="post" action="{{ url_for('deletePlayer', playerId=p.id) }}"
            onsubmit='return confirm({{ ("Delete " ~ p.name ~ " and all " ~ p.runs ~ " runs?")|tojson }})'>
        <input type="hidden" name="csrf" value="{{ csrf }}">
        {% if selected %}<input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">{% endif %}
        <button class="danger">Delete</button></form>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="3" class="muted">No players yet.</td></tr>
  {% endfor %}
</table></div>

{% if selected %}
<h2>Danger zone</h2>
<form class="card row" method="post" action="{{ url_for('deleteCombo') }}"
      onsubmit='return confirm({{ ("Delete ALL runs on " ~ selected.track ~ " with " ~ selected.car ~ "? Download a backup first.")|tojson }})'>
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <input type="hidden" name="track" value="{{ selected.track }}"><input type="hidden" name="car" value="{{ selected.car }}">
  <button class="danger">Delete all runs on this track &amp; car</button>
  <span class="muted">Players without any remaining runs are removed too.</span>
</form>
{% endif %}
</main></body></html>'''

if __name__ == '__main__':
    dbPath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'tournament.db')
    adminPort = findFreePort('0.0.0.0', int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT)
    code = sys.argv[3] if len(sys.argv) > 3 else 'jermu'
    print(f'Admin portal for {dbPath} on http://localhost:{adminPort}')
    serve(TournamentDatabase(dbPath), code, port=adminPort)
