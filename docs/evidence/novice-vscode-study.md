# Novice VS Code usability evidence

Status: amended protocol locked; recruitment deliberately deferred until
eligible participant contacts are available; participant results not yet
collected.

This is a small, informal usability check—not a controlled experiment. Its
purpose is to show whether GhostCursor helps a novice find and complete one
specific real task. It must not be described as statistically representative.

## Participant threshold and claim rule

- Preferred: 3 participants who do not routinely use VS Code. This is the
  complete planned evidence tier, not evidence of general effectiveness.
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

Invitation status: **deliberately deferred**. The message and protocol are
ready, but recruitment will resume only when eligible participant contacts or
an authorized communication channel are available. This is an intentional
dependency decision, not evidence that invitations were sent.

## Recruitment tracking

- Invitation date/time: deferred—contacts unavailable
- Number of eligible people invited: 0
- Number confirmed: 0
- Confirmed session slots: none

Update counts and slots only. Keep names, handles, phone numbers, email
addresses, and message screenshots outside the repository.

## Setup

1. Use a normal interactive Windows desktop with VS Code on its Welcome page.
2. Close the integrated terminal and any native file picker.
3. Prepare two harmless, empty folders with neutral names (`study-a` and
   `study-b`). Randomize which folder is used first.
4. Use the same display scaling and window layout for both attempts.
5. Explain that GhostCursor points and verifies but never clicks or types for
   the participant.
6. Record a pre-study confidence rating before the baseline attempt: “How
   confident are you that you could open a project folder in VS Code?” from
   1 (not confident) to 5 (very confident).

## Measurement contract

- Both attempts have the same 120-second limit.
- `first correct action` is the participant activating VS Code's
  `Open Folder...` command.
- `verified completion` means the selected neutral folder is active as the VS
  Code workspace. The observer checks for the normalized folder name in the
  VS Code workspace/window title; exact title equality is not required.
- For the guided attempt, `Tour complete.` must also be printed. A hint or an
  opened picker alone is not completion.
- A `wrong turn` is an unrelated control or menu activated before the first
  correct action. Record the count and a short neutral description.
- A `help request` is any request for navigation or task guidance. Record the
  count. Do not answer it during the timed attempt beyond the fixed protocol
  instruction.
- Record both time to first correct action and time to verified completion.
  A value not reached by 120 seconds is recorded as `timeout`, not estimated.

## Baseline attempt

Prompt: **“Open this project folder in VS Code.”**

- Start the timer when the prompt is read.
- Give no navigation hints for up to 120 seconds.
- Record time to the first correct action, wrong turns, help requests, whether
  verified completion occurred, and total time to verified completion.
- If the participant is stuck at 120 seconds, record a timeout; do not coach the
  baseline attempt.
- Reset to a clean Welcome window before the guided attempt.

## GhostCursor-guided attempt

1. Start GhostCursor against the clean VS Code window.
2. Have the participant use Ask and submit `Open a folder in VS Code`.
3. Start the timer when Submit is pressed.
4. Do not coach beyond “follow the on-screen guide.”
5. Record planner status, whether the correct hint appeared, time to the first
   correct action, wrong turns, help requests, whether verified completion
   occurred, and total time to verified completion plus `Tour complete.`.
6. After the guided attempt, record a post-study confidence rating using the
   same 1–5 question and scale as the pre-study rating.

The two attempts have an unavoidable order/learning effect. Report individual
observations and that limitation; do not claim the timing difference was
caused solely by GhostCursor.

## Results table

Fill this table during each session. Do not reconstruct it later from memory.

| Participant | Routine VS Code user? | Pre confidence | Baseline first-action / completion | Baseline wrong turns | Baseline help requests | Baseline complete | Guided planner status | Guided first-action / completion | Guided wrong turns | Guided help requests | Guided complete | Post confidence | Notes |
|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---|
| P1 |  |  |  |  |  |  |  |  |  |  |  |  |  |
| P2 |  |  |  |  |  |  |  |  |  |  |  |  |  |
| P3 |  |  |  |  |  |  |  |  |  |  |  |  |  |

## Reporting rules

- Report every collected participant row, including failures and timeouts.
- Prefer individual values over averages for this small sample.
- If at least two sessions are completed, report medians for first-action and
  completion times alongside the raw values, plus completion counts, total
  wrong turns, total help requests, and each participant's confidence change.
- State the final sample size and disclose the unavoidable baseline-first
  learning/order effect. Do not use statistical-significance language.
- Keep reliability evidence (3/3 engineering runs) separate from participant
  value evidence; they answer different questions.
- The strongest permitted conclusion is: “In this informal `n=N` check, these
  novice participants reached the correct action/completion with the guide,
  with the recorded timings and confidence ratings shown above.”
- If a run fails, retain it in the table and explain the observed failure.
