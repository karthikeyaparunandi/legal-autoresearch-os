from __future__ import annotations

from pathlib import Path

from .models import Evaluation, TuningParams, to_jsonable
import json


PARAMS_FILE = "tuning_params.json"


def load_tuning_params(out_dir: Path) -> TuningParams:
    path = out_dir / PARAMS_FILE
    if not path.exists():
        return TuningParams()

    raw = json.loads(path.read_text(encoding="utf-8"))
    defaults = TuningParams()
    return TuningParams(
        supported_claim_threshold=raw.get("supported_claim_threshold", defaults.supported_claim_threshold),
        contradiction_penalty_weight=raw.get("contradiction_penalty_weight", defaults.contradiction_penalty_weight),
        min_primary_sources=raw.get("min_primary_sources", defaults.min_primary_sources),
        target_source_diversity=raw.get("target_source_diversity", defaults.target_source_diversity),
        gap_task_limit=raw.get("gap_task_limit", defaults.gap_task_limit),
        evaluator_weights=raw.get("evaluator_weights", defaults.evaluator_weights),
        learning_rate=raw.get("learning_rate", defaults.learning_rate),
    )


def tune_params(params: TuningParams, evaluation: Evaluation) -> TuningParams:
    """Small online tuner that nudges legal research toward unmet quality gates."""
    next_params = TuningParams(**to_jsonable(params))
    lr = next_params.learning_rate

    if evaluation.citation_grounding < 0.9:
        next_params.supported_claim_threshold = _clamp(next_params.supported_claim_threshold + lr, 0.55, 0.9)
        next_params.min_primary_sources = min(4, next_params.min_primary_sources + 1)

    if evaluation.source_diversity < 0.8:
        next_params.target_source_diversity = min(6, next_params.target_source_diversity + 1)

    if evaluation.contradiction_resolution < 0.9:
        next_params.contradiction_penalty_weight = _clamp(next_params.contradiction_penalty_weight + lr, 0.1, 0.5)

    if evaluation.open_question_count > 2:
        next_params.gap_task_limit = min(8, next_params.gap_task_limit + 1)

    if evaluation.overall_confidence >= 0.85 and evaluation.open_question_count <= 2:
        next_params.supported_claim_threshold = _clamp(next_params.supported_claim_threshold - lr / 2, 0.55, 0.9)

    return next_params


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 3)
