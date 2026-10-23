@echo off
cd /d "%~dp0"
rem PyYAML has no prebuilt Windows wheel for the newest Python versions.
rem Skip its optional C speed-up so no C++ compiler is needed.
set PYYAML_FORCE_LIBYAML=0
py -m pip install -r requirements-tournament.txt
pause
