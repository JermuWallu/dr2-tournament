'''
The basic UDP logic, should rarely change and is difficult to test.

Uses a plain blocking socket with a short timeout instead of asyncore,
which was removed from the standard library in Python 3.12.
'''
import socket
import struct

from .statsProcessor import StatsProcessor
from .log import getLogger
from . import config

logger = getLogger(__name__)

SOCKET_TIMEOUT_SECONDS = 0.25

class Receiver():

    def __init__(self, approot, statsProcessor=None):
        self.address = config.GET.server
        self.field_count = 66
        self.stats_processor = statsProcessor if statsProcessor is not None else StatsProcessor(approot)
        self.received_data = False
        self.socket = None
        self.running = False

    def reconnect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(SOCKET_TIMEOUT_SECONDS)
        self.socket.bind(self.address)
        logger.info("Waiting for data on %s:%s", *self.address)

    def recv(self, size):
        return self.socket.recv(size)

    def close(self):
        self.running = False
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def handle_read(self):
        data = self.recv(self.field_count * 8)

        if not data:
            return

        if not self.received_data:
            self.received_data = True
            logger.debug("Receiving data on %s:%s", *self.address)

        self.parse(data)

    def parse(self, data):
        if len(data) < self.field_count * 4:
            logger.debug("Ignoring short packet of %s bytes", len(data))
            return

        stats = struct.unpack(str(self.field_count) + 'f', data[0:self.field_count * 4])

        self.stats_processor.handleStats(stats)

    def loop(self, tick=None):
        '''
        Receive until close() is called. The optional tick callback is invoked after every
        packet and at least every SOCKET_TIMEOUT_SECONDS, which allows detecting silence.
        '''
        self.running = True
        try:
            while self.running:
                try:
                    self.handle_read()
                except socket.timeout:
                    pass

                if tick is not None:
                    tick()
        finally:
            self.close()
