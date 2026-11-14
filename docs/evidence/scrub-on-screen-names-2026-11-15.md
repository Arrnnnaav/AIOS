# Default scrub over recorded on-screen names, 15 Nov 2026

Question: with hiding on (the default), how often does the scrub change the
names of on-screen controls that Teach and Jev use to pick a target? Measured
offline over every JSON/JSONL record under `.artifacts/` and `docs/evidence/`
(recorded PowerPoint and manager runs, Sept to Nov 2026). No model was called.

Script: the session scratchpad `measure_names.py` (reads the fields `name`,
`label`, `title`, `text`, `uia_name`, `control_name`, 1 to 200 characters).
The same logic is checked in as `tools/measure_scrub_names.py`; its run on
the tree after the review fixes is at the end of this file.

Before the fix (tree d0e39dd plus the keep-secrets switch). First line as printed; on the second line the list of four examples is shortened here to one, marked `...`:

```
files 3058  distinct names 239  changed by default scrub 9 (3.77%)
KEY 9 ['[Sources]
- Repository: docs/pitch/ghostcursor-inv', ...]
```

Every change was one false positive: the KEY pattern took any word starting
with `gho` (here `ghostcursor-investor-deck-content`) for a GitHub token.

After tightening KEY to each provider's real token shape, as printed:

```
files read: 3058; distinct on-screen names (fields name/label/title/text/uia_name/control_name, 1-200 chars): 239
changed by the default scrub: 0 (0.00%); by category: {}
```

Limits: 239 names from one application family (PowerPoint and the Orbyn
manager) is a small, narrow sample. It says nothing about dates read as
phone numbers on other screens, and it does not measure whether Jev's
choices change; that needs a live run.

## Re-run with tools/measure_scrub_names.py

After the key pattern also took Groq, NVIDIA, Tavily, Hugging Face, Google
and AWS temporary key shapes (tree after cbaaca3), as printed:

```
files read: 3058; distinct on-screen names (fields name/label/title/text/uia_name/control_name, 1-200 chars): 239
changed by the default scrub: 0 (0.00%); by category: {}
```
