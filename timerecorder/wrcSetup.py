'''
Sets up EA SPORTS WRC to send the telemetry the tournament needs.

It writes our packet structure to

    Documents\\My Games\\WRC\\telemetry\\udp\\tournament.json

and registers one entry per packet type in `telemetry\\config.json`, keeping everything else
in that file as it is (the original is copied to config.json.backup first).

    python -m timerecorder.wrcSetup            install
    python -m timerecorder.wrcSetup --check    show what is installed, change nothing
    python -m timerecorder.wrcSetup --remove   remove our entries again

Close the game first: it reads these files at start-up.
'''
import json
import os
import shutil
import sys

from .log import getLogger
from .wrcReceiver import DEFAULT_PORTS
from .wrcTelemetry import STRUCTURE_ID, DEFINITION_FILE, defaultDefinition

logger = getLogger(__name__)

CONFIG_FILE = 'config.json'
UDP_FOLDER = 'udp'
UPDATE_FREQUENCY_HZ = 20  # only used for liveness and the fallback pause check, 20 is plenty

def candidateTelemetryFolders():
    '''Where EA WRC keeps its telemetry settings, most likely first.'''
    home = os.path.expanduser('~')
    documents = [os.path.join(home, 'Documents'), os.path.join(home, 'OneDrive', 'Documents')]
    oneDrive = os.environ.get('OneDrive') or os.environ.get('OneDriveConsumer')
    if oneDrive:
        documents.append(os.path.join(oneDrive, 'Documents'))

    folders = []
    for folder in documents:
        candidate = os.path.join(folder, 'My Games', 'WRC', 'telemetry')
        if candidate not in folders:
            folders.append(candidate)
    return folders

def findTelemetryFolder(override=None):
    '''
    The game's telemetry folder. An existing one wins; otherwise the first candidate, which
    is created on install. Raises FileNotFoundError when `override` does not exist.
    '''
    if override:
        if not os.path.isdir(override):
            raise FileNotFoundError(f'No such folder: {override}')
        return override

    candidates = candidateTelemetryFolders()
    return next((candidate for candidate in candidates if os.path.isdir(candidate)), candidates[0])

def _readConfig(path):
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as file:
            return json.load(file) or {}
    except (OSError, ValueError, json.JSONDecodeError):
        logger.exception('Could not read %s', path)
        raise

def _packetList(config):
    '''
    The list of packet entries, wherever this game version keeps it, creating it when missing.
    Returns (list, container) so the caller can store a freshly created list back.
    '''
    if isinstance(config.get('udp'), dict):
        udp = config['udp']
    elif isinstance(config.get('packets'), list):
        udp = config
    else:
        udp = config.setdefault('udp', {})

    if not isinstance(udp.get('packets'), list):
        udp['packets'] = []
    return udp['packets'], udp

def entriesFor(ports=None, host='127.0.0.1', frequencyHz=UPDATE_FREQUENCY_HZ):
    '''One config entry per packet type, each on its own port.'''
    ports = ports or DEFAULT_PORTS
    return [{
        'structure': STRUCTURE_ID,
        'packet': packetType,
        'ip': host,
        'port': int(port),
        'frequencyHz': frequencyHz,
        'bEnabled': True,
    } for packetType, port in sorted(ports.items(), key=lambda item: item[1])]

def install(folder=None, ports=None, host='127.0.0.1'):
    '''Writes the structure and registers it. Returns (telemetry folder, entries written).'''
    telemetry = findTelemetryFolder(folder)
    udpFolder = os.path.join(telemetry, UDP_FOLDER)
    os.makedirs(udpFolder, exist_ok=True)

    definitionPath = os.path.join(udpFolder, DEFINITION_FILE)
    with open(definitionPath, 'w', encoding='utf-8') as file:
        json.dump(defaultDefinition(), file, indent=2)
    logger.info('Wrote %s', definitionPath)

    configPath = os.path.join(telemetry, CONFIG_FILE)
    config = _readConfig(configPath)
    if os.path.isfile(configPath) and not os.path.isfile(configPath + '.backup'):
        shutil.copyfile(configPath, configPath + '.backup')

    packets, udp = _packetList(config)
    kept = [entry for entry in packets if entry.get('structure') != STRUCTURE_ID]
    entries = entriesFor(ports, host)
    udp['packets'] = kept + entries
    udp.setdefault('enabled', True)
    config.setdefault('versions', {'schema': 1, 'data': 3})

    with open(configPath, 'w', encoding='utf-8') as file:
        json.dump(config, file, indent=2)
    logger.info('Registered %s packet types in %s', len(entries), configPath)

    return telemetry, entries

def remove(folder=None):
    telemetry = findTelemetryFolder(folder)
    configPath = os.path.join(telemetry, CONFIG_FILE)
    config = _readConfig(configPath)
    packets, udp = _packetList(config)
    kept = [entry for entry in packets if entry.get('structure') != STRUCTURE_ID]
    removed = len(packets) - len(kept)
    udp['packets'] = kept
    with open(configPath, 'w', encoding='utf-8') as file:
        json.dump(config, file, indent=2)

    definitionPath = os.path.join(telemetry, UDP_FOLDER, DEFINITION_FILE)
    if os.path.isfile(definitionPath):
        os.remove(definitionPath)
    return telemetry, removed

def describeInstallation(folder=None):
    '''Lines describing what is installed, for --check.'''
    telemetry = findTelemetryFolder(folder)
    lines = [f'Telemetry folder: {telemetry}']
    if not os.path.isdir(telemetry):
        return lines + ['  MISSING. Start EA WRC once, or pass the folder as an argument.']

    installed = os.path.isfile(os.path.join(telemetry, UDP_FOLDER, DEFINITION_FILE))
    lines.append(f'  {DEFINITION_FILE}: {"installed" if installed else "NOT installed"}')

    configPath = os.path.join(telemetry, CONFIG_FILE)
    if not os.path.isfile(configPath):
        return lines + [f'  {CONFIG_FILE}: NOT found']

    packets, _udp = _packetList(_readConfig(configPath))
    ours = [entry for entry in packets if entry.get('structure') == STRUCTURE_ID]
    lines.append(f'  {CONFIG_FILE}: {len(packets)} entries, {len(ours)} ours')
    for entry in ours:
        state = 'on' if entry.get('bEnabled') else 'OFF'
        lines.append(f"    {entry.get('packet')} -> {entry.get('ip')}:{entry.get('port')} ({state})")
    return lines

HELP = ('\n\nStart EA SPORTS WRC once so it creates its telemetry folder, or pass the folder as an '
        'argument, e.g.\n  python -m timerecorder.wrcSetup "D:\\Documents\\My Games\\WRC\\telemetry"')

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    action = 'install'
    for flag in ('--check', '--remove'):
        if flag in argv:
            action = flag[2:]
            argv.remove(flag)
    folder = argv[0] if argv else None

    try:
        if action == 'check':
            print('\n'.join(describeInstallation(folder)))
        elif action == 'remove':
            telemetry, removed = remove(folder)
            print(f'Removed {removed} entries from {telemetry}')
        else:
            telemetry, entries = install(folder)
            print(f'EA WRC telemetry set up in {telemetry}')
            for entry in entries:
                print(f"  {entry['packet']} -> {entry['ip']}:{entry['port']}")
            print('\nRestart EA SPORTS WRC for this to take effect, then run wrc-capture.bat to check it.')
        return 0
    except FileNotFoundError as exc:
        print(f'{exc}{HELP}')
        return 1
    except OSError as exc:
        print(f'Could not write the telemetry settings: {exc}')
        return 1

if __name__ == '__main__':
    sys.exit(main())
