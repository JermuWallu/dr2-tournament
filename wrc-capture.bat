@echo off
cd /d "%~dp0"
echo Recording EA WRC telemetry. Drive a stage, then press Ctrl+C.
python -m timerecorder.wrcCapture
pause
