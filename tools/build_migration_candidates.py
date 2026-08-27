"""Author the three schema-v2 migration candidates as quarantined artifacts.

The v1 recipes are the specification. This script does not invent behaviour: it
re-expresses what `ghostcursor/packs/recipes/` already certifies in the v2
schema, and `tests/test_migrated_candidates.py` is what checks the
re-expression against the originals. Migration changes representation, not
selectors, title behaviour, step identity, provenance, wrong-action surface,
OCR policy, or verification meaning.

Two things it is careful about:

* **Canonical bytes.** UTF-8, LF, no BOM, sorted keys, one trailing newline.
  The digest is over exactly the bytes written, and the filename carries only
  a readability fragment of it -- the full digest is recorded separately, in
  `digests.json`, because a filename is not a binding and nothing may parse
  one to decide what it loaded.
* **Quarantine.** Everything lands under
  `docs/superpowers/candidates/`, outside `ghostcursor/packs/`. Committing a
  candidate must not make it discoverable: production reads neither this
  directory nor the index/activation fixtures beside it.

    py -3.12 tools/build_migration_candidates.py          # write
    py -3.12 tools/build_migration_candidates.py --check  # verify, never write
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATE_ROOT = (
    REPO_ROOT / "docs" / "superpowers" / "candidates" / "declarative-workflow-compiler"
)

#: How much of the digest goes in a filename. Readability only: the loader
#: resolves by exact path and compares the FULL digest it was given, so this
#: fragment is never parsed and never trusted.
FILENAME_DIGEST_CHARS = 16


def canonical_bytes(value) -> bytes:
    """The one serialisation a candidate artifact may have.

    `sort_keys` so the same content always produces the same digest regardless
    of how the dict was built, and an explicit `.encode()` so what gets hashed
    is what gets written.

    Line endings are guaranteed by writing BYTES, not by scrubbing text here.
    `json.dumps` separates lines with a newline and escapes any carriage
    return inside a string, so no CR can reach this return value -- a
    normalisation pass over it would be a guard that cannot fire, which reads
    as protection while enforcing nothing (D031). The real hazard is text-mode
    writing, where Windows translates on the way out, and the writer below
    refuses it by never using text mode.
    """
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Synthetic Export
# ---------------------------------------------------------------------------

SYNTHETIC_PACK = {
    "schema_version": 2,
    "pack_id": "synthetic",
    "pack_kind": "application",
    "display_name": "Synthetic Export",
    "executable_names": ["python.exe"],
    "title_patterns": ["^Synthetic Export$"],
    # OCR off. The demo is a Win32 app whose controls UIA reads cleanly, and
    # the certified behaviour never needed a pixel tier -- enabling one here
    # would let a run ground through a path v1 never used.
    "tier2_capture": "disabled",
    # The demo is hosted by python.exe, but an interpreter's patch version is
    # not this application's release identity (D073). Its bytes are.
    "version_identity": {
        "kind": "content_sha256",
        "path": "ghostcursor/demo/synthetic_export_app.py",
    },
    "aliases": {},
}

SYNTHETIC_INTENT = {
    "schema_version": 2,
    "intent_id": "EXPORT_DATA",
    # The v1 registry's value, verbatim. This is what the planner surfaces
    # for a known-but-unavailable intent, so inventing a "better" one here
    # would change what a user is told (D058).
    "canonical_target": "Synthetic Export",
    "rules": [
        {
            "tier": "exact",
            "phrases": [
                "export this table as csv",
                "export as csv",
                "export data",
                "export the current file",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {
                    "any_of": [
                        {"token": "csv"},
                        {"token": "spreadsheet"},
                        {"token": "table"},
                    ]
                },
                {
                    "any_of": [
                        {"token": "export"},
                        {"token": "save"},
                        {"token": "download"},
                    ]
                },
            ],
        },
    ],
}

SYNTHETIC_PROVENANCE = {
    "source_urls": [],
    "source_tier": "hand-authored",
    "model": "none",
    "prompt_version": "none",
    "created_at": "2026-08-14",
}

SYNTHETIC_RECIPE = {
    "schema_version": 2,
    "intent_id": "EXPORT_DATA",
    # EXACTLY the v1 `intent` string. `step_key()` hashes this with the claimed
    # descriptor, so any other value silently orphans every observation the
    # workflow has already learned (D016).
    "step_key_namespace": "export the current file",
    "selectors": {
        "export_button": {
            "strategy": "bounded_descendants",
            "control_type": "Button",
            "names": ["Export"],
            "normalise": "none",
            "cardinality": "exactly_one",
            "result_limit": 4,
        },
        "export_status": {
            "strategy": "bounded_descendants",
            "control_type": "Text",
            "names": ["Export finished: table.csv"],
            "normalise": "none",
            "cardinality": "at_least_one",
            "result_limit": 4,
        },
        # The wrong-action surface, declared rather than discovered. The
        # certified test clicks this instead of Export; a recipe that never
        # named it would leave the run unable to say what the user touched.
        "wrong_control": {
            "strategy": "bounded_descendants",
            "control_type": "Button",
            "names": ["Wrong control"],
            "normalise": "none",
            "cardinality": "at_least_one",
            "result_limit": 4,
        },
    },
    "context_selectors": ["wrong_control"],
    "steps": [
        {
            "user_action": "click",
            "target_selector": "export_button",
            "target_descriptor": {
                "claimed": {
                    "name": "Export",
                    "name_synonyms": ["Export As", "Save As"],
                    "ocr_text": None,
                    "visual_description": None,
                },
                "confirmed": [],
            },
            "instruction_text": "Click Export to start exporting your file.",
            "verification_rule": {
                "kind": "element_appears",
                "selector": "export_status",
                "args": {},
                "timeout_s": 30.0,
            },
            "risk": "normal",
            "preconditions": [],
            "provenance": dict(SYNTHETIC_PROVENANCE),
        },
        {
            "user_action": "observe",
            "target_selector": None,
            "target_descriptor": {
                "claimed": {
                    "name": "Export finished: table.csv",
                    "name_synonyms": [],
                    "ocr_text": None,
                    "visual_description": None,
                },
                "confirmed": [],
            },
            "instruction_text": (
                "Check the status line — it should show the export finished."
            ),
            "verification_rule": {
                "kind": "user_confirms",
                "args": {},
                "timeout_s": 30.0,
            },
            "risk": "normal",
            "preconditions": [],
            "provenance": dict(SYNTHETIC_PROVENANCE),
        },
    ],
}


# ---------------------------------------------------------------------------
# VS Code
# ---------------------------------------------------------------------------

VSCODE_PACK = {
    "schema_version": 2,
    "pack_id": "vscode",
    "pack_kind": "application",
    "display_name": "Visual Studio Code",
    "executable_names": ["code.exe"],
    "title_patterns": [".*Visual Studio Code.*", ".* - Code$"],
    "tier2_capture": "executable_bounded",
    # VS Code's shipped UI genuinely changes with its release version, and the
    # Open Folder degradation is what proved exact equality is required.
    "version_identity": {"kind": "executable_version"},
    "aliases": {"vscode_names": ["vs code", "vscode", "visual studio code"]},
}

OPEN_FOLDER_INTENT = {
    "schema_version": 2,
    "intent_id": "OPEN_FOLDER",
    "canonical_target": None,
    "rules": [
        {
            "tier": "exact",
            "phrases": [
                "open a folder in vs code",
                "open a folder in vscode",
                "open a folder in visual studio code",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {"any_of": [{"token": "open"}]},
                {"any_of": [{"alias": "vscode_names"}]},
                {"any_of": [{"token": "folder"}, {"path": True}]},
            ],
        },
    ],
}

OPEN_FOLDER_RECIPE = {
    "schema_version": 2,
    "intent_id": "OPEN_FOLDER",
    "step_key_namespace": "open a folder in vscode",
    "selectors": {
        # The reviewed VS Code walker: a Code.exe-bounded Button walk filtered
        # by NORMALISED name against the Open Folder variants. Never the
        # generic descendant walk, and never a provider-side exact query --
        # that returns a dead pointer for this target while the walk reads it
        # cleanly (D069).
        "open_folder": {
            "strategy": "bounded_descendants",
            "control_type": "Button",
            "names": ["Open Folder...", "Open Folder…"],
            "normalise": "strip_leading_private_use",
            "cardinality": "exactly_one",
            "result_limit": 4,
        }
    },
    "context_selectors": [],
    "steps": [
        {
            "user_action": "click",
            "target_selector": "open_folder",
            "target_descriptor": {
                "claimed": {
                    "name": "Open Folder...",
                    "name_synonyms": ["Open Folder…", "Open Folder"],
                    "ocr_text": "Open Folder...",
                    "visual_description": (
                        "the Open Folder action in the VS Code Welcome page"
                    ),
                },
                "confirmed": [],
            },
            "instruction_text": (
                "Click Open Folder… and select the folder in the Windows dialog."
            ),
            "verification_rule": {
                "kind": "window_title_matches",
                "args": {
                    # The two suffixes the v1 regex accepts after whitespace
                    # normalisation. Deliberately NOT the pack's title
                    # patterns: those are broad window-DISCOVERY patterns that
                    # every failed run satisfies too.
                    "completion_title_suffixes": ["visual studio code", " - code"],
                    "goal_reference": {
                        "strip_leading_token": "open",
                        "alias": "vscode_names",
                        "nonspecific_templates": [
                            "a folder in {alias}",
                            "folder in {alias}",
                        ],
                        "strip_trailing_alias_clause": {"preposition": "in"},
                        "basename_separators": ["/", "\\"],
                        "minimum_length": 2,
                    },
                    "fail_after_timeout": True,
                },
                "timeout_s": 20.0,
            },
            "risk": "normal",
            "preconditions": [],
            "provenance": {
                "source_urls": [
                    "https://code.visualstudio.com/docs/getstarted/getting-started"
                ],
                "source_tier": "official-docs-hand-authored",
                "model": "none",
                "prompt_version": "none",
                "created_at": "2026-08-24",
            },
        }
    ],
}

OPEN_TERMINAL_INTENT = {
    "schema_version": 2,
    "intent_id": "OPEN_TERMINAL",
    "canonical_target": None,
    "rules": [
        {
            "tier": "exact",
            "phrases": [
                "open the integrated terminal in vs code",
                "open the integrated terminal in vscode",
                "open a terminal in vs code",
                "open a terminal in vscode",
            ],
        },
        {
            "tier": "heuristic",
            "all_of": [
                {"any_of": [{"token": "open"}, {"token": "show"}]},
                {"any_of": [{"token": "terminal"}]},
                {"any_of": [{"alias": "vscode_names"}]},
            ],
        },
    ],
}

OPEN_TERMINAL_RECIPE = {
    "schema_version": 2,
    "intent_id": "OPEN_TERMINAL",
    "step_key_namespace": "open the integrated terminal in vscode",
    "selectors": {
        # EXACTLY the two names the certified walker accepts, with no
        # normalisation and no synonym. `Toggle Panel` alone is a v1
        # descriptor synonym used for the hint text, never for matching, and
        # promoting it to a selector name would broaden certified behaviour.
        "toggle_panel": {
            "strategy": "bounded_descendants",
            "control_type": "Button",
            "names": ["Toggle Panel (Ctrl+J)"],
            "normalise": "none",
            "cardinality": "exactly_one",
            "result_limit": 4,
        },
        "terminal_section": {
            "strategy": "bounded_descendants",
            "control_type": "Button",
            "names": ["Terminal Section"],
            "normalise": "none",
            "cardinality": "at_least_one",
            "result_limit": 4,
        },
    },
    "context_selectors": [],
    "steps": [
        {
            "user_action": "press_keys",
            "target_selector": "toggle_panel",
            "target_descriptor": {
                "claimed": {
                    "name": "Toggle Panel (Ctrl+J)",
                    "name_synonyms": ["Toggle Panel"],
                    "ocr_text": None,
                    "visual_description": (
                        "the Toggle Panel button in the VS Code title bar"
                    ),
                },
                "confirmed": [],
            },
            "instruction_text": (
                "Press Ctrl+` to open the integrated terminal. The highlighted "
                "Toggle Panel button identifies VS Code's panel control."
            ),
            "verification_rule": {
                "kind": "element_appears",
                "selector": "terminal_section",
                "args": {
                    "fail_after_timeout": True,
                    # A no-op shortcut provides no observable action event, so
                    # this recipe's clock starts at first render instead.
                    "timeout_from_hint": True,
                    # Toggle Panel restores whichever panel was last active, so
                    # an already-open terminal must complete rather than
                    # receive a shortcut that closes it (D057).
                    "accept_if_already_present": True,
                },
                "timeout_s": 20.0,
            },
            "risk": "normal",
            "preconditions": [],
            "provenance": {
                "source_urls": [
                    "https://code.visualstudio.com/docs/terminal/getting-started"
                ],
                "source_tier": "official-docs-hand-authored",
                "model": "none",
                "prompt_version": "none",
                "created_at": "2026-08-25",
            },
        }
    ],
}


PACKS = {
    "synthetic": {
        "pack": SYNTHETIC_PACK,
        "intents": {"open_export": SYNTHETIC_INTENT},
        "recipes": {"open_export": SYNTHETIC_RECIPE},
    },
    "vscode": {
        "pack": VSCODE_PACK,
        "intents": {
            "open_folder": OPEN_FOLDER_INTENT,
            "open_terminal": OPEN_TERMINAL_INTENT,
        },
        "recipes": {
            "open_folder": OPEN_FOLDER_RECIPE,
            "open_terminal": OPEN_TERMINAL_RECIPE,
        },
    },
}


def build() -> dict:
    """Every artifact's canonical bytes, relative path, and full digest."""
    artifacts: dict[str, dict] = {}
    for pack_id, parts in PACKS.items():
        entries = [("pack", pack_id, parts["pack"])]
        entries += [
            ("intents", name, value) for name, value in parts["intents"].items()
        ]
        entries += [
            ("recipes", name, value) for name, value in parts["recipes"].items()
        ]
        for folder, name, value in entries:
            raw = canonical_bytes(value)
            digest = hashlib.sha256(raw).hexdigest()
            relative = (
                f"{pack_id}/{folder}/{name}.{digest[:FILENAME_DIGEST_CHARS]}.json"
            )
            artifacts[relative] = {"bytes": raw, "sha256": digest}
    return artifacts


