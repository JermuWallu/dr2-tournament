'''
Tournament state machine sitting on top of StatsProcessor events.

  IDLE ──stageStarted──▶ PROMPTING ──start(nickname)──▶ RUNNING
   ▲                        │                              │
   │◀── silence / finish ───┘                              │
   │◀── finish: record time ───────────────────────────────┤
   │◀── restart / silence / new stage: record DNF ─────────┘

Packet, stage and tick events arrive on the UDP thread; lookup() and start() are called
from the UI thread. A re-entrant lock serialises both.
'''
import threading
import time

from .databaseAccess import identify, AMBIGUOUS
from .log import getLogger
from .tournamentDatabase import FINISHED, DNF, AttemptsExhausted, formatTime

logger = getLogger(__name__)

IDLE = 'IDLE'
PROMPTING = 'PROMPTING'
RUNNING = 'RUNNING'

# DR2 keeps sending packets while paused, with every field frozen except the run time (field 0)
FROZEN_PACKETS_FOR_PAUSE = 10
PAUSE_CHECK_DELAY_SECONDS = 1.5

def describe(element, lookupName, unknown):
    '''Name for an identified id, joined names for ambiguous candidates.'''
    if identify(element) != AMBIGUOUS:
        return lookupName(element)
    if not element:
        return unknown
    return ' / '.join(lookupName(candidate) for candidate in element)

class NullUi():
    def showPrompt(self, track, car, tournamentSetup=None):
        pass

    def hidePrompt(self):
        pass

    def setGamePaused(self, paused):
        pass

    def showResult(self, text):
        pass

class TournamentSession():  #pylint: disable=too-many-instance-attributes

    def __init__(self, database, gameController, ui=None, dnfTimeoutSeconds=15.0, autoPause=True, clock=time.monotonic):  #pylint: disable=too-many-arguments
        self.database = database
        self.game = gameController
        self.ui = ui if ui is not None else NullUi()
        self.dnf_timeout = dnfTimeoutSeconds
        self.auto_pause = autoPause
        self.clock = clock

        self.lock = threading.RLock()
        self.state = IDLE
        self.track = None
        self.car = None
        self.player = None
        self.name_lookup = None

        self.last_packet_at = None
        self.previous_stats = None
        self.frozen_count = 0
        self.pause_check_at = None

    def setNameLookup(self, trackName, carName):
        '''Functions resolving track and car ids to names (from the base database).'''
        self.name_lookup = (trackName, carName)

    # --- events from StatsProcessor (UDP thread) ---

    def packetReceived(self, stats):
        with self.lock:
            self.last_packet_at = self.clock()
            if self.previous_stats is not None and tuple(stats[1:]) == tuple(self.previous_stats[1:]):
                self.frozen_count += 1
            else:
                self.frozen_count = 0
            self.previous_stats = stats

    def isGamePaused(self):
        return self.frozen_count >= FROZEN_PACKETS_FOR_PAUSE

    def stageStarted(self, track, car):
        with self.lock:
            if self.state == RUNNING:
                self._recordDnf('new stage started before finishing')

            self.track, self.car = self._names(track, car)
            self.state = PROMPTING
            logger.info('Stage loaded, waiting for nickname: %s | %s', self.track, self.car)

            if self.auto_pause:
                self.game.pause()
            self.pause_check_at = self.clock() + PAUSE_CHECK_DELAY_SECONDS

            # the tournament (track, car) when this stage is something else, so the driver can be warned
            active = self.database.activeCombo()
            mismatch = active if active is not None and active != (self.track, self.car) else None
            if mismatch:
                logger.warning('Stage is not the tournament setup (%s | %s), time will not be on the leaderboard', *mismatch)

            self.ui.showPrompt(self.track, self.car, mismatch)

    def stageFinished(self, laptime, _track=None, _car=None):
        with self.lock:
            if self.state == RUNNING:
                self._record(laptime, FINISHED, None)
            elif self.state == PROMPTING:
                logger.warning('Stage finished without a nickname, result NOT recorded')
                self.ui.hidePrompt()
            self.state = IDLE

    def stageAborted(self):
        with self.lock:
            if self.state == RUNNING:
                self._recordDnf('stage restarted')
                self.state = IDLE
            # While PROMPTING, the restarted stage triggers stageStarted again and keeps the prompt open

    def tick(self):
        with self.lock:
            now = self.clock()
            silent = self.last_packet_at is not None and now - self.last_packet_at > self.dnf_timeout

            if self.state == RUNNING and silent:
                self._recordDnf(f'no telemetry for {self.dnf_timeout:.0f} s (left stage)')
                self.state = IDLE

            elif self.state == PROMPTING and silent:
                logger.info('Stage left before a nickname was entered')
                self.ui.hidePrompt()
                self.state = IDLE

            if self.state == PROMPTING and self.pause_check_at is not None and now >= self.pause_check_at:
                self.pause_check_at = None
                self.ui.setGamePaused(self.isGamePaused())

    # --- calls from the nickname window (UI thread) ---

    def lookup(self, name):
        with self.lock:
            if self.track is None:
                return None
            return self.database.lookup(name, self.track, self.car)

    def start(self, name):
        '''
        Registers the nickname for the stage that is waiting and resumes the game.
        Returns None on success, otherwise an error message for the window.
        '''
        with self.lock:
            if self.state != PROMPTING:
                return 'No stage is waiting to start.'

            info = self.database.lookup(name, self.track, self.car)
            if info is None:
                return 'Enter a nickname.'
            if info['remaining'] == 0:
                return f"{info['name']} has completed all {info['max']} attempts."

            self.player = info['name']
            self.state = RUNNING
            # grace period: silence is measured from the moment the player starts
            self.last_packet_at = self.clock()
            logger.info('%s starts attempt %s/%s', self.player, info['used'] + 1, info['max'])

        if self.auto_pause:
            self.game.resume()
        return None

    # --- helpers ---

    def _names(self, track, car):
        if self.name_lookup is None:
            return str(track), str(car)
        trackName, carName = self.name_lookup
        return describe(track, trackName, 'Unknown track'), describe(car, carName, 'Unknown car')

    def _recordDnf(self, reason):
        self._record(None, DNF, reason)

    def _record(self, laptime, status, note):
        try:
            onLeaderboard = self.database.isActiveCombo(self.track, self.car)
            attempt = self.database.recordResult(self.player, self.track, self.car, laptime, status, note)
            result = formatTime(laptime) if status == FINISHED else f'DNF ({note})'
            text = f'{self.player} - attempt {attempt}: {result}'
            if not onLeaderboard:
                text += ' (other track/car, not on the leaderboard)'
            logger.info('RESULT %s', text)
            self.ui.showResult(text)
        except AttemptsExhausted as exc:
            logger.error('Result not recorded: %s', exc)
        except Exception:  #pylint: disable=broad-except
            logger.exception('Failed to record result for %s', self.player)
        finally:
            self.player = None
