import os
import struct
import tempfile
import unittest
from unittest.mock import MagicMock

from timerecorder.tournamentDatabase import TournamentDatabase
from timerecorder.tournamentSession import TournamentSession, IDLE, PROMPTING, RUNNING
from timerecorder.wrcNames import WrcNames
from timerecorder.wrcReceiver import WrcReceiver
from timerecorder.wrcTelemetry import SESSION_START, SESSION_END, SESSION_PAUSE, SESSION_RESUME

TRACK, CAR = 'Estonia - Otepaa', 'Ford Puma'

class Clock():
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

class TestWrcTournamentFlow(unittest.TestCase):
    '''The WRC receiver driving the shared tournament logic end to end.'''

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 'wrc.db'))
        self.game = MagicMock()
        self.ui = MagicMock()
        self.clock = Clock()
        self.session = TournamentSession(self.db, self.game, self.ui, dnfTimeoutSeconds=15, clock=self.clock)
        names = WrcNames(routes={101: 'Otepaa'}, locations={5: 'Estonia'}, vehicles={103: 'Ford Puma'})
        self.receiver = WrcReceiver(self.session, names=names)

    def tearDown(self):
        self.dir.cleanup()

    def started(self, routeId=101, vehicleId=103):
        self.receiver.handle(struct.pack('<QBHHdHHH', 1, 0, 5, routeId, 7000.0, vehicleId, 0, 0), [SESSION_START])

    def ended(self, status=1, laptime=187.654):
        self.receiver.handle(struct.pack('<QBff', 2, status, laptime, 0.0), [SESSION_END])

    def testFullAttempt(self):
        self.started()
        self.assertEqual(PROMPTING, self.session.state)
        self.ui.showPrompt.assert_called_once_with(TRACK, CAR, None)
        self.game.pause.assert_called_once()

        self.assertIsNone(self.session.start('Jere'))
        self.assertEqual(RUNNING, self.session.state)
        self.game.resume.assert_called_once()

        self.ended()

        self.assertEqual(IDLE, self.session.state)
        attempts = self.db.lookup('jere', TRACK, CAR)['attempts']
        self.assertEqual([(1, 187.654, 'FINISHED')], [(a['attempt'], a['time'], a['status']) for a in attempts])
        self.assertEqual((TRACK, CAR), self.db.activeCombo())

    def testRetireIsADnfAndUsesAnAttempt(self):
        self.started()
        self.session.start('Jere')
        self.ended(status=3)

        attempts = self.db.lookup('Jere', TRACK, CAR)['attempts']
        self.assertEqual([(1, None, 'DNF')], [(a['attempt'], a['time'], a['status']) for a in attempts])
        self.assertIn('status 3', attempts[0]['note'])
        self.assertEqual(1, self.db.lookup('Jere', TRACK, CAR)['remaining'])

    def testThirdAttemptIsBlocked(self):
        for _ in range(2):
            self.started()
            self.session.start('Jere')
            self.ended()
        self.started()
        self.assertIn('completed all 2 attempts', self.session.start('jere'))
        self.assertEqual(PROMPTING, self.session.state)

    def testPauseAndResumeComeFromTheGame(self):
        self.started()
        self.assertFalse(self.session.isGamePaused())

        self.receiver.handle(struct.pack('<Qf', 4, 1.0), [SESSION_PAUSE])
        self.assertTrue(self.session.isGamePaused())
        self.clock.now += 2
        self.session.tick()
        self.ui.setGamePaused.assert_called_once_with(True)

        self.receiver.handle(struct.pack('<Qf', 5, 2.0), [SESSION_RESUME])
        self.assertFalse(self.session.isGamePaused())

    def testLeavingTheStageIsADnf(self):
        self.started()
        self.session.start('Jere')
        self.clock.now += 16
        self.session.tick()

        self.assertEqual(IDLE, self.session.state)
        self.assertEqual('DNF', self.db.lookup('Jere', TRACK, CAR)['attempts'][0]['status'])

    def testAnotherCarWarnsButIsStillRecorded(self):
        self.started()
        self.session.start('Jere')
        self.ended()

        self.started(vehicleId=104)
        self.ui.showPrompt.assert_called_with('Estonia - Otepaa', 'Car 104', (TRACK, CAR))
        self.session.start('Jere')
        self.ended(laptime=90.0)

        self.assertEqual(1, self.db.lookup('Jere', TRACK, 'Car 104')['used'])
        self.assertEqual((TRACK, CAR), self.db.activeCombo())
        self.assertEqual(['Jere'], [row['name'] for row in self.db.standings(TRACK, CAR)])

if __name__ == '__main__':
    unittest.main()