def activation_fixtures(artifacts: dict) -> dict[str, bytes]:
    """The candidate-only index and activation documents.

    Every intent is registered with `active_adoption_id: null` and no
    adoptions, because none of these has been accepted. That state is the
    honest one and it is also the safe one: a registered id is nameable but
    not executable, so loading this graph proves the intents parse, cross-file
    ids agree, and the matcher they compile to behaves -- without any of them
    gaining authority to run.

    These live beside the artifacts, outside `ghostcursor/packs/`. Production
    reads `ghostcursor/packs/index.json`, which does not exist; a test
    assembles a throwaway tree to load these, and nothing installs them.
    """
    by_pack: dict[str, dict[str, dict]] = {}
    for relative, entry in artifacts.items():
        pack_id, folder, name = relative.split("/")
        by_pack.setdefault(pack_id, {}).setdefault(folder, {})[name] = entry

    documents: dict[str, bytes] = {}
    for pack_id, parts in sorted(by_pack.items()):
        pack_name, pack_entry = next(iter(parts["pack"].items()))
        intents = {}
        for name, intent_entry in sorted(parts["intents"].items()):
            stem = name.split(".")[0]
            intent_id = next(
                value["intent_id"]
                for value in PACKS[pack_id]["intents"].values()
                if value["intent_id"]
                == PACKS[pack_id]["intents"][stem]["intent_id"]
            )
            intents[intent_id] = {
                "intent": {
                    "path": f"intents/{name}",
                    "sha256": intent_entry["sha256"],
                },
                # Not accepted. No adoption record exists, so none is claimed.
                "active_adoption_id": None,
                "adoptions": {},
            }
        documents[f"{pack_id}/activation.json"] = canonical_bytes(
            {
                "schema_version": 2,
                "activation_generation": 1,
                "pack": {
                    "path": f"pack/{pack_name}",
                    "sha256": pack_entry["sha256"],
                },
                "intents": intents,
            }
        )

    documents["index.json"] = canonical_bytes(
        {
            "schema_version": 2,
            "packs": [
                {"pack_id": pack_id, "path": pack_id} for pack_id in sorted(by_pack)
            ],
        }
    )
    return documents


