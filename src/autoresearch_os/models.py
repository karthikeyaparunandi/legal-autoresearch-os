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
class ResearchProgram:
    objective: str
    subquestions: list[str]
    evidence_requirements: list[str]
    success_metrics: list[str]
    stop_conditions: StopConditions = field(default_factory=StopConditions)


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
    contradiction_resolution: float
    citation_grounding: float
    open_question_count: int
    overall_confidence: float


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
