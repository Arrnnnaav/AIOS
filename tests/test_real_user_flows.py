"""Real-user flows (D186): the messy things a person actually does on the
platform -- typos, empty/garbage input, missing files, wrong formats, bounds,
and a revoked plugin in the catalog. Every path here is deterministic (no
model), so it exercises the error handling a real session hits, not the happy
path the feature tests already cover.
"""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ghostcursor.providers import ExpectedChange, PlanStep, TeachPlan
from ghostcursor.workspace import clips as clips_mod
from ghostcursor.workspace import convert, diffs, kit, palette, pins, snippets, todos
from ghostcursor.workspace.brain import Brain
from ghostcursor.workspace.session import Workspace


# --- the console utility belt under fat-fingered input ------------------------


def test_user_fat_fingers_the_utility_belt():
    # a typo'd command gets a suggestion, not a stack dump
    assert palette.suggest("/covnert")[0] == "/convert"
    assert palette.suggest("/?!?") == []
    # inline calc: a real sum works; nonsense and danger fall through to None
    assert palette.calc("12 * (3 + 4)") == "= 84"
    assert palette.calc("1/0") is None
    assert palette.calc("__import__('os')") is None
    assert palette.calc("lunch at 1pm") is None
    # /x with junk never raises
    assert kit.run("unb64", "not base64!!").startswith("not valid base64")
    assert kit.run("hex2rgb", "#zzz").startswith("want a hex")
    assert kit.run("rgb2hex", "999 0 0").startswith("want three")
    assert kit.run("time", "yesterday").startswith("want a whole")
    assert kit.run("totallymadeup", "x").startswith("unknown op")
    # a bounded password even when the user asks for something silly
    assert len(kit.run("pass", "0")) == 8
    assert len(kit.run("pass", "100000")) == 128


# --- notes/snippets/clips/todos/pins error paths ------------------------------


def test_user_saves_things_with_empty_or_missing_input(tmp_path):
    # snippet with no text is refused with a message, not a traceback
    with pytest.raises(ValueError):
        snippets.save(tmp_path, "sig", "   ")
    assert snippets.get(tmp_path, "never-saved") is None
    assert snippets.remove(tmp_path, "never-saved") is False

    # clipboard history ignores blanks and dupes
    ring = clips_mod.Clips(maxlen=3)
    assert ring.offer("  ") is False
    ring.offer("one")
    assert ring.offer("one") is False
    assert ring.get(99) is None

    # todos: mark/clear on an empty list is harmless
    assert todos.mark(tmp_path, 1) is False
    assert todos.clear_done(tmp_path) == 0
    with pytest.raises(ValueError):
        todos.add(tmp_path, "")

    # pins: empty refused, bound enforced
    with pytest.raises(ValueError):
        pins.add(tmp_path, "")
    for i in range(pins.MAX_PINS):
        pins.add(tmp_path, f"note {i}")
    with pytest.raises(ValueError):
        pins.add(tmp_path, "one too many")


# --- file conversions a user points at the wrong thing ------------------------


def test_user_converts_the_wrong_things(tmp_path):
    missing = tmp_path / "nope.png"
    with pytest.raises((OSError, ValueError, RuntimeError)):
        convert.convert(str(missing), "jpg")

    # an unsupported target is refused clearly
    from PIL import Image

    img = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (1, 2, 3)).save(img)
    with pytest.raises(ValueError):
        convert.convert(str(img), "exe")

    # diff of a file against itself says identical
    same = tmp_path / "x.txt"
    same.write_text("line\n", encoding="utf-8")
    assert diffs.unified(same.read_text(), same.read_text(), "x", "x") == "(identical)"


# --- workspace flow without a model: guards, proposal, scrubbing --------------


class _SilentGateway:
    """A gateway that is 'present' but answers nothing (no model configured)."""

    def complete(self, *a, **k):
        from ghostcursor.providers.errors import FailureKind, ProviderError

        raise ProviderError(FailureKind.UNAVAILABLE, "no model")

    def plan(self, *a, **k):
        from ghostcursor.providers.errors import FailureKind, ProviderError

        raise ProviderError(FailureKind.UNAVAILABLE, "no model")


def test_user_drives_the_workspace_with_no_model(tmp_path):
    brain = Brain(tmp_path / "b.sqlite")
    ws = Workspace("my-project", _SilentGateway(), brain, root=tmp_path / "briefs")

    # asking things when nothing is set up -> clear messages, never a crash
    assert "ask what" in ws.ask("   ", "material")
    assert "no model answered" in ws.ask("real question", "some material")
    assert "no plan" in ws.critique()
    assert "no plan" in ws.todos_from_plan()
    assert "no Company Brain" in ws.related("anything")
    assert "_(no plan yet)_" in ws.export_md()

    # a user pastes a plan with a secret in a step, then exports a handoff:
    # the secret must be scrubbed out of what they would share
    ws._propose(
        TeachPlan(
            (
                PlanStep(
                    "email the key AKIA1234567890ABCDEF", ExpectedChange.TITLE_CHANGES
                ),
            )
        )
    )
    handoff = ws.export_md()
    assert "AKIA1234567890ABCDEF" not in handoff
    # and turning that plan into todos also scrubs
    ws.todos_from_plan()
    assert not any("AKIA1234567890ABCDEF" in t for _i, _d, t in todos.items(ws.root))
    brain.close()


# --- marketplace: a user browses a messy bundle folder and hits a revoked one -


def _key():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, {"release": public}


def _bundle(root, private, *, plugin_id="ghostcursor.one", version="1.0.0"):
    files = {"ghostcursor/packs/index.json": b'{"packs":[],"schema_version":2}\n'}
    manifest = {
        "schema_version": 1,
        "plugin_id": plugin_id,
        "version": version,
        "plugin_api_version": 1,
        "core_compatibility": {"minimum": "0.1.0", "maximum_exclusive": "2.0.0"},
        "applications": [{"kind": "executable", "value": "One.exe"}],
        "signing_key_id": "release",
        "adapter_api": None,
        "files": {n: hashlib.sha256(r).hexdigest() for n, r in files.items()},
    }
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    path = root / f"{plugin_id}-{version}.ghostplugin"
    with zipfile.ZipFile(path, "w") as a:
        a.writestr("plugin.json", raw)
        a.writestr("signature.ed25519", private.sign(raw))
        for n, r in files.items():
            a.writestr(n, r)
    return path


