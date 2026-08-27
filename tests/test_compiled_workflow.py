"""Binding a classified intent to one live window.

Classification names an intent; that grants nothing. A workflow becomes
executable only against a real window, owned by a real process, running an
application whose identity exactly equals the one acceptance was recorded
against -- and it stays executable only while every one of those is still true
at the moment of launch.

Three properties carry this file:

* **parity.** The declarative title contract must reproduce
  `vscode.verify_open_folder`, not approximate it. The migration is allowed to
  change how the check is written and not what it accepts.
* **one resolver.** Acceptance, planning, and pre-launch all ask the same
  question the same way (D073). Two resolvers would compare two different
  questions and could never disagree honestly.
* **ordering.** Revalidation runs before anything creates a window. An overlay
  is full-screen, topmost and click-through; a launch that aborts after
  creating one has already covered the user's screen for a workflow it refuses
  to run.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ghostcursor.packs.activation import (
    AdoptionRecord,
    ApplicationIdentity,
    IntentAvailability,
    VerifiedCatalog,
    VerifiedIntent,
    VerifiedPack,
)
from ghostcursor.packs.compile import (
    compile_goal_reference,
    derive_goal_reference,
    normalise_title_text,
    reference_is_specific,
)
from ghostcursor.packs.trusted import ArtifactRef
from ghostcursor.packs.workflow import (
    AppSnapshot,
    TargetContext,
    WindowCandidate,
    WorkflowUnavailable,
    materialize,
    resolve_application_identity,
    resolve_target,
    revalidate,
    validate_live_target,
)
from ghostcursor.reasoning.vscode import (
    folder_reference_from_goal,
    verify_open_folder,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_SOURCE = "ghostcursor/demo/synthetic_export_app.py"

VSCODE_ALIASES = {"vscode_names": ["vs code", "vscode", "visual studio code"]}

GOAL_REFERENCE = {
    "strip_leading_token": "open",
    "alias": "vscode_names",
    "nonspecific_templates": ["a folder in {alias}", "folder in {alias}"],
    "strip_trailing_alias_clause": {"preposition": "in"},
    "basename_separators": ["/", "\\"],
    "minimum_length": 2,
}

COMPLETION_SUFFIXES = ["visual studio code", " - code"]

DIGEST = "a" * 64


def _ref(path: str, digest: str = DIGEST) -> ArtifactRef:
    return ArtifactRef(path=path, sha256=digest)


def _selector(names=("Open Folder...",), cardinality="exactly_one"):
    return {
        "strategy": "bounded_descendants",
        "control_type": "Button",
        "names": list(names),
        "normalise": "strip_leading_private_use",
        "cardinality": cardinality,
        "result_limit": 4,
    }


def _recipe_value():
    return {
        "schema_version": 2,
        "intent_id": "OPEN_FOLDER",
        "step_key_namespace": "vscode.open_folder",
        "selectors": {"open_folder": _selector()},
        "context_selectors": [],
        "steps": [
            {
                "user_action": "click",
                "target_selector": "open_folder",
                "target_descriptor": {
                    "claimed": {
                        "name": "Open Folder...",
                        "name_synonyms": [],
                        "ocr_text": None,
                        "visual_description": None,
                    },
                    "confirmed": [],
                },
                "instruction_text": "Click Open Folder.",
                "verification_rule": {
                    "kind": "window_title_matches",
                    "args": {
                        "completion_title_suffixes": COMPLETION_SUFFIXES,
                        "goal_reference": GOAL_REFERENCE,
                        "fail_after_timeout": True,
                    },
                    "timeout_s": 20.0,
                },
                "risk": "normal",
                "preconditions": [],
                "provenance": {
                    "source_urls": [],
                    "source_tier": "trusted",
                    "model": "none",
                    "prompt_version": "none",
                    "created_at": "2026-08-27T00:00:00Z",
                },
            }
        ],
    }


def _pack_value(
    kind="application",
    executables=("code.exe",),
    patterns=(r".*Visual Studio Code.*",),
    identity=None,
    tier2="executable_bounded",
):
    return {
        "schema_version": 2,
        "pack_id": "vscode",
        "pack_kind": kind,
        "display_name": "Visual Studio Code",
        "executable_names": list(executables),
        "title_patterns": list(patterns),
        "tier2_capture": tier2,
        "version_identity": (
            {"kind": "executable_version"} if identity is None else identity
        ),
        "aliases": dict(VSCODE_ALIASES),
    }


def _adoption(identity=ApplicationIdentity("executable_version", "1.134.0")):
    return AdoptionRecord(
        adoption_id="adopt-1",
        recipe=_ref("recipes/open_folder.aaaa.json", "b" * 64),
        recipe_value=_recipe_value(),
        accepted_pack=_ref("pack/vscode.aaaa.json"),
        accepted_intent=_ref("intents/open_folder.aaaa.json", "c" * 64),
        accepted_application_identity=identity,
        evidence=_ref("docs/evidence/open-folder.md", "d" * 64),
        adopted_at="2026-08-27T00:00:00Z",
        reviewer_id="reviewer-1",
        review_commit="0" * 40,
        supersedes_adoption_id=None,
        supersedes_recipe_sha256=None,
    )


def _catalog(pack_value=None, adoption=None, generation=7, index=("e" * 64)):
    adoption = adoption if adoption is not None else _adoption()
    intent = VerifiedIntent(
        intent_id="OPEN_FOLDER",
        intent=_ref("intents/open_folder.aaaa.json", "c" * 64),
        intent_value={"intent_id": "OPEN_FOLDER"},
        availability=IntentAvailability.ACTIVE,
        active_adoption=adoption,
        adoptions={adoption.adoption_id: adoption},
    )
    pack = VerifiedPack(
        pack_id="vscode",
        directory=PROJECT_ROOT / "ghostcursor" / "packs" / "vscode",
        activation_generation=generation,
        activation_sha256="f" * 64,
        pack=_ref("pack/vscode.aaaa.json"),
        pack_value=pack_value if pack_value is not None else _pack_value(),
        intents={"OPEN_FOLDER": intent},
        declared_intents=("OPEN_FOLDER",),
    )
    catalog = VerifiedCatalog(
        root_valid=True, packs={"vscode": pack}, index_sha256=index
    )
    return catalog, pack, intent


def _window(
    hwnd=101,
    title="demo - Visual Studio Code",
    exe="Code.exe",
    version="1.134.0",
    pid=4242,
):
    return WindowCandidate(
        hwnd=hwnd,
        title=title,
        app=AppSnapshot(executable_name=exe, version=version, process_id=pid),
    )


def _target(window=None, identity=None):
    window = window if window is not None else _window()
    return TargetContext(
        hwnd=window.hwnd,
        title=window.title,
        app=window.app,
        identity=identity
        or ApplicationIdentity("executable_version", window.app.version),
    )


def _workflow(**overrides):
    catalog, pack, intent = _catalog(**overrides.pop("catalog_kwargs", {}))
    return (
        materialize(
            catalog,
            pack,
            intent,
            overrides.pop("goal", "Open C:\\Projects\\Demo in VS Code"),
            overrides.pop("target", _target()),
        ),
        catalog,
    )


# ---------------------------------------------------------------------------
# Goal reference extraction -- parity with the verifier being replaced
# ---------------------------------------------------------------------------


SPEC = compile_goal_reference(GOAL_REFERENCE, VSCODE_ALIASES)

PARITY_GOALS = [
    "Open a folder in VS Code",
    "open a folder in visual studio code",
    "Open folder in VS Code",
    "Open C:\\Projects\\Demo in VS Code",
    "Open C:/Projects/Demo in VS Code",
    "open notes in vscode",
    "Open   a   folder   in   vs   code",
    "open my folder a/b in vs code",
    "Open \\\\server\\share in VS Code",
    "open ./relative/path in vs code",
    "opener in vs code",
    "Open Demo",
    "open a folder in vs  code",
    "notes a folder in vs code",
    "open .",
    "open the report and/or the sheet in vs code",
    "OPEN C:\\Users\\user\\AIOS IN VISUAL STUDIO CODE",
]


@pytest.mark.parametrize("goal", PARITY_GOALS)
def test_the_compiled_extractor_reproduces_the_verifier_it_replaces(goal) -> None:
    """Parity is the constraint, not approximation.

    The migration may change how the reference is derived; it may not change
    which reference comes out. A drift here silently changes what every
    Open Folder run verifies, and nothing on screen would look different.
    """
    assert derive_goal_reference(SPEC, goal) == folder_reference_from_goal(goal)


def test_a_nonspecific_goal_yields_no_reference_at_all() -> None:
    """The parity mechanism for `open a folder in VS Code`.

    Once the alias and the intent phrase are stripped this goal names nothing,
    so condition 3 must not apply. That is exactly today's behaviour, and the
    length floor is what preserves it.
    """
    assert derive_goal_reference(SPEC, "Open a folder in VS Code") == ""
    assert not reference_is_specific(SPEC, "")


def test_a_one_character_reference_is_not_specific() -> None:
    """`.` appears in ordinary titles and would self-satisfy condition 3."""
    reference = derive_goal_reference(SPEC, "open .")
    assert reference == "."
    assert not reference_is_specific(SPEC, reference)
    assert reference_is_specific(SPEC, derive_goal_reference(SPEC, "Open Demo"))


def test_step_five_uses_separator_containment_not_the_path_predicate() -> None:
    """The two predicates answer different questions and must be allowed to.

    D072 asks whether a goal is ABOUT a path and deliberately rejects a bare
    forward slash. This step asks whether a reference HAS a final segment. A
    goal that grounds through its `folder` token would otherwise verify against
    `my folder a/b` instead of `b`, silently changing what is checked.
    """
    from ghostcursor.packs.compile import is_path_reference

    assert not is_path_reference("a/b")
    assert derive_goal_reference(SPEC, "open my folder a/b in vs code") == "b"


def test_an_unknown_alias_is_a_hard_failure() -> None:
    from ghostcursor.packs.compile import UnknownAliasError

    with pytest.raises(UnknownAliasError):
        compile_goal_reference(GOAL_REFERENCE, {"other_names": ["vs code"]})


# ---------------------------------------------------------------------------
# Declarative title verification -- parity with verify_open_folder
# ---------------------------------------------------------------------------


def _snapshot(title):
    from ghostcursor.reasoning.verification import Snapshot

    return Snapshot(title=title, elements=())


def _title_rule():
    from ghostcursor.reasoning.schema import VerificationKind, VerificationRule

    return VerificationRule(
        VerificationKind.WINDOW_TITLE_MATCHES,
        args={
            "completion_title_suffixes": COMPLETION_SUFFIXES,
            "goal_reference": GOAL_REFERENCE,
        },
    )


def _declarative(before, after, goal):
    from ghostcursor.reasoning.verification import verify

    return verify(
        _title_rule(),
        _snapshot(before),
        _snapshot(after),
        goal_reference=derive_goal_reference(SPEC, goal),
    )


TITLE_CASES = [
    # (before, after, goal)
    (
        "Visual Studio Code",
        "demo - Visual Studio Code",
        "Open C:\\Projects\\Demo in VS Code",
    ),
    ("Visual Studio Code", "demo - Visual Studio Code", "Open a folder in VS Code"),
    (
        "Visual Studio Code",
        "other - Visual Studio Code",
        "Open C:\\Projects\\Demo in VS Code",
    ),
    (
        "demo - Visual Studio Code",
        "demo - Visual Studio Code",
        "Open C:\\Projects\\Demo in VS Code",
    ),
    ("Visual Studio Code", "Untitled - Notepad", "Open a folder in VS Code"),
    ("Visual Studio Code", "demo - Code", "Open C:\\Projects\\Demo in VS Code"),
    (
        "Visual Studio Code",
        "DEMO - Visual Studio Code",
        "Open C:\\Projects\\Demo in VS Code",
    ),
    (
        "Visual Studio Code",
        "demo  -  Visual  Studio  Code",
        "Open C:/Projects/Demo in VS Code",
    ),
    ("Welcome - Visual Studio Code", "Visual Studio Code", "Open a folder in VS Code"),
    # A suffix appearing mid-title is not a completed title. Containment
    # instead of `endswith` would accept this Chrome window as a finished
    # Open Folder.
    (
        "Visual Studio Code",
        "some visual studio code tutorial - Chrome",
        "Open Demo in VS Code",
    ),
    ("Visual Studio Code", "visual studio code - Google Chrome", "Open a folder in VS Code"),
    # A nonspecific reference must SKIP condition 3, not fail it. `.` is one
    # character and appears in ordinary titles, so requiring containment here
    # would report a real completion as unverified.
    ("Visual Studio Code", "demo - Visual Studio Code", "open ."),
    ("Visual Studio Code", "workspace - Visual Studio Code", "open ."),
]


@pytest.mark.parametrize("before,after,goal", TITLE_CASES)
def test_the_declarative_title_check_reproduces_the_hardcoded_one(
    before, after, goal
) -> None:
    assert _declarative(before, after, goal) is verify_open_folder(
        _snapshot(before), _snapshot(after), goal
    )


def test_the_declared_suffix_list_narrows_one_case_the_regex_accepted() -> None:
    """A documented, deliberate divergence -- and the safe direction.

    The v1 pattern is `(?:visual studio code|\\s-\\s*code)$`, whose `\\s*`
    also accepts a dash with NO following space. Two declared literal suffixes
    cannot express that, so `demo -Code` now fails where it used to pass.

    Kept rather than papered over with a third suffix: VS Code does not emit
    that title, the slack was incidental to the regex rather than intended
    behaviour, and the difference can only make verification stricter -- a run
    that used to pass now fails, never the reverse. Recorded here so authoring
    a real recipe can add the suffix if a live title ever needs it.
    """
    goal = "Open C:\\Projects\\Demo in VS Code"
    assert verify_open_folder(
        _snapshot("Visual Studio Code"), _snapshot("demo -Code"), goal
    )
    assert not _declarative("Visual Studio Code", "demo -Code", goal)

    # Every other suffix form still agrees.
    for title in ("demo - Code", "demo -  Code", "demo - Visual Studio Code"):
        assert _declarative("Visual Studio Code", title, goal) is verify_open_folder(
            _snapshot("Visual Studio Code"), _snapshot(title), goal
        )


def test_pack_title_patterns_are_never_the_completion_check() -> None:
    """A discovery pattern is satisfied by every failed run too.

    `.*Visual Studio Code.*` has to be broad enough to FIND the window. Reusing
    it as the completion check would weaken verification to "the window is
    still VS Code", which is true before the user does anything.
    """
    import re

    discovery = re.compile(_pack_value()["title_patterns"][0])
    unfinished = "Welcome - Visual Studio Code"
    assert discovery.search(unfinished)
    assert not _declarative(unfinished, unfinished, "Open Demo in VS Code")


def test_the_title_must_change_even_when_it_already_matches() -> None:
    finished = "demo - Visual Studio Code"
    assert not _declarative(finished, finished, "Open C:\\Projects\\Demo in VS Code")


def test_normalisation_is_shared_by_the_check_and_the_reference() -> None:
    """One definition, or a reference could be derived under a rule it is then
    matched under differently."""
    assert normalise_title_text("  Demo  -  Visual  Studio  Code ") == (
        "demo - visual studio code"
    )


# ---------------------------------------------------------------------------
# D073 -- one resolver for every stage
# ---------------------------------------------------------------------------


def test_executable_version_identity_reads_the_matched_application() -> None:
    _catalog_, pack, _intent = _catalog()
    identity = resolve_application_identity(
        pack, _window().app, project_root=PROJECT_ROOT
    )
    assert identity == ApplicationIdentity("executable_version", "1.134.0")


def test_content_identity_hashes_the_checked_in_module(tmp_path) -> None:
    pack_value = _pack_value(identity={"kind": "content_sha256", "path": DEMO_SOURCE})
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)
    identity = resolve_application_identity(
        pack, _window().app, project_root=PROJECT_ROOT
    )
    expected = hashlib.sha256((PROJECT_ROOT / DEMO_SOURCE).read_bytes()).hexdigest()
    assert identity == ApplicationIdentity("content_sha256", expected)


def test_a_python_version_change_does_not_invalidate_a_content_identity() -> None:
    """The reason Synthetic Export is not bound to its interpreter (D073).

    The demo is hosted by python.exe, but Python is an interpreter, not the
    demo's release identity. Binding to it would invalidate accepted human runs
    after an unrelated patch update while still failing to notice a change to
    the script those runs exercised.
    """
    pack_value = _pack_value(identity={"kind": "content_sha256", "path": DEMO_SOURCE})
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)

    old_python = _window(version="3.12.1").app
    new_python = _window(version="3.12.9").app
    assert resolve_application_identity(
        pack, old_python, project_root=PROJECT_ROOT
    ) == resolve_application_identity(pack, new_python, project_root=PROJECT_ROOT)


def test_one_changed_demo_byte_changes_the_content_identity(tmp_path) -> None:
    """The implication the interpreter version lacks: bytes change, identity
    changes."""
    root = tmp_path
    source = root / DEMO_SOURCE
    source.parent.mkdir(parents=True)
    source.write_bytes(b"print('demo')\n")
    pack_value = _pack_value(identity={"kind": "content_sha256", "path": DEMO_SOURCE})
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)

    before = resolve_application_identity(pack, _window().app, project_root=root)
    source.write_bytes(b"print('demo!')\n")
    after = resolve_application_identity(pack, _window().app, project_root=root)
    assert before != after


def test_a_missing_executable_version_fails_closed() -> None:
    _catalog_, pack, _intent = _catalog()
    with pytest.raises(WorkflowUnavailable):
        resolve_application_identity(
            pack, _window(version="").app, project_root=PROJECT_ROOT
        )
    with pytest.raises(WorkflowUnavailable):
        resolve_application_identity(pack, None, project_root=PROJECT_ROOT)


def test_a_content_path_outside_the_project_root_fails_closed(tmp_path) -> None:
    pack_value = _pack_value(identity={"kind": "content_sha256", "path": DEMO_SOURCE})
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)
    with pytest.raises(WorkflowUnavailable, match="does not exist"):
        resolve_application_identity(pack, _window().app, project_root=tmp_path)


def test_a_traversing_content_path_fails_closed(tmp_path) -> None:
    """This function does not get to trust its own input.

    The artifact schema rejects `..`, and this is still checked here, because
    the schema validated a STRING while this resolves a FILE. Containment is
    what makes the two agree; without it the string rule would be the only
    thing standing between a declared path and any file on the machine.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "impostor.py").write_bytes(b"x")
    root = tmp_path / "root"
    root.mkdir()

    pack_value = _pack_value(
        identity={"kind": "content_sha256", "path": "../outside/impostor.py"}
    )
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)
    with pytest.raises(WorkflowUnavailable, match="escapes"):
        resolve_application_identity(pack, _window().app, project_root=root)


