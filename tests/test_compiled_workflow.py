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


def test_two_matching_windows_refuse_rather_than_pick_one() -> None:
    """Ambiguity fails closed. A window is the outermost selector.

    An `EXACTLY_ONE` action selector already refuses to choose one control
    among several rather than taking the first; choosing one WINDOW among
    several is the same decision at a larger scale, and gets the same answer.
    """
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="a - Visual Studio Code"),
        _window(hwnd=2, title="b - Visual Studio Code"),
    ]
    with pytest.raises(WorkflowUnavailable) as caught:
        resolve_target(pack, windows, project_root=PROJECT_ROOT)

    message = str(caught.value)
    # Every candidate, with its handle: two windows can share a title, and the
    # handle is the only thing that always separates them. Without the list
    # the operator is told to narrow and given nothing to narrow against.
    assert "1 'a - Visual Studio Code'" in message
    assert "2 'b - Visual Studio Code'" in message


def test_the_focused_window_gets_no_say_in_which_one_is_chosen() -> None:
    """No foreground tie-break, in either direction.

    It used to break ties, and two matching windows then resolved silently to
    whichever happened to be focused -- a different workspace, with a trusted
    recipe pointed at it and nothing to show a choice had been made. Neither
    candidate being focused, nor one of them being focused, may change the
    answer now: both are the same refusal.
    """
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="a - Visual Studio Code"),
        _window(hwnd=2, title="b - Visual Studio Code"),
    ]
    with pytest.raises(WorkflowUnavailable):
        resolve_target(pack, windows, project_root=PROJECT_ROOT)

    # The resolver cannot even be TOLD which window is focused any more. A
    # parameter that no longer decides anything reads like a guard while
    # enforcing nothing, so it is gone rather than ignored.
    import ast
    import inspect

    # Membership on `.parameters` is by exact NAME, so `"foreground" not in`
    # would only ever have refused a parameter called exactly that -- and the
    # one being refused is `foreground_hwnd`. Scan the names instead.
    named = [
        name
        for name in inspect.signature(resolve_target).parameters
        if "foreground" in name
    ]
    assert not named, named

    # And it must not fetch the foreground itself. With the parameter gone
    # that is the only way the tie-break could return, and no behavioural
    # test would see it: a real `GetForegroundWindow()` never matches a
    # synthetic candidate, so the resolver would keep refusing here while
    # silently choosing on a live desktop.
    source = ast.unparse(
        next(
            node
            for node in ast.parse(
                (
                    PROJECT_ROOT / "ghostcursor" / "packs" / "workflow.py"
                ).read_text(encoding="utf-8")
            ).body
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_target"
        )
    )
    # The docstring explains WHY there is no tie-break, so scan code only.
    body = ast.parse(
        (PROJECT_ROOT / "ghostcursor" / "packs" / "workflow.py").read_text(
            encoding="utf-8"
        )
    )
    resolver = next(
        node
        for node in body.body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_target"
    )
    calls = [
        ast.unparse(node)
        for node in ast.walk(resolver)
        if isinstance(node, (ast.Name, ast.Attribute))
        and "oreground" in ast.unparse(node)
    ]
    assert not calls, calls


def test_a_narrowing_that_does_not_narrow_to_one_still_refuses() -> None:
    """The subtle case, and the reason foreground had to go rather than yield.

    An operator who passes an explicit pattern believes they disambiguated.
    Under the old order a pattern matching two windows fell through to the
    foreground tie-break anyway, so the narrowing looked authoritative and was
    not. A pattern that fails to reach one window is not a choice.
    """
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="alpha - Visual Studio Code"),
        _window(hwnd=2, title="beta - Visual Studio Code"),
    ]
    with pytest.raises(WorkflowUnavailable) as caught:
        resolve_target(
            pack,
            windows,
            target_title_re="Visual Studio Code",
            project_root=PROJECT_ROOT,
        )
    assert "even after narrowing" in str(caught.value)


