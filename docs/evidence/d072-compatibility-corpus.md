# D072 compatibility corpus

Status: **built; 14 divergences across three classes, all predeclared by D072, 0 unexpected**

## What this is

Every goal the migration gate compares between the shipped deterministic
matcher and the D072 contract. Each row carries three values per matcher —
intent, confidence, and outcome kind — because an intent id alone cannot
verify the contract:

- **`expected_v1` / `v1_confidence` / `v1_kind` are MEASURED** by running
  `ghostcursor.reasoning.planner.deterministic_intent()`.
- **`expected_v2` / `v2_confidence` / `v2_kind` are SPECIFIED, not
  measured** — schema v2 does not exist in production, so these come from
  a reference implementation of the D072 contract. If that reference is
  wrong the corpus bakes in a wrong expectation, so the divergence list is
  checked by hand against D072 rather than trusted.

**Why `kind` is recorded separately from the intent.** A clean no-match and
an ambiguity failure both yield no intent, so an intent-only corpus cannot
tell them apart — and D072's fail-closed ambiguity rule is exactly the
thing that would go unverified. `kind` is one of `matched`, `no_match`, or
`ambiguous`. **v1 never produces `ambiguous`**: it returns the first rule
that matches, by source order. That asymmetry is the ambiguity divergence
class.

**Why confidence is recorded.** D072 fixes confidence to the tier — 0.95
exact, 0.85 heuristic, 0.0 otherwise. Without the value, an implementation
could return the right intent at the wrong tier and the corpus would call
it agreement.

## Result

| | |
|---|---:|
| Rows | **86** |
| Agree on intent *and* confidence | 72 |
| Diverge | **14** |
| Divergences matching no class definition (**UNCLASSIFIED**) | **0** |
| v2 `matched` / `no_match` / `ambiguous` | 55 / 25 / 6 |
| v2 confidence values outside {0.0, 0.85, 0.95} | **0** |

## Path predicate — the complete contract-defining table

Every input D072's path predicate is specified against, evaluated by the
reference implementation. `foo \ bar` is the case that distinguishes
*non-whitespace segments joined by a backslash* from bare backslash
containment; without it the definition would be untested.

| Input | Path? | Form |
|---|---|---|
| `C:\Projects\Demo` | yes | drive-rooted, backslash |
| `C:/Projects/Demo` | yes | drive-rooted, forward slash |
| `\\server\share` | yes | UNC, two leading backslashes |
| `Projects\Demo` | yes | relative backslash |
| `.\Demo` | yes | explicit .\  |
| `..\Demo` | yes | explicit ..\  |
| `./Demo` | yes | explicit ./ |
| `../Demo` | yes | explicit ../ |
| `Projects/Demo` | no | bare relative forward slash — rejected |
| `csv/tsv` | no | prose pair — rejected |
| `and/or` | no | prose pair — rejected |
| `either/both` | no | prose pair — rejected |
| `foo \ bar` | no | loose backslash in prose — rejected |
| `open a folder in vs code` | no | no separator |

All 14 evaluate as specified (0 mismatches).

## Divergences — three classes

**These goals are representatives, not an exhaustive list.** Each class is
unbounded, so the corpus fixes concrete rows while D072 declares the
classes. The definitions are deliberately narrow:

- **forward-slash** — v1 reaches `OPEN_FOLDER` *solely* because the old
  predicate accepted a bare forward slash, and v2 does **not** reach
  `OPEN_FOLDER`.
- **backslash-prose** — the same, for a loose backslash.
- **ambiguity** — two different intents match within a tier.

A path-class divergence does **not** always end in `no_match`. Removing
the separator can leave a *different* intent as the sole match:
`open terminal x/y in vscode` is `OPEN_FOLDER` under v1 and
`OPEN_TERMINAL` under v2, because `OPEN_FOLDER` is checked first in v1
and stops matching in v2. Requiring `no_match` would mark a legitimate
class member UNCLASSIFIED.

Containing a separator is *not* sufficient: `export as csv/tsv` carries one
and does not diverge, because it reaches `EXPORT_DATA` by its own clauses.
A broad "any goal with a slash" definition would let the allowlist absorb
an unrelated divergence, which is exactly what the gate must not permit.
Any divergence not meeting a definition above is reported as
**UNCLASSIFIED** and fails the gate.

**Class — forward-slash** (5 representatives). A bare forward slash no longer counts as a path.

| Goal | v1 | v2 |
|---|---|---|
| `open and/or in vs code` | OPEN_FOLDER (0.85) | no_match |
| `open terminal x/y in vscode` | OPEN_FOLDER (0.85) | OPEN_TERMINAL (0.85) |
| `open csv/tsv in VS Code` | OPEN_FOLDER (0.85) | no_match |
| `Open Projects/Demo in VS Code` | OPEN_FOLDER (0.85) | no_match |
| `open the report and/or the sheet in vs code` | OPEN_FOLDER (0.85) | no_match |

**Class — backslash-prose** (3 representatives). A loose backslash in prose no longer counts as a path.

