'''
Storage for the LAN tournament: players and their attempts per track/car combination.

Kept in its own SQLite file (tournament.db) so the original laptimes database stays untouched.
Every call opens its own connection, so it can be used from the UDP thread, the UI thread
and the web server at the same time.
'''
import sqlite3
import time
from contextlib import closing

FINISHED = 'FINISHED'
DNF = 'DNF'

MAX_NAME_LENGTH = 24

SCHEMA = '''
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id),
    track TEXT NOT NULL,
    car TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    time REAL,
    status TEXT NOT NULL CHECK (status IN ('FINISHED', 'DNF')),
    note TEXT,
    recorded_at REAL NOT NULL,
    UNIQUE (player_id, track, car, attempt)
);
CREATE INDEX IF NOT EXISTS results_combo ON results (track, car);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
'''

ACTIVE_TRACK = 'active_track'
ACTIVE_CAR = 'active_car'

class AttemptsExhausted(Exception):
    pass

def cleanName(name):
    return ' '.join((name or '').split())[:MAX_NAME_LENGTH]

def nameKey(name):
    return cleanName(name).casefold()

def formatTime(seconds):
    if seconds is None:
        return 'DNF'
    millis = int(round(seconds * 1000))
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f'{minutes:02d}:{secs:02d}.{millis:03d}'

