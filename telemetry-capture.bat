@echo off
cd /d "%~dp0"
echo Recording telemetry. Pause, retire, restart and finish a stage, then press Ctrl+C.
python -m timerecorder.telemetryCapture
pause
