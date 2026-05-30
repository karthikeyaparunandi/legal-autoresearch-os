from __future__ import annotations

from dataclasses import dataclass, field

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
    defects: list[dict] = field(default_factory=list)


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
                    target_metric="citation_grounding",
                    expected_delta=min(0.35, 0.9 - evaluation.citation_grounding),
                    done_condition="Claim has at least one accepted source that directly supports it.",
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
                    target_metric="primary_source_coverage",
                    expected_delta=min(0.3, 0.85 - evaluation.primary_source_coverage),
                    done_condition="Claim has accepted official, statutory, regulatory, or similarly authoritative evidence.",
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
                    target_metric="contradiction_resolution",
                    expected_delta=min(0.25, 0.8 - evaluation.contradiction_resolution),
                    done_condition="Contradiction has a scoped resolution note or a revised claim boundary.",
                )
            )
            next_id += 1

    if evaluation.objective_coverage < 0.9 or evaluation.open_critical_questions > 0:
        candidates.append(
            _task(
                next_id,
                "startup_risk_agent",
                "Close the practical implications, risk, or forecast-uncertainty gap for c004.",
                _priority(
                    confidence_gap=max(0.0, 0.9 - evaluation.objective_coverage),
                    source_gap=0.2,
                    contradiction_gap=0.0,
                    claim_importance=0.25,
                ),
                "startup-risk claim evidence and open-question updates",
                supports_claim="c004",
                target_metric="objective_coverage",
                expected_delta=max(0.1, min(0.3, 0.9 - evaluation.objective_coverage)),
                done_condition="The least-covered practical implication claim has accepted evidence.",
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
    target_metric: str = "",
    expected_delta: float = 0.0,
    cost: float = 1.0,
    uncertainty: float = 0.2,
    done_condition: str = "",
) -> ResearchTask:
    return ResearchTask(
        task_id=f"t{number:03d}",
        agent_type=agent_type,
        goal=goal,
        priority=round(priority, 3),
        expected_output=expected_output,
        supports_claim=supports_claim,
        blocks_contradiction=blocks_contradiction,
        target_metric=target_metric,
        expected_delta=round(expected_delta, 3),
        cost=cost,
        uncertainty=uncertainty,
        done_condition=done_condition,
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
