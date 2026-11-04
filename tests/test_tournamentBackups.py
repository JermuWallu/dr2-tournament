import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from timerecorder.adminPortal import createApp
from timerecorder.tournamentBackups import BackupManager, SCHEDULED, NEW_BEST, BEFORE_RESTORE
from timerecorder.tournamentDatabase import TournamentDatabase, FINISHED, DNF
from timerecorder.tournamentSession import TournamentSession

T, C = 'Sweet Lamb', 'Golf'

class TestTournamentBackups(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 'tournament.db'))
        self.folder = os.path.join(self.dir.name, 'backups')
        self.thing = BackupManager(self.db, self.folder, keep=3)

    def tearDown(self):
        self.dir.cleanup()

    def create(self, reason, **kwargs):
        name = self.thing.create(reason, **kwargs)
        time.sleep(0.002)  # distinct millisecond names
        return name

    def testKeepsOnlyNewestThree(self):
        names = []
        for i in range(5):
            self.db.recordResult(f'p{i}', T, C, 100.0 + i, FINISHED)
            names.append(self.create(SCHEDULED))
        listed = [b['name'] for b in self.thing.list()]
        self.assertEqual(list(reversed(names[2:])), listed)
        self.assertEqual(3, len(os.listdir(self.folder)))

    def testScheduledBackupSkippedWhenUnchanged(self):
        self.db.recordResult('a', T, C, 100.0, FINISHED)
        self.assertIsNotNone(self.create(SCHEDULED, skipIfUnchanged=True))
        self.assertIsNone(self.create(SCHEDULED, skipIfUnchanged=True))
        self.db.recordResult('b', T, C, 100.0, FINISHED)
        self.assertIsNotNone(self.create(SCHEDULED, skipIfUnchanged=True))

    def testSummaryAndViewDoNotChangeBackup(self):
        self.db.recordResult('Jere', T, C, 90.0, FINISHED)
        self.db.recordResult('Ville', T, C, None, DNF)
        name = self.create(NEW_BEST)
        before = open(self.thing.path(name), 'rb').read()

        info = self.thing.summary(name)

        self.assertEqual((2, 2, 'Jere', 90.0), (info['runs'], info['players'], info['leader'], info['best']))
        self.assertEqual(before, open(self.thing.path(name), 'rb').read())

    def testRestoreReplacesDataAndSavesCurrentState(self):
        self.db.recordResult('Jere', T, C, 90.0, FINISHED)
        name = self.create(SCHEDULED)
        self.db.recordResult('Ville', T, C, 80.0, FINISHED)
        time.sleep(0.002)

        safety = self.thing.restore(name)

        self.assertEqual(['Jere'], [r['name'] for r in self.db.runs()])
        self.assertIn(BEFORE_RESTORE, safety)
        self.assertEqual(2, self.thing.summary(safety)['runs'])
        # the live database still works
        self.db.recordResult('Ville', T, C, 85.0, FINISHED)
        self.assertEqual(2, len(self.db.runs()))

    def testRestoreOldestWhenFull(self):
        self.db.recordResult('a', T, C, 1.0, FINISHED)
        oldest = self.create(SCHEDULED)
        for name in 'bc':
            self.db.recordResult(name, T, C, 1.0, FINISHED)
            self.create(SCHEDULED)
        self.thing.restore(oldest)  # the safety backup rotates the chosen file out
        self.assertEqual(['a'], [r['name'] for r in self.db.runs()])

    def testPathRejectsOtherFiles(self):
        for name in ('../tournament.db', 'tournament.db', ''):
            with self.assertRaises(FileNotFoundError):
                self.thing.path(name)

    def testSessionBacksUpOnNewBestOnly(self):
        session = TournamentSession(self.db, MagicMock(), MagicMock())
        session.on_new_best = MagicMock()
        for name, laptime, track, car in (('a', 100.0, T, C), ('b', 105.0, T, C), ('c', 99.0, T, C), ('d', 50.0, 'X', 'Y')):
            session.stageStarted(track, car)
            session.start(name)
            session.stageFinished(laptime)
        self.assertEqual(2, session.on_new_best.call_count)  # a (first), c (faster); not b, not other setup

class TestBackupAdmin(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 'tournament.db'))
        self.backups = BackupManager(self.db, os.path.join(self.dir.name, 'backups'))
        self.client = createApp(self.db, 'jermu', self.backups).test_client()
        self.client.post('/login', data={'passcode': 'jermu'})
        with self.client.session_transaction() as session:
            self.csrf = session['csrf']

    def tearDown(self):
        self.dir.cleanup()

    def testCreateListViewRestore(self):
        self.db.recordResult('Jere', T, C, 90.0, FINISHED)
        page = self.client.post('/backups/create', data={'csrf': self.csrf}, follow_redirects=True).get_data(as_text=True)
        self.assertIn('created', page)
        name = self.backups.list()[0]['name']
        self.assertIn('Made by admin', page)

        view = self.client.get(f'/backups/{name}').get_data(as_text=True)
        self.assertIn('Read-only view', view)
        self.assertIn('Jere', view)

        self.db.recordResult('Ville', T, C, 80.0, FINISHED)
        page = self.client.post(f'/backups/{name}/restore', data={'csrf': self.csrf}, follow_redirects=True).get_data(as_text=True)
        self.assertIn('Restored', page)
        self.assertEqual(['Jere'], [r['name'] for r in self.db.runs()])

        download = self.client.get(f'/backups/{name}/download')
        self.assertTrue(download.data.startswith(b'SQLite format 3'))
        download.close()

    def testUnknownBackup(self):
        self.assertEqual(404, self.client.get('/backups/nope.db').status_code)
        self.assertEqual(404, self.client.post('/backups/..%2Ftournament.db/restore', data={'csrf': self.csrf}).status_code)

    def testRestoreNeedsCsrf(self):
        self.db.recordResult('Jere', T, C, 90.0, FINISHED)
        name = self.backups.create()
        self.assertEqual(400, self.client.post(f'/backups/{name}/restore').status_code)

if __name__ == '__main__':
    unittest.main()
