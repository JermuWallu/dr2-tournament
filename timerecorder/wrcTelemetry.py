'''
EA SPORTS WRC UDP telemetry: packet structure definitions and decoding.

Unlike DiRT Rally 2.0, which sends one fixed packet of 66 floats, EA WRC lets you define
exactly which channels it sends, as JSON files under

    Documents\\My Games\\WRC\\telemetry\\udp\\

and it sends separate packets for the events we care about: session_start when a stage is
loaded, session_end when it is over (with the result and whether it was finished), plus
session_update, session_pause and session_resume.

Because we write the structure definition ourselves, decoding is derived from that same
file: the channel order in the JSON is the byte order on the wire. Use `wrcSetup` to install
it into the game, and `wrcCapture` to see what the game actually sends.
'''
import json
import os
import struct

from .log import getLogger

logger = getLogger(__name__)

STRUCTURE_ID = 'tournament'
DEFINITION_FILE = f'{STRUCTURE_ID}.json'

SESSION_START = 'session_start'
SESSION_UPDATE = 'session_update'
SESSION_END = 'session_end'
SESSION_PAUSE = 'session_pause'
SESSION_RESUME = 'session_resume'

PACKET_TYPES = (SESSION_START, SESSION_UPDATE, SESSION_END, SESSION_PAUSE, SESSION_RESUME)

# WRC channel types mapped to struct codes (little endian)
TYPE_CODES = {
    'boolean': '?',
    'uint8': 'B', 'int8': 'b',
    'uint16': 'H', 'int16': 'h',
    'uint32': 'I', 'int32': 'i',
    'uint64': 'Q', 'int64': 'q',
    'float32': 'f', 'float64': 'd',
}

# The channels we ask the game for. Keep these minimal: a channel name the game does not know
# makes it reject the whole structure, and then nothing is sent at all.
HEADER_CHANNELS = [
    {'id': 'packet_uid', 'type': 'uint64'},
]

PACKET_CHANNELS = {
    SESSION_START: [
        {'id': 'game_mode', 'type': 'uint8'},
        {'id': 'location_id', 'type': 'uint16'},
        {'id': 'route_id', 'type': 'uint16'},
        {'id': 'stage_length', 'type': 'float64'},
        {'id': 'vehicle_id', 'type': 'uint16'},
        {'id': 'vehicle_class_id', 'type': 'uint16'},
        {'id': 'vehicle_manufacturer_id', 'type': 'uint16'},
    ],
    SESSION_UPDATE: [
        {'id': 'game_total_time', 'type': 'float32'},
        {'id': 'stage_current_time', 'type': 'float32'},
        {'id': 'stage_current_distance', 'type': 'float64'},
        {'id': 'stage_length', 'type': 'float64'},
        {'id': 'vehicle_speed', 'type': 'float32'},
    ],
    SESSION_END: [
        {'id': 'stage_result_status', 'type': 'uint8'},
        {'id': 'stage_result_time', 'type': 'float32'},
        {'id': 'stage_result_time_penalty', 'type': 'float32'},
    ],
    SESSION_PAUSE: [
        {'id': 'game_total_time', 'type': 'float32'},
    ],
    SESSION_RESUME: [
        {'id': 'game_total_time', 'type': 'float32'},
    ],
}

def defaultDefinition():
    '''The structure definition we install into the game.'''
    return {
        'versions': {'schema': 1, 'data': 3},
        'id': STRUCTURE_ID,
        'header': {'channels': list(HEADER_CHANNELS)},
        'packets': {name: {'channels': list(channels)} for name, channels in PACKET_CHANNELS.items()},
    }


class PacketFormat():
    '''Decodes one packet type into {channel name: value}.'''

    def __init__(self, name, channels):
        self.name = name
        self.channels = [channel['id'] for channel in channels]
        try:
            self.format = '<' + ''.join(TYPE_CODES[channel['type']] for channel in channels)
        except KeyError as exc:
            raise ValueError(f'Unknown channel type {exc} in packet {name}') from None
        self.size = struct.calcsize(self.format)

    def decode(self, data):
        '''
        Values by channel name. Extra bytes at the end are ignored, so a game version that
        appends something does not break decoding; too few bytes raises ValueError.
        '''
        if len(data) < self.size:
            raise ValueError(f'{self.name} needs {self.size} bytes, got {len(data)}')
        return dict(zip(self.channels, struct.unpack(self.format, data[:self.size])))

    def __repr__(self):
        return f'<PacketFormat {self.name} {self.size} bytes: {", ".join(self.channels)}>'


class Definition():
    '''A loaded structure definition: the packet formats the game will send us.'''

    def __init__(self, definition):
        self.raw = definition
        header = definition.get('header', {}).get('channels', [])
        self.formats = {}
        for name, packet in definition.get('packets', {}).items():
            self.formats[name] = PacketFormat(name, list(header) + list(packet.get('channels', [])))

    @classmethod
    def default(cls):
        return cls(defaultDefinition())

    @classmethod
    def load(cls, path):
        with open(path, encoding='utf-8') as file:
            return cls(json.load(file))

    @classmethod
    def loadOrDefault(cls, path):
        '''
        The definition installed in the game when it is readable, otherwise the built-in one.
        The installed file is what the game sends, so it wins.
        '''
        try:
            if path and os.path.isfile(path):
                definition = cls.load(path)
                logger.debug('Using telemetry structure from %s', path)
                return definition
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception('Could not read %s, using the built-in structure', path)
        return cls.default()

    def format(self, packetType):
        return self.formats.get(packetType)

    def sizes(self):
        return {name: fmt.size for name, fmt in self.formats.items()}


# What stage_result_status means is not documented publicly, so it is configurable.
# Anything not listed as finished is treated as a DNF, which is the safe way round:
# a retirement never silently becomes a time.
DEFAULT_FINISHED_STATUSES = (1,)

def isFinished(status, finishedStatuses=DEFAULT_FINISHED_STATUSES):
    return int(status) in tuple(finishedStatuses)
