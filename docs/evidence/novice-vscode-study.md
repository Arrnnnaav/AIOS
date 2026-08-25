# Novice VS Code usability evidence

Status: protocol ready; participant results not yet collected.

This is a small, informal usability check—not a controlled experiment. Its
purpose is to show whether GhostCursor helps a novice find and complete one
specific real task. It must not be described as statistically representative.

## Participant threshold and claim rule

- Preferred: 3 participants who do not routinely use VS Code.
- Acceptable fallback: 2 participants, with `n=2` disclosed everywhere.
- Fewer than 2: publish engineering/reliability evidence only and make no
  participant-value claim.
- Use participant labels (`P1`, `P2`, `P3`), not names or contact details.
- Obtain permission before screen or voice recording. Do not record private
  folders, account details, or unrelated desktop content.

## Recruitment message

> I am testing a Windows accessibility-style guide for people who are new to
> VS Code. The session takes about 15 minutes. You will try one simple task
> once without guidance and once with GhostCursor; I will record task timing
> and a short confidence rating, not personal data. Could you join one of
> these IST slots: 27 August 18:00, 28 August 18:00, or 29 August 12:00?

Sending this message is intentionally outside the repository workflow. Record
only that invitations were sent and the number of confirmed participants; do
not put recipients' identities in Git.

## Setup

1. Use a normal interactive Windows desktop with VS Code on its Welcome page.
2. Close the integrated terminal and any native file picker.
3. Prepare two harmless, empty folders with neutral names (`study-a` and
   `study-b`). Randomize which folder is used first.
4. Use the same display scaling and window layout for both attempts.
5. Explain that GhostCursor points and verifies but never clicks or types for
   the participant.

## Baseline attempt

Prompt: **“Open this project folder in VS Code.”**

- Start the timer when the prompt is read.
- Give no navigation hints for up to 60 seconds.
- Record time to the first correct VS Code action (`Open Folder...`), wrong
  controls/menus opened, whether the folder opened, total time, and confidence
  from 1 (not confident) to 5 (very confident).
- If the participant is stuck at 60 seconds, record a timeout; do not coach the
  baseline attempt.
- Reset to a clean Welcome window before the guided attempt.

## GhostCursor-guided attempt

1. Start GhostCursor against the clean VS Code window.
2. Have the participant use Ask and submit `Open a folder in VS Code`.
3. Start the timer when Submit is pressed.
4. Do not coach beyond “follow the on-screen guide.”
5. Record planner status, whether the correct hint appeared, time to the first
   correct action, wrong controls/menus opened, total time to `Tour complete.`,
   and the same 1–5 confidence rating.

The two attempts have an unavoidable order/learning effect. Report individual
observations and that limitation; do not claim the timing difference was
caused solely by GhostCursor.

## Results table

Fill this table during each session. Do not reconstruct it later from memory.

| Participant | Routine VS Code user? | Baseline first-action / total | Baseline wrong actions | Baseline complete | Baseline confidence | Guided planner status | Guided first-action / total | Guided wrong actions | Guided complete | Guided confidence | Notes |
|---|---|---:|---:|---|---:|---|---:|---:|---|---:|---|
| P1 |  |  |  |  |  |  |  |  |  |  |  |
| P2 |  |  |  |  |  |  |  |  |  |  |  |
| P3 |  |  |  |  |  |  |  |  |  |  |  |

## Reporting rules

- Report every collected participant row, including failures and timeouts.
- Prefer individual values over averages for this small sample.
- Keep reliability evidence (3/3 engineering runs) separate from participant
  value evidence; they answer different questions.
- The strongest permitted conclusion is: “In this informal `n=N` check, these
  novice participants reached the correct action/completion with the guide,
  with the recorded timings and confidence ratings shown above.”
- If a run fails, retain it in the table and explain the observed failure.
