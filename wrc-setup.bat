@echo off
cd /d "%~dp0"
echo Setting up EA SPORTS WRC telemetry. Close the game first.
python -m timerecorder.wrcSetup %*
pause
