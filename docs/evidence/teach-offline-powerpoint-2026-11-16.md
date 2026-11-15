# Offline Teach: a local model choosing controls, 16 Nov 2026

Gap found on 15 Nov: with everything kept on the computer, Teach could not
point at anything, because only Jev (a cloud model) chose controls. This
measures the local fallback on the same 21 PowerPoint steps as
`teach-replay-powerpoint-2026-11-15.md` (one Home-tab frame; 4 dev, 14 test,
3 adversarial; labels by the agent). No request left the computer and no
credit was spent.

## What was run

- Offline switch on in the replay process only, so Jev was blocked and the
  gateway's local chooser answered through Ollama on this PC.
- `qwen3:4b-instruct` (Orbyn's configured local model): about 974 s for the
  21 steps on this PC's CPU. `qwen2.5:7b-instruct`: about 193 s (it was
  already loaded).
- The local model sees a compact list (one line per control: type, name,
  screen area). The full view Jev gets did not fit its 4,096-token context.
- Answers are recorded in `.artifacts/teach-corpus/ppt-home-2026-11-15.local-cassette.json`
  and `.local7b-cassette.json` (ignored by git, on this PC).

## Result, through the real gate (floor 0.6, margin 0.2)

"Name check" keeps a local pick only when it is also the control whose name
best matches the step's words (rapidfuzz token-set ratio); otherwise no
pointer is shown. Rows computed by replaying the recorded answers, as printed:

```
lexical baseline         | dev: 1 shown / 0 wrong / 0 high-risk | test: 3 shown / 1 wrong / 0 high-risk | adversarial: 1 shown / 1 wrong / 1 high-risk
Jev (online)             | dev: 3 shown / 0 wrong / 0 high-risk | test: 12 shown / 0 wrong / 0 high-risk | adversarial: 1 shown / 1 wrong / 1 high-risk
qwen3:4b raw             | dev: 4 shown / 1 wrong / 0 high-risk | test: 11 shown / 3 wrong / 0 high-risk | adversarial: 1 shown / 1 wrong / 0 high-risk
qwen3:4b + name check    | dev: 2 shown / 0 wrong / 0 high-risk | test: 4 shown / 0 wrong / 0 high-risk | adversarial: 0 shown / 0 wrong / 0 high-risk
qwen2.5:7b raw           | dev: 3 shown / 1 wrong / 0 high-risk | test: 13 shown / 6 wrong / 0 high-risk | adversarial: 1 shown / 1 wrong / 1 high-risk
qwen2.5:7b + name check  | dev: 1 shown / 0 wrong / 0 high-risk | test: 3 shown / 0 wrong / 0 high-risk | adversarial: 1 shown / 1 wrong / 1 high-risk
```

## Reading it

- Raw, the local models are confidently wrong: about a quarter to a half of
  their pointers are wrong, each stated at 0.99, so the gate cannot filter
  them. The 7b model is worse than the 4b one here.
- With the name check, `qwen3:4b-instruct` showed 6 pointers and none was
  wrong; it points far less often than Jev (15 shown, 0 wrong). Orbyn ships
  this: offline, the 4b model with the name check.
- The name check was chosen after seeing these same answers, on this same
  corpus. It is tuned on this test set, not validated on fresh screens.
- The fallback runs only when the person or the organisation keeps
  everything on this computer. A Jev outage online gives no pointer, as
  before; it never switches quietly to the weaker model.

## Not shown

- One application, one screen, 21 steps: far too few for a rate.
- No live offline Teach session was run (replay of a captured frame only).
