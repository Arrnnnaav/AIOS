"""Versioned, human-labelled model-durability dataset loader."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ghostcursor.reasoning.planner import PlanStatus, deterministic_intent, registry


DATASET_PATH = Path(__file__).resolve().parent / "data" / "model_durability_v1.json"
EXPECTED_CATEGORY_COUNTS = {
    "exact_supported": 6,
    "paraphrase": 6,
    "misspelling": 4,
    "ambiguous": 4,
    "near_miss": 5,
    "adversarial": 5,
}


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    family_id: str
    category: str
    goal: str
    expected_raw_intent: str | None
    expected_deterministic_intent: str | None
    expected_final_status: PlanStatus
    expected_final_intent: str | None
    expected_launch_eligible: bool
    previously_probed: bool


@dataclass(frozen=True)
class EvaluationDataset:
    dataset_version: str
    review_status: str
    reviewed_by: str | None
    reviewed_at: str | None
    frozen_before_first_full_baseline_run: bool
    prior_exposure_disclosure: str
    cases: tuple[EvaluationCase, ...]


def load_dataset(
    path: Path = DATASET_PATH, *, require_reviewed: bool = False
) -> EvaluationDataset:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if set(raw) != {"dataset_version", "label_review", "cases"}:
        raise ValueError("dataset must have the exact top-level fields")
    review = raw["label_review"]
    if not isinstance(review, dict) or set(review) != {
        "status",
        "reviewed_by",
        "reviewed_at",
        "frozen_before_first_full_baseline_run",
        "prior_exposure_disclosure",
    }:
        raise ValueError("dataset label_review fields are invalid")
    if require_reviewed and (
        review["status"] != "owner-reviewed"
        or not review["reviewed_by"]
        or not review["reviewed_at"]
        or review["frozen_before_first_full_baseline_run"] is not True
    ):
        raise ValueError("dataset labels are not owner-reviewed and frozen")

    known_intents = set(registry())
    known_statuses = {status.value: status for status in PlanStatus}
    fields = {
        "case_id",
        "family_id",
        "category",
        "goal",
        "expected_raw_intent",
        "expected_deterministic_intent",
        "expected_final_status",
        "expected_final_intent",
        "expected_launch_eligible",
        "previously_probed",
    }
    cases: list[EvaluationCase] = []
    for item in raw["cases"]:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("dataset case fields are invalid")
        for key in ("case_id", "family_id", "category", "goal"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"dataset case has invalid {key}")
        for key in (
            "expected_raw_intent",
            "expected_deterministic_intent",
            "expected_final_intent",
        ):
            if item[key] is not None and item[key] not in known_intents:
                raise ValueError(f"dataset case has unknown {key}")
        if item["expected_final_status"] not in known_statuses:
            raise ValueError("dataset case has unknown final status")
        if not isinstance(item["expected_launch_eligible"], bool) or not isinstance(
            item["previously_probed"], bool
        ):
            raise ValueError("dataset case booleans are invalid")
        actual_deterministic = deterministic_intent(item["goal"])[0]
        if actual_deterministic != item["expected_deterministic_intent"]:
            raise ValueError(
                f"{item['case_id']} deterministic label drifted: "
                f"expected {item['expected_deterministic_intent']!r}, "
                f"got {actual_deterministic!r}"
            )
        cases.append(
            EvaluationCase(
                case_id=item["case_id"],
                family_id=item["family_id"],
                category=item["category"],
                goal=item["goal"],
                expected_raw_intent=item["expected_raw_intent"],
                expected_deterministic_intent=item["expected_deterministic_intent"],
                expected_final_status=known_statuses[item["expected_final_status"]],
                expected_final_intent=item["expected_final_intent"],
                expected_launch_eligible=item["expected_launch_eligible"],
                previously_probed=item["previously_probed"],
            )
        )

    counts = Counter(case.category for case in cases)
    if counts != Counter(EXPECTED_CATEGORY_COUNTS):
        raise ValueError(f"dataset category counts are invalid: {dict(counts)}")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset case_id values must be unique")
    if len(cases) != 30:
        raise ValueError("dataset must contain exactly 30 cases")
    return EvaluationDataset(
        dataset_version=raw["dataset_version"],
        review_status=review["status"],
        reviewed_by=review["reviewed_by"],
        reviewed_at=review["reviewed_at"],
        frozen_before_first_full_baseline_run=review[
            "frozen_before_first_full_baseline_run"
        ],
        prior_exposure_disclosure=review["prior_exposure_disclosure"],
        cases=tuple(cases),
    )