def test_a_narrowing_that_reaches_exactly_one_window_is_accepted() -> None:
    """Fail-closed is not fail-always: specific enough still resolves."""
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=1, title="alpha - Visual Studio Code"),
        _window(hwnd=2, title="beta - Visual Studio Code"),
    ]
    target = resolve_target(
        pack, windows, target_title_re="^alpha", project_root=PROJECT_ROOT
    )
    assert target.hwnd == 1


def test_one_matching_window_needs_no_narrowing_at_all() -> None:
    """The ordinary case is untouched: a single window still just works."""
    _catalog_, pack, _intent = _catalog()
    target = resolve_target(
        pack,
        [_window(hwnd=7, title="only - Visual Studio Code")],
        project_root=PROJECT_ROOT,
    )
    assert target.hwnd == 7
# ---------------------------------------------------------------------------
# The production binding path, window by window
# ---------------------------------------------------------------------------
#
# `resolve_target` is tested directly above. These drive the seam production
# actually calls -- catalog in, bound `CompiledWorkflow` out -- because a
# correct resolver reached through a wrapper that drops the narrowing, or
# picks the wrong pack, is still a wrong target.


def _bind(windows, narrowing=None, goal="Open a folder in VS Code"):
    from ghostcursor.packs.workflow import _bind_workflow_with_windows

    catalog, pack, intent = _catalog()
    return _bind_workflow_with_windows(
        catalog,
        pack,
        intent,
        goal,
        windows=windows,
        target_title_re=narrowing,
        project_root=PROJECT_ROOT,
    )


def test_the_launch_path_binds_a_single_window_without_narrowing() -> None:
    """The ordinary case: one window, no flag, and it just runs."""
    workflow = _bind([_window(hwnd=7, title="only - Visual Studio Code")])
    assert workflow.target.hwnd == 7


def test_the_launch_path_refuses_two_windows_without_narrowing() -> None:
    """No flag and no way to tell them apart is a refusal, not a guess."""
    with pytest.raises(WorkflowUnavailable) as caught:
        _bind(
            [
                _window(hwnd=1, title="a - Visual Studio Code"),
                _window(hwnd=2, title="b - Visual Studio Code"),
            ]
        )
    assert "1 'a - Visual Studio Code'" in str(caught.value)
    assert "2 'b - Visual Studio Code'" in str(caught.value)


def test_the_launch_path_honours_an_exact_narrowing() -> None:
    """The operator's flag reaches `resolve_target` and decides the target."""
    workflow = _bind(
        [
            _window(hwnd=1, title="alpha - Visual Studio Code"),
            _window(hwnd=2, title="beta - Visual Studio Code"),
        ],
        narrowing="^beta",
    )
    assert workflow.target.hwnd == 2


def test_the_launch_path_refuses_a_narrowing_that_still_matches_several() -> None:
    """A flag that does not reach one window is not a choice.

    This is the row that decided the policy: under the old order such a
    pattern fell through to the foreground, so an operator who thought they
    had disambiguated had not.
    """
    with pytest.raises(WorkflowUnavailable) as caught:
        _bind(
            [
                _window(hwnd=1, title="alpha - Visual Studio Code"),
                _window(hwnd=2, title="beta - Visual Studio Code"),
            ],
            narrowing="Visual Studio Code",
        )
    assert "even after narrowing" in str(caught.value)


def test_the_launch_path_ignores_which_window_is_focused(monkeypatch) -> None:
    """Focus changes nothing, whichever window holds it.

    Driven through a real `GetForegroundWindow` stub rather than a parameter,
    because the parameter is gone: the only way the tie-break could return is
    the resolver fetching the foreground itself, and this is what that would
    look like from the outside.
    """
    import win32gui

    windows = [
        _window(hwnd=1, title="a - Visual Studio Code"),
        _window(hwnd=2, title="b - Visual Studio Code"),
    ]
    for focused in (0, 1, 2, 999):
        monkeypatch.setattr(win32gui, "GetForegroundWindow", lambda f=focused: f)
        with pytest.raises(WorkflowUnavailable):
            _bind(windows)


