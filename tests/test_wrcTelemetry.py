import json
import os
import struct
import tempfile
import unittest

from timerecorder.wrcNames import WrcNames
from timerecorder.wrcTelemetry import (Definition, PacketFormat, defaultDefinition, isFinished,
                                       SESSION_START, SESSION_END, SESSION_UPDATE, PACKET_TYPES)

class TestWrcTelemetry(unittest.TestCase):

    def testDefaultDefinitionCoversEveryPacketType(self):
        definition = Definition.default()
        self.assertEqual(set(PACKET_TYPES), set(definition.sizes()))

    def testHeaderIsPartOfEveryPacket(self):
        definition = Definition.default()
        for name in PACKET_TYPES:
            self.assertEqual('packet_uid', definition.format(name).channels[0])

    def testSizesMatchTheChannelTypes(self):
        definition = Definition.default()
        # uint64 + uint8 + uint16 + uint16 + float64 + uint16 + uint16 + uint16
        self.assertEqual(8 + 1 + 2 + 2 + 8 + 2 + 2 + 2, definition.format(SESSION_START).size)
        self.assertEqual(8 + 1 + 4 + 4, definition.format(SESSION_END).size)

    def testDecodeReturnsChannelsByName(self):
        packetFormat = PacketFormat('x', [{'id': 'a', 'type': 'uint16'}, {'id': 'b', 'type': 'float32'}])
        values = packetFormat.decode(struct.pack('<Hf', 7, 1.5))
        self.assertEqual({'a': 7, 'b': 1.5}, values)

    def testDecodeIgnoresExtraBytesButNotMissingOnes(self):
        packetFormat = PacketFormat('x', [{'id': 'a', 'type': 'uint16'}])
        self.assertEqual({'a': 7}, packetFormat.decode(struct.pack('<Hf', 7, 1.5)))
        with self.assertRaises(ValueError):
            packetFormat.decode(b'\x01')

    def testUnknownChannelTypeIsRejected(self):
        with self.assertRaises(ValueError):
            PacketFormat('x', [{'id': 'a', 'type': 'float128'}])

    def testRoundTripThroughTheInstalledFile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'tournament.json')
            with open(path, 'w', encoding='utf-8') as file:
                json.dump(defaultDefinition(), file)
            self.assertEqual(Definition.default().sizes(), Definition.load(path).sizes())

    def testLoadOrDefaultFallsBackOnRubbish(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'broken.json')
            with open(path, 'w', encoding='utf-8') as file:
                file.write('not json')
            self.assertEqual(Definition.default().sizes(), Definition.loadOrDefault(path).sizes())
            self.assertEqual(Definition.default().sizes(),
                             Definition.loadOrDefault(os.path.join(folder, 'missing.json')).sizes())

    def testInstalledDefinitionWinsOverTheBuiltIn(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'tournament.json')
            with open(path, 'w', encoding='utf-8') as file:
                json.dump({'header': {'channels': []},
                           'packets': {SESSION_UPDATE: {'channels': [{'id': 'only', 'type': 'uint8'}]}}}, file)
            definition = Definition.loadOrDefault(path)
            self.assertEqual({SESSION_UPDATE: 1}, definition.sizes())

    def testFinishedStatuses(self):
        self.assertTrue(isFinished(1))
        self.assertFalse(isFinished(0))
        self.assertTrue(isFinished(4, (1, 4)))

class TestWrcNames(unittest.TestCase):

    def testFallsBackToIds(self):
        names = WrcNames()
        self.assertEqual('Route 12345', names.track(12345))
        self.assertEqual('Car 103', names.car(103))

    def testCombinesLocationAndRoute(self):
        names = WrcNames(routes={101: 'Otepaa'}, locations={5: 'Estonia'}, vehicles={103: 'Ford Puma'})
        self.assertEqual('Estonia - Otepaa', names.track(101, 5))
        self.assertEqual('Ford Puma', names.car(103))

    def testDoesNotRepeatTheLocationInTheRouteName(self):
        names = WrcNames(routes={101: 'Estonia Otepaa'}, locations={5: 'Estonia'})
        self.assertEqual('Estonia Otepaa', names.track(101, 5))

    def testKnownLocationUnknownRoute(self):
        names = WrcNames(locations={5: 'Estonia'})
        self.assertEqual('Estonia - Route 101', names.track(101, 5))

    def testLoadsStringKeysFromFile(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, 'resources'))
            with open(os.path.join(folder, 'resources', 'wrc-names.json'), 'w', encoding='utf-8') as file:
                json.dump({'routes': {'101': 'Otepaa'}, 'vehicles': {'103': 'Puma'}}, file)
            names = WrcNames.load(folder)
            self.assertEqual('Otepaa', names.track(101))
            self.assertEqual('Puma', names.car(103))

    def testMissingFileIsFine(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual('Route 1', WrcNames.load(folder).track(1))

if __name__ == '__main__':
    unittest.main()
