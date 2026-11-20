## EA SPORTS WRC tournament mode

The same two-attempt LAN time attack as [DiRT Rally 2.0 tournament mode](tournament.md), driven by EA SPORTS WRC telemetry. The rules, nickname window, leaderboard, admin portal and backups are shared code, so both behave identically.

The two run side by side: separate database, ports, backups folder and log.

| | DiRT Rally 2.0 | EA SPORTS WRC |
|---|---|---|
| Start | `tournament.bat` | `wrc-tournament.bat` |
| Database | `tournament.db` | `wrc-tournament.db` |
| Backups | `backups/` | `wrc-backups/` |
| Leaderboard | port 5000 | port 5001 |
| Admin portal | port 6969 | port 6970 |
| Log | `tournament.log` | `wrc-tournament.log` |

### Why WRC is different

DiRT Rally 2.0 sends one fixed packet and the tool works out the car, the track, the finish and a DNF from the raw numbers. EA WRC is more direct:

- You choose which channels the game sends, in a JSON file.
- It sends **separate packets** for the things we care about: `session_start` when a stage loads, `session_end` when it is over, plus `session_update`, `session_pause` and `session_resume`.
- `session_end` carries the result time and a **status** saying whether the stage was finished, so a DNF is reported rather than guessed.
- The car and the stage come as **numbers** (`vehicle_id`, `route_id`, `location_id`), not names.

### Set up

1. Install Python 3.12 or newer and the packages, as in the [main README](../README.md#installation) (`install-tournament.bat`).
2. **Start EA SPORTS WRC once** so it creates `Documents\My Games\WRC\telemetry\`, then close it.
3. Run **`wrc-setup.bat`**. It writes `telemetry\udp\tournament.json` and registers the five packet types in `telemetry\config.json`, keeping anything already there. The original `config.json` is copied to `config.json.backup` first.
   - If it can't find the folder, pass it: `python -m timerecorder.wrcSetup "D:\Documents\My Games\WRC\telemetry"`
   - `wrc-setup.bat --check` shows what is installed; `--remove` undoes it.
4. **Restart EA SPORTS WRC** so it reads the new settings.
5. Run **`wrc-capture.bat`** and drive a stage: start it, pause, resume, finish once, retire once. See [Confirming the telemetry](#confirming-the-telemetry) below. Do this before the event.
6. Set the game to **borderless** or **windowed**, so the nickname window can appear over it.
7. Start **`wrc-tournament.bat`**.

### Confirming the telemetry

EA's UDP channel names and the meaning of `stage_result_status` are not published in a form this project could verify, so **check them once on the machine that runs the game**. `wrc-capture.bat` prints every `session_start` and `session_end` with its decoded values, and writes every packet to a CSV.

What to look for:

- **Nothing arrives at all.** The game rejected the structure, most likely because a channel name is wrong for your game version. Open `Documents\My Games\WRC\telemetry\readme\` — EA ships its UDP guide there with the channel list — and correct the names in `telemetry\udp\tournament.json`. The tournament reads that same file, so it follows your edit.
- **`session_end` after a clean finish.** Note the `stage_result_status` value. The tool treats **1** as finished; anything else is a DNF. If your finish shows a different number, set it in `config.yml`:
  ```yaml
  wrc:
    finished_statuses: [1]
  ```
- **`session_end` after retiring.** Confirm the status differs from the finished one.
- **The time.** `stage_result_time` should match the time the game showed. Any `stage_result_time_penalty` is added to it.
- **`route_id` and `vehicle_id`** for the track and car you will use. Add them to `resources/wrc-names.json` so the leaderboard shows real names:
  ```json
  {
    "locations": { "5": "Estonia" },
    "routes": { "101": "Otepää" },
    "vehicles": { "103": "Ford Puma Rally1 HYBRID" }
  }
  ```
  Without them the leaderboard shows `Route 101` and `Car 103`, which still works; you can also rename them later in the admin portal.

Safety net: anything the tool cannot read as a finish is recorded as a **DNF**, never as a time. A wrong setting can cost someone a valid time, but it can never invent one, and the admin portal can fix any run.

### Rules

Identical to DiRT Rally 2.0, with the DNFs coming from the game instead of being inferred:

| Situation | What is recorded |
|---|---|
| Driver finishes the stage | `stage_result_time` (plus any penalty) for the next attempt |
| `session_end` with a status that is not in `finished_statuses` | DNF, with the status number in the note |
| `session_end` with a finished status but no time | DNF |
| Telemetry stops for `dnf_timeout_seconds` after Start | DNF |
| A new stage loads before the running one finished | DNF |
| Stage finished without a nickname | Nothing |

The first recorded run sets the tournament route and car; runs on anything else are saved but kept off the public leaderboard, and the nickname window says so.

Pausing is exact here: the game's own `session_pause` and `session_resume` tell the window whether the game is paused, rather than the frozen-packet guess used for DiRT Rally.

### Settings (`config.yml`)

The `wrc:` section only holds what must differ from `tournament:`; everything else (attempts, auto-pause, DNF timeout, prompt mode, countdown, passcode, backups) is shared.

```yaml
wrc:
  tournament_db: wrc-tournament.db
  game_window_title: WRC        # window to send Esc to when pausing
  telemetry_host: 127.0.0.1
  ports:
    session_update: 20777
    session_start: 20778
    session_end: 20779
    session_pause: 20780
    session_resume: 20781
  finished_statuses: [1]
  leaderboard_port: 5001
  admin_port: 6970
```

Each packet type gets its own port, so they can be told apart with no guessing. If you change a port here, run `wrc-setup.bat` again so the game is told as well. Port 20777 is also DiRT Rally 2.0's default, so don't run both tournaments at once without changing it.

### Troubleshooting

**`Cannot listen for EA WRC telemetry`**
Another program holds one of the ports: the DR2 tournament, `wrc-capture.bat`, SimHub or similar. Close it, or change the ports as above.

**The nickname window never appears**
Run `wrc-setup.bat --check`, then `wrc-capture.bat`. If the capture shows nothing while you drive, the game isn't sending: check that you restarted it after setup, and see [Confirming the telemetry](#confirming-the-telemetry).

**Every run is a DNF**
`stage_result_status` for a finish on your version isn't 1. The capture tool shows the real value; put it in `finished_statuses`.

**Times look wrong**
Check `stage_result_time` in the capture against the game's own time. If the game sends it in a different unit or type, correct the channel's type in `telemetry\udp\tournament.json`; the tool follows that file.

**The leaderboard shows `Route 101` / `Car 103`**
Expected until you fill in `resources/wrc-names.json`, or rename them in the admin portal.
