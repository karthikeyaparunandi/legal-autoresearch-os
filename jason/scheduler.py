from __future__ import annotations

from dataclasses import dataclass

from .memory import ResearchTask


@dataclass
class EvaluationSnapshot:
    objective_coverage: float
    citation_grounding: float
    primary_source_coverage: float
    contradiction_resolution: float
    open_critical_questions: int
    weak_claim_ids: list[str]
    unresolved_contradiction_ids: list[str]


def schedule_from_evaluation(evaluation: EvaluationSnapshot, existing_task_goals: set[str]) -> list[ResearchTask]:
    candidates: list[ResearchTask] = []
    next_id = 1

    if evaluation.citation_grounding < 0.9:
        for claim_id in evaluation.weak_claim_ids or ["all weak claims"]:
            candidates.append(
                _task(
                    next_id,
                    "citation_verifier_agent",
                    f"Verify citations and source support for {claim_id}.",
                    _priority(confidence_gap=0.9 - evaluation.citation_grounding, source_gap=0.5, contradiction_gap=0.0),
                    "accepted or rejected evidence support mappings",
                    supports_claim=claim_id if claim_id != "all weak claims" else None,
                )
            )
            next_id += 1

    if evaluation.primary_source_coverage < 0.85:
        for claim_id in evaluation.weak_claim_ids or ["claims missing primary authority"]:
            candidates.append(
                _task(
                    next_id,
                    "legal_authority_agent",
                    f"Find primary legal authority for {claim_id}.",
                    _priority(confidence_gap=0.85 - evaluation.primary_source_coverage, source_gap=0.35, contradiction_gap=0.0),
                    "primary-source evidence records",
                    supports_claim=claim_id if claim_id.startswith("c") else None,
                )
            )
            next_id += 1

    if evaluation.contradiction_resolution < 0.8:
        for contradiction_id in evaluation.unresolved_contradiction_ids or ["unresolved contradictions"]:
            candidates.append(
                _task(
                    next_id,
                    "contradiction_resolver_agent",
                    f"Resolve or scope contradiction {contradiction_id}.",
                    _priority(confidence_gap=0.0, source_gap=0.3, contradiction_gap=0.8 - evaluation.contradiction_resolution, claim_importance=0.25),
                    "resolution note and revised claim scope",
                    blocks_contradiction=contradiction_id if contradiction_id.startswith("k") else None,
                )
            )
            next_id += 1

    if evaluation.objective_coverage < 0.9 or evaluation.open_critical_questions > 0:
        candidates.append(
            _task(
                next_id,
                "startup_risk_agent",
                "Find startup-specific ownership, licensing, provenance, and diligence risks.",
                _priority(
                    confidence_gap=max(0.0, 0.9 - evaluation.objective_coverage),
                    source_gap=0.2,
                    contradiction_gap=0.0,
                    claim_importance=0.25,
                ),
                "startup-risk claim evidence and open-question updates",
                supports_claim="c004",
            )
        )

    unique = [task for task in candidates if task.goal not in existing_task_goals]
    return sorted(unique, key=lambda task: task.priority, reverse=True)


def _task(
    number: int,
    agent_type: str,
    goal: str,
    priority: float,
    expected_output: str,
    supports_claim: str | None = None,
    blocks_contradiction: str | None = None,
) -> ResearchTask:
    return ResearchTask(
        task_id=f"t{number:03d}",
        agent_type=agent_type,
        goal=goal,
        priority=round(priority, 3),
        expected_output=expected_output,
        supports_claim=supports_claim,
        blocks_contradiction=blocks_contradiction,
    )


def _priority(
    confidence_gap: float,
    source_gap: float,
    contradiction_gap: float,
    claim_importance: float = 0.1,
    duplicate_penalty: float = 0.0,
) -> float:
    return max(
        0.0,
        0.35 * confidence_gap
        + 0.25 * source_gap
        + 0.25 * contradiction_gap
        + 0.15 * claim_importance
        - duplicate_penalty,
    )
