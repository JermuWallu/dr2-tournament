import socket
import struct
import threading
import time
import unittest
from unittest.mock import MagicMock

from timerecorder.wrcNames import WrcNames
from timerecorder.wrcReceiver import WrcReceiver, DEFAULT_PORTS
from timerecorder.wrcTelemetry import (Definition, SESSION_START, SESSION_UPDATE, SESSION_END,
                                       SESSION_PAUSE, SESSION_RESUME)

def startPacket(routeId=101, locationId=5, vehicleId=103, length=7000.0):
    return struct.pack('<QBHHdHHH', 1, 0, locationId, routeId, length, vehicleId, 0, 0)

def endPacket(status=1, laptime=187.654, penalty=0.0):
    return struct.pack('<QBff', 2, status, laptime, penalty)

def updatePacket():
    return struct.pack('<Qffddf', 3, 1.0, 2.0, 10.0, 7000.0, 25.0)

def pausePacket():
    return struct.pack('<Qf', 4, 1.0)

class TestWrcReceiver(unittest.TestCase):

    def setUp(self):
        self.listener = MagicMock()
        names = WrcNames(routes={101: 'Otepaa'}, locations={5: 'Estonia'}, vehicles={103: 'Ford Puma'})
        self.thing = WrcReceiver(self.listener, names=names)

    def testSessionStartResolvesNames(self):
        self.thing.handle(startPacket(), [SESSION_START])
        self.listener.stageStarted.assert_called_once_with('Estonia - Otepaa', 'Ford Puma')
        self.listener.packetReceived.assert_called_once_with()

    def testSessionEndFinished(self):
        self.thing.handle(endPacket(laptime=187.654, penalty=10.0), [SESSION_END])
        self.assertAlmostEqual(197.654, self.listener.stageFinished.call_args[0][0], places=3)
        self.listener.stageAborted.assert_not_called()

    def testSessionEndWithAnotherStatusIsADnf(self):
        self.thing.handle(endPacket(status=3), [SESSION_END])
        self.listener.stageFinished.assert_not_called()
        self.assertIn('status 3', self.listener.stageAborted.call_args[0][0])

    def testFinishedStatusesAreConfigurable(self):
        self.thing.finished_statuses = (3,)
        self.thing.handle(endPacket(status=3, laptime=100.0), [SESSION_END])
        self.listener.stageFinished.assert_called_once()

    def testFinishedWithoutATimeIsADnf(self):
        self.thing.handle(endPacket(status=1, laptime=0.0), [SESSION_END])
        self.listener.stageAborted.assert_called_once()

    def testPauseAndResume(self):
        self.thing.handle(pausePacket(), [SESSION_PAUSE])
        self.thing.handle(pausePacket(), [SESSION_RESUME])
        self.assertEqual([True, False], [call[0][0] for call in self.listener.gamePaused.call_args_list])

    def testUpdateOnlyCountsAsLiveness(self):
        self.thing.handle(updatePacket(), [SESSION_UPDATE])
        self.listener.packetReceived.assert_called_once_with()
        self.listener.stageStarted.assert_not_called()

    def testShortPacketIsIgnored(self):
        self.thing.handle(b'\x01\x02', [SESSION_START])
        self.listener.stageStarted.assert_not_called()

    def testSharedPortTellsTypesApartBySize(self):
        self.thing.handle(startPacket(), [SESSION_START, SESSION_END])
        self.thing.handle(endPacket(), [SESSION_START, SESSION_END])
        self.listener.stageStarted.assert_called_once()
        self.listener.stageFinished.assert_called_once()

    def testSharedPortWithEqualSizesIsRefused(self):
        self.thing.handle(pausePacket(), [SESSION_PAUSE, SESSION_RESUME])
        self.listener.gamePaused.assert_not_called()

    def testListenerErrorsDoNotStopTheReceiver(self):
        self.listener.stageStarted.side_effect = RuntimeError('boom')
        self.thing.handle(startPacket(), [SESSION_START])  # must not raise

    def testDecodingFollowsTheGivenDefinition(self):
        definition = Definition({'header': {'channels': []},
                                 'packets': {SESSION_END: {'channels': [
                                     {'id': 'stage_result_status', 'type': 'uint8'},
                                     {'id': 'stage_result_time', 'type': 'float64'}]}}})
        thing = WrcReceiver(self.listener, definition=definition)
        thing.handle(struct.pack('<Bd', 1, 99.5), [SESSION_END])
        self.assertAlmostEqual(99.5, self.listener.stageFinished.call_args[0][0])

class TestWrcReceiverSockets(unittest.TestCase):

    def setUp(self):
        self.listener = MagicMock()
        ports = {name: port + 1000 for name, port in DEFAULT_PORTS.items()}
        self.ports = ports
        self.thing = WrcReceiver(self.listener, ports=ports)

    def tearDown(self):
        self.thing.close()

    def testReceivesOverRealSockets(self):
        self.thing.reconnect()
        thread = threading.Thread(target=self.thing.loop, daemon=True)
        thread.start()

        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.sendto(startPacket(), ('127.0.0.1', self.ports[SESSION_START]))
        out.sendto(endPacket(), ('127.0.0.1', self.ports[SESSION_END]))

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self.listener.stageFinished.called:
            time.sleep(0.02)
        self.thing.close()
        thread.join(timeout=5)
        out.close()

        self.listener.stageStarted.assert_called_once_with('Route 101', 'Car 103')
        self.listener.stageFinished.assert_called_once()

    def testPortAlreadyInUseIsReported(self):
        taken = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        taken.bind(('127.0.0.1', self.ports[SESSION_START]))
        try:
            with self.assertRaises(OSError):
                self.thing.reconnect()
            self.assertEqual([], self.thing.sockets)
        finally:
            taken.close()

if __name__ == '__main__':
    unittest.main()
