'''
Listens for EA SPORTS WRC telemetry and turns it into the same stage events the DiRT Rally
side produces, so the tournament logic, leaderboard, admin portal and backups are shared.

WRC sends each packet type to its own address and port, so one socket is opened per port.
Where several packet types share a port, they are told apart by payload size.

Events sent to the listener:
    stageStarted(track, car)   session_start: a stage is loaded, prompt for a nickname
    stageFinished(laptime)     session_end with a finished status
    stageAborted(reason)       session_end with any other status (retired, restarted)
    packetReceived()           any packet, so silence can be detected
    gamePaused(paused)         session_pause / session_resume
'''
import selectors
import socket

from .log import getLogger
from .wrcNames import WrcNames
from .wrcTelemetry import (Definition, SESSION_START, SESSION_UPDATE, SESSION_END,
                           SESSION_PAUSE, SESSION_RESUME, DEFAULT_FINISHED_STATUSES, isFinished)

logger = getLogger(__name__)

SELECT_TIMEOUT_SECONDS = 0.25
BUFFER_SIZE = 2048

DEFAULT_PORTS = {
    SESSION_UPDATE: 20777,
    SESSION_START: 20778,
    SESSION_END: 20779,
    SESSION_PAUSE: 20780,
    SESSION_RESUME: 20781,
}

class WrcReceiver():  #pylint: disable=too-many-instance-attributes

    def __init__(self, listener=None, host='127.0.0.1', ports=None, definition=None,  #pylint: disable=too-many-arguments
                 names=None, finishedStatuses=DEFAULT_FINISHED_STATUSES):
        self.listener = listener
        self.host = host
        self.ports = dict(ports or DEFAULT_PORTS)
        self.definition = definition if definition is not None else Definition.default()
        self.names = names if names is not None else WrcNames()
        self.finished_statuses = tuple(finishedStatuses)

        self.selector = None
        self.sockets = []
        self.running = False
        self.received_data = False

    # --- socket handling ---

    def _packetTypesByPort(self):
        byPort = {}
        for packetType, port in self.ports.items():
            byPort.setdefault(int(port), []).append(packetType)
        return byPort

    def reconnect(self):
        self.close()
        self.selector = selectors.DefaultSelector()
        for port, packetTypes in sorted(self._packetTypesByPort().items()):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                sock.bind((self.host, port))
            except OSError:
                sock.close()
                self.close()
                raise
            self.sockets.append(sock)
            self.selector.register(sock, selectors.EVENT_READ, packetTypes)
            logger.info('Waiting for %s on %s:%s', ' / '.join(sorted(packetTypes)), self.host, port)

    def close(self):
        self.running = False
        for sock in self.sockets:
            sock.close()
        self.sockets = []
        if self.selector is not None:
            self.selector.close()
            self.selector = None

    def loop(self, tick=None):
        '''Receives until close() is called, calling tick at least every SELECT_TIMEOUT_SECONDS.'''
        self.running = True
        try:
            while self.running:
                for key, _mask in self.selector.select(SELECT_TIMEOUT_SECONDS):
                    self._readFrom(key.fileobj, key.data)
                if tick is not None:
                    tick()
        finally:
            self.close()

    def _readFrom(self, sock, packetTypes):
        while True:
            try:
                data, _address = sock.recvfrom(BUFFER_SIZE)
            except BlockingIOError:
                return
            except OSError:
                return
            if data:
                self.handle(data, packetTypes)

    # --- decoding ---

    def _identify(self, data, packetTypes):
        '''Which of the packet types on this port the payload is, by size.'''
        if len(packetTypes) == 1:
            return packetTypes[0]

        matches = [name for name in packetTypes
                   if self.definition.format(name) and self.definition.format(name).size == len(data)]
        if len(matches) == 1:
            return matches[0]

        logger.warning('Cannot tell %s apart on a shared port from %s bytes, give them separate ports',
                       ' / '.join(sorted(packetTypes)), len(data))
        return None

    def handle(self, data, packetTypes):
        packetType = self._identify(data, packetTypes)
        if packetType is None:
            return

        packetFormat = self.definition.format(packetType)
        if packetFormat is None:
            logger.warning('No structure for %s', packetType)
            return

        try:
            values = packetFormat.decode(data)
        except ValueError as exc:
            logger.warning('Could not read %s: %s. Re-run the WRC setup so the game and this '
                           'tool use the same structure.', packetType, exc)
            return

        if not self.received_data:
            self.received_data = True
            logger.info('Receiving WRC telemetry')

        self._notify('packetReceived')
        self.dispatch(packetType, values)

    def dispatch(self, packetType, values):
        if packetType == SESSION_START:
            self._started(values)
        elif packetType == SESSION_END:
            self._ended(values)
        elif packetType == SESSION_PAUSE:
            self._notify('gamePaused', True)
        elif packetType == SESSION_RESUME:
            self._notify('gamePaused', False)

    def _started(self, values):
        track = self.names.track(values.get('route_id'), values.get('location_id'))
        car = self.names.car(values.get('vehicle_id'))
        logger.debug('session_start %s', values)
        self._notify('stageStarted', track, car)

    def _ended(self, values):
        status = values.get('stage_result_status')
        laptime = values.get('stage_result_time')
        penalty = values.get('stage_result_time_penalty') or 0.0
        logger.debug('session_end %s', values)

        if status is not None and not isFinished(status, self.finished_statuses):
            logger.info('Stage ended with status %s, recording a DNF', status)
            self._notify('stageAborted', f'did not finish (status {int(status)})')
            return

        if not laptime or laptime <= 0:
            logger.warning('Stage ended with status %s but no time, recording a DNF', status)
            self._notify('stageAborted', f'no time reported (status {status})')
            return

        self._notify('stageFinished', laptime + penalty)

    def _notify(self, event, *args):
        if self.listener is None:
            return
        callback = getattr(self.listener, event, None)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:  #pylint: disable=broad-except
            logger.exception('Listener failed to handle %s', event)