def test_the_bound_workflow_carries_the_chosen_handle_onward() -> None:
    """Binding is not advice: the handle travels into execution unchanged.

    Perception pins its worker to this handle and revalidation re-reads this
    handle, so a target chosen here and rediscovered later by title could move
    to a different window at exactly the moment the title changes -- which for
    Open Folder is the verified outcome itself.
    """
    workflow = _bind([_window(hwnd=4242, title="only - Visual Studio Code")])
    assert workflow.target.hwnd == 4242
    assert workflow.target.title == "only - Visual Studio Code"


def test_the_public_binding_never_accepts_a_window_list() -> None:
    """Windows carry the PID, executable, title and version that authorize a
    launch, so a caller who supplied them would supply the identity
    revalidation then checks. The public entry enumerates them itself."""
    import inspect

    from ghostcursor.packs.workflow import bind_workflow

    parameters = set(inspect.signature(bind_workflow).parameters)
    for authority in ("windows", "list_windows", "candidates"):
        assert authority not in parameters, authority


def test_an_unknown_intent_refuses_before_any_window_is_read() -> None:
    """A refusal that named no pack would send the operator hunting."""
    from ghostcursor.packs.workflow import _catalog_entry

    catalog, _pack, _intent = _catalog()
    with pytest.raises(WorkflowUnavailable, match="OPEN_EXTENSIONS"):
        _catalog_entry(catalog, "OPEN_EXTENSIONS")


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
    from ghostcursor.reasoning.planner import (
        Classification,
        IntentDecision,
        PlanStatus,
        classify_decision,
    )

    def _explode(*args, **kwargs):
        raise AssertionError("classification touched the filesystem")

    monkeypatch.setattr(Path, "read_bytes", _explode)
    monkeypatch.setattr(Path, "read_text", _explode)
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


def _driven_clock(on_sleep=None):
    """A clock the sleeper advances.

    Never a frozen clock: the executor's only bound is the deadline, so a
    `clock` that cannot move turns a tour that does not complete into an
    infinite loop. A test that supplies one is testing a caller error, not the
    executor.
    """
    now = [0.0]

    def _sleep(seconds):
        now[0] += seconds
        if on_sleep is not None:
            on_sleep()

    return (lambda: now[0]), _sleep