def test_a_symlinked_content_path_fails_closed(tmp_path) -> None:
    """The vector the containment re-check exists for.

    The schema validated a relative path STRING. A symlink turns a contained
    string into an uncontained file at read time, so the string alone proves
    nothing about the bytes that get hashed. Checking components BEFORE
    resolution is what refuses it -- a check placed after `resolve()` can never
    fire, because a resolved path is never itself a symlink.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    impostor = outside / "impostor.py"
    impostor.write_bytes(b"print('not the demo')\n")

    root = tmp_path / "root"
    (root / "ghostcursor" / "demo").mkdir(parents=True)
    try:
        (root / DEMO_SOURCE).symlink_to(impostor)
    except (OSError, NotImplementedError):
        pytest.skip("this environment cannot create symlinks")

    pack_value = _pack_value(identity={"kind": "content_sha256", "path": DEMO_SOURCE})
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)
    with pytest.raises(WorkflowUnavailable, match="symlink"):
        resolve_application_identity(pack, _window().app, project_root=root)


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def test_no_matching_window_is_unavailable() -> None:
    _catalog_, pack, _intent = _catalog()
    with pytest.raises(WorkflowUnavailable):
        resolve_target(pack, [], project_root=PROJECT_ROOT)
    with pytest.raises(WorkflowUnavailable):
        resolve_target(pack, [_window(exe="chrome.exe")], project_root=PROJECT_ROOT)


def test_a_title_match_without_the_executable_is_not_a_target() -> None:
    """The collision that made identity-bounded grounding mandatory (D046).

    A browser tab reading about VS Code carries a matching title and nothing
    else. Titles are free text; the executable is not.
    """
    _catalog_, pack, _intent = _catalog()
    browser = _window(exe="chrome.exe", title="Visual Studio Code - Google Chrome")
    with pytest.raises(WorkflowUnavailable):
        resolve_target(pack, [browser], project_root=PROJECT_ROOT)


def test_two_candidates_without_a_foreground_are_ambiguous() -> None:
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="a - Visual Studio Code"),
        _window(hwnd=2, title="b - Visual Studio Code"),
    ]
    with pytest.raises(WorkflowUnavailable) as caught:
        resolve_target(pack, windows, project_root=PROJECT_ROOT)
    assert "none is in the foreground" in str(caught.value)


def test_the_foreground_window_wins_among_several_candidates() -> None:
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="a - Visual Studio Code"),
        _window(hwnd=2, title="b - Visual Studio Code"),
    ]
    target = resolve_target(pack, windows, foreground_hwnd=2, project_root=PROJECT_ROOT)
    assert target.hwnd == 2


def test_a_foreground_window_that_is_not_a_candidate_is_ignored() -> None:
    """Foreground is a tie-break among candidates, never an override."""
    _catalog_, pack, _intent = _catalog()
    windows = [_window(hwnd=1, title="a - Visual Studio Code")]
    target = resolve_target(
        pack, windows, foreground_hwnd=999, project_root=PROJECT_ROOT
    )
    assert target.hwnd == 1


def test_target_narrowing_can_filter_but_never_replace_the_executable_check() -> None:
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="alpha - Visual Studio Code"),
        _window(hwnd=2, title="beta - Visual Studio Code"),
        _window(hwnd=3, exe="chrome.exe", title="beta - Visual Studio Code"),
    ]

    narrowed = resolve_target(
        pack, windows, target_title_re="beta", project_root=PROJECT_ROOT
    )
    assert narrowed.hwnd == 2, "the chrome window must never become the target"

    with pytest.raises(WorkflowUnavailable):
        resolve_target(
            pack, windows, target_title_re="gamma", project_root=PROJECT_ROOT
        )


def test_a_planner_only_pack_never_matches_a_window() -> None:
    pack_value = _pack_value(
        kind="planner_only", executables=(), patterns=(), tier2="disabled"
    )
    pack_value["version_identity"] = None
    _catalog_, pack, _intent = _catalog(pack_value=pack_value)
    with pytest.raises(WorkflowUnavailable, match="matches no window"):
        resolve_target(pack, [_window()], project_root=PROJECT_ROOT)

    # The kind check must be what refuses, not the empty identity lists that
    # happen to accompany it. A pack carrying both would still match no window,
    # so a test that only asserts "something raised" passes either way.
    populated = _pack_value(kind="planner_only", tier2="disabled")
    _catalog2, populated_pack, _i = _catalog(pack_value=populated)
    with pytest.raises(WorkflowUnavailable, match="matches no window"):
        resolve_target(populated_pack, [_window()], project_root=PROJECT_ROOT)


def test_the_chosen_hwnd_is_captured_not_rediscovered_by_title() -> None:
    """The title changes the moment the folder opens -- the verified event.

    Re-finding the window by title mid-run would move to a different window at
    exactly the wrong moment.
    """
    _catalog_, pack, _intent = _catalog()
    window = _window(hwnd=77, title="Welcome - Visual Studio Code")
    target = resolve_target(pack, [window], project_root=PROJECT_ROOT)
    assert target.hwnd == 77
    workflow, _catalog2 = _workflow(target=target)
    assert workflow.target.hwnd == 77


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def test_a_materialized_workflow_binds_every_digest_it_will_be_checked_against() -> (
    None
):
    workflow, catalog = _workflow()
    assert workflow.index_sha256 == catalog.index_sha256
    assert workflow.activation_sha256 == "f" * 64
    assert workflow.recipe_sha256 == "b" * 64
    assert workflow.evidence_sha256 == "d" * 64
    assert workflow.activation_generation == 7
    assert workflow.executable_names == ("code.exe",)
    assert workflow.tier2_capture == "executable_bounded"


def test_the_goal_reference_is_derived_once_and_carried() -> None:
    """Verification reads this rather than re-extracting from the goal.

    A second extractor living in the verifier could disagree with the one that
    planned the run, and the disagreement would surface only as a workflow that
    never verifies.
    """
    workflow, _catalog = _workflow(goal="Open C:\\Projects\\Demo in VS Code")
    assert workflow.goal_reference_for(0) == "demo"
    assert workflow.goal_reference_for(1) is None


def test_an_identity_mismatch_yields_no_workflow() -> None:
    catalog, pack, intent = _catalog()
    stale = _target(_window(version="1.100.0"))
    with pytest.raises(WorkflowUnavailable) as caught:
        materialize(catalog, pack, intent, "Open Demo in VS Code", stale)
    assert "accepted against" in str(caught.value)


def test_an_intent_with_no_active_adoption_yields_no_workflow() -> None:
    catalog, pack, intent = _catalog()
    inactive = VerifiedIntent(
        intent_id=intent.intent_id,
        intent=intent.intent,
        intent_value=intent.intent_value,
        availability=IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE,
        active_adoption=None,
        adoptions={},
    )
    with pytest.raises(WorkflowUnavailable):
        materialize(catalog, pack, inactive, "Open Demo in VS Code", _target())


def test_naming_an_intent_is_not_permission_to_run_it() -> None:
    """D058 at the materialization boundary.

    The model influences which intent is NAMED. It cannot influence whether an
    active adoption exists, nor whether the live application identity equals
    the accepted one -- so it can name this intent all it likes and still get
    no workflow.
    """
    catalog, pack, intent = _catalog()
    with pytest.raises(WorkflowUnavailable):
        materialize(
            catalog, pack, intent, "Open Demo", _target(_window(version="9.9.9"))
        )


# ---------------------------------------------------------------------------
# Classification loads nothing
# ---------------------------------------------------------------------------


def test_classification_never_loads_a_recipe(monkeypatch) -> None:
    """Naming an intent must not touch the filesystem.

    In v1 the two were one act, so the authority policy could not be reasoned
    about without a loadable recipe on disk.
    """
    from ghostcursor.reasoning import planner
    from ghostcursor.reasoning.planner import (
        Classification,
        IntentDecision,
        PlanStatus,
        classify_decision,
    )

    def _explode(*args, **kwargs):
        raise AssertionError("classification loaded a recipe")

    monkeypatch.setattr(planner, "_trusted_recipe", _explode)
    monkeypatch.setattr(planner, "recipe_path_for", _explode)
    monkeypatch.setattr(planner.Recipe, "load", staticmethod(_explode))

    result = classify_decision(
        "Open a folder in VS Code",
        IntentDecision("OPEN_FOLDER", 0.9, "model agrees"),
        deterministic=lambda goal: ("OPEN_FOLDER", 0.95, "exact phrase"),
        available=frozenset({"OPEN_FOLDER"}),
    )
    assert isinstance(result, Classification)
    assert result.status is PlanStatus.SUPPORTED
    assert not hasattr(result, "recipe")


def test_a_model_selected_available_intent_needs_deterministic_agreement() -> None:
    from ghostcursor.reasoning.planner import (
        IntentDecision,
        PlanStatus,
        classify_decision,
    )

    disagreeing = classify_decision(
        "Open a folder in VS Code",
        IntentDecision("OPEN_TERMINAL", 0.9, "model guess"),
        deterministic=lambda goal: ("OPEN_FOLDER", 0.95, "exact phrase"),
        available=frozenset({"OPEN_FOLDER", "OPEN_TERMINAL"}),
    )
    assert disagreeing.status is PlanStatus.INVALID_MODEL_OUTPUT
    assert disagreeing.intent_id == "OPEN_FOLDER"

    ungrounded = classify_decision(
        "do something",
        IntentDecision("OPEN_TERMINAL", 0.9, "model guess"),
        deterministic=lambda goal: (None, 0.0, "nothing matched"),
        available=frozenset({"OPEN_TERMINAL"}),
    )
    assert ungrounded.status is PlanStatus.UNSUPPORTED_GOAL
    assert ungrounded.intent_id is None


def test_an_intent_with_no_adoption_classifies_as_recipe_unavailable() -> None:
    from ghostcursor.reasoning.planner import (
        IntentDecision,
        PlanStatus,
        classify_decision,
    )

    result = classify_decision(
        "make a document",
        IntentDecision("CREATE_DOCUMENT", 0.8, "model chose"),
        deterministic=lambda goal: (None, 0.0, "nothing matched"),
        available=frozenset(),
    )
    assert result.status is PlanStatus.KNOWN_INTENT_RECIPE_UNAVAILABLE
    assert result.intent_id == "CREATE_DOCUMENT"


# ---------------------------------------------------------------------------
# Pre-launch revalidation
# ---------------------------------------------------------------------------


def _reader(window=None, *, missing=False):
    """A fake SCREEN, never a fake verdict.

    Tests substitute what the OS reports about a handle. They cannot
    substitute whether that report is acceptable -- `revalidate()` takes no
    boolean, so there is nothing for a test double to say yes to.
    """

    def _read(hwnd):
        if missing:
            return None
        live = window if window is not None else _window()
        return WindowCandidate(hwnd=hwnd, title=live.title, app=live.app)

    return _read


def _revalidate(workflow, catalog, *, live=None, missing=False):
    revalidate(
        workflow,
        reload_catalog=lambda: catalog,
        read_window=_reader(live, missing=missing),
        project_root=PROJECT_ROOT,
    )


def test_an_unchanged_graph_revalidates() -> None:
    workflow, catalog = _workflow()
    _revalidate(workflow, catalog)


def _replaced_pack(catalog, **changes):
    pack = catalog.packs["vscode"]
    fields = {
        "pack_id": pack.pack_id,
        "directory": pack.directory,
        "activation_generation": pack.activation_generation,
        "activation_sha256": pack.activation_sha256,
        "pack": pack.pack,
        "pack_value": pack.pack_value,
        "intents": pack.intents,
        "declared_intents": pack.declared_intents,
    }
    fields.update(changes)
    return VerifiedCatalog(
        root_valid=True,
        packs={"vscode": VerifiedPack(**fields)},
        index_sha256=catalog.index_sha256,
    )


def test_a_changed_index_digest_aborts() -> None:
    workflow, catalog = _workflow()
    changed = VerifiedCatalog(
        root_valid=True, packs=catalog.packs, index_sha256="9" * 64
    )
    with pytest.raises(WorkflowUnavailable, match="index.json"):
        _revalidate(workflow, changed)


def test_a_withdrawn_pack_aborts_rather_than_failing_later() -> None:
    """A pack no longer named by the index must stop the launch here.

    Otherwise the run proceeds and surfaces as a confusing perception failure
    minutes later, with the overlay already on screen.
    """
    workflow, catalog = _workflow()
    empty = VerifiedCatalog(
        root_valid=True, packs={}, index_sha256=catalog.index_sha256
    )
    with pytest.raises(WorkflowUnavailable, match="no longer indexed"):
        _revalidate(workflow, empty)


def test_a_changed_activation_digest_aborts() -> None:
    workflow, catalog = _workflow()
    with pytest.raises(WorkflowUnavailable, match="activation.json"):
        _revalidate(workflow, _replaced_pack(catalog, activation_sha256="9" * 64))


def test_a_changed_generation_aborts() -> None:
    workflow, catalog = _workflow()
    with pytest.raises(WorkflowUnavailable, match="generation"):
        _revalidate(workflow, _replaced_pack(catalog, activation_generation=8))


def test_a_changed_pack_digest_aborts() -> None:
    workflow, catalog = _workflow()
    with pytest.raises(WorkflowUnavailable, match="pack artifact"):
        _revalidate(
            workflow,
            _replaced_pack(catalog, pack=_ref("pack/vscode.aaaa.json", "9" * 64)),
        )


def _replaced_adoption(catalog, **changes):
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    adoption = intent.active_adoption
    fields = {f: getattr(adoption, f) for f in adoption.__dataclass_fields__}
    fields.update(changes)
    replaced = AdoptionRecord(**fields)
    return _replaced_pack(
        catalog,
        intents={
            "OPEN_FOLDER": VerifiedIntent(
                intent_id=intent.intent_id,
                intent=intent.intent,
                intent_value=intent.intent_value,
                availability=intent.availability,
                active_adoption=replaced,
                adoptions={replaced.adoption_id: replaced},
            )
        },
    )


def test_a_changed_recipe_digest_aborts() -> None:
    workflow, catalog = _workflow()
    changed = _replaced_adoption(
        catalog, recipe=_ref("recipes/open_folder.aaaa.json", "9" * 64)
    )
    with pytest.raises(WorkflowUnavailable, match="recipe artifact"):
        _revalidate(workflow, changed)


def test_a_changed_evidence_digest_aborts() -> None:
    """Acceptance evidence is bound by digest, not by path.

    A path alone names a mutable file and cannot prove which bytes were
    reviewed -- the same failure shape as an unbound recipe.
    """
    workflow, catalog = _workflow()
    changed = _replaced_adoption(
        catalog, evidence=_ref("docs/evidence/open-folder.md", "9" * 64)
    )
    with pytest.raises(WorkflowUnavailable, match="evidence"):
        _revalidate(workflow, changed)


def test_a_changed_intent_digest_aborts() -> None:
    workflow, catalog = _workflow()
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    changed = _replaced_pack(
        catalog,
        intents={
            "OPEN_FOLDER": VerifiedIntent(
                intent_id=intent.intent_id,
                intent=_ref("intents/open_folder.aaaa.json", "9" * 64),
                intent_value=intent.intent_value,
                availability=intent.availability,
                active_adoption=intent.active_adoption,
                adoptions=intent.adoptions,
            )
        },
    )
    with pytest.raises(WorkflowUnavailable, match="intent artifact"):
        _revalidate(workflow, changed)


def test_a_withdrawn_adoption_aborts() -> None:
    workflow, catalog = _workflow()
    intent = catalog.packs["vscode"].intents["OPEN_FOLDER"]
    changed = _replaced_pack(
        catalog,
        intents={
            "OPEN_FOLDER": VerifiedIntent(
                intent_id=intent.intent_id,
                intent=intent.intent,
                intent_value=intent.intent_value,
                availability=IntentAvailability.KNOWN_INTENT_RECIPE_UNAVAILABLE,
                active_adoption=None,
                adoptions={},
            )
        },
    )
    with pytest.raises(WorkflowUnavailable, match="no longer adopted"):
        _revalidate(workflow, changed)


def test_a_changed_application_identity_aborts() -> None:
    """The application updated between planning and launch.

    The LIVE window now reports a different version. Recomputing identity from
    the workflow's own frozen snapshot would compare a value to itself and
    agree every time -- it would read as a check and detect nothing, which is
    exactly what this test used to prove by mutating the stored snapshot
    instead of the screen.
    """
    workflow, catalog = _workflow()
    upgraded = _window(version="1.200.0")
    with pytest.raises(WorkflowUnavailable, match="identity changed"):
        _revalidate(workflow, catalog, live=upgraded)


def test_a_lost_window_aborts() -> None:
    workflow, catalog = _workflow()
    with pytest.raises(WorkflowUnavailable, match="no longer exists"):
        _revalidate(workflow, catalog, missing=True)


def test_a_recycled_hwnd_owned_by_another_process_aborts() -> None:
    """A handle that still exists proves nothing about what is behind it.

    Windows recycles HWND values. The same handle can belong to a process
    started after planning, so "the window exists" is not "the window is still
    my target".
    """
    workflow, catalog = _workflow()
    recycled = _window(pid=9999)
    with pytest.raises(WorkflowUnavailable, match="belongs to process"):
        _revalidate(workflow, catalog, live=recycled)


def test_the_bound_window_changing_executable_aborts() -> None:
    workflow, catalog = _workflow()
    impostor = _window(exe="chrome.exe")
    with pytest.raises(WorkflowUnavailable, match="is now"):
        _revalidate(workflow, catalog, live=impostor)


def test_a_title_that_no_longer_satisfies_the_pack_aborts() -> None:
    workflow, catalog = _workflow()
    renamed = _window(title="Untitled - Notepad")
    with pytest.raises(WorkflowUnavailable, match="no longer satisfies"):
        _revalidate(workflow, catalog, live=renamed)


def test_revalidation_offers_no_way_to_assert_a_window_is_valid() -> None:
    """The injection point is the OS reader, never the verdict.

    An unrestricted boolean callback would let any caller -- a test double, a
    future entry point, a refactor in a hurry -- pass `lambda _: True` and
    bypass the whole live-target invariant while every digest check still ran
    and every test still passed.
    """
    import inspect

    parameters = inspect.signature(revalidate).parameters
    assert "read_window" in parameters
    assert "window_still_valid" not in parameters

    returns = inspect.signature(validate_live_target).return_annotation
    assert returns in (None, "None"), "a validator that returns a verdict invites one"


def CompiledWorkflowReplacement(workflow, **changes):
    """A copy of `workflow` with fields replaced, for mutation tests."""
    from dataclasses import replace

    return replace(workflow, **changes)


# ---------------------------------------------------------------------------
# Launch ordering
# ---------------------------------------------------------------------------


def _launch(workflow, catalog, *, live=None, missing=False, create_overlay=lambda: 1):
    from ghostcursor.run import _launch_compiled_workflow

    return _launch_compiled_workflow(
        workflow,
        seconds=1.0,
        reload_catalog=lambda: catalog,
        read_window=_reader(live, missing=missing),
        project_root=PROJECT_ROOT,
        clock=lambda: 0.0,
        sleeper=lambda _s: None,
        warmup_budget_s=2.0,
        create_overlay=create_overlay,
    )


def test_a_failed_revalidation_never_reaches_overlay_creation() -> None:
    """Ordering is the entire guarantee.

    An overlay is full-screen, topmost and click-through. A launch that aborts
    after creating one has already covered the user's screen for a workflow it
    then refuses to run.
    """
    workflow, catalog = _workflow()
    created = []

    def _create_overlay():
        created.append(True)
        raise AssertionError("overlay created despite a failed revalidation")

    empty = VerifiedCatalog(
        root_valid=True, packs={}, index_sha256=catalog.index_sha256
    )
    with pytest.raises(WorkflowUnavailable):
        _launch(workflow, empty, create_overlay=_create_overlay)
    assert created == []


def test_the_launch_entry_point_takes_a_workflow_not_a_path() -> None:
    """`--recipe <path>` has no counterpart in the v2 entry point.

    A path-based loader exists only inside the developer acceptance harness and
    must be unreachable from planning, Ask, and this function.
    """
    import inspect

    from ghostcursor.run import run_tour_for_workflow

    parameters = inspect.signature(run_tour_for_workflow).parameters
    assert list(parameters)[0] == "workflow"
    assert "recipe_path" not in parameters


def test_the_public_launch_path_accepts_no_authority_inputs() -> None:
    """A caller who supplies the facts supplies the authority.

    The window reader, the catalog loader, and the project root are what
    revalidation decides with. Accepting any of them from a caller is the same
    bypass the boolean callback was, spelled with more arguments -- fabricated
    PID, executable, title, and version would authorize the launch. The public
    entry point selects all three itself.

    `clock` and `sleeper` stay parameters: they drive the timeline and decide
    nothing about authority.
    """
    import inspect

    from ghostcursor.run import run_tour_for_workflow

    parameters = set(inspect.signature(run_tour_for_workflow).parameters)
    authority = {
        "read_window",
        "reload_catalog",
        "project_root",
        "create_overlay",
        "window_still_valid",
        "catalog",
        "target",
        "identity",
    }
    assert not (parameters & authority), (
        "the public launch path accepts authority inputs: "
        f"{sorted(parameters & authority)}"
    )
    assert parameters == {"workflow", "seconds", "clock", "sleeper", "warmup_budget_s"}


def test_the_injection_seam_is_private() -> None:
    """Hermetic tests reach it; nothing importable as public API does."""
    from ghostcursor import run

    assert hasattr(run, "_launch_compiled_workflow")
    assert not hasattr(run, "launch_compiled_workflow")


def test_a_revalidated_launch_reaches_the_execution_body() -> None:
    """The gate passes and hands over; the body itself lands at the cutover."""
    workflow, catalog = _workflow()
    with pytest.raises(NotImplementedError, match="Task 9"):
        _launch(workflow, catalog)


# ---------------------------------------------------------------------------
# Immutability of the bound workflow
# ---------------------------------------------------------------------------


def test_the_derived_goal_reference_cannot_be_rewritten_after_planning() -> None:
    """Nothing here is bound by a digest, so nothing else would catch it.

    The reference is DERIVED from the goal at plan time, not loaded from an
    artifact. A mutable mapping would let what a step verifies be rewritten
    after planning with every bound digest still matching -- and revalidation,
    which only compares digests and live identity, would pass.

    `frozen=True` on the dataclass is not enough on its own: it stops the
    FIELD being reassigned and says nothing about the contents of a mutable
    object the field points at.
    """
    workflow, catalog = _workflow(goal=r"Open C:\Projects\Demo in VS Code")
    assert workflow.goal_reference_for(0) == "demo"

    with pytest.raises(TypeError):
        workflow.goal_references[0] = "attacker"
    with pytest.raises((TypeError, AttributeError)):
        workflow.goal_references.clear()
    with pytest.raises((TypeError, AttributeError)):
        workflow.goal_references.pop(0)

    assert workflow.goal_reference_for(0) == "demo"
    _revalidate(workflow, catalog)


def test_replacing_the_whole_field_is_refused_too() -> None:
    from dataclasses import FrozenInstanceError

    workflow, _catalog = _workflow()
    with pytest.raises(FrozenInstanceError):
        workflow.goal_references = {0: "attacker"}


def test_verification_arguments_are_frozen_at_every_level() -> None:
    """A shallow freeze protects nothing that decides behaviour.

    The values a recipe actually decides with live one and two levels down.
    `minimum_length` is the clearest: it is what says whether a title must
    contain the derived reference at all, so raising it to 99 turns every
    reference nonspecific and makes condition 3 stop applying -- with no bound
    digest changing and revalidation still passing.

    The trust boundary already deep-froze this. The compiler was undoing it:
    `MappingProxyType(dict(args))` unwraps the frozen outer mapping into a
    mutable dict and re-wraps only that one level.
    """
    workflow, catalog = _workflow()
    args = workflow.recipe.steps[0].verification.args

    with pytest.raises(TypeError):
        args["goal_reference"]["minimum_length"] = 99
    with pytest.raises(TypeError):
        args["goal_reference"]["strip_trailing_alias_clause"]["preposition"] = "at"
    with pytest.raises(TypeError):
        args["goal_reference"]["alias"] = "attacker"

    assert args["goal_reference"]["minimum_length"] == 2
    _revalidate(workflow, catalog)


def test_frozen_sequences_are_tuples_not_lists() -> None:
    """A list inside a frozen mapping is still a mutable list."""
    workflow, _catalog = _workflow()
    args = workflow.recipe.steps[0].verification.args

    assert isinstance(args["completion_title_suffixes"], tuple)
    assert isinstance(args["goal_reference"]["nonspecific_templates"], tuple)
    assert isinstance(args["goal_reference"]["basename_separators"], tuple)
    with pytest.raises((TypeError, AttributeError)):
        args["completion_title_suffixes"].append("- notepad")


def test_a_frozen_recipe_still_compiles_and_verifies() -> None:
    """Freezing must not break the readers -- the reason to check.

    `compile_goal_reference` reads these values; a freeze that made them
    unreadable would trade one failure for another.
    """
    workflow, _catalog = _workflow(goal=r"Open C:\Projects\Demo in VS Code")
    assert workflow.goal_reference_for(0) == "demo"
    assert _declarative(
        "Visual Studio Code", "demo - Visual Studio Code",
        r"Open C:\Projects\Demo in VS Code",
    )


def test_the_compiled_plan_is_immutable_the_same_way() -> None:
    """The same rule already holds one layer down; this keeps them consistent."""
    workflow, _catalog = _workflow()
    with pytest.raises(TypeError):
        workflow.recipe.plan.selectors["open_folder"] = None
    with pytest.raises(TypeError):
        workflow.recipe.steps[0].verification.args["goal_reference"] = None


def test_the_validator_does_not_trust_the_arguments_it_is_handed() -> None:
    """Two checks `revalidate()` alone cannot reach, and why they stay.

    Inside `revalidate()` both are implied by the checks before them: the
    executable was already compared against the workflow's own, and the
    adoption already accepted that identity at materialization. Reached
    through that path they can never fire, so the mutation audit finds them
    surviving -- correctly.

    They are kept and tested HERE because `validate_live_target()` is exported
    and takes the pack and the adoption as arguments. A caller that pairs a
    workflow with the wrong pack, or with an adoption for a different
    application version, gets a refusal rather than a launch. This is the last
    gate before an overlay covers the user's screen; it does not get to assume
    its caller did the pairing correctly.
    """
    workflow, catalog = _workflow()
    pack = catalog.packs["vscode"]
    adoption = pack.intents["OPEN_FOLDER"].active_adoption

    # A pack that does not claim this workflow's executable.
    other_pack = _catalog(pack_value=_pack_value(executables=("notepad.exe",)))[1]
    with pytest.raises(WorkflowUnavailable, match="not an executable pack"):
        validate_live_target(
            workflow,
            other_pack,
            adoption,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )

    # An adoption accepted against a different application version.
    stale = _adoption(identity=ApplicationIdentity("executable_version", "1.100.0"))
    with pytest.raises(WorkflowUnavailable, match="no longer accepted"):
        validate_live_target(
            workflow,
            pack,
            stale,
            read_window=_reader(),
            project_root=PROJECT_ROOT,
        )
