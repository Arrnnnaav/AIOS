import json
from collections import Counter

import pytest

from ghostcursor.evaluation.dataset import DATASET_PATH, load_dataset


def test_dataset_has_reviewable_versioned_shape_and_required_category_counts():
    dataset = load_dataset()

    assert dataset.dataset_version == "1.0.0-draft"
    assert dataset.review_status == "pending-owner-review"
    assert len(dataset.cases) == 30
    assert Counter(case.category for case in dataset.cases) == Counter(
        {
            "exact_supported": 6,
            "paraphrase": 6,
            "misspelling": 4,
            "ambiguous": 4,
            "near_miss": 5,
            "adversarial": 5,
        }
    )


def test_deploy_confusion_is_human_labelled_as_abstention_and_disclosed():
    dataset = load_dataset()
    case = next(case for case in dataset.cases if case.family_id == "deploy_confusion")

    assert case.goal == "Deploy this project to production"
    assert case.expected_raw_intent is None
    assert case.expected_launch_eligible is False
    assert case.previously_probed is True


def test_pending_labels_cannot_be_loaded_as_trusted_baseline():
    with pytest.raises(ValueError, match="not owner-reviewed"):
        load_dataset(require_reviewed=True)


def test_dataset_detects_deterministic_classifier_drift(tmp_path):
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    raw["cases"][0]["expected_deterministic_intent"] = None
    path = tmp_path / "drift.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="deterministic label drifted"):
        load_dataset(path)


def test_dataset_rejects_unknown_case_fields(tmp_path):
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    raw["cases"][0]["surprise"] = True
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="case fields"):
        load_dataset(path)
