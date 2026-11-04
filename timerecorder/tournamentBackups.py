'''
Rotating backups of tournament.db: the live database plus the newest `keep` copies (default 3)
in a backups folder next to it.

A backup is taken every interval (skipped when nothing changed since the newest backup),
when a run sets a new best time on the tournament leaderboard, on request from the admin
portal, and right before a restore.
'''
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import datetime

from .log import getLogger
from .tournamentDatabase import TournamentDatabase

logger = getLogger(__name__)

SCHEDULED = 'scheduled'
NEW_BEST = 'new-best'
MANUAL = 'manual'
BEFORE_RESTORE = 'before-restore'
REASONS = {
    SCHEDULED: 'Every 15 minutes',
    NEW_BEST: 'New best time',
    MANUAL: 'Made by admin',
    BEFORE_RESTORE: 'Before a restore',
}

NAME_PATTERN = re.compile(r'^tournament-(\d{8}-\d{6}-\d{3})-([a-z-]+)\.db$')

def fingerprint(path):
    '''Hash of the database contents, independent of page layout.'''
    digest = hashlib.sha256()
    with closing(sqlite3.connect(path)) as conn:
        for line in conn.iterdump():
            digest.update(line.encode('utf-8'))
    return digest.hexdigest()

class BackupManager():

    def __init__(self, database, folder, keep=3, intervalMinutes=15.0):
        self.database = database
        self.folder = folder
        self.keep = max(1, int(keep))
        self.interval = max(1.0, float(intervalMinutes)) * 60
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        os.makedirs(folder, exist_ok=True)
        REASONS[SCHEDULED] = f'Every {intervalMinutes:g} minutes'

    # --- listing ---

    def list(self):
        '''Backups, newest first.'''
        backups = []
        for name in os.listdir(self.folder):
            match = NAME_PATTERN.match(name)
            if not match:
                continue
            created = datetime.strptime(match.group(1), '%Y%m%d-%H%M%S-%f')
            path = os.path.join(self.folder, name)
            backups.append({
                'name': name,
                'created': created,
                'created_text': created.strftime('%d.%m.%Y %H:%M:%S'),
                'reason': match.group(2),
                'reason_text': REASONS.get(match.group(2), match.group(2)),
                'size': os.path.getsize(path),
            })
        return sorted(backups, key=lambda b: b['name'], reverse=True)

    def path(self, name):
        '''Full path of a listed backup; anything else (e.g. ../) is refused.'''
        if not NAME_PATTERN.match(name or '') or not os.path.isfile(os.path.join(self.folder, name)):
            raise FileNotFoundError(f'No backup called {name}')
        return os.path.join(self.folder, name)

    # --- creating ---

    def create(self, reason=MANUAL, skipIfUnchanged=False):
        '''Takes a backup and drops the oldest beyond `keep`. Returns the new name, or None if skipped.'''
        with self.lock:
            now = datetime.now()
            name = f"tournament-{now.strftime('%Y%m%d-%H%M%S')}-{now.microsecond // 1000:03d}-{reason}.db"
            target = os.path.join(self.folder, name)
            temporary = target + '.tmp'
            self.database.backup(temporary)

            if skipIfUnchanged:
                newest = self.list()
                if newest and fingerprint(temporary) == fingerprint(self.path(newest[0]['name'])):
                    os.remove(temporary)
                    logger.debug('Database unchanged, no %s backup', reason)
                    return None

            os.replace(temporary, target)
            self._prune()
            logger.info('Backup %s', name)
            return name

    def _prune(self):
        for old in self.list()[self.keep:]:
            try:
                os.remove(os.path.join(self.folder, old['name']))
            except OSError:
                logger.exception('Could not remove old backup %s', old['name'])

    # --- viewing and restoring ---

    def open(self, name):
        '''
        A TournamentDatabase on a private copy of the backup, so viewing never changes the file.
        Returns (database, cleanup function).
        '''
        source = self.path(name)
        folder = tempfile.mkdtemp(prefix='tournament-view-')
        copy = os.path.join(folder, 'view.db')
        shutil.copyfile(source, copy)
        view = TournamentDatabase(copy, self.database.max_attempts)
        return view, lambda: shutil.rmtree(folder, ignore_errors=True)

    def summary(self, name):
        view, cleanup = self.open(name)
        try:
            active = view.activeCombo()
            standings = view.standings(*active) if active else []
            best = standings[0] if standings else None
            return {
                'runs': len(view.runs()),
                'players': len(view.players()),
                'active': active,
                'leader': best['name'] if best and best['best'] is not None else None,
                'best': best['best'] if best else None,
            }
        finally:
            cleanup()

    def restore(self, name):
        '''
        Replaces the live database contents with the backup. The current state is backed up first,
        so a restore can be undone. Returns the name of that safety backup.
        '''
        with self.lock:
            with tempfile.TemporaryDirectory() as folder:
                # copy first: the safety backup may rotate the chosen file away
                chosen = os.path.join(folder, 'restore.db')
                shutil.copyfile(self.path(name), chosen)
                safety = self.create(BEFORE_RESTORE)
                self.database.restoreFrom(chosen)
            logger.warning('Restored database from backup %s (previous state saved as %s)', name, safety)
            return safety

    # --- triggers ---

    def newBest(self):
        try:
            self.create(NEW_BEST)
        except Exception:  #pylint: disable=broad-except
            logger.exception('New best time backup failed')

    def startSchedule(self):
        def run():
            while not self.stop_event.wait(self.interval):
                try:
                    self.create(SCHEDULED, skipIfUnchanged=True)
                except Exception:  #pylint: disable=broad-except
                    logger.exception('Scheduled backup failed')

        thread = threading.Thread(target=run, name='backups', daemon=True)
        thread.start()
        return thread

    def stop(self):
        self.stop_event.set()

def describeAge(created, now=None):
    seconds = int(((now or datetime.now()) - created).total_seconds())
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f'{seconds // 60} min ago'
    return f'{seconds // 3600} h {seconds % 3600 // 60} min ago'
