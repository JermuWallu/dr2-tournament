import os
import tempfile
import unittest
from unittest.mock import MagicMock

from timerecorder.tournamentDatabase import TournamentDatabase
from timerecorder.tournamentSession import TournamentSession, IDLE, PROMPTING, RUNNING, describe

class Clock():
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

def packet(clock, moving=True):
    stats = [0.0] * 66
    stats[0] = clock.now
    stats[2] = clock.now if moving else 5.0
    return stats

class TestTournamentSession(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = TournamentDatabase(os.path.join(self.dir.name, 't.db'))
        self.game = MagicMock()
        self.ui = MagicMock()
        self.clock = Clock()
        self.thing = TournamentSession(self.db, self.game, self.ui, dnfTimeoutSeconds=15, clock=self.clock)
        self.thing.setNameLookup(lambda t: {309: 'Sweet Lamb'}[t], lambda c: {200: 'Golf', 201: '205'}[c])

    def tearDown(self):
        self.dir.cleanup()

    def load(self):
        self.thing.packetReceived(packet(self.clock))
        self.thing.stageStarted(309, 200)

    def testStageStartPausesAndPrompts(self):
        self.load()
        self.assertEqual(PROMPTING, self.thing.state)
        self.game.pause.assert_called_once()
        self.ui.showPrompt.assert_called_once_with('Sweet Lamb', 'Golf')

    def testAmbiguousCarNames(self):
        self.thing.stageStarted(309, [200, 201])
        self.ui.showPrompt.assert_called_once_with('Sweet Lamb', 'Golf / 205')

    def testStartResumesAndFinishRecordsTime(self):
        self.load()
        self.assertIsNone(self.thing.start('Jere'))
        self.game.resume.assert_called_once()
        self.assertEqual(RUNNING, self.thing.state)

        self.thing.stageFinished(187.123)

        self.assertEqual(IDLE, self.thing.state)
        attempts = self.db.lookup('jere', 'Sweet Lamb', 'Golf')['attempts']
        self.assertEqual([(1, 187.123, 'FINISHED')], [(a['attempt'], a['time'], a['status']) for a in attempts])

    def testRestartIsDnfAndPromptsAgain(self):
        self.load()
        self.thing.start('Jere')
        self.thing.stageAborted()
        self.assertEqual(IDLE, self.thing.state)
        self.thing.stageStarted(309, 200)

        self.assertEqual(PROMPTING, self.thing.state)
        info = self.db.lookup('Jere', 'Sweet Lamb', 'Golf')
        self.assertEqual('DNF', info['attempts'][0]['status'])
        self.assertEqual(2, self.ui.showPrompt.call_count)

    def testSilenceIsDnf(self):
        self.load()
        self.thing.start('Jere')
        self.clock.now += 10
        self.thing.packetReceived(packet(self.clock))
        self.clock.now += 14
        self.thing.tick()
        self.assertEqual(RUNNING, self.thing.state)

        self.clock.now += 2
        self.thing.tick()

        self.assertEqual(IDLE, self.thing.state)
        self.assertEqual('DNF', self.db.lookup('Jere', 'Sweet Lamb', 'Golf')['attempts'][0]['status'])

    def testNewStageWhileRunningIsDnf(self):
        self.load()
        self.thing.start('Jere')
        self.thing.stageStarted(309, 200)
        self.assertEqual(PROMPTING, self.thing.state)
        self.assertEqual(1, self.db.lookup('Jere', 'Sweet Lamb', 'Golf')['used'])

    def testPlayerWithoutAttemptsCannotStart(self):
        self.db.recordResult('Jere', 'Sweet Lamb', 'Golf', 1.0, 'FINISHED')
        self.db.recordResult('Jere', 'Sweet Lamb', 'Golf', 2.0, 'FINISHED')
        self.load()

        self.assertIn('completed all 2 attempts', self.thing.start('jere'))
        self.assertEqual(PROMPTING, self.thing.state)
        self.game.resume.assert_not_called()

    def testFinishWithoutNicknameIsNotRecorded(self):
        self.load()
        self.thing.stageFinished(100.0)
        self.assertEqual(IDLE, self.thing.state)
        self.assertEqual([], self.db.combos())
        self.ui.hidePrompt.assert_called_once()

    def testRestartWhilePromptingKeepsPrompt(self):
        self.load()
        self.thing.stageAborted()
        self.assertEqual(PROMPTING, self.thing.state)

    def testPauseCheckReportsFrozenPackets(self):
        self.load()
        frozen = packet(self.clock, moving=False)
        for _ in range(12):
            self.clock.now += 0.01
            stats = list(frozen)
            stats[0] = self.clock.now
            self.thing.packetReceived(stats)
        self.clock.now += 2
        self.thing.tick()
        self.ui.setGamePaused.assert_called_once_with(True)

    def testAutoPauseOff(self):
        self.thing.auto_pause = False
        self.load()
        self.thing.start('x')
        self.game.pause.assert_not_called()
        self.game.resume.assert_not_called()

    def testDescribeUnknown(self):
        self.assertEqual('Unknown car', describe([], str, 'Unknown car'))

if __name__ == '__main__':
    unittest.main()
