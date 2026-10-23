'''
LAN tournament mode: asks for a nickname when a stage loads, records two attempts per player
and serves a live web leaderboard.

    python -m timerecorder.tournament
'''
import os
import socket
import sqlite3
import sys
import threading

try:
    from . import log, config
    from .gameControl import GameController
    from .nicknamePrompt import PromptWindow, TkUiBridge
    from .receiver import Receiver
    from .statsProcessor import StatsProcessor
    from .tournamentDatabase import TournamentDatabase
    from .tournamentSession import TournamentSession
except ImportError:
    from timerecorder import log, config  # @Reimport
    from timerecorder.gameControl import GameController  # @Reimport
    from timerecorder.nicknamePrompt import PromptWindow, TkUiBridge  # @Reimport
    from timerecorder.receiver import Receiver  # @Reimport
    from timerecorder.statsProcessor import StatsProcessor  # @Reimport
    from timerecorder.tournamentDatabase import TournamentDatabase  # @Reimport
    from timerecorder.tournamentSession import TournamentSession  # @Reimport

LOGFILE = 'tournament.log'
TOURNAMENT_DB = 'tournament.db'
BASE_DB = 'dirtrally-lb.db'

logger = log.getLogger('timerecorder.tournament')

def appRoot():
    if getattr(sys, 'frozen', None):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

def ensureBaseDatabase(approot):
    '''Builds the car/track database from resources/setup-dr2.sql if it does not exist yet.'''
    path = os.path.join(approot, BASE_DB)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return

    script = os.path.join(approot, 'resources', 'setup-dr2.sql')
    logger.info('Creating %s from %s', BASE_DB, script)
    with open(script, encoding='utf-8') as file:
        sql = file.read()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()

def localAddress():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))
            return probe.getsockname()[0]
    except OSError:
        return 'localhost'

def startLeaderboard(database, host, port):
    from .leaderboard import serve  #pylint: disable=import-outside-toplevel
    thread = threading.Thread(target=serve, args=(database, host, port), name='leaderboard', daemon=True)
    thread.start()

def startTelemetry(approot, session, bridge):
    '''Runs the UDP receiver on its own thread. SQLite objects must be created on the thread using them.'''

    def run():
        try:
            statsProcessor = StatsProcessor(approot)
            database = statsProcessor.database
            session.setNameLookup(database.getTrackName, database.getCarName)
            statsProcessor.setListener(session)

            receiver = Receiver(approot, statsProcessor)
            receiver.reconnect()
            receiver.loop(tick=session.tick)
        except OSError as exc:
            logger.exception('Telemetry receiver failed')
            bridge.fatal(f'Cannot listen for telemetry on {config.GET.server}: {exc}\n'
                         'Is another recorder already running?')
        except Exception as exc:  #pylint: disable=broad-except
            logger.exception('Telemetry receiver crashed')
            bridge.fatal(f'Telemetry receiver crashed: {exc}\nSee {LOGFILE}.')

    thread = threading.Thread(target=run, name='telemetry', daemon=True)
    thread.start()

def main():
    approot = appRoot()
    log.init(os.path.join(approot, LOGFILE))
    logger.info('Starting tournament mode %s', config.readVersion(approot))

    config.init(os.path.join(approot, 'config.yml'))
    settings = config.GET.tournament

    ensureBaseDatabase(approot)
    database = TournamentDatabase(os.path.join(approot, TOURNAMENT_DB), settings['max_attempts'])

    bridge = TkUiBridge()
    game = GameController(settings['game_window_title'], enabled=bool(settings['auto_pause']))
    session = TournamentSession(database, game, bridge,
                                dnfTimeoutSeconds=settings['dnf_timeout_seconds'],
                                autoPause=bool(settings['auto_pause']))

    port = settings['leaderboard_port']
    url = f'http://{localAddress()}:{port}'
    startLeaderboard(database, settings['leaderboard_host'], port)
    logger.info('Leaderboard: %s', url)

    startTelemetry(approot, session, bridge)

    window = PromptWindow(session, bridge, leaderboardUrl=url)
    try:
        window.run()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
