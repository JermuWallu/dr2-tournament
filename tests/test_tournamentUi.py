import os
import tempfile
import unittest

from timerecorder.nicknamePrompt import describeLookup, setupWarning, OK, WARNING
from timerecorder.tournamentDatabase import TournamentDatabase, FINISHED, DNF
from timerecorder.leaderboard import createApp, formatGap

class TestTournamentUi(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 't.db'))

    def tearDown(self):
        self.dir.cleanup()

    def testNothingForEmptyName(self):
        self.assertEqual(('', 'info', False), describeLookup(self.db.lookup('', 'T', 'C')))

    def testNewPlayer(self):
        text, level, canStart = describeLookup(self.db.lookup('new', 'T', 'C'))
        self.assertIn('attempt 1 of 2', text)
        self.assertEqual(OK, level)
        self.assertTrue(canStart)

    def testReturningPlayer(self):
        self.db.recordResult('Jere', 'T', 'C', 75.5, FINISHED)
        text, level, canStart = describeLookup(self.db.lookup('jere', 'T', 'C'))
        self.assertIn('1 of 2 attempts used', text)
        self.assertIn('Attempt 1: 01:15.500', text)
        self.assertIn('Next: attempt 2 of 2', text)
        self.assertTrue(canStart)

    def testAllAttemptsUsed(self):
        self.db.recordResult('Jere', 'T', 'C', 75.5, FINISHED)
        self.db.recordResult('Jere', 'T', 'C', None, DNF)
        text, level, canStart = describeLookup(self.db.lookup('jere', 'T', 'C'))
        self.assertIn('completed all 2 attempts', text)
        self.assertIn('Attempt 2: DNF', text)
        self.assertEqual(WARNING, level)
        self.assertFalse(canStart)

    def testLeaderboardApi(self):
        self.db.recordResult('b', 'T', 'C', 80.0, FINISHED)
        self.db.recordResult('a', 'T', 'C', 75.5, FINISHED)
        self.db.recordResult('a', 'T', 'C', None, DNF)
        client = createApp(self.db).test_client()

        self.assertEqual(200, client.get('/').status_code)
        data = client.get('/api/standings').get_json()

        self.assertEqual('T', data['track'])
        self.assertEqual(['a', 'b'], [r['name'] for r in data['rows']])
        self.assertEqual('01:15.500', data['rows'][0]['best'])
        self.assertEqual(['time', 'dnf'], [c['kind'] for c in data['rows'][0]['attempts']])
        self.assertEqual('+4.500', data['rows'][1]['gap'])

    def testLeaderboardShowsOnlyTournamentSetup(self):
        self.db.recordResult('a', 'T', 'C', 75.5, FINISHED)
        self.db.recordResult('b', 'Other', 'C', 60.0, FINISHED)
        client = createApp(self.db).test_client()

        data = client.get('/api/standings?track=Other&car=C').get_json()

        self.assertEqual(('T', 'C'), (data['track'], data['car']))
        self.assertEqual(['a'], [r['name'] for r in data['rows']])
        self.assertNotIn('combos', data)
        self.assertNotIn('<select', client.get('/').get_data(as_text=True))

    def testSetupWarningText(self):
        self.assertIn('Tournament: T · C', setupWarning(('T', 'C')))

    def testGameNameIsShown(self):
        self.db.recordResult('a', 'T', 'C', 1.0, FINISHED)
        data = createApp(self.db, 'EA SPORTS WRC').test_client().get('/api/standings').get_json()
        self.assertEqual('EA SPORTS WRC', data['game'])
        self.assertEqual('DiRT Rally 2.0', createApp(self.db).test_client()
                         .get('/api/standings').get_json()['game'])

    def testLeaderboardEmpty(self):
        data = createApp(self.db).test_client().get('/api/standings').get_json()
        self.assertEqual([], data['rows'])

    def testFormatGap(self):
        self.assertEqual('', formatGap(0))
        self.assertEqual('+01:01.000', formatGap(61))

if __name__ == '__main__':
    unittest.main()