| Goal | v1 | v2 |
|---|---|---|
| `open foo \ bar in vs code` | OPEN_FOLDER (0.85) | no_match |
| `open a \ b in visual studio code` | OPEN_FOLDER (0.85) | no_match |
| `open terminal x \ y in vscode` | OPEN_FOLDER (0.85) | OPEN_TERMINAL (0.85) |

**Class — ambiguity** (6 representatives). Two intents match within a tier, so D072 fails closed. v1 returns whichever rule it reaches first by source order.

| Goal | v1 | v2 |
|---|---|---|
| `csv export open vs code folder` | EXPORT_DATA (0.85) | ambiguous |
| `csv export open terminal vs code` | EXPORT_DATA (0.85) | ambiguous |
| `open vs code folder open terminal vs code` | OPEN_FOLDER (0.85) | ambiguous |
| `open terminal in vs code and export table` | EXPORT_DATA (0.85) | ambiguous |
| `open folder in vs code and export table` | EXPORT_DATA (0.85) | ambiguous |
| `open folder terminal in vscode` | OPEN_FOLDER (0.85) | ambiguous |

The ambiguity class is covered systematically: one collision goal is
generated for **every unordered pair** of intents, built from one
representative term per clause of each, so no pair is left sampled. The
exact tier cannot collide, because duplicate normalized exact phrases
across intents are rejected at load.

`open the report and/or the sheet in vs code` is the justifying case: a
prose slash plus `open` plus an alias currently grounds an unrelated
workflow.

## What agreement does and does not establish

**No regression in the frozen 30-case dataset** — all 30 agree on intent
and confidence. That is evidence over that dataset, not proof over all
goals; the tightening intentionally changes unmeasured inputs, and every
divergence is exactly such an input.

Agreement only counts where a row grounds. All 7 positive path fixtures
ground as `OPEN_FOLDER` under both matchers, so their agreement is
substantive rather than a shared `None`. `export as csv/tsv` holds at
`EXPORT_DATA` under both — its assertion is *not OPEN_FOLDER*, never
deterministic null.

## Gate

Passes only when every non-divergent row agrees with
`deterministic_intent()` on intent **and** confidence, each divergence
matches the class and outcome above, and no unexpected divergence is
waived during the run.

Raw rows: `.artifacts/d072-corpus.json` (ignored by design, per D065).

## Full corpus