def digest_record(artifacts: dict) -> bytes:
    """The separately recorded full digests.

    Recorded apart from the filenames on purpose: a filename fragment is
    readability, and anything that parsed one to decide what it had loaded
    would be trusting a name instead of the bytes.
    """
    return canonical_bytes(
        {
            "note": (
                "Full SHA-256 of each candidate artifact's exact bytes. The "
                "hex fragment in each filename is readability only and is "
                "never parsed or trusted; these are the digests to pass to "
                "the acceptance harness."
            ),
            "artifacts": {
                path: entry["sha256"] for path, entry in sorted(artifacts.items())
            },
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    artifacts = build()
    written = {
        CANDIDATE_ROOT / path: entry["bytes"] for path, entry in artifacts.items()
    }
    for path, raw in activation_fixtures(artifacts).items():
        written[CANDIDATE_ROOT / path] = raw
    written[CANDIDATE_ROOT / "digests.json"] = digest_record(artifacts)

    # Content-addressed names change when content does, so an edit leaves the
    # PREVIOUS file behind under its old digest. An orphan is not harmless
    # here: it is a schema-valid artifact nothing references, sitting where a
    # human choosing a path to accept will see it.
    existing = set(CANDIDATE_ROOT.rglob("*.json")) if CANDIDATE_ROOT.exists() else set()
    orphans = sorted(existing - set(written))

    if args.check:
        for path, raw in sorted(written.items()):
            if not path.exists() or path.read_bytes() != raw:
                print(f"{path} is out of date", file=sys.stderr)
                return 1
        for path in orphans:
            print(f"{path} is an orphaned artifact", file=sys.stderr)
        return 1 if orphans else 0

    for path in orphans:
        path.unlink()
        print(f"removed orphan {path.relative_to(REPO_ROOT)}")
    for path, raw in sorted(written.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != raw:
            path.write_bytes(raw)
            print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
