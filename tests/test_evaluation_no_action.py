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
        "from ghostcursor.run import run_tour\n"
        "run_tour('recipe', 'target', 10)\n"
        "SendInput(1, None, 0)\n",
        encoding="utf-8",
    )

    violations = evaluation_safety_violations(Path(tmp_path))

    assert any("forbidden-import:ghostcursor.run" in item for item in violations)
    assert any("call:run_tour" in item for item in violations)
    assert any("call:SendInput" in item for item in violations)
