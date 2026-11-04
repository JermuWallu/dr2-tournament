import os
import tempfile
import unittest

from timerecorder.tournamentDatabase import TournamentDatabase, AttemptsExhausted, FINISHED, DNF, formatTime, nameKey

TRACK = 'Sweet Lamb'
CAR = 'Peugeot 205 GTI'

class TestTournamentDatabase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.thing = TournamentDatabase(os.path.join(self.dir.name, 't.db'), maxAttempts=2)

    def tearDown(self):
        self.dir.cleanup()

    def testEmptyNameShowsNothing(self):
        self.assertIsNone(self.thing.lookup('   ', TRACK, CAR))

    def testUnknownPlayer(self):
        info = self.thing.lookup('Jere', TRACK, CAR)
        self.assertFalse(info['found'])
        self.assertEqual(0, info['used'])
        self.assertEqual(2, info['remaining'])

    def testAttemptsAreNumberedAndNameIsCaseInsensitive(self):
        self.assertEqual(1, self.thing.recordResult('Jere', TRACK, CAR, 190.5, FINISHED))
        self.assertEqual(2, self.thing.recordResult('  jERE ', TRACK, CAR, None, DNF, 'restart'))

        info = self.thing.lookup('JERE', TRACK, CAR)
        self.assertTrue(info['found'])
        self.assertEqual('Jere', info['name'])
        self.assertEqual(0, info['remaining'])
        self.assertEqual([1, 2], [a['attempt'] for a in info['attempts']])

    def testThirdAttemptIsRejected(self):
        self.thing.recordResult('a', TRACK, CAR, 1.0, FINISHED)
        self.thing.recordResult('a', TRACK, CAR, 2.0, FINISHED)
        with self.assertRaises(AttemptsExhausted):
            self.thing.recordResult('A', TRACK, CAR, 3.0, FINISHED)

    def testAttemptsArePerTrackAndCar(self):
        self.thing.recordResult('a', TRACK, CAR, 1.0, FINISHED)
        self.thing.recordResult('a', TRACK, CAR, 2.0, FINISHED)
        self.assertEqual(2, self.thing.lookup('a', TRACK, 'Other car')['remaining'])

    def testStandingsSortByBestTimeThenName(self):
        self.thing.recordResult('Zed', TRACK, CAR, 100.0, FINISHED)
        self.thing.recordResult('bob', TRACK, CAR, 120.0, FINISHED)
        self.thing.recordResult('bob', TRACK, CAR, 100.0, FINISHED)
        self.thing.recordResult('Amy', TRACK, CAR, 105.0, FINISHED)
        self.thing.recordResult('Dnfer', TRACK, CAR, None, DNF)
        self.thing.recordResult('carl', TRACK, CAR, None, DNF)

        rows = self.thing.standings(TRACK, CAR)

        self.assertEqual(['bob', 'Zed', 'Amy', 'carl', 'Dnfer'], [r['name'] for r in rows])
        self.assertEqual([1, 1, 3, None, None], [r['position'] for r in rows])
        self.assertEqual([120.0, 100.0], rows[0]['attempts'])
        self.assertEqual([100.0, None], rows[1]['attempts'])
        self.assertEqual(['DNF', None], rows[3]['attempts'])
        self.assertEqual(5.0, rows[2]['gap'])

    def testCombosMostRecentFirst(self):
        self.thing.recordResult('a', 'T1', CAR, 1.0, FINISHED)
        self.thing.recordResult('a', 'T2', CAR, 1.0, FINISHED)
        self.assertEqual(['T2', 'T1'], [c['track'] for c in self.thing.combos()])

    def testFirstRunSetsActiveCombo(self):
        self.assertIsNone(self.thing.activeCombo())
        self.assertTrue(self.thing.isActiveCombo(TRACK, CAR))
        self.thing.recordResult('a', TRACK, CAR, None, DNF)
        self.thing.recordResult('a', 'Other', CAR, 1.0, FINISHED)
        self.assertEqual((TRACK, CAR), self.thing.activeCombo())
        self.assertFalse(self.thing.isActiveCombo('Other', CAR))

    def testSetAndClearActiveCombo(self):
        self.thing.setActiveCombo('Other', CAR)
        self.assertEqual(('Other', CAR), self.thing.activeCombo())
        self.thing.setActiveCombo(None, None)
        self.assertIsNone(self.thing.activeCombo())

    def testDeletingActiveComboClearsSetup(self):
        self.thing.recordResult('a', TRACK, CAR, 1.0, FINISHED)
        self.thing.recordResult('a', 'Other', CAR, 1.0, FINISHED)
        self.thing.deleteCombo('Other', CAR)
        self.assertEqual((TRACK, CAR), self.thing.activeCombo())
        self.thing.deleteCombo(TRACK, CAR)
        self.assertIsNone(self.thing.activeCombo())

    def testFormatTime(self):
        self.assertEqual('03:00.240', formatTime(180.24))
        self.assertEqual('00:59.999', formatTime(59.9994))
        self.assertEqual('DNF', formatTime(None))

    def testNameKey(self):
        self.assertEqual('jere w', nameKey('  Jere   W '))

if __name__ == '__main__':
    unittest.main()
