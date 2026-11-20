# Rally Tournament

A LAN tournament tool for **DiRT Rally 2.0** and **EA SPORTS WRC**: every driver gets two attempts on the same track and car. The game pauses to ask each driver's nickname, results are recorded automatically from the game's telemetry, and a live leaderboard runs in the browser.

Built on top of [dirt-rally-time-recorder](https://github.com/soong-construction/dirt-rally-time-recorder) by Max Bechtold. The original stage time recorder still works as before (see [Original time recorder](#original-time-recorder)).

---

## Contents

- [Rally Tournament](#rally-tournament)
  - [Contents](#contents)
  - [Features](#features)
  - [Which game](#which-game)
  - [Requirements](#requirements)
  - [Installation](#installation)
    - [1. Download](#1-download)
    - [2. Install Python packages](#2-install-python-packages)
    - [3. Enable telemetry in DiRT Rally 2.0](#3-enable-telemetry-in-dirt-rally-20)
    - [4. Set the display mode](#4-set-the-display-mode)
    - [5. Change the admin passcode](#5-change-the-admin-passcode)
    - [6. Check the PC (recommended)](#6-check-the-pc-recommended)
    - [Updating](#updating)
  - [Running a tournament](#running-a-tournament)
  - [EA SPORTS WRC](#ea-sports-wrc)
  - [Admin portal](#admin-portal)
  - [Backups](#backups)
  - [Rules as implemented](#rules-as-implemented)
  - [Configuration](#configuration)
  - [Troubleshooting](#troubleshooting)
  - [Original time recorder](#original-time-recorder)
  - [Credits](#credits)
  - [Declaration of AI use](#declaration-of-ai-use)
  - [License](#license)

---

## Features

**Nickname prompt**
- When a stage has loaded, the tool pauses DiRT Rally 2.0 (by sending Esc to the game) and shows a nickname window, fullscreen by default so it can't be missed on ultrawide screens.
- The nickname box starts empty. After typing, it shows whether the driver is new or how many attempts they have used, with their earlier times.
- A driver who has used both attempts sees a warning, and **Start** stays disabled.
- After **Start**, a big **HYVÄÄ RALLIA!** appears with a 2-second countdown, then the game resumes.

**Automatic results**
- The finish time is read from the game's UDP telemetry and saved with the nickname and attempt number.
- DNFs are detected automatically: a stage restart, leaving the stage (telemetry stops), or loading a new stage before finishing.
- Nicknames are case-insensitive (`Jere` = `jere`).

**Tournament setup**
- The first recorded run sets the tournament track and car.
- If a driver loads a different track or car, the nickname window warns that the time won't be on the current leaderboard. The run is still saved.

**Live web leaderboard** (port 5000)
- Shows the tournament track and car only, with one row per driver: position, best time, gap to the leader, run 1 and run 2.
- Sorted by best time, then name. Drivers with only DNFs are listed last.
- Refreshes every 3 seconds and works on any device on the LAN: a projector, a TV or phones.

**Admin portal** (port 6969, passcode protected)
- Edit, delete or add runs by hand. Rename or delete players.
- Change the tournament track and car, and view the leaderboard of every driven combination.
- Find, view, download and restore backups.

**Rotating backups**
- The live database plus the newest 3 copies.
- A copy is made every 15 minutes (only if something changed), on every new best time, and before a restore.

**Two games**
- The same rules, windows and web pages for DiRT Rally 2.0 and EA SPORTS WRC.
- Each has its own database, ports and backups, so both can run at the same time.

**Other**
- Runs on Python 3.12 and newer. The original recorder needed Python 3.11 because of `asyncore`, which Python 3.12 removed.
- Includes a telemetry capture tool and a pause self-test, for checking a new PC before the event.

---

## Which game

| | DiRT Rally 2.0 | EA SPORTS WRC |
|---|---|---|
| Set-up | Edit `hardware_settings_config.xml` ([step 3](#3-enable-telemetry-in-dirt-rally-20)) | Run `wrc-setup.bat` ([details](docs/wrc-tournament.md)) |
| Start | `tournament.bat` | `wrc-tournament.bat` |
| Leaderboard | port 5000 | port 5001 |
| Admin portal | port 6969 | port 6970 |
| Database | `tournament.db` | `wrc-tournament.db` |

The instructions below are for DiRT Rally 2.0. WRC uses the same installation and the same rules, with its own telemetry set-up: see **[docs/wrc-tournament.md](docs/wrc-tournament.md)**.

## Requirements

- **Windows 10 or 11** on the PC that runs the game.
- **DiRT Rally 2.0** and/or **EA SPORTS WRC** on PC. UDP telemetry only exists on PC, not on consoles.
- **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/). It includes tkinter, which the nickname window needs. Tested with Python 3.15.
- Optional: [Git](https://git-scm.com/download/win), to download and update with `git pull`.
- For the web pages: other devices must be on the same network.

---

## Installation

### 1. Download

With Git:

```powershell
git clone https://github.com/JermuWallu/dr2-tournament.git
cd dr2-tournament
```

Or, on GitHub, choose **Code → Download ZIP** and unzip it somewhere, e.g. `C:\dr2-tournament`.

### 2. Install Python packages

Double-click **`install-tournament.bat`** in the folder, or run it in PowerShell:

```powershell
.\install-tournament.bat
```

It installs Flask and PyYAML. It also sets `PYYAML_FORCE_LIBYAML=0`, so PyYAML installs without the Microsoft C++ Build Tools on Python versions that have no prebuilt PyYAML package yet.

### 3. Enable telemetry in DiRT Rally 2.0

1. Open `%USERPROFILE%\Documents\My Games\DiRT Rally 2.0\hardwaresettings\hardware_settings_config.xml` in a text editor.
2. Change the `udp` line to:
   ```xml
   <udp enabled="true" extradata="3" ip="127.0.0.1" port="20777" delay="1" />
   ```
3. For VR, make the same change in `hardware_settings_config_vr.xml`.

Steam updates sometimes reset this file, so check it again after a game update.

### 4. Set the display mode

In DiRT Rally 2.0, set the display mode to **borderless** or **windowed**. In exclusive fullscreen, the nickname window cannot appear over the game.

### 5. Change the admin passcode

Start `tournament.bat` once and close it. This creates `config.yml`. Open it and change `admin_passcode` under `tournament:` (the default is `jermu`).

### 6. Check the PC (recommended)

Run these once, with tournament mode closed:

- **Pausing:** run `python -m timerecorder.gameControl`, then drive onto a stage within 5 seconds. The game should pause, then resume 5 seconds later. If it doesn't, set `auto_pause: 0` in `config.yml`, and drivers press Esc themselves.
- **Telemetry:** run `telemetry-capture.bat`, then on a stage pause, restart, finish and retire once each. The console reports what the game sends (`FROZEN`, `SILENCE`, `ALL-ZERO`, clock jumps), and a CSV file stores every packet.

### Updating

```powershell
git pull
```

With a ZIP download, download it again and copy your `tournament.db`, `backups` folder and `config.yml` into the new folder.

---

## Running a tournament

1. Start DiRT Rally 2.0 and open a **Time Trial** with the tournament track and car.
2. Double-click **`tournament.bat`**. The console shows the addresses, for example:
   ```
   Leaderboard: http://192.168.1.20:5000
   Admin portal: http://192.168.1.20:6969
   ```
   The first time, allow Python through the Windows firewall so other devices can open the pages.
3. Open the leaderboard on the screen everyone watches.
4. Each driver loads the stage, types a nickname, presses **Start** and drives. The result appears on the leaderboard within a few seconds.

The first recorded run sets the tournament track and car. To change it, use the admin portal.

To start a new tournament, close the program and rename or delete `tournament.db`. Keep the old file if you want its results.

---

## EA SPORTS WRC

Full instructions: **[docs/wrc-tournament.md](docs/wrc-tournament.md)**. In short:

1. Start EA SPORTS WRC once so it creates `Documents\My Games\WRC\telemetry\`, then close it.
2. Run **`wrc-setup.bat`**, which tells the game what to send.
3. Restart the game.
4. Run **`wrc-capture.bat`** and drive a stage (start, pause, finish, retire) to confirm the telemetry and to note the `route_id` and `vehicle_id` of your tournament stage and car.
5. Run **`wrc-tournament.bat`**.

WRC reports finishing and retiring itself, so DNFs are read from the game rather than inferred, and pausing is exact. The car and stage arrive as numbers; add friendly names to `resources/wrc-names.json` or rename them in the admin portal.

Because EA's channel names and result codes are not published in a form this project could verify, **run step 4 before the event**. Anything the tool cannot read as a finish is recorded as a DNF, never as a time.

## Admin portal

Open `http://<PC address>:6969` (or the next free port, shown in the console) and log in with `admin_passcode`.

| Section | What you can do |
|---|---|
| Tournament setup | See the current track and car (marked LIVE), switch to any driven combination, or clear it so the next run sets it |
| Leaderboard | Pick any driven track and car from a dropdown and see its standings |
| Runs | Change a run's status (Finished/DNF), time (`3:07.654`) or note, or delete it. Deleting a run moves later attempts up, so the driver can drive that attempt again |
| Add a run by hand | e.g. after a game crash. Counts as the driver's next attempt, and the attempt limit still applies |
| Players | Rename (a name that's already taken is refused) or delete a player and all their runs |
| Backups | Back up now, then view, download or restore any backup |
| Danger zone | Delete all runs of a track and car |

Anyone on the network who knows the passcode can change results, so use your own passcode. Logins reset when the program restarts.

---

## Backups

The `backups` folder next to `tournament.db` holds the newest **3** copies. Older ones are deleted automatically. A copy is made:

- every **15 minutes**, skipped when nothing changed since the newest copy
- whenever a run sets a **new best time** on the tournament leaderboard
- right **before a restore**, so a restore can be undone
- when you press **Back up now** in the admin portal

**View** opens a read-only page with the backup's setup, leaderboard and all runs. **Restore** replaces all live data (runs, players, tournament setup) and works while the tournament is running. Because the safety copy counts as one of the 3, a restore pushes out the oldest backup.

---

## Rules as implemented

| Situation | What is recorded |
|---|---|
| Driver finishes the stage | Finish time for the next attempt |
| Driver restarts the stage (pause menu → Restart) | DNF, and the nickname window opens again |
| Telemetry stops for 15 s after Start (retired or quit to the menu) | DNF |
| A new stage loads before the running one finished | DNF |
| Stage finished without a nickname | Nothing |
| Stage on another track or car | Saved, with its own attempt count, but not on the public leaderboard |

For EA WRC the first three rows come from the game's own `session_end` status rather than being inferred from the telemetry.

- Each driver gets 2 attempts per track and car combination.
- Equal best times share a position, and equal times are listed alphabetically.

---

## Configuration

`config.yml` is created on first start. Tournament settings (shared by both games):

```yaml
tournament:
  max_attempts: 2
  auto_pause: 1                  # 0: drivers pause/resume with Esc themselves
  game_window_title: DiRT Rally 2.0
  dnf_timeout_seconds: 15        # telemetry silence after Start that counts as a DNF
  leaderboard_host: 0.0.0.0      # 127.0.0.1 keeps both web pages on this PC only
  leaderboard_port: 5000
  prompt_mode: fullscreen        # or 'centered'
  start_delay_seconds: 2         # HYVÄÄ RALLIA! countdown after Start
  admin_passcode: jermu          # change this
  admin_port: 6969               # the next free port is used if taken
  backup_keep: 3
  backup_interval_minutes: 15
telemetry_server:
  host: 127.0.0.1
  port: 20777                    # must match the port in hardware_settings_config.xml
```

EA WRC adds a `wrc:` section holding only what must differ (its own database, ports and result codes). See [docs/wrc-tournament.md](docs/wrc-tournament.md#settings-configyml).

Changes apply the next time you start `tournament.bat`. For the original recorder's settings, see [docs/configuration.md](docs/configuration.md). More detail on tournament mode is in [docs/tournament.md](docs/tournament.md).

---

## Troubleshooting

**`pip` asks for "Microsoft Visual C++ 14.0 or greater"**
Your Python is newer than PyYAML's prebuilt packages. Use `install-tournament.bat`, or in PowerShell run `$env:PYYAML_FORCE_LIBYAML = "0"` in the same window before `py -m pip install -r requirements-tournament.txt`.

**`OSError: [WinError 10048]` when starting**
Another program already listens on port 20777: a second copy of this tool, SimHub, or dashboard, motion or wheel software. To find out which, run:
```powershell
Get-NetUDPEndpoint -LocalPort 20777 | ForEach-Object { Get-Process -Id $_.OwningProcess }
```
Close it, or let that app forward the telemetry to another port and set that port under `telemetry_server` in `config.yml`.

**The nickname window doesn't appear over the game**
Set the game to borderless or windowed mode.

**The game doesn't pause, or the window says "Game does not look paused"**
Run the pause self-test (Installation, step 6). If pausing doesn't work on that PC, set `auto_pause: 0`.

**Nothing happens when a stage loads**
Telemetry is probably off. A game update may have reset `hardware_settings_config.xml`. Also check that the port matches `config.yml`.

**Other devices can't open the leaderboard**
Allow Python in Windows Defender Firewall for private networks. Use the address shown in the console, not `localhost`.

The log files `tournament.log` and `timerecord.log` are in the program folder.

---

## Original time recorder

The original personal stage time recorder is still included and unchanged in use:

```powershell
py -m pip install -r requirements.txt
py -m timerecorder.timerecord
```

It records every finished stage to `dirtrally-laptimes.db` (see `resources/list-laptimes.bat` and `export-laptimes.bat`). For its features, heuristics for cars that can't be told apart and its limitations, see the [original project's README](https://github.com/soong-construction/dirt-rally-time-recorder#readme) and [docs/configuration.md](docs/configuration.md).

---

## Credits

This project is a fork of **[dirt-rally-time-recorder](https://github.com/soong-construction/dirt-rally-time-recorder)** by **Max Bechtold** (soong-construction), MIT License. All telemetry decoding, car and track recognition, and the car/track database come from that project. The tournament features are built on top of it.

The original project credits, which also apply here:

- [Slocan/timerecord](https://github.com/Slocan/timerecord): the initial version
- [Billiam/pygauge](https://github.com/Billiam/pygauge): the core code
- [ErlerPhilipp/dr2_logger](https://github.com/ErlerPhilipp/dr2_logger): DR2 UDP data recognition, and the reference for detecting paused telemetry used in tournament mode

EA SPORTS WRC support uses the game's own documented UDP telemetry, configured through the JSON files in `Documents\My Games\WRC\telemetry\`.

Third-party licenses are listed in [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt).

DiRT Rally 2.0 and EA SPORTS WRC are trademarks of their respective owners. This project is not affiliated with or endorsed by Codemasters, Electronic Arts or Nacon.

---

## Declaration of AI use

The tournament features of this fork were written with the help of an AI assistant: **Claude** by Anthropic, used through the Claude desktop app. This covers:

- the nickname prompt and game pausing
- results and DNF detection
- the tournament setup
- the web leaderboard, admin portal and backups
- the Python 3.12+ receiver and the EA SPORTS WRC support
- the tests and documentation, including this README

The project owner chose the features and rules, reviewed the changes, and tested them with DiRT Rally 2.0 on real hardware. The AI wrote the code from those instructions and checked it with automated tests and simulated telemetry.

The code from the original project is not AI-generated, apart from the small changes needed for tournament mode and Python 3.12+.

---

## License

MIT License: see [LICENSE](LICENSE). Copyright for the original work: Max Bechtold and the original authors listed there. The tournament additions are under the same license.