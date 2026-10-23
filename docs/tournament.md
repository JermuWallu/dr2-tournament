## LAN tournament mode

Tournament mode turns the recorder into a two-attempt time attack for one gaming PC:

- when a stage has loaded, the game is paused and a window asks for the driver's nickname
- after typing, the window shows the attempts the driver has already used on this track and car
- a driver who has used both attempts cannot start
- **Start** resumes the game, and the result (time or DNF) is saved with the nickname and attempt number
- a web leaderboard shows the standings live, ranked by best time, then name

### Set up

1. Install Python 3.12 or newer from python.org (it includes tkinter).
2. In the repository folder, run `pip install -r requirements-tournament.txt`.
   - On a Python too new for PyYAML's prebuilt Windows wheels (e.g. 3.15), pip tries to compile it and asks for Microsoft C++ Build Tools. Install the pure-Python version instead: in PowerShell run `$env:PYYAML_FORCE_LIBYAML = "0"` first, then the pip command again.
3. Enable DR2 UDP telemetry as described in the [README](../README.md#configuration) (`extradata="3"`).
4. Set DiRT Rally 2.0 to **borderless** or **windowed** display mode. In exclusive fullscreen, the nickname window cannot appear over the game.
5. Start a **Time Trial** with the tournament track and car.
6. Double-click `tournament.bat`, or run `python -m timerecorder.tournament`.

On first start, the tool creates `dirtrally-lb.db` (cars and tracks) from `resources/setup-dr2.sql`. Results go into `tournament.db`. The console and the nickname window show the leaderboard address, e.g. `http://192.168.1.20:5000`. Open it on any device on the LAN. Allow Python through the Windows firewall when asked.

The leaderboard can also run on its own: `python -m timerecorder.leaderboard tournament.db 5000`.

### Rules as implemented

| Situation | What is recorded |
|---|---|
| Driver finishes the stage | finish time for the next attempt |
| Driver restarts the stage (pause menu → Restart) | DNF, and the nickname window opens again |
| Telemetry stops for `dnf_timeout_seconds` after Start (retired / quit to menu) | DNF |
| A new stage loads before the running one finished | DNF |
| Stage finished without a nickname | nothing |

- Nicknames are case-insensitive (`Jere` = `jere`) and keep the spelling of the first result.
- Attempts are counted per track **and** car combination. The leaderboard shows the most recently driven combination and offers a selector when there are several.
- Leaderboard: one row per driver with best time, gap to leader, and each run. Equal best times share a position. Drivers with only DNFs are listed last.

### Settings (`config.yml`)

```
tournament:
  max_attempts: 2
  auto_pause: 1              # 0: driver pauses/resumes with Esc themselves
  game_window_title: DiRT Rally 2.0
  dnf_timeout_seconds: 15
  leaderboard_host: 0.0.0.0  # 127.0.0.1 to keep the leaderboard on this PC only
  leaderboard_port: 5000
```

### Check on your PC before the event

Some game behaviour can only be confirmed on a real install:

1. **Pausing:** run `python -m timerecorder.gameControl`, drive onto a stage within 5 seconds. The game should pause, then resume 5 seconds later. If not, set `auto_pause: 0`.
2. **Telemetry when pausing, retiring, restarting and finishing:** run `telemetry-capture.bat` (with tournament mode closed). On a stage:
   - pause for a few seconds
   - restart
   - finish once
   - retire once

   The console reports `FROZEN`, `SILENCE`, `ALL-ZERO` and clock jumps, and the CSV holds every packet. This confirms DNF detection, especially that retiring stops the packets.

To reset the tournament, close the program and delete or rename `tournament.db`.