def _launch(workflow, catalog, *, live=None, missing=False, create_overlay=lambda: 1,
            observe=None, renderer=None, seconds=1.0, on_sleep=None):
    from ghostcursor.run import _launch_compiled_workflow

    clock, sleeper = _driven_clock(on_sleep)
    return _launch_compiled_workflow(
        workflow,
        seconds=seconds,
        reload_catalog=lambda: catalog,
        read_window=_reader(live, missing=missing),
        project_root=PROJECT_ROOT,
        clock=clock,
        sleeper=sleeper,
        warmup_budget_s=2.0,
        create_overlay=create_overlay,
        observe=observe,
        renderer=renderer,
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
    """The gate passes, the overlay is created, and the shared executor runs.

    The same `execute_compiled_workflow()` the candidate harness calls. Two
    executors would let acceptance certify semantics production does not have,
    so the cutover changes which authority path arrives here and nothing about
    what happens once it does.
    """
    from ghostcursor.perception.uia import Element
    from ghostcursor.reasoning.compiled_tour import TickInput

    workflow, catalog = _workflow()
    created = []
    # A published SLOT, advanced by the worker between ticks -- the executor
    # reads what was published and never walks UIA itself (D021).
    titles = [
        "Welcome - Visual Studio Code",
        "Welcome - Visual Studio Code",
        "demo - Visual Studio Code",
    ]
    slot = {}

    def _publish():
        title = titles.pop(0) if len(titles) > 1 else titles[0]
        matched = (
            Element(
                name="Open Folder...",
                control_type="Button",
                automation_id="",
                bbox=(10, 20, 110, 60),
                path=("Button",),
            ),
        )
        slot["value"] = TickInput(
            title=title, selectors={"open_folder": matched}, union=matched
        )

    _publish()

    def _observe():
        return slot.get("value")

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    exit_code = _launch(
        workflow,
        catalog,
        seconds=60.0,
        create_overlay=lambda: created.append(True) or 1,
        observe=_observe,
        renderer=_Renderer(),
        on_sleep=_publish,
    )
    assert exit_code == 0
    assert created == [True], "the overlay is created once, after revalidation"


def test_the_live_compiled_launch_owns_and_disposes_the_control_bar(
    monkeypatch,
) -> None:
    """Production must not regress to the cursor-only surface the harness exposed."""
    from ghostcursor import run
    from ghostcursor.perception.uia import Element
    from ghostcursor.reasoning import renderer as renderer_module
    from ghostcursor.reasoning.compiled_tour import TickInput

    workflow, catalog = _workflow()
    titles = [
        "Welcome - Visual Studio Code",
        "Welcome - Visual Studio Code",
        "demo - Visual Studio Code",
    ]
    slot = {}

    def _publish():
        title = titles.pop(0) if len(titles) > 1 else titles[0]
        matched = (
            Element(
                name="Open Folder...", control_type="Button", automation_id="",
                bbox=(10, 20, 110, 60), path=("Button",),
            ),
        )
        slot["value"] = TickInput(
            title=title, selectors={"open_folder": matched}, union=matched
        )

    class _Renderer:
        def __init__(self, *args, **kwargs):
            pass

        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    class _Controls:
        hwnd = 77

        def __init__(self):
            self.polls = 0
            self.disposed = False
            self.steps_reported = []

        def poll(self):
            self.polls += 1

        def should_abort(self):
            return False

        def should_pause(self):
            return self.polls == 1

        def report_step(self, index, total):
            self.steps_reported.append((index, total))

        def dispose(self):
            self.disposed = True

    controls = _Controls()
    monkeypatch.setattr(renderer_module, "OverlayRenderer", _Renderer)
    monkeypatch.setattr(
        run, "create_compiled_tour_controls", lambda: controls
    )
    _publish()

    exit_code = _launch(
        workflow,
        catalog,
        seconds=60.0,
        create_overlay=lambda: 1,
        observe=lambda: slot["value"],
        renderer=None,
        on_sleep=_publish,
    )

    assert exit_code == 0
    assert controls.polls >= 2
    assert controls.disposed is True
    # The production launch reports progress to its own rail, not just the
    # harness one -- the two wire the executor separately.
    assert controls.steps_reported == [(0, 1)]


def test_the_production_launch_always_prints_its_timing(capsys) -> None:
    """Every run, not only the failing ones.

    A timeout is the case that needs the marks, and a launch that printed them
    only on failure would leave nothing to compare the bad run against. This
    run SUCCEEDS, and must still say when its landmarks happened.
    """
    from ghostcursor.perception.uia import Element
    from ghostcursor.reasoning.compiled_tour import TickInput

    workflow, catalog = _workflow()
    slot = {"value": None}
    target = Element("Open Folder...", "Button", "", (10, 20, 110, 60))

    titles = iter(
        ["Welcome - Visual Studio Code"] * 3 + ["demo - Visual Studio Code"] * 40
    )

    def _publish():
        # A baseline first, then the changed title: `window_title_matches`
        # verifies a CHANGE, so a title that was always the goal's would time
        # out and the run would never reach the success path being asserted.
        slot["value"] = TickInput(
            title=next(titles, "demo - Visual Studio Code"),
            selectors={"open_folder": (target,)},
            union=(target,),
        )

    class _Renderer:
        def show(self, grounded, instruction_text):
            pass

        def clear(self):
            pass

        def settle(self):
            pass

    _publish()
    exit_code = _launch(
        workflow,
        catalog,
        seconds=60.0,
        create_overlay=lambda: 1,
        observe=lambda: slot["value"],
        renderer=_Renderer(),
        on_sleep=_publish,
    )

    assert exit_code == 0
    printed = capsys.readouterr().out
    assert "timing: " in printed
    assert "first_observation_s=" in printed
    assert "ended_s=" in printed
    assert "nothing recorded" not in printed


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
def test_two_windows_sharing_a_title_still_refuse_usefully() -> None:
    """The live shape, which distinct-title tests do not reach.

    Two Synthetic Export demo windows were up during acceptance and both were
    titled exactly `'Synthetic Export'`. Every other ambiguity test here uses
    distinct titles, so the diagnostic's usefulness in the one case where the
    title cannot separate them was untested.

    The handles are the whole answer here: a message listing two identical
    titles and nothing else tells the operator there is a conflict and gives
    them no way to see which windows, or to act. See
    `docs/superpowers/FOLLOWUPS.md` -- narrowing cannot resolve this shape at
    all, which is why the handles have to be in the message.
    """
    _catalog_, pack, _intent = _catalog()
    windows = [
        _window(hwnd=3607180, title="demo - Visual Studio Code"),
        _window(hwnd=328996, title="demo - Visual Studio Code"),
    ]
    with pytest.raises(WorkflowUnavailable) as caught:
        resolve_target(pack, windows, project_root=PROJECT_ROOT)

    message = str(caught.value)
    assert "3607180" in message and "328996" in message, message
    # And a narrowing cannot rescue it, however specific: the titles are equal,
    # so any pattern matching one matches both.
    with pytest.raises(WorkflowUnavailable) as narrowed:
        resolve_target(
            pack,
            windows,
            target_title_re="^demo - Visual Studio Code$",
            project_root=PROJECT_ROOT,
        )
    assert "even after narrowing" in str(narrowed.value)
    assert "3607180" in str(narrowed.value)


def test_every_production_caller_of_the_executor_consumes_its_timing() -> None:
    """The D076 landmarks must survive the cutover, whatever calls the executor.

    `test_the_production_launch_always_prints_its_timing` pins the launch
    function that exists today. It says nothing about a launch path Task 9
    introduces: a new entry point could call `execute_compiled_workflow` and
    drop `result.timing` on the floor with every existing test still green,
    and the first anyone would know is a timeout nobody could diagnose --
    which is exactly the hole D075 was written to close.

    So the rule is about the CALL, not about one function's name: whatever
    invokes the executor in production must do something with the timing.
    """
    import ast

    modules = [
        PROJECT_ROOT / "ghostcursor" / "run.py",
        PROJECT_ROOT / "ghostcursor" / "devtools" / "candidate_acceptance.py",
    ]

    def result_names_consuming_timing(function: ast.FunctionDef, calls) -> bool:
        """Prove the executor result reaches a timing-aware consumer.

        A caller may print/read ``result.timing`` (the production path), or
        pass the result to ``record_for`` (the acceptance path, which copies
        ``result.timing`` into the persisted record).  Looking for the word
        ``timing`` in source, including docstrings and comments, proves
        neither shape.
        """
        result_names = set()
        for child in ast.walk(function):
            value = None
            targets = ()
            if isinstance(child, ast.Assign):
                value = child.value
                targets = child.targets
            elif isinstance(child, ast.AnnAssign):
                value = child.value
                targets = (child.target,)
            if not isinstance(value, ast.Call) or value not in calls:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    result_names.add(target.id)

        if not result_names:
            return False

        for child in ast.walk(function):
            if isinstance(child, ast.Attribute) and child.attr == "timing":
                if isinstance(child.value, ast.Name) and child.value.id in result_names:
                    return True
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "record_for"
                and any(
                    isinstance(argument, ast.Name)
                    and argument.id in result_names
                    for argument in child.args
                )
            ):
                return True
        return False

    callers = []
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            source = ast.unparse(node)
            if "execute_compiled_workflow(" not in source:
                continue
            # The import statement alone is not a call site.
            calls = [
                child
                for child in ast.walk(node)
                if isinstance(child, ast.Call)
                and getattr(child.func, "id", "") == "execute_compiled_workflow"
            ]
            if calls:
                callers.append(
                    (module.name, node.name, result_names_consuming_timing(node, calls))
                )

    assert callers, "nothing calls the executor: the scan is looking in the wrong place"
    missing = [(m, f) for m, f, uses in callers if not uses]
    assert not missing, (
        f"these call the compiled executor and ignore its timing: {missing}"
    )
