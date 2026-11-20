'''
LAN tournament mode for EA SPORTS WRC. Same rules, nickname window, leaderboard, admin portal
and backups as the DiRT Rally 2.0 version, with EA WRC telemetry instead.

    python -m timerecorder.wrcTournament

Run `python -m timerecorder.wrcSetup` once first so the game sends the telemetry.
Its database, ports and log are separate, so both tournaments can run side by side.
'''
import os
import sys
import threading

try:
    from . import log, config
    from .gameControl import GameController
    from .nicknamePrompt import PromptWindow, TkUiBridge
    from .tournament import appRoot, localAddress, startAdminPortal, startLeaderboard
    from .tournamentBackups import BackupManager
    from .tournamentDatabase import TournamentDatabase
    from .tournamentSession import TournamentSession
    from .wrcNames import WrcNames
    from .wrcReceiver import WrcReceiver
    from .wrcSetup import findTelemetryFolder, UDP_FOLDER
    from .wrcTelemetry import Definition, DEFINITION_FILE
except ImportError:
    from timerecorder import log, config  # @Reimport
    from timerecorder.gameControl import GameController  # @Reimport
    from timerecorder.nicknamePrompt import PromptWindow, TkUiBridge  # @Reimport
    from timerecorder.tournament import appRoot, localAddress, startAdminPortal, startLeaderboard  # @Reimport
    from timerecorder.tournamentBackups import BackupManager  # @Reimport
    from timerecorder.tournamentDatabase import TournamentDatabase  # @Reimport
    from timerecorder.tournamentSession import TournamentSession  # @Reimport
    from timerecorder.wrcNames import WrcNames  # @Reimport
    from timerecorder.wrcReceiver import WrcReceiver  # @Reimport
    from timerecorder.wrcSetup import findTelemetryFolder, UDP_FOLDER  # @Reimport
    from timerecorder.wrcTelemetry import Definition, DEFINITION_FILE  # @Reimport

LOGFILE = 'wrc-tournament.log'
BACKUP_FOLDER = 'wrc-backups'
GAME_NAME = 'EA SPORTS WRC'

logger = log.getLogger('timerecorder.wrcTournament')

def installedDefinition():
    '''
    The structure the game was actually given, so this tool decodes exactly what it sends.
    Falls back to the built-in one when the game's folder cannot be found.
    '''
    try:
        path = os.path.join(findTelemetryFolder(), UDP_FOLDER, DEFINITION_FILE)
    except (FileNotFoundError, OSError):
        return Definition.default()
    return Definition.loadOrDefault(path)

def startTelemetry(session, bridge, settings):
    '''Runs the WRC receiver on its own thread.'''
    receiver = WrcReceiver(listener=session,
                           host=settings['telemetry_host'],
                           ports=settings['ports'],
                           definition=installedDefinition(),
                           names=settings['names'],
                           finishedStatuses=settings['finished_statuses'])

    def run():
        try:
            receiver.reconnect()
            receiver.loop(tick=session.tick)
        except OSError as exc:
            logger.exception('WRC telemetry receiver failed')
            bridge.fatal(f'Cannot listen for EA WRC telemetry: {exc}\n\n'
                         'Another program may be using one of the ports, or another copy of '
                         'this tool is already running.')
        except Exception as exc:  #pylint: disable=broad-except
            logger.exception('WRC telemetry receiver crashed')
            bridge.fatal(f'Telemetry receiver crashed: {exc}\nSee {LOGFILE}.')

    thread = threading.Thread(target=run, name='wrc-telemetry', daemon=True)
    thread.start()
    return receiver

def main():
    approot = appRoot()
    log.init(os.path.join(approot, LOGFILE))
    logger.info('Starting EA WRC tournament mode %s', config.readVersion(approot))

    config.init(os.path.join(approot, 'config.yml'))
    settings = dict(config.GET.tournament)
    settings.update(config.GET.wrc)
    settings['names'] = WrcNames.load(approot)

    database = TournamentDatabase(os.path.join(approot, settings['tournament_db']), settings['max_attempts'])

    bridge = TkUiBridge()
    game = GameController(settings['game_window_title'], enabled=bool(settings['auto_pause']))
    session = TournamentSession(database, game, bridge,
                                dnfTimeoutSeconds=settings['dnf_timeout_seconds'],
                                autoPause=bool(settings['auto_pause']))

    backups = BackupManager(database, os.path.join(approot, BACKUP_FOLDER),
                            settings['backup_keep'], settings['backup_interval_minutes'])
    session.on_new_best = backups.newBest
    backups.startSchedule()

    port = settings['leaderboard_port']
    url = f'http://{localAddress()}:{port}'
    startLeaderboard(database, settings['leaderboard_host'], port, GAME_NAME)
    logger.info('Leaderboard: %s', url)

    startAdminPortal(database, settings, backups)
    startTelemetry(session, bridge, settings)

    window = PromptWindow(session, bridge, leaderboardUrl=url,
                          mode=settings['prompt_mode'], startDelaySeconds=settings['start_delay_seconds'])
    try:
        window.run()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    sys.exit(main())