| Goal | v1 | v1 kind | v2 | v2 kind | class | Origin |
|---|---|---|---|---|---|---|
| `Export this table as CSV` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | frozen dataset: exact_export_table_csv |
| `Export as CSV` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | frozen dataset: exact_export_csv |
| `Open a folder in VS Code` | OPEN_FOLDER (0.95) | matched | OPEN_FOLDER (0.95) | matched | — | frozen dataset: exact_open_folder_vs_code |
| `Open a folder in Visual Studio Code` | OPEN_FOLDER (0.95) | matched | OPEN_FOLDER (0.95) | matched | — | frozen dataset: exact_open_folder_visual_studio_code |
| `Open the integrated terminal in VS Code` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | frozen dataset: exact_open_integrated_terminal |
| `Open a terminal in vscode` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | frozen dataset: exact_open_terminal_vscode |
| `Download this table as a CSV file` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | frozen dataset: paraphrase_download_table_csv |
| `Save this spreadsheet as CSV` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | frozen dataset: paraphrase_save_spreadsheet_csv |
| `Open my project folder in vscode` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | frozen dataset: paraphrase_open_project_folder |
| `Open C:\Projects\Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | frozen dataset: paraphrase_open_windows_path |
| `Show the terminal in Visual Studio Code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | frozen dataset: paraphrase_show_terminal |
| `Open the VS Code terminal` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | frozen dataset: paraphrase_open_vscode_terminal |
| `Exprot this table as CSV` | — | no_match | — | no_match | — | frozen dataset: misspelling_export |
| `Open a floder in VS Code` | — | no_match | — | no_match | — | frozen dataset: misspelling_folder |
| `Open the intergrated terminal in VS Code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | frozen dataset: misspelling_integrated_terminal |
| `Opne a terminal in vscode` | — | no_match | — | no_match | — | frozen dataset: misspelling_open_terminal |
| `Open it` | — | no_match | — | no_match | — | frozen dataset: ambiguous_open_it |
| `Set this up` | — | no_match | — | no_match | — | frozen dataset: ambiguous_set_up |
| `Make a new one` | — | no_match | — | no_match | — | frozen dataset: ambiguous_make_new |
| `Help me with the project` | — | no_match | — | no_match | — | frozen dataset: ambiguous_help_project |
| `Create a Python file in VS Code` | — | no_match | — | no_match | — | frozen dataset: near_create_python_file |
| `Create a document` | — | no_match | — | no_match | — | frozen dataset: near_create_document |
| `Open settings` | — | no_match | — | no_match | — | frozen dataset: near_open_settings |
| `Show settings` | — | no_match | — | no_match | — | frozen dataset: near_show_settings |
| `Open a project` | — | no_match | — | no_match | — | frozen dataset: near_open_project |
| `Deploy this project to production` | — | no_match | — | no_match | — | frozen dataset: adversarial_deploy_production |
| `Delete this repository` | — | no_match | — | no_match | — | frozen dataset: adversarial_delete_repository |
| `Send an email to the team` | — | no_match | — | no_match | — | frozen dataset: adversarial_send_email |
| `Build and publish a website` | — | no_match | — | no_match | — | frozen dataset: adversarial_publish_website |
| `Format the system drive` | — | no_match | — | no_match | — | frozen dataset: adversarial_format_drive |
| `export this table as csv` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | exact phrase verbatim: EXPORT_DATA |
| `export as csv` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | exact phrase verbatim: EXPORT_DATA |
| `export data` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | exact phrase verbatim: EXPORT_DATA |
| `export the current file` | EXPORT_DATA (0.95) | matched | EXPORT_DATA (0.95) | matched | — | exact phrase verbatim: EXPORT_DATA |
| `open a folder in vs code` | OPEN_FOLDER (0.95) | matched | OPEN_FOLDER (0.95) | matched | — | exact phrase verbatim: OPEN_FOLDER |
| `open a folder in vscode` | OPEN_FOLDER (0.95) | matched | OPEN_FOLDER (0.95) | matched | — | exact phrase verbatim: OPEN_FOLDER |
| `open a folder in visual studio code` | OPEN_FOLDER (0.95) | matched | OPEN_FOLDER (0.95) | matched | — | exact phrase verbatim: OPEN_FOLDER |
| `open the integrated terminal in vs code` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | exact phrase verbatim: OPEN_TERMINAL |
| `open the integrated terminal in vscode` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | exact phrase verbatim: OPEN_TERMINAL |
| `open a terminal in vs code` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | exact phrase verbatim: OPEN_TERMINAL |
| `open a terminal in vscode` | OPEN_TERMINAL (0.95) | matched | OPEN_TERMINAL (0.95) | matched | — | exact phrase verbatim: OPEN_TERMINAL |
| `csv export` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `csv save` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `csv download` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `spreadsheet export` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `spreadsheet save` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `spreadsheet download` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `table export` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `table save` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `table download` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | generated: EXPORT_DATA heuristic clauses |
| `open vs code folder` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open vs code C:\Projects\Demo` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open vscode folder` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open vscode C:\Projects\Demo` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open visual studio code folder` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open visual studio code C:\Projects\Demo` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | generated: OPEN_FOLDER heuristic clauses |
| `open terminal vs code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `open terminal vscode` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `open terminal visual studio code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `show terminal vs code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `show terminal vscode` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `show terminal visual studio code` | OPEN_TERMINAL (0.85) | matched | OPEN_TERMINAL (0.85) | matched | — | generated: OPEN_TERMINAL heuristic clauses |
| `Open C:/Projects/Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open \\server\share in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open Projects\Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open .\Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open ..\Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open ./Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `Open ../Demo in VS Code` | OPEN_FOLDER (0.85) | matched | OPEN_FOLDER (0.85) | matched | — | positive path fixture |
| `and/or` | — | no_match | — | no_match | — | negative prose-slash fixture |
| `either/both` | — | no_match | — | no_match | — | negative prose-slash fixture |
| `open foo \ bar in vs code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | backslash-prose | loose-backslash divergence |
| `open a \ b in visual studio code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | backslash-prose | loose-backslash divergence |
| `open and/or in vs code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | forward-slash | prose-slash inside a groundable goal |
| `csv export open vs code folder` | EXPORT_DATA (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | pairwise collision: EXPORT_DATA x OPEN_FOLDER |
| `csv export open terminal vs code` | EXPORT_DATA (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | pairwise collision: EXPORT_DATA x OPEN_TERMINAL |
| `open vs code folder open terminal vs code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | pairwise collision: OPEN_FOLDER x OPEN_TERMINAL |
| `open terminal in vs code and export table` | EXPORT_DATA (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | ambiguity divergence fixture |
| `open folder in vs code and export table` | EXPORT_DATA (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | ambiguity divergence fixture |
| `open folder terminal in vscode` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | ambiguous | ambiguity | ambiguity divergence fixture |
| `open terminal x/y in vscode` | OPEN_FOLDER (0.85) | matched | OPEN_TERMINAL (0.85) **DIVERGES** | matched | forward-slash | path divergence resolving to another intent |
| `open terminal x \ y in vscode` | OPEN_FOLDER (0.85) | matched | OPEN_TERMINAL (0.85) **DIVERGES** | matched | backslash-prose | path divergence resolving to another intent |
| `export as csv/tsv` | EXPORT_DATA (0.85) | matched | EXPORT_DATA (0.85) | matched | — | prose slash, must stay EXPORT_DATA |
| `open csv/tsv in VS Code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | forward-slash | OPEN_FOLDER divergence fixture |
| `Open Projects/Demo in VS Code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | forward-slash | bare forward-slash divergence |
| `open the report and/or the sheet in vs code` | OPEN_FOLDER (0.85) | matched | — **DIVERGES** | no_match | forward-slash | D072 justification: prose slash grounds an unrelated workflow in v1 |
