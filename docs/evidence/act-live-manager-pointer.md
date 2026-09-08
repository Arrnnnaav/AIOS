# Live manager-owned PowerPoint pointer proof

**Date:** 8 September 2026  
**Repository commit:** `27413857333e72ff4652d5fd59b9e7d5aad53529`  
**Application:** Microsoft PowerPoint `16.0.20326.20132`  
**Target:** `powerpnt.exe`, hwnd `264482`, pid `29768`  
**Intent:** `ADD_SLIDE`  
**Plan:** `add-slide-uia-v1`, one node

## Result

The controlled presentation began with one blank slide and ended with two.
The production manager-owned path returned:

```text
action_started   n001-new-slide  1/1  authorized action started
action_completed n001-new-slide  1/1  the declared postcondition was independently observed
completed        -               1/1  all actions verified

result: completed
completed_node_ids: [n001-new-slide]
elapsed: 5.672 s
slide count: 1 -> 2
```

The run used `prepare_act_goal()` followed by the real `_ActWorker` and
`_create_manager_act_presentation()` factory. The overlay, bridge, and bound
presentation surface were created on the main/UI thread; `_ActWorker` invoked
`execute_act_proposal()` on its worker thread. No diagnostic node executor,
stubbed approval, injected store, or caller-assembled presentation surface was
used.

Dispatch could occur only after the trusted manager-owned surface returned
the request-bound `geometry_started` and `presentation_completed` receipts.
The signed generic UIA adapter then invoked PowerPoint's New Slide control, and
the separate signed live-state verifier confirmed the declared
`slide.count.increased_by_one` postcondition against the pre-action baseline.
The real OS cursor was not moved and no mouse or keyboard input was
synthesized.

## Bound production authority

```text
catalog generation: 4
active index: 9b131a71c25283fb652de2675fad3b0e746993bea204e3004237c6378f9a605b
manifest: c048e47b2ec066ae23aa62d1aa18471a1f0118c47a1320a086859731cd63925e
activation: 234104e6e0f3fce90c27fd58528490e798af8faef661c156fbb3a37f6c991591
intent: b977a9e62a2e9810e479bf137c92edffdec9578984399780543642856be3caa3
plan: 86130fc9f8ec891febfe12bbf44b07ca2040a2c0392200a0de7ae84622a52532
object adapter: c8fd3ccea3fe77f431ac3229554f529bb2ff51a9e7f6194840fc379b31f66912
UIA adapter: 5c20779cb895b798b549b1e720b6df56f618761083c81c749dc1f075be162ae6
live verifier: 2af9da2a732bc3d0bad2073452a5dcedd58828c38c27ed3e4b42806628b50bb1
graph: 38cd88be632d4aed415f341ba9534a56b5f3727e9826c15dcb912871350b9d3d
validation: d4b35437d53b1b3d21caba62785cff54e2c42ae69deb6248026e130b1c9c14fc
```

## Failed-safe precursor

An earlier attempt added an in-process screenshot loop while the manager UI
thread was servicing the cue. It returned `render_timeout`; the action was not
dispatched and the slide count remained `1 -> 1`. The capture also showed that
PowerPoint was visible but obscured by another foreground window. The clean
proof removed that instrumentation and activated PowerPoint through its own
COM window before starting Act. No receipt deadline was enlarged or bypassed.

This is evidence that instrumentation sharing the UI process can perturb the
deadline it is trying to observe. Raw frames from that failed diagnostic are
not retained because they captured unrelated desktop content.

## Scope and remaining gates

This is one successful live integration proof, not the final 3/3 acceptance
campaign. It proves the real production proposal/approval path, manager-owned
presentation bridge, signed UIA dispatch, and independent live verification
work together for one PowerPoint action. It does not prove semantic stages,
the 255-node staged deck, repeated UIA acceptance, release activation, or a
pixel-perfect retained screenshot. A fresh D032 review of this evidence and
the exact path remains required before the roadmap item is closed.
