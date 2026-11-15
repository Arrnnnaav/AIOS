# Installing Orbyn on a computer with no internet

For organisations whose machines never connect to the internet (YC Winter 2027
"AI for the Air-Gapped Economy"). Everything below is copied in by hand; the
offline computer downloads nothing.

## On a connected computer, collect

1. The Orbyn release zip, `Orbyn-<version>-windows-x64-unsigned.zip`, from
   https://github.com/Arrnnnaav/AIOS/releases (check its SHA-256 against the
   release notes).
2. The Ollama installer for Windows, from https://ollama.com/download.
3. The local model: run `ollama pull qwen3:4b-instruct`, then copy the folder
   `%USERPROFILE%\.ollama\models` (about 2.5 GB).
4. Optional, for voice: run Orbyn once with voice on so the Whisper model is
   cached, then copy `%USERPROFILE%\.cache\huggingface\hub`.

## On the offline computer

1. Install Ollama from the installer. Copy the `models` folder into
   `%USERPROFILE%\.ollama\models`. Check with `ollama list`.
2. Unzip Orbyn and run `Orbyn\Orbyn.exe`.
3. Keep everything on the computer, either way:
   - for one person: Brain → Setup → offline → On;
   - for the organisation: Group Policy (templates in `tools/policy/`),
     *What may leave this PC* = Local only (`MaxEgress` = 0).
4. Optional voice: copy the Whisper cache into
   `%USERPROFILE%\.cache\huggingface\hub`. Offline, Orbyn only loads weights
   already present and never downloads them.

## What works offline

- Chat, planning and answers from the local model (Ollama).
- Teach: the local model chooses which on-screen control to point at when Jev
  is unavailable, through the same safety gate. It is markedly weaker than Jev
  and points less often; see `docs/evidence/teach-offline-powerpoint-2026-11-16.md`.
- Act through the signed PowerPoint plans (no model involved).
- Personal and Company Brain (encrypted on disk), skills and test-case exports,
  the audit record.

## What does not

- Research, Ask a link, GitHub, calendar, mail, update checks, ChatGPT
  sign-in, crash reports and agent access: all blocked while offline.
- Jev (cloud) and every cloud model.
- Team folder publish and sync still write to the folder your organisation
  configured; point it at a local network share, or leave it unset.
