'''
Password-protected web admin for tournament.db: edit or delete runs, add runs by hand,
rename or remove players, clear a track/car combination and download a backup.

Started by the tournament program on port 6969 (or the next free port), or on its own:

    python -m timerecorder.adminPortal [path/to/tournament.db] [port] [passcode]
'''
import hmac
import io
import json
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

from .leaderboard import standingsRows
from .tournamentBackups import BackupManager, MANUAL, describeAge
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

def createApp(database, passcode, backups=None):  #pylint: disable=too-many-locals,too-many-statements
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
        active = database.activeCombo()
        for combo in combos:
            combo['active'] = active == (combo['track'], combo['car'])
            combo['key'] = json.dumps([combo['track'], combo['car']])
        track, car = request.args.get('track'), request.args.get('car')
        if track is None and active is not None:
            track, car = active
        selected = next((c for c in combos if c['track'] == track and c['car'] == car), combos[0] if combos else None)
        runs = database.runs(selected['track'], selected['car']) if selected else []
        standings = standingsRows(database, selected['track'], selected['car']) if selected else []
        for run in runs:
            run['time_text'] = formatTime(run['time']) if run['time'] is not None else ''
            run['recorded_text'] = datetime.fromtimestamp(run['recorded_at']).strftime('%d.%m. %H:%M:%S')
        backupList = backupRows()
        return render_template_string(MAIN_PAGE, css=CSS, combos=combos, selected=selected, runs=runs,
                                      active=active, standings=standings, backups=backupList,
                                      backups_enabled=backups is not None,
                                      backup_keep=backups.keep if backups else 0,
                                      backup_interval=f'{backups.interval / 60:g}' if backups else '',
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

    @app.post('/setup')
    @loggedIn
    def setSetup():
        choice = request.form.get('combo', '')
        if choice == 'clear':
            database.setActiveCombo(None, None)
            flash('Tournament setup cleared, the next recorded run sets it again', 'ok')
            return redirect(url_for('index'))
        try:
            track, car = json.loads(choice)
        except (ValueError, TypeError):
            flash('Choose a track and car', 'error')
            return redirect(url_for('index'))
        if not any(c['track'] == track and c['car'] == car for c in database.combos()):
            flash('That track and car has no runs', 'error')
            return redirect(url_for('index'))
        database.setActiveCombo(track, car)
        flash(f'Tournament setup is now {track} · {car}', 'ok')
        return redirect(url_for('index', track=track, car=car))

    @app.post('/combo/delete')
    @loggedIn
    def deleteCombo():
        count = database.deleteCombo(request.form.get('track'), request.form.get('car'))
        flash(f'Deleted {count} runs', 'ok')
        return redirect(url_for('index'))

    def backupRows():
        if backups is None:
            return []
        rows = backups.list()
        for row in rows:
            row['age'] = describeAge(row['created'])
            try:
                info = backups.summary(row['name'])
            except Exception:  #pylint: disable=broad-except
                info = {'runs': None, 'players': None, 'active': None, 'leader': None, 'best': None}
            row.update(info)
            row['best_text'] = formatTime(info['best']) if info['best'] is not None else ''
        return rows

    def needBackups():
        if backups is None:
            abort(404)

    @app.post('/backups/create')
    @loggedIn
    def createBackup():
        needBackups()
        flash(f'Backup {backups.create(MANUAL)} created', 'ok')
        return redirect(url_for('index') + '#backups')

    @app.get('/backups/<name>')
    @loggedIn
    def viewBackup(name):
        needBackups()
        try:
            view, cleanup = backups.open(name)
        except FileNotFoundError:
            abort(404)
        try:
            info = next(b for b in backups.list() if b['name'] == name)
            active = view.activeCombo()
            runs = view.runs()
            for run in runs:
                run['time_text'] = formatTime(run['time']) if run['time'] is not None else 'DNF'
                run['recorded_text'] = datetime.fromtimestamp(run['recorded_at']).strftime('%d.%m. %H:%M:%S')
            return render_template_string(BACKUP_PAGE, css=CSS, info=info, active=active, runs=runs,
                                          standings=standingsRows(view, *active) if active else [],
                                          players=view.players(), max_attempts=view.max_attempts,
                                          csrf=session['csrf'])
        finally:
            cleanup()

    @app.get('/backups/<name>/download')
    @loggedIn
    def downloadBackup(name):
        needBackups()
        try:
            return send_file(backups.path(name), as_attachment=True, download_name=name,
                             mimetype='application/vnd.sqlite3')
        except FileNotFoundError:
            abort(404)

    @app.post('/backups/<name>/restore')
    @loggedIn
    def restoreBackup(name):
        needBackups()
        try:
            safety = backups.restore(name)
        except FileNotFoundError:
            abort(404)
        flash(f'Restored {name}. The state before the restore was saved as {safety}.', 'ok')
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

def serve(database, passcode, host='0.0.0.0', port=DEFAULT_PORT, backups=None):  #pylint: disable=too-many-arguments
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    createApp(database, passcode, backups).run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

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
.badge { background:var(--ok); color:#10261a; font-weight:800; font-size:11px; letter-spacing:.1em; padding:3px 7px; border-radius:4px; }
.setup { font-size:18px; margin-bottom:4px; }
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
    <h1>Tournament admin</h1></div>
  <div class="row">
    <a class="button ghost" href="#backups">Backups</a>
    <a class="button ghost" href="{{ url_for('backup') }}">Download database</a>
    <form class="inline" method="post" action="{{ url_for('logout') }}"><input type="hidden" name="csrf" value="{{ csrf }}">
      <button class="ghost">Log out</button></form>
  </div>
</div>

{% for category, message in get_flashed_messages(with_categories=true) %}
  <div class="flash {{ category }}">{{ message }}</div>
{% endfor %}

<h2>Tournament setup</h2>
<div class="card">
  {% if active %}
    <div class="setup"><span class="badge">LIVE</span> <strong>{{ active[0] }}</strong> · {{ active[1] }}</div>
    <div class="muted">The public leaderboard shows only runs on this track and car.</div>
  {% else %}
    <div class="setup"><strong>Not set.</strong></div>
    <div class="muted">The next recorded run sets the tournament track and car.</div>
  {% endif %}
  {% if combos %}
  <form class="row" method="post" action="{{ url_for('setSetup') }}" style="margin-top:12px">
    <input type="hidden" name="csrf" value="{{ csrf }}">
    <select name="combo">
      {% for c in combos %}
      <option value="{{ c.key }}" {{ 'selected' if c.active else '' }}>{{ c.track }} · {{ c.car }} ({{ c.players }} players)</option>
      {% endfor %}
      {% if active %}<option value="clear">Clear: next run sets it</option>{% endif %}
    </select>
    <button>Set as tournament setup</button>
  </form>
  {% endif %}
</div>

{% if selected %}
<h2>Leaderboard</h2>
<div class="row">
  <select onchange="location = this.value" aria-label="Leaderboard">
    {% for c in combos %}
    <option value="{{ url_for('index', track=c.track, car=c.car) }}"
      {{ 'selected' if c.track == selected.track and c.car == selected.car else '' }}>
      {{ '★ ' if c.active else '' }}{{ c.track }} · {{ c.car }} ({{ c.players }})</option>
    {% endfor %}
  </select>
  {% if selected.active %}<span class="badge">LIVE</span>{% else %}<span class="muted">Not the tournament setup, not on the public leaderboard</span>{% endif %}
</div>
<div class="card scroll" style="margin-top:10px"><table>
  <tr><th>Pos</th><th>Driver</th><th>Best</th><th>Gap</th>{% for n in range(1, max_attempts + 1) %}<th>Run {{ n }}</th>{% endfor %}</tr>
  {% for r in standings %}
  <tr><td>{{ r.position or '–' }}</td><td><strong>{{ r.name }}</strong></td>
    <td class="{{ 'dnf' if r.best == 'DNF' else '' }}"><strong>{{ r.best }}</strong></td><td class="muted">{{ r.gap }}</td>
    {% for a in r.attempts %}<td class="{{ 'dnf' if a.kind == 'dnf' else '' }}">{{ a.text or '–' }}</td>{% endfor %}</tr>
  {% endfor %}
</table></div>
{% endif %}

{% if selected %}
<h2>Runs on {{ selected.track }} · {{ selected.car }}</h2>
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

{% if backups_enabled %}
<h2 id="backups">Backups</h2>
<div class="card">
  <div class="row" style="justify-content:space-between">
    <span class="muted">The newest {{ backup_keep }} copies are kept. A copy is made every {{ backup_interval }} minutes (only if something changed), on every new best time, and before a restore.</span>
    <form class="inline" method="post" action="{{ url_for('createBackup') }}"><input type="hidden" name="csrf" value="{{ csrf }}">
      <button class="ghost">Back up now</button></form>
  </div>
  <div class="scroll" style="margin-top:10px"><table>
    <tr><th>Created</th><th>Reason</th><th>Runs</th><th>Players</th><th>Leader</th><th></th></tr>
    {% for b in backups %}
    <tr>
      <td>{{ b.created_text }} <span class="muted">· {{ b.age }}</span></td>
      <td>{{ b.reason_text }}</td>
      <td>{{ b.runs if b.runs is not none else '?' }}</td>
      <td>{{ b.players if b.players is not none else '?' }}</td>
      <td>{% if b.leader %}{{ b.leader }} <span class="muted">{{ b.best_text }}</span>{% else %}<span class="muted">–</span>{% endif %}</td>
      <td>
        <a class="button ghost" href="{{ url_for('viewBackup', name=b.name) }}">View</a>
        <a class="button ghost" href="{{ url_for('downloadBackup', name=b.name) }}">Download</a>
        <form class="inline" method="post" action="{{ url_for('restoreBackup', name=b.name) }}"
              onsubmit='return confirm({{ ("Restore the backup from " ~ b.created_text ~ "? All current data is replaced. The current state is backed up first.")|tojson }})'>
          <input type="hidden" name="csrf" value="{{ csrf }}"><button class="danger">Restore</button></form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="6" class="muted">No backups yet.</td></tr>
    {% endfor %}
  </table></div>
</div>
{% endif %}

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

BACKUP_PAGE = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backup · Tournament Admin</title><style>{{ css }}</style></head>
<body><main>
<div class="top">
  <div><div class="kicker">DR2 TOURNAMENT · ADMIN · BACKUP</div>
    <h1>{{ info.created_text }}</h1>
    <div class="muted">{{ info.reason_text }} · {{ info.name }}</div></div>
  <div class="row">
    <a class="button ghost" href="{{ url_for('index') }}#backups">Back</a>
    <a class="button ghost" href="{{ url_for('downloadBackup', name=info.name) }}">Download</a>
    <form class="inline" method="post" action="{{ url_for('restoreBackup', name=info.name) }}"
          onsubmit='return confirm({{ ("Restore this backup? All current data is replaced. The current state is backed up first.")|tojson }})'>
      <input type="hidden" name="csrf" value="{{ csrf }}"><button class="danger">Restore this backup</button></form>
  </div>
</div>
<div class="flash ok" style="background:#1d2129;color:var(--muted)">Read-only view of the backup. Nothing here changes the live tournament until you restore.</div>

<h2>Tournament setup</h2>
<div class="card">{% if active %}<strong>{{ active[0] }}</strong> · {{ active[1] }}{% else %}<span class="muted">Not set</span>{% endif %}</div>

{% if active %}
<h2>Leaderboard</h2>
<div class="card scroll"><table>
  <tr><th>Pos</th><th>Driver</th><th>Best</th><th>Gap</th>{% for n in range(1, max_attempts + 1) %}<th>Run {{ n }}</th>{% endfor %}</tr>
  {% for r in standings %}
  <tr><td>{{ r.position or '–' }}</td><td><strong>{{ r.name }}</strong></td>
    <td class="{{ 'dnf' if r.best == 'DNF' else '' }}"><strong>{{ r.best }}</strong></td><td class="muted">{{ r.gap }}</td>
    {% for a in r.attempts %}<td class="{{ 'dnf' if a.kind == 'dnf' else '' }}">{{ a.text or '–' }}</td>{% endfor %}</tr>
  {% else %}<tr><td colspan="6" class="muted">No runs.</td></tr>{% endfor %}
</table></div>
{% endif %}

<h2>All runs ({{ runs|length }})</h2>
<div class="card scroll"><table>
  <tr><th>Track · car</th><th>Player</th><th>Attempt</th><th>Time</th><th>Note</th><th>Recorded</th></tr>
  {% for r in runs %}
  <tr><td class="muted">{{ r.track }} · {{ r.car }}</td><td><strong>{{ r.name }}</strong></td><td>{{ r.attempt }}/{{ max_attempts }}</td>
    <td class="{{ 'dnf' if r.status == 'DNF' else '' }}">{{ r.time_text }}</td><td class="muted">{{ r.note or '' }}</td>
    <td class="muted">{{ r.recorded_text }}</td></tr>
  {% else %}<tr><td colspan="6" class="muted">No runs.</td></tr>{% endfor %}
</table></div>
</main></body></html>'''

if __name__ == '__main__':
    dbPath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), 'tournament.db')
    adminPort = findFreePort('0.0.0.0', int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT)
    code = sys.argv[3] if len(sys.argv) > 3 else 'jermu'
    print(f'Admin portal for {dbPath} on http://localhost:{adminPort}')
    standalone = TournamentDatabase(dbPath)
    serve(standalone, code, port=adminPort,
          backups=BackupManager(standalone, os.path.join(os.path.dirname(os.path.abspath(dbPath)), 'backups')))
