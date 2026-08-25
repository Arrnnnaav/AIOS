# Open Track demo video script

Target runtime: **4:45 maximum**. Rehearse the complete sequence once before
recording. Protect the live product segments; shorten explanation segments if
the rehearsal exceeds the budget. Record the refusal clip separately so it is
independently retakeable.

## Preflight

- Use the exact commit intended for submission and a clean worktree.
- Run the documented hermetic lane and save its result.
- Prewarm the local model:

  ```powershell
  ollama run qwen3:4b-instruct "Return only the word READY"
  ```

- Open a clean VS Code Welcome window, close Terminal, and prepare a harmless
  folder for the picker.
- Hide notifications and unrelated/private windows; keep the terminal text
  large enough to read in the recording.
- Do not splice a failed action into a successful result. If a post-recording
  product fix changes an affected segment, rerun its tests and rerecord it.

## Locked sequence and budget

| Time | Segment | Protected? |
|---|---|---|
| 0:00–0:25 | Specific problem: a new developer on day one does not know where a real software action lives. | Cuttable explanation |
| 0:25–0:50 | Product promise: state a goal, local AI selects a bounded intent, GhostCursor points, the human acts, application state verifies. It never clicks or types. | Cuttable explanation |
| 0:50–2:05 | **Live Open Folder:** show the natural-language goal, `SUPPORTED`, the trusted hint on real VS Code, the human folder selection, and `Tour complete.` | **Protected live demo** |
| 2:05–3:15 | **Live Ask/Open Terminal:** expand the vertical Ask panel, type `Open the integrated terminal in VS Code`, Submit, show the thinking/planner handoff and hint, press `Ctrl+\``, and show verified `Tour complete.` | **Protected live demo** |
| 3:15–3:40 | **Separately recorded refusal:** submit `Deploy this project to production`; show `UNSUPPORTED_GOAL` and that no tour launches. | **Protected safety proof** |
| 3:40–4:15 | Evidence: two 3/3 real-desktop workflow gates, 361-test hermetic lane, and only the participant observations actually collected under the published protocol. | Cuttable evidence narration |
| 4:15–4:45 | Honest close: two proven VS Code workflows; packs/installer/tray/web retrieval are designed or deferred, not claimed as built. | Cuttable close |

## Recording commands

Open Folder control run:

```powershell
py -3.12 -m ghostcursor.run `
  --goal "Open a folder in VS Code" `
  --target "Visual Studio Code" `
  --seconds 120
```

After that tour completes, use the visible Ask panel for Open Terminal so the
video contains the judge-facing “user types a goal → AI thinks → trusted hint
appears” moment.

Record the refusal in a separate take:

```powershell
py -3.12 -m ghostcursor.run `
  --goal "Deploy this project to production" `
  --target "Visual Studio Code" `
  --seconds 30
```

Expected invariant: no recipe and no tour launch. The exact non-launch status
must match the observed contract in `docs/evidence/never-fabricate-matrix.md`.

## Final review checklist

- Runtime is at or below 4:45.
- Goal text, planner status, hints, and `Tour complete.` are legible.
- At least one workflow is submitted through Ask, not only the CLI.
- The local-AI decision and deterministic safety boundary are both explained.
- The refusal clip proves behavior rather than merely showing a slide.
- Participant claims exactly match the filled evidence table and sample size.
- Repository URL and final video link open from a signed-out/private browser.
