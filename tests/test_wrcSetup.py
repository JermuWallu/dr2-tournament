import json
import os
import tempfile
import unittest

from timerecorder import wrcSetup
from timerecorder.wrcTelemetry import STRUCTURE_ID, DEFINITION_FILE, PACKET_TYPES

class TestWrcSetup(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.telemetry = os.path.join(self.dir.name, 'telemetry')
        os.makedirs(self.telemetry)

    def tearDown(self):
        self.dir.cleanup()

    def configPath(self):
        return os.path.join(self.telemetry, 'config.json')

    def writeConfig(self, data):
        with open(self.configPath(), 'w', encoding='utf-8') as file:
            json.dump(data, file)

    def readConfig(self):
        with open(self.configPath(), encoding='utf-8') as file:
            return json.load(file)

    def testInstallWritesStructureAndEntries(self):
        _folder, entries = wrcSetup.install(self.telemetry)

        definitionPath = os.path.join(self.telemetry, 'udp', DEFINITION_FILE)
        self.assertTrue(os.path.isfile(definitionPath))
        with open(definitionPath, encoding='utf-8') as file:
            self.assertEqual(set(PACKET_TYPES), set(json.load(file)['packets']))

        self.assertEqual(len(PACKET_TYPES), len(entries))
        packets = self.readConfig()['udp']['packets']
        self.assertEqual(set(PACKET_TYPES), {entry['packet'] for entry in packets})
        self.assertEqual(len(PACKET_TYPES), len({entry['port'] for entry in packets}))
        self.assertTrue(all(entry['bEnabled'] for entry in packets))

    def testInstallKeepsOtherEntriesAndSettings(self):
        self.writeConfig({'udp': {'enabled': True, 'packets': [
            {'structure': 'wrc', 'packet': 'session_update', 'port': 20888}]}, 'mine': 'keep'})

        wrcSetup.install(self.telemetry)

        config = self.readConfig()
        self.assertEqual('keep', config['mine'])
        structures = [entry['structure'] for entry in config['udp']['packets']]
        self.assertEqual(1, structures.count('wrc'))
        self.assertEqual(len(PACKET_TYPES), structures.count(STRUCTURE_ID))

    def testInstallTwiceDoesNotDuplicate(self):
        wrcSetup.install(self.telemetry)
        wrcSetup.install(self.telemetry)
        packets = self.readConfig()['udp']['packets']
        self.assertEqual(len(PACKET_TYPES), len(packets))

    def testInstallBacksUpTheOriginalConfigOnce(self):
        self.writeConfig({'original': True})
        wrcSetup.install(self.telemetry)
        backup = self.configPath() + '.backup'
        self.assertTrue(os.path.isfile(backup))
        with open(backup, encoding='utf-8') as file:
            self.assertEqual({'original': True}, json.load(file))

        wrcSetup.install(self.telemetry)
        with open(backup, encoding='utf-8') as file:
            self.assertEqual({'original': True}, json.load(file))

    def testInstallHandlesTopLevelPacketList(self):
        self.writeConfig({'packets': [{'structure': 'custom1', 'packet': 'session_update'}]})
        wrcSetup.install(self.telemetry)
        packets = self.readConfig()['packets']
        self.assertEqual(1 + len(PACKET_TYPES), len(packets))

    def testRemoveTakesOurEntriesAndStructureAway(self):
        self.writeConfig({'udp': {'packets': [{'structure': 'wrc', 'packet': 'session_update'}]}})
        wrcSetup.install(self.telemetry)

        _folder, removed = wrcSetup.remove(self.telemetry)

        self.assertEqual(len(PACKET_TYPES), removed)
        self.assertEqual([{'structure': 'wrc', 'packet': 'session_update'}], self.readConfig()['udp']['packets'])
        self.assertFalse(os.path.isfile(os.path.join(self.telemetry, 'udp', DEFINITION_FILE)))

    def testDescribeInstallation(self):
        lines = '\n'.join(wrcSetup.describeInstallation(self.telemetry))
        self.assertIn('NOT installed', lines)

        wrcSetup.install(self.telemetry)
        lines = '\n'.join(wrcSetup.describeInstallation(self.telemetry))
        self.assertIn(f'{DEFINITION_FILE}: installed', lines)
        self.assertIn('session_start -> 127.0.0.1:', lines)

    def testUnknownFolderIsReported(self):
        with self.assertRaises(FileNotFoundError):
            wrcSetup.install(os.path.join(self.dir.name, 'nope'))
        self.assertEqual(1, wrcSetup.main([os.path.join(self.dir.name, 'nope')]))

    def testMainInstallsChecksAndRemoves(self):
        self.assertEqual(0, wrcSetup.main([self.telemetry]))
        self.assertEqual(0, wrcSetup.main(['--check', self.telemetry]))
        self.assertEqual(0, wrcSetup.main(['--remove', self.telemetry]))
        self.assertEqual([], self.readConfig()['udp']['packets'])

    def testCandidateFoldersLookInDocuments(self):
        candidates = wrcSetup.candidateTelemetryFolders()
        self.assertTrue(candidates)
        self.assertTrue(all(candidate.endswith(os.path.join('My Games', 'WRC', 'telemetry'))
                            for candidate in candidates))

if __name__ == '__main__':
    unittest.main()
