from __future__ import annotations

from .scheduler import EvaluationSnapshot


PRIMARY_SOURCE_TYPES = {"statute", "case_law", "agency_guidance", "regulation", "official_material"}


def evaluate_state(state: dict, iteration: int) -> dict:
    claims = state["claims"]
    evidence = state["evidence"]
    contradictions = state["contradictions"]

    claim_count = max(1, len(claims))
    evidence_by_id = evidence
    defects: list[dict] = []
    claims_with_evidence = [
        claim
        for claim in claims.values()
        if any(evidence_by_id.get(evidence_id, {}).get("accepted", False) for evidence_id in claim["supporting_evidence"])
    ]
    claims_with_primary = [
        claim
        for claim in claims.values()
        if any(evidence_by_id.get(evidence_id, {}).get("source_type") in PRIMARY_SOURCE_TYPES for evidence_id in claim["supporting_evidence"])
    ]
    unresolved_contradictions = [item for item in contradictions.values() if not item.get("resolved")]
    weak_claim_ids = [
        claim["claim_id"]
        for claim in claims.values()
        if len(claim["supporting_evidence"]) < 2 or claim["confidence"] < 0.82
    ]
    for claim in claims.values():
        claim_id = claim["claim_id"]
        accepted_support = [
            evidence_by_id.get(evidence_id, {})
            for evidence_id in claim.get("supporting_evidence", [])
            if evidence_by_id.get(evidence_id, {}).get("accepted", False)
        ]
        has_primary = any(item.get("source_type") in PRIMARY_SOURCE_TYPES for item in accepted_support)
        if not accepted_support:
            defects.append(
                {
                    "defect_id": f"missing_evidence:{claim_id}",
                    "kind": "missing_evidence",
                    "claim_id": claim_id,
                    "target_metric": "citation_grounding",
                    "severity": 0.9,
                    "recommendation": "Find directly supporting accepted evidence.",
                }
            )
        if not has_primary:
            defects.append(
                {
                    "defect_id": f"missing_primary:{claim_id}",
                    "kind": "missing_primary_authority",
                    "claim_id": claim_id,
                    "target_metric": "primary_source_coverage",
                    "severity": 0.75,
                    "recommendation": "Find an authoritative source for this claim.",
                }
            )
        if claim["confidence"] < 0.82:
            defects.append(
                {
                    "defect_id": f"low_confidence:{claim_id}",
                    "kind": "low_confidence",
                    "claim_id": claim_id,
                    "target_metric": "objective_coverage",
                    "severity": round(0.82 - claim["confidence"], 3),
                    "recommendation": "Increase confidence through stronger or corroborating evidence.",
                }
            )
    startup_claims = [claim for claim in claims.values() if "startup" in claim["claim"].lower() or claim["claim_id"] == "c004"]
    startup_covered = any(claim["supporting_evidence"] for claim in startup_claims)

    objective_coverage = min(1.0, (len(claims_with_evidence) + (1 if startup_covered else 0)) / max(1, claim_count + 1))
    citation_grounding = len(claims_with_evidence) / claim_count
    primary_source_coverage = len(claims_with_primary) / claim_count
    contradiction_resolution = 1.0 if not contradictions else 1.0 - (len(unresolved_contradictions) / len(contradictions))
    for item in unresolved_contradictions:
        defects.append(
            {
                "defect_id": f"unresolved_contradiction:{item['contradiction_id']}",
                "kind": "unresolved_contradiction",
                "contradiction_id": item["contradiction_id"],
                "claim_id": item.get("claim_id"),
                "target_metric": "contradiction_resolution",
                "severity": 0.8,
                "recommendation": "Resolve the contradiction or scope the affected claim.",
            }
        )
    open_critical_questions = len(weak_claim_ids) + len(unresolved_contradictions)
    open_question_score = max(0.0, 1.0 - (open_critical_questions / 5.0))
    quality_score = round(
        (
            objective_coverage
            + citation_grounding
            + primary_source_coverage
            + contradiction_resolution
            + open_question_score
        )
        / 5.0,
        4,
    )
    status = (
        "stop"
        if objective_coverage >= 0.9
        and citation_grounding >= 0.9
        and primary_source_coverage >= 0.75
        and contradiction_resolution >= 0.8
        and open_critical_questions <= 1
        else "continue"
    )
    return {
        "iteration": iteration,
        "objective_coverage": round(objective_coverage, 2),
        "citation_grounding": round(citation_grounding, 2),
        "primary_source_coverage": round(primary_source_coverage, 2),
        "contradiction_resolution": round(contradiction_resolution, 2),
        "open_critical_questions": open_critical_questions,
        "weak_claim_ids": weak_claim_ids,
        "unresolved_contradiction_ids": [item["contradiction_id"] for item in unresolved_contradictions],
        "defects": defects,
        "quality_score": quality_score,
        "status": status,
    }


def snapshot_from_eval(evaluation: dict) -> EvaluationSnapshot:
    return EvaluationSnapshot(
        objective_coverage=evaluation["objective_coverage"],
        citation_grounding=evaluation["citation_grounding"],
        primary_source_coverage=evaluation["primary_source_coverage"],
        contradiction_resolution=evaluation["contradiction_resolution"],
        open_critical_questions=evaluation["open_critical_questions"],
        weak_claim_ids=evaluation["weak_claim_ids"],
        unresolved_contradiction_ids=evaluation["unresolved_contradiction_ids"],
        defects=evaluation.get("defects", []),
    )
