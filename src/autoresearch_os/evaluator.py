from __future__ import annotations

from .models import Claim, Contradiction, Evaluation, Evidence, ResearchProgram, TuningParams


def evaluate(
    iteration: int,
    program: ResearchProgram,
    claims: list[Claim],
    evidence: list[Evidence],
    contradictions: list[Contradiction],
    open_questions: list[str],
    params: TuningParams | None = None,
) -> Evaluation:
    params = params or TuningParams()
    supported_claims = [claim for claim in claims if claim.status == "supported"]
    objective_completion = min(1.0, len(supported_claims) / max(1, len(program.subquestions) - 1))
    evidence_coverage = min(1.0, len(evidence) / max(1, len(program.subquestions)))
    source_types = {item.source_type for item in evidence}
    source_diversity = min(1.0, len(source_types) / params.target_source_diversity)
    resolved = [item for item in contradictions if item.resolution_status == "resolved"]
    contradiction_resolution = 1.0 if not contradictions else len(resolved) / len(contradictions)
    citation_grounding = 0.0 if not claims else sum(1 for claim in claims if claim.supporting_sources) / len(claims)

    weights = params.evaluator_weights
    overall = (
        weights["objective_completion"] * objective_completion
        + weights["evidence_coverage"] * evidence_coverage
        + weights["source_diversity"] * source_diversity
        + weights["contradiction_resolution"] * contradiction_resolution
        + weights["citation_grounding"] * citation_grounding
    )
    return Evaluation(
        iteration=iteration,
        objective_completion=round(objective_completion, 2),
        evidence_coverage=round(evidence_coverage, 2),
        source_diversity=round(source_diversity, 2),
        contradiction_resolution=round(contradiction_resolution, 2),
        citation_grounding=round(citation_grounding, 2),
        open_question_count=len(open_questions),
        overall_confidence=round(overall, 2),
    )


def stop_conditions_met(program: ResearchProgram, evaluation: Evaluation) -> bool:
    stops = program.stop_conditions
    return (
        evaluation.overall_confidence >= stops.confidence
        and evaluation.citation_grounding >= stops.citation_grounding
        and evaluation.open_question_count <= stops.open_questions
        and evaluation.objective_completion >= stops.objective_completion
    )
