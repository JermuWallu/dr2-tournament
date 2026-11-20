'''
Shows what EA SPORTS WRC actually sends, so the channel names and the stage_result_status
values can be confirmed on the machine that runs the game.

    python -m timerecorder.wrcCapture [capture.csv]

Run it with tournament mode closed (both need the same ports). On a stage: start it, pause,
resume, finish once, and retire once. Every packet is written to the CSV, and the console
shows each session_start / session_end with its decoded values and raw bytes.
'''
import csv
import selectors
import socket
import sys
import time

from .wrcReceiver import DEFAULT_PORTS
from .wrcTelemetry import Definition, SESSION_UPDATE

UPDATE_SUMMARY_SECONDS = 1.0

def main(argv=None):  #pylint: disable=too-many-locals,too-many-branches,too-many-statements
    argv = list(sys.argv[1:] if argv is None else argv)
    path = argv[0] if argv else f'wrc-capture-{int(time.time())}.csv'
    definition = Definition.default()

    selector = selectors.DefaultSelector()
    sockets = []
    for packetType, port in sorted(DEFAULT_PORTS.items(), key=lambda item: item[1]):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            print(f'Cannot listen on port {port} for {packetType}: {exc}')
            print('Close tournament mode and any other telemetry tool, then try again.')
            for opened in sockets:
                opened.close()
            return 1
        sockets.append(sock)
        selector.register(sock, selectors.EVENT_READ, packetType)

    print('Expected packet sizes:')
    for name, size in sorted(definition.sizes().items()):
        print(f'  {name}: {size} bytes on port {DEFAULT_PORTS[name]}')
    print(f'\nListening. Writing {path}. Ctrl+C to stop.\n')

    started = time.monotonic()
    counts = {}
    lastSummary = 0.0

    with open(path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['seconds', 'packet', 'bytes', 'channel', 'value'])
        try:
            while True:
                for key, _mask in selector.select(0.25):
                    packetType = key.data
                    try:
                        data, _address = key.fileobj.recvfrom(2048)
                    except (BlockingIOError, OSError):
                        continue

                    now = time.monotonic() - started
                    counts[packetType] = counts.get(packetType, 0) + 1
                    packetFormat = definition.format(packetType)
                    expected = packetFormat.size if packetFormat else None

                    values = None
                    if packetFormat is not None:
                        try:
                            values = packetFormat.decode(data)
                        except ValueError:
                            values = None

                    if values:
                        for channel, value in values.items():
                            writer.writerow([f'{now:.3f}', packetType, len(data), channel, value])
                    else:
                        writer.writerow([f'{now:.3f}', packetType, len(data), 'raw_hex', data.hex()])

                    if packetType != SESSION_UPDATE:
                        print(f'[{now:8.2f}] {packetType}  {len(data)} bytes'
                              f'{"" if expected is None or expected == len(data) else f" (expected {expected}!)"}')
                        if values:
                            for channel, value in values.items():
                                print(f'              {channel} = {value}')
                        else:
                            print(f'              could not decode, raw: {data.hex()}')
                        print()

                now = time.monotonic() - started
                if now - lastSummary >= UPDATE_SUMMARY_SECONDS:
                    lastSummary = now
                    summary = ', '.join(f'{name}={count}' for name, count in sorted(counts.items()))
                    print(f'[{now:8.2f}] {summary or "nothing received yet"}          ', end='\r')
        except KeyboardInterrupt:
            print(f'\n\nSaved {path}')
            if not counts:
                print('No packets at all. Check that wrc-setup.bat ran, that EA WRC was restarted '
                      'after it, and that you were on a stage.')
            else:
                print('Received: ' + ', '.join(f'{name}={count}' for name, count in sorted(counts.items())))
        finally:
            for sock in sockets:
                sock.close()
            selector.close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