class TournamentDatabase():

    def __init__(self, path, maxAttempts=2):
        self.path = path
        self.max_attempts = maxAttempts
        with closing(self._connect()) as conn:
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON;')
        return conn

    def _findPlayer(self, conn, name):
        return conn.execute('SELECT id, name FROM players WHERE name_key = ?', (nameKey(name),)).fetchone()

    def _attempts(self, conn, playerId, track, car):
        rows = conn.execute('SELECT attempt, time, status, note FROM results '
                            'WHERE player_id = ? AND track = ? AND car = ? ORDER BY attempt',
                            (playerId, track, car)).fetchall()
        return [dict(row) for row in rows]

    def lookup(self, name, track, car):
        '''
        Information for the nickname prompt. Returns None for an empty name.
        '''
        if not nameKey(name):
            return None

        with closing(self._connect()) as conn:
            player = self._findPlayer(conn, name)
            attempts = self._attempts(conn, player['id'], track, car) if player else []

        return {
            'found': player is not None,
            'name': player['name'] if player else cleanName(name),
            'attempts': attempts,
            'used': len(attempts),
            'max': self.max_attempts,
            'remaining': max(0, self.max_attempts - len(attempts)),
        }

    def recordResult(self, name, track, car, laptime, status, note=None):
        '''
        Stores the next attempt for the player and returns its number.
        The player is created on their first result, keeping the name as first typed.
        '''
        if not nameKey(name):
            raise ValueError('Empty nickname')
        if status not in (FINISHED, DNF):
            raise ValueError(f'Unknown status {status}')

        with closing(self._connect()) as conn:
            with conn:
                player = self._findPlayer(conn, name)
                if player is None:
                    cursor = conn.execute('INSERT INTO players (name, name_key, created_at) VALUES (?, ?, ?)',
                                          (cleanName(name), nameKey(name), time.time()))
                    playerId = cursor.lastrowid
                else:
                    playerId = player['id']

                used = len(self._attempts(conn, playerId, track, car))
                if used >= self.max_attempts:
                    raise AttemptsExhausted(f'{cleanName(name)} has used all {self.max_attempts} attempts')

                attempt = used + 1
                if self._activeCombo(conn) is None:
                    # the first run of the tournament defines its track and car
                    self._setActiveCombo(conn, track, car)
                conn.execute('INSERT INTO results (player_id, track, car, attempt, time, status, note, recorded_at) '
                             'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                             (playerId, track, car, attempt, round(laptime, 3) if status == FINISHED else None,
                              status, note, time.time()))
        return attempt

    # --- tournament setup (the track and car the leaderboard shows) ---

    @staticmethod
    def _activeCombo(conn):
        rows = dict(conn.execute('SELECT key, value FROM settings WHERE key IN (?, ?)',
                                 (ACTIVE_TRACK, ACTIVE_CAR)).fetchall())
        if rows.get(ACTIVE_TRACK) is None or rows.get(ACTIVE_CAR) is None:
            return None
        return rows[ACTIVE_TRACK], rows[ACTIVE_CAR]

    @staticmethod
    def _setActiveCombo(conn, track, car):
        conn.executemany('INSERT INTO settings (key, value) VALUES (?, ?) '
                         'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                         ((ACTIVE_TRACK, track), (ACTIVE_CAR, car)))

    def activeCombo(self):
        '''The tournament (track, car), or None until the first run is recorded.'''
        with closing(self._connect()) as conn:
            return self._activeCombo(conn)

    def setActiveCombo(self, track, car):
        with closing(self._connect()) as conn:
            with conn:
                if track is None or car is None:
                    conn.execute('DELETE FROM settings WHERE key IN (?, ?)', (ACTIVE_TRACK, ACTIVE_CAR))
                else:
                    self._setActiveCombo(conn, track, car)

    def isActiveCombo(self, track, car):
        '''True when (track, car) is the tournament setup, or no setup has been chosen yet.'''
        active = self.activeCombo()
        return active is None or active == (track, car)

    def combos(self):
        '''
        All track/car combinations with results, most recently active first.
        '''
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT track, car, COUNT(DISTINCT player_id) AS players, MAX(recorded_at) AS last '
                                'FROM results GROUP BY track, car ORDER BY last DESC').fetchall()
        return [dict(row) for row in rows]

    def standings(self, track, car):
        '''
        One row per player: best time first, then name alphabetically. Players without
        a finished run (only DNFs) go to the bottom, alphabetically.
        '''
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT p.name, r.attempt, r.time, r.status FROM results r '
                                'JOIN players p ON p.id = r.player_id '
                                'WHERE r.track = ? AND r.car = ?', (track, car)).fetchall()

        players = {}
        for row in rows:
            entry = players.setdefault(row['name'], {'name': row['name'], 'attempts': {}, 'best': None})
            entry['attempts'][row['attempt']] = row['time'] if row['status'] == FINISHED else DNF
            if row['status'] == FINISHED and (entry['best'] is None or row['time'] < entry['best']):
                entry['best'] = row['time']

        def sortKey(entry):
            noTime = entry['best'] is None
            return (noTime, entry['best'] if not noTime else 0.0, entry['name'].casefold())

        ordered = sorted(players.values(), key=sortKey)

        leader = ordered[0]['best'] if ordered else None
        position = 0
        previousBest = object()
        for index, entry in enumerate(ordered, start=1):
            if entry['best'] is None:
                entry['position'] = None
            else:
                # equal times share a position
                if entry['best'] != previousBest:
                    position = index
                    previousBest = entry['best']
                entry['position'] = position
            entry['gap'] = entry['best'] - leader if entry['best'] is not None and leader is not None else None
            entry['attempts'] = [entry['attempts'].get(n) for n in range(1, self.max_attempts + 1)]
            entry['used'] = sum(1 for a in entry['attempts'] if a is not None)

        return ordered

    # --- administration ---

    def players(self):
        with closing(self._connect()) as conn:
            rows = conn.execute('SELECT p.id, p.name, COUNT(r.id) AS runs FROM players p '
                                'LEFT JOIN results r ON r.player_id = p.id '
                                'GROUP BY p.id ORDER BY p.name COLLATE NOCASE').fetchall()
        return [dict(row) for row in rows]

    def runs(self, track=None, car=None):
        '''All runs, optionally for one track/car combination, by player and attempt.'''
        query = ('SELECT r.id, r.player_id, p.name, r.track, r.car, r.attempt, r.time, r.status, r.note, r.recorded_at '
                 'FROM results r JOIN players p ON p.id = r.player_id')
        args = ()
        if track is not None:
            query += ' WHERE r.track = ? AND r.car = ?'
            args = (track, car)
        query += ' ORDER BY r.track, r.car, p.name COLLATE NOCASE, r.attempt'
        with closing(self._connect()) as conn:
            return [dict(row) for row in conn.execute(query, args).fetchall()]

    @staticmethod
    def _renumber(conn, playerId, track, car):
        # ascending, so each new number is free by the time it is assigned
        rows = conn.execute('SELECT id, attempt FROM results WHERE player_id = ? AND track = ? AND car = ? '
                            'ORDER BY attempt, recorded_at', (playerId, track, car)).fetchall()
        for number, row in enumerate(rows, start=1):
            if row['attempt'] != number:
                conn.execute('UPDATE results SET attempt = ? WHERE id = ?', (number, row['id']))

    def deleteRun(self, runId):
        '''Removes a run; later attempts of that player move up, so the attempt becomes available again.'''
        with closing(self._connect()) as conn:
            with conn:
                row = conn.execute('SELECT player_id, track, car FROM results WHERE id = ?', (runId,)).fetchone()
                if row is None:
                    return False
                conn.execute('DELETE FROM results WHERE id = ?', (runId,))
                self._renumber(conn, row['player_id'], row['track'], row['car'])
        return True

    def updateRun(self, runId, laptime, status, note=None):
        if status not in (FINISHED, DNF):
            raise ValueError(f'Unknown status {status}')
        if status == FINISHED and (laptime is None or laptime <= 0):
            raise ValueError('A finished run needs a time')
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute('UPDATE results SET time = ?, status = ?, note = ? WHERE id = ?',
                                      (round(laptime, 3) if status == FINISHED else None, status, note or None, runId))
        return cursor.rowcount == 1

    def renamePlayer(self, playerId, newName):
        if not nameKey(newName):
            raise ValueError('Empty nickname')
        with closing(self._connect()) as conn:
            with conn:
                other = self._findPlayer(conn, newName)
                if other is not None and other['id'] != playerId:
                    raise ValueError(f"The nickname {other['name']} is already taken")
                cursor = conn.execute('UPDATE players SET name = ?, name_key = ? WHERE id = ?',
                                      (cleanName(newName), nameKey(newName), playerId))
        return cursor.rowcount == 1

    def deletePlayer(self, playerId):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute('DELETE FROM results WHERE player_id = ?', (playerId,))
                cursor = conn.execute('DELETE FROM players WHERE id = ?', (playerId,))
        return cursor.rowcount == 1

    def deleteCombo(self, track, car):
        with closing(self._connect()) as conn:
            with conn:
                cursor = conn.execute('DELETE FROM results WHERE track = ? AND car = ?', (track, car))
                conn.execute('DELETE FROM players WHERE id NOT IN (SELECT player_id FROM results)')
                if self._activeCombo(conn) == (track, car):
                    # the next recorded run defines the setup again
                    conn.execute('DELETE FROM settings WHERE key IN (?, ?)', (ACTIVE_TRACK, ACTIVE_CAR))
        return cursor.rowcount

    def bestTime(self, track, car):
        '''Fastest finished time on a track/car, or None.'''
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MIN(time) FROM results WHERE track = ? AND car = ? AND status = 'FINISHED'",
                               (track, car)).fetchone()
        return row[0]

    def restoreFrom(self, path):
        '''Replaces all contents with those of another database file (online, other connections stay valid).'''
        with closing(sqlite3.connect(path)) as source, closing(self._connect()) as target:
            source.backup(target)
        with closing(self._connect()) as conn:
            conn.execute('PRAGMA journal_mode=WAL;')  # backups are stored in rollback-journal mode
            conn.executescript(SCHEMA)  # an older backup may lack newer tables

    def backup(self, path):
        '''Consistent copy of the database, safe while it is in use.'''
        with closing(self._connect()) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
            target.execute('PRAGMA journal_mode=DELETE;')  # a single self-contained file, no -wal/-shm


def parseTime(text):
    '''Parses "m:ss.mmm", "ss.mmm" or "h:mm:ss.mmm" into seconds.'''
    text = (text or '').strip().replace(',', '.')
    if not text:
        raise ValueError('Enter a time')
    seconds = 0.0
    try:
        for part in text.split(':'):
            seconds = seconds * 60 + float(part)
    except ValueError:
        raise ValueError(f'Cannot read the time "{text}", use e.g. 3:07.654') from None
    if seconds <= 0:
        raise ValueError('The time must be positive')
    return seconds
