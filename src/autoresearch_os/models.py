from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class StopConditions:
    confidence: float = 0.85
    citation_grounding: float = 0.90
    open_questions: int = 2
    objective_completion: float = 0.90


@dataclass
class LegalMetadata:
    domain: str = "legal"
    jurisdiction: str = "United States"
    practice_area: str = "copyright and software"
    authority_hierarchy: list[str] = field(
        default_factory=lambda: [
            "statute",
            "binding_case_law",
            "agency_guidance",
            "persuasive_case_law",
            "secondary_source",
            "expert_analysis",
        ]
    )
    required_source_types: list[str] = field(default_factory=lambda: ["statute", "case_law", "agency_guidance"])
    citation_style: str = "source_id plus URL"
    risk_posture: str = "startup decision support, not legal advice"
    temporal_sensitivity: str = "high"
    uncertainty_policy: str = "Surface unsettled doctrine, jurisdiction limits, and missing primary authority."


@dataclass
class TuningParams:
    supported_claim_threshold: float = 0.70
    contradiction_penalty_weight: float = 0.25
    min_primary_sources: int = 2
    target_source_diversity: int = 4
    gap_task_limit: int = 4
    evaluator_weights: dict[str, float] = field(
        default_factory=lambda: {
            "objective_completion": 0.18,
            "evidence_coverage": 0.12,
            "source_diversity": 0.07,
            "contradiction_resolution": 0.10,
            "citation_grounding": 0.15,
            "mean_claim_confidence": 0.18,
            "primary_authority_coverage": 0.15,
            "confidence_stability": 0.05,
        }
    )
    learning_rate: float = 0.05


@dataclass
class ResearchProgram:
    objective: str
    subquestions: list[str]
    evidence_requirements: list[str]
    success_metrics: list[str]
    stop_conditions: StopConditions = field(default_factory=StopConditions)
    legal_metadata: LegalMetadata = field(default_factory=LegalMetadata)


@dataclass
class Task:
    task_id: str
    title: str
    question: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"


@dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    rationale: str
    status: str = "open"


@dataclass
class Evidence:
    source_id: str
    title: str
    url: str
    source_type: str
    excerpt: str
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    reliability: float = 0.7


@dataclass
class Claim:
    claim_id: str
    claim: str
    supporting_sources: list[str] = field(default_factory=list)
    contradicting_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "untested"
    objective_refs: list[str] = field(default_factory=list)


@dataclass
class Contradiction:
    claim: str
    supporting_sources: list[str]
    contradicting_sources: list[str]
    resolution_status: str = "unresolved"
    note: str = ""


@dataclass
class Evaluation:
    iteration: int
    objective_completion: float
    evidence_coverage: float
    source_diversity: float
    primary_authority_coverage: float
    contradiction_resolution: float
    citation_grounding: float
    mean_claim_confidence: float
    weakest_claim_confidence: float
    confidence_stability: float
    open_question_penalty: float
    confidence_cap: float
    open_question_count: int
    overall_confidence: float


@dataclass
class RunMetrics:
    generated_at: str
    total_runtime_seconds: float
    component_metrics: dict[str, dict[str, float | int]]
    iteration_history: list[dict[str, float | int | str | bool]]
    retrieval_metrics: dict[str, int | bool | list[str] | dict[str, str]]
    agent_traces: list[dict[str, Any]]
    llm_reasoning_enabled: bool
    llm_model: str | None
    iterations_completed: int
    agents_spun_off: int
    agent_breakdown: dict[str, int]
    tasks_count: int
    hypotheses_count: int
    evidence_count: int
    source_type_count: int
    claims_count: int
    supported_claims_count: int
    contradictions_count: int
    resolved_contradictions_count: int
    open_questions_count: int
    final_confidence: float
    stop_conditions_met: bool
    generated_artifacts: list[str]


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(value), indent=2) + "\n", encoding="utf-8")
