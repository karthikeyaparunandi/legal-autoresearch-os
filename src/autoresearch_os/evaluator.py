from __future__ import annotations

from .models import Claim, Contradiction, Evaluation, Evidence, ResearchProgram, TuningParams


PRIMARY_SOURCE_TYPES = {"statute", "case_law", "binding_case_law", "agency_guidance", "regulation", "official_material"}


def evaluate(
    iteration: int,
    program: ResearchProgram,
    claims: list[Claim],
    evidence: list[Evidence],
    contradictions: list[Contradiction],
    open_questions: list[str],
    params: TuningParams | None = None,
    previous_evaluation: Evaluation | None = None,
    retrieval_metrics: dict | None = None,
) -> Evaluation:
    params = params or TuningParams()
    evidence_by_id = {item.source_id: item for item in evidence}
    supported_claims = [claim for claim in claims if claim.status == "supported"]
    objective_completion = min(1.0, len(supported_claims) / max(1, len(program.subquestions) - 1))
    evidence_coverage = min(1.0, len(evidence) / max(1, len(program.subquestions)))
    source_types = {item.source_type for item in evidence}
    source_diversity = min(1.0, len(source_types) / params.target_source_diversity)
    resolved = [item for item in contradictions if item.resolution_status == "resolved"]
    contradiction_resolution = 1.0 if not contradictions else len(resolved) / len(contradictions)
    mean_claim_confidence = sum(claim.confidence for claim in claims) / max(1, len(claims))
    weakest_claim_confidence = min((claim.confidence for claim in claims), default=0.0)
    primary_authority_coverage = _primary_authority_coverage(claims, evidence_by_id)
    citation_grounding = _strict_citation_grounding(claims, evidence_by_id)
    confidence_stability = _confidence_stability(previous_evaluation, mean_claim_confidence)
    open_question_penalty = min(0.25, len(open_questions) * 0.05)
    blocked_source_penalty = _blocked_source_penalty(retrieval_metrics)

    weights = params.evaluator_weights
    overall = (
        weights["objective_completion"] * objective_completion
        + weights["evidence_coverage"] * evidence_coverage
        + weights["source_diversity"] * source_diversity
        + weights["contradiction_resolution"] * contradiction_resolution
        + weights["citation_grounding"] * citation_grounding
        + weights.get("mean_claim_confidence", 0.0) * mean_claim_confidence
        + weights.get("primary_authority_coverage", 0.0) * primary_authority_coverage
        + weights.get("confidence_stability", 0.0) * confidence_stability
    )
    overall = max(0.0, overall - open_question_penalty - blocked_source_penalty)
    confidence_cap = _confidence_cap(claims, evidence, retrieval_metrics)
    overall = min(overall, confidence_cap)
    return Evaluation(
        iteration=iteration,
        objective_completion=round(objective_completion, 2),
        evidence_coverage=round(evidence_coverage, 2),
        source_diversity=round(source_diversity, 2),
        primary_authority_coverage=round(primary_authority_coverage, 2),
        contradiction_resolution=round(contradiction_resolution, 2),
        citation_grounding=round(citation_grounding, 2),
        mean_claim_confidence=round(mean_claim_confidence, 2),
        weakest_claim_confidence=round(weakest_claim_confidence, 2),
        confidence_stability=round(confidence_stability, 2),
        open_question_penalty=round(open_question_penalty, 2),
        blocked_source_penalty=round(blocked_source_penalty, 2),
        confidence_cap=round(confidence_cap, 2),
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


def _strict_citation_grounding(claims: list[Claim], evidence_by_id: dict[str, Evidence]) -> float:
    if not claims:
        return 0.0

    grounded = 0
    for claim in claims:
        supporting_sources = [evidence_by_id[source_id] for source_id in claim.supporting_sources if source_id in evidence_by_id]
        has_primary_source = any(_is_primary_source(item) for item in supporting_sources)
        has_enough_sources = len(supporting_sources) >= 2
        if has_primary_source and has_enough_sources and not claim.contradicting_sources:
            grounded += 1
        elif has_primary_source and has_enough_sources and claim.confidence >= 0.8:
            grounded += 1
    return grounded / len(claims)


def _primary_authority_coverage(claims: list[Claim], evidence_by_id: dict[str, Evidence]) -> float:
    if not claims:
        return 0.0
    claims_with_primary_support = 0
    for claim in claims:
        supporting_sources = [evidence_by_id[source_id] for source_id in claim.supporting_sources if source_id in evidence_by_id]
        if any(_is_primary_source(item) for item in supporting_sources):
            claims_with_primary_support += 1
    return claims_with_primary_support / len(claims)


def _confidence_stability(previous_evaluation: Evaluation | None, mean_claim_confidence: float) -> float:
    if previous_evaluation is None:
        return 0.0
    delta = abs(previous_evaluation.mean_claim_confidence - mean_claim_confidence)
    return max(0.0, 1.0 - min(1.0, delta * 3))


def _blocked_source_penalty(retrieval_metrics: dict | None) -> float:
    if not retrieval_metrics:
        return 0.0
    return min(0.20, int(retrieval_metrics.get("blocked_sources", 0)) * 0.05)


def _confidence_cap(claims: list[Claim], evidence: list[Evidence], retrieval_metrics: dict | None = None) -> float:
    cap = 0.98
    if len(evidence) < 8:
        cap = min(cap, 0.90)
    if any(item.url.startswith("local://") for item in evidence):
        cap = min(cap, 0.88)
    if any(claim.confidence < 0.70 for claim in claims):
        cap = min(cap, 0.84)
    if any(claim.status != "supported" for claim in claims):
        cap = min(cap, 0.82)
    if retrieval_metrics and int(retrieval_metrics.get("blocked_sources", 0)) > 0:
        cap = min(cap, 0.80)
    return cap


def _is_primary_source(item: Evidence) -> bool:
    return item.source_type in PRIMARY_SOURCE_TYPES
