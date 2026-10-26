@echo off
REM Orbyn desktop app -- double-click to open the compact workspace island.
REM Local UI uses token-protected 127.0.0.1; chosen providers/connectors may send data out.
py -3.12 "%~dp0tools\orbyn_app.py" %*
