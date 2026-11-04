import os
import re
import socket
import tempfile
import unittest

from timerecorder.adminPortal import createApp, findFreePort
from timerecorder.tournamentDatabase import TournamentDatabase, FINISHED, DNF

T, C = 'Sweet Lamb', 'Peugeot 205 GTI'

class TestAdminPortal(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 't.db'))
        self.client = createApp(self.db, 'jermu').test_client()

    def tearDown(self):
        self.dir.cleanup()

    def login(self):
        self.client.post('/login', data={'passcode': 'jermu'})
        page = self.client.get('/').get_data(as_text=True)
        return re.search(r'name="csrf" value="([0-9a-f]+)"', page).group(1)

    def post(self, url, **data):
        data.setdefault('track', T)
        data.setdefault('car', C)
        return self.client.post(url, data=dict(data, csrf=self.csrf), follow_redirects=True)

    def testRequiresPasscode(self):
        self.assertIn('/login', self.client.get('/').headers['Location'])
        page = self.client.post('/login', data={'passcode': 'wrong'}).get_data(as_text=True)
        self.assertIn('Wrong passcode', page)
        self.assertEqual(302, self.client.get('/').status_code)

    def testPostWithoutCsrfIsRejected(self):
        self.login()
        self.assertEqual(400, self.client.post('/combo/delete', data={'track': T, 'car': C}).status_code)

    def testDeleteRunRenumbersAttempts(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.db.recordResult('Jere', T, C, 90.0, FINISHED)
        self.csrf = self.login()
        first = self.db.runs(T, C)[0]['id']

        self.post(f'/runs/{first}/delete')

        runs = self.db.runs(T, C)
        self.assertEqual([(1, 90.0)], [(r['attempt'], r['time']) for r in runs])
        self.assertEqual(1, self.db.lookup('jere', T, C)['remaining'])
        self.assertEqual(2, self.db.recordResult('Jere', T, C, 80.0, FINISHED))

    def testUpdateRun(self):
        self.db.recordResult('Jere', T, C, None, DNF)
        self.csrf = self.login()
        runId = self.db.runs(T, C)[0]['id']

        page = self.post(f'/runs/{runId}/update', status=FINISHED, time='3:07,654', note='fixed').get_data(as_text=True)

        self.assertIn('Run saved', page)
        run = self.db.runs(T, C)[0]
        self.assertEqual((187.654, FINISHED, 'fixed'), (run['time'], run['status'], run['note']))

    def testUpdateRunWithBadTime(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        runId = self.db.runs(T, C)[0]['id']
        page = self.post(f'/runs/{runId}/update', status=FINISHED, time='abc').get_data(as_text=True)
        self.assertIn('Cannot read the time', page)
        self.assertEqual(100.0, self.db.runs(T, C)[0]['time'])

    def testAddRunRespectsMaxAttempts(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        self.post('/runs/add', name='jere', status=DNF, time='')
        page = self.post('/runs/add', name='Jere', status=FINISHED, time='1:00').get_data(as_text=True)
        self.assertIn('used all 2 attempts', page)
        self.assertEqual(2, len(self.db.runs(T, C)))

    def testRenameAndDeletePlayer(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.db.recordResult('Ville', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        jere, ville = [p['id'] for p in self.db.players()]

        page = self.post(f'/players/{jere}/rename', name='VILLE').get_data(as_text=True)
        self.assertIn('already taken', page)
        self.post(f'/players/{jere}/rename', name='Jermu')
        self.post(f'/players/{ville}/delete')

        self.assertEqual(['Jermu'], [p['name'] for p in self.db.players()])
        self.assertEqual(['Jermu'], [r['name'] for r in self.db.runs()])

    def testDeleteCombo(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.db.recordResult('Jere', 'Other', C, 100.0, FINISHED)
        self.csrf = self.login()
        self.post('/combo/delete')
        self.assertEqual(['Other'], [c['track'] for c in self.db.combos()])

    def testChangeTournamentSetup(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.db.recordResult('Jere', 'Other', 'Car 2', 90.0, FINISHED)
        self.csrf = self.login()
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('LIVE', page)
        self.assertIn('Other · Car 2', page)

        page = self.post('/setup', combo='["Other", "Car 2"]').get_data(as_text=True)

        self.assertIn('Tournament setup is now Other · Car 2', page)
        self.assertEqual(('Other', 'Car 2'), self.db.activeCombo())

    def testSetupMustBeADrivenCombo(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        page = self.post('/setup', combo='["Nope", "Car"]').get_data(as_text=True)
        self.assertIn('has no runs', page)
        self.assertEqual((T, C), self.db.activeCombo())

    def testClearSetup(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        self.post('/setup', combo='clear')
        self.assertIsNone(self.db.activeCombo())

    def testLeaderboardDropdownShowsOtherCombo(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.db.recordResult('Ville', 'Other', C, 90.0, FINISHED)
        self.csrf = self.login()
        page = self.client.get('/', query_string={'track': 'Other', 'car': C}).get_data(as_text=True)
        self.assertIn('Runs on Other · ' + C, page)
        self.assertIn('not on the public leaderboard', page)

    def testPageEscapesNicknames(self):
        self.db.recordResult('<b>"x\'', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        page = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('<b>"x', page)

    def testBackupDownload(self):
        self.db.recordResult('Jere', T, C, 100.0, FINISHED)
        self.csrf = self.login()
        response = self.client.get('/backup')
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.data.startswith(b'SQLite format 3'))

    def testFindFreePortSkipsTakenPort(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
            taken.bind(('127.0.0.1', 0))
            port = taken.getsockname()[1]
            self.assertNotEqual(port, findFreePort('127.0.0.1', port))

if __name__ == '__main__':
    unittest.main()
