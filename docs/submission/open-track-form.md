# GhostCursor Open Track Submission Copy

This copy is locked for the submission form. Add only the final video URL and
measured evidence where the form requires them; do not rewrite these answers
under deadline pressure.

## Project title

GhostCursor — A Local AI Guide for Learning Unfamiliar Software

## Project objective

New developers lose time switching between documentation, chat assistants,
and unfamiliar interfaces. GhostCursor accepts a natural-language goal,
observes live VS Code, uses bounded local AI to select a trusted next step,
points to it in place, lets the user act, and verifies that the application
reached the expected state. It never moves the mouse, sends keyboard input, or
executes model-generated instructions.

## GitHub repository

https://github.com/Arrnnnaav/AIOS

## Build challenges and technical obstacles

The hardest challenge was reliably understanding live Windows applications
without freezing the guidance interface or trusting stale observations.
Electron UI Automation calls could stall, so perception was isolated in a
worker with bounded health monitoring and one controlled restart. When
accessibility information was incomplete, GhostCursor used DPI-correct window
capture and Windows OCR while visibly lowering hint confidence. Local-model
output was constrained to registered intents and observed, recipe-approved
controls; model-generated paths, coordinates, and actions are never
executable. We also implemented wrong-action detection, focus-safe keyboard
arbitration, trusted recipe containment, and application-state verification so
the system advances only when the requested outcome is genuinely observed.
