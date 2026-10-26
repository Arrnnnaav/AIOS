@echo off
REM Orbyn desktop app -- double-click to open the compact workspace island.
REM Runs locally on 127.0.0.1 behind a per-launch token; nothing leaves the box.
py -3.12 "%~dp0tools\orbyn_app.py" %*
