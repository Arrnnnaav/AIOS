# Aside computer-use helper: decompiled input-yield (29 October 2026)

Follows `docs/evidence/aside-rea-2026-10-29.md` (strings only). Target:
`AsideComputerUse.exe` from Aside 1.0.1022.1, copied to a scratch folder,
SHA-256 `1f27bfb9749f3d168614101b71fcb4ba809b72190fbd8dd7a5880238a195c61e`.
Analysed with REA (Ghidra 12.1.4, default auto-analysis); nothing was run.
Function names below are Ghidra's; the PDB was not loaded.

## How Aside decides "the user is using the mouse or keyboard"

- `FUN_1400e0000` stores `GetTickCount64()` in a global (`DAT_1403f64c8`)
  each time it is called, and for mouse events notes which top-level window
  was under the pointer.
- The low-level mouse hook `FUN_140042ae0` calls it for every event whose
  `dwExtraInfo` is not `0x45435553` (ASCII "SUCE", the signature Aside stamps
  on its own `SendInput` events). It does not test `LLMHF_INJECTED`, and
  mouse moves (`WM_MOUSEMOVE`) count. It also records click and drag events
  for its own activity log.
- Before acting, `FUN_1400fcc30` treats the user as busy while the stored time
  is under 2,000 ms old or any virtual key 1-255 reads as held
  (`GetAsyncKeyState` high bit). It polls every 20 ms, checking its stop flag
  each time, and gives up after 20 s with "The user is using the mouse or
  keyboard, so nothing was sent".

## What Orbyn took

- Every event Orbyn sends carries `dwExtraInfo = 0x4E42524F` ("ORBN") so a
  hook or audit can tell Orbyn's input from the user's.
- Before a step, Orbyn waits while any key or mouse button is held, for at
  most 0.4 s (inside D020's 0.5 s Stop), then lets Teach retry on its next
  tick. On the owner's machine no key read as held in 30 samples over 3 s
  (`GetLastInputInfo`, by contrast, never passed 0.25 s idle; see FOLLOWUPS).

## Not taken

- The low-level hook and its 2 s recent-input window. A Python callback on
  every mouse move risks system-wide pointer lag, and Windows silently
  removes a low-level hook whose callback exceeds `LowLevelHooksTimeout`. It
  would need a native helper.
