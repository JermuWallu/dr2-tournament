'''
Records raw DR2 telemetry to a CSV file and prints what the game is doing, to check how
pausing, retiring, restarting and finishing look in the data.

    python -m timerecorder.telemetryCapture [capture.csv] [port]

Stop with Ctrl+C. Do not run it together with the recorder (both need the same port).
'''
import csv
import socket
import struct
import sys
import time

FIELD_COUNT = 66
SILENCE_SECONDS = 1.0
FROZEN_PACKETS = 10

def describe(stats):
    progress = stats[2] / stats[61] if stats[61] else 0.0
    return (f'clock={stats[0]:9.2f} lapTime={stats[1]:8.2f} distance={stats[2]:9.1f} '
            f'progress={progress:6.3f} lap={stats[59]:.0f} speed={stats[7] * 3.6:6.1f}kph '
            f'finalTime={stats[62]:8.3f}')

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else f'capture-{int(time.time())}.csv'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 20777

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    sock.settimeout(0.2)
    print(f'Listening on 127.0.0.1:{port}, writing {path}. Ctrl+C to stop.')

    last = ()  # previous packet; empty until the first one arrives
    lastAt = None
    frozen = 0
    reportedSilence = False
    reportedFrozen = False
    started = time.monotonic()

    with open(path, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['wall_s', 'event'] + [f'f{i}' for i in range(FIELD_COUNT)])
        try:
            while True:
                now = time.monotonic()
                try:
                    data = sock.recv(FIELD_COUNT * 8)
                except socket.timeout:
                    if lastAt is not None and now - lastAt > SILENCE_SECONDS and not reportedSilence:
                        print(f'[{now - started:8.2f}] SILENCE: no packets since {now - lastAt:.1f} s')
                        writer.writerow([f'{now - started:.3f}', 'silence'])
                        reportedSilence = True
                    continue

                if len(data) < FIELD_COUNT * 4:
                    print(f'[{now - started:8.2f}] short packet: {len(data)} bytes')
                    continue
                stats = struct.unpack(f'{FIELD_COUNT}f', data[:FIELD_COUNT * 4])

                event = ''
                if reportedSilence:
                    print(f'[{now - started:8.2f}] packets resumed after {now - lastAt:.1f} s: {describe(stats)}')
                    event = 'resumed'
                    reportedSilence = False

                if stats.count(0.0) == len(stats):
                    event = event or 'all_zero'
                    if not last or last.count(0.0) != len(last):
                        print(f'[{now - started:8.2f}] ALL-ZERO packet')

                frozen = frozen + 1 if last and stats[1:] == last[1:] else 0
                if frozen >= FROZEN_PACKETS and not reportedFrozen:
                    print(f'[{now - started:8.2f}] FROZEN (paused?): {describe(stats)}')
                    reportedFrozen = True
                    event = event or 'frozen'
                elif frozen == 0 and reportedFrozen:
                    print(f'[{now - started:8.2f}] moving again: {describe(stats)}')
                    reportedFrozen = False
                    event = event or 'unfrozen'

                if last and stats[0] < last[0]:
                    print(f'[{now - started:8.2f}] CLOCK WENT BACKWARDS {last[0]:.2f} -> {stats[0]:.2f}')
                    event = event or 'clock_back'
                if last and stats[59] != last[59]:
                    print(f'[{now - started:8.2f}] LAP changed {last[59]} -> {stats[59]}')
                if lastAt is None or int(now - started) != int(lastAt - started):
                    print(f'[{now - started:8.2f}] {describe(stats)}', end='\r')

                writer.writerow([f'{now - started:.3f}', event] + [f'{v:.6g}' for v in stats])
                last = stats
                lastAt = now
        except KeyboardInterrupt:
            print(f'\nSaved {path}')
        finally:
            sock.close()

if __name__ == '__main__':
    main()
