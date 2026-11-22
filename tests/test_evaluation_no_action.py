import pytest
from pathlib import Path

from ghostcursor.evaluation.safety import (
    assert_evaluation_is_read_only,
    evaluation_safety_violations,
)


def test_evaluation_package_has_no_tour_or_input_synthesis_path():
    result = assert_evaluation_is_read_only()

    assert result["violations"] == []
    assert result["third_party_recursive_scan"] is False


def test_evaluation_scan_rejects_tour_import_and_input_call(tmp_path):
    module = tmp_path / "bad.py"
    module.write_text(
        "from ghostcursor.harness.act import perform\n"
        "run_tour('recipe', 'target', 10)\n"
        "SendInput(1, None, 0)\n",
        encoding="utf-8",
    )

    violations = evaluation_safety_violations(Path(tmp_path))

    assert any("forbidden-import:ghostcursor.harness.act" in item for item in violations)
    assert any("call:run_tour" in item for item in violations)
    assert any("call:SendInput" in item for item in violations)


@pytest.mark.parametrize(
    "source",
    [
        "send = user32.SendInput\nsend(1)\n",
        "from ctypes.windll.user32 import SendInput as s\n",
        "getattr(user32, 'SendInput')(1)\n",
        "import importlib\nimportlib.import_module('ghostcursor.harness.act')\n",
    ],
)
def test_an_aliased_or_dynamic_input_call_is_still_caught(tmp_path, source):
    from ghostcursor.evaluation.safety import evaluation_safety_violations

    (tmp_path / "sneaky.py").write_text(source, encoding="utf-8")
    assert evaluation_safety_violations(tmp_path)


def test_a_relative_import_cannot_slip_past_the_scan(tmp_path):
    (tmp_path / "bad.py").write_text("from ..run import run_tour" + chr(10), encoding="utf-8")
    assert any("relative-import" in v for v in evaluation_safety_violations(Path(tmp_path)))
