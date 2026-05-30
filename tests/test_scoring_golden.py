from __future__ import annotations

import pytest

from autoresearch_os.evaluator import evaluate
from autoresearch_os.models import Claim, Contradiction, Evidence, ResearchProgram


def test_strong_primary_authority_scores_high_but_not_perfect():
    evaluation = evaluate(
        1,
        _program(),
        [
            _claim("c001", ["source_001", "source_002"], confidence=0.92),
            _claim("c002", ["source_003", "source_004"], confidence=0.9),
        ],
        [
            _evidence("source_001", "statute", ["h001"]),
            _evidence("source_002", "agency_guidance", ["h001"]),
            _evidence("source_003", "case_law", ["h002"]),
            _evidence("source_004", "agency_guidance", ["h002"]),
            _evidence("source_005", "statute", []),
            _evidence("source_006", "case_law", []),
            _evidence("source_007", "agency_guidance", []),
            _evidence("source_008", "regulation", []),
        ],
        [],
        [],
    )

    assert 0.90 <= evaluation.overall_confidence <= 0.96
    assert evaluation.primary_authority_coverage == 1.0
    assert evaluation.citation_grounding == 1.0


def test_local_only_evidence_stays_mid_confidence_even_when_claims_are_supported():
    evaluation = evaluate(
        1,
        _program(),
        [
            _claim("c001", ["source_001", "source_002"], confidence=0.76),
            _claim("c002", ["source_001"], confidence=0.74),
        ],
        [
            _evidence("source_001", "domain_analysis", ["h001", "h002"], url="local://analysis"),
            _evidence("source_002", "expert_analysis", ["h001"], url="local://expert"),
        ],
        [],
        [],
    )

    assert 0.45 <= evaluation.overall_confidence <= 0.60
    assert evaluation.primary_authority_coverage == 0.0
    assert evaluation.citation_grounding == 0.0
    assert evaluation.confidence_cap == 0.88


def test_no_evidence_scores_near_zero():
    evaluation = evaluate(
        1,
        _program(),
        [_claim("c001", [], confidence=0.0, status="weak")],
        [],
        [],
        ["Find primary authority.", "Find supporting evidence."],
    )

    assert 0.0 <= evaluation.overall_confidence <= 0.15
    assert evaluation.evidence_coverage == 0.0
    assert evaluation.citation_grounding == 0.0


def test_unresolved_contradiction_keeps_confidence_below_decision_threshold():
    evaluation = evaluate(
        1,
        _program(),
        [_claim("c001", ["source_001", "source_002"], contradicting=["source_003"], confidence=0.72)],
        [
            _evidence("source_001", "statute", ["h001"]),
            _evidence("source_002", "agency_guidance", ["h001"]),
            _evidence("source_003", "case_law", [], contradicts=["h001"]),
        ],
        [Contradiction("Authorship rule is contested.", ["source_001", "source_002"], ["source_003"])],
        ["Resolve contradiction."],
    )

    assert 0.45 <= evaluation.overall_confidence <= 0.70
    assert evaluation.contradiction_resolution == 0.0
    assert evaluation.citation_grounding == 0.0


def test_blocked_sources_apply_penalty_and_cap():
    clean = evaluate(
        1,
        _program(),
        [_claim("c001", ["source_001", "source_002"], confidence=0.9)],
        [
            _evidence("source_001", "statute", ["h001"]),
            _evidence("source_002", "agency_guidance", ["h001"]),
        ],
        [],
        [],
        retrieval_metrics={"blocked_sources": 0},
    )
    blocked = evaluate(
        1,
        _program(),
        [_claim("c001", ["source_001", "source_002"], confidence=0.9)],
        [
            _evidence("source_001", "statute", ["h001"]),
            _evidence("source_002", "agency_guidance", ["h001"]),
        ],
        [],
        [],
        retrieval_metrics={"blocked_sources": 2},
    )

    assert 0.50 <= blocked.overall_confidence <= 0.80
    assert blocked.blocked_source_penalty == pytest.approx(0.10)
    assert blocked.confidence_cap == 0.80
    assert blocked.overall_confidence < clean.overall_confidence


def _program() -> ResearchProgram:
    return ResearchProgram(
        objective="Can AI-generated code be copyrighted?",
        subquestions=[
            "What legal standard controls authorship?",
            "Which primary authorities apply?",
            "What risk remains?",
        ],
        evidence_requirements=[],
        success_metrics=[],
    )


def _claim(
    claim_id: str,
    supporting: list[str],
    *,
    contradicting: list[str] | None = None,
    confidence: float,
    status: str = "supported",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        claim=f"Golden claim {claim_id}",
        supporting_sources=supporting,
        contradicting_sources=contradicting or [],
        confidence=confidence,
        status=status,
    )


def _evidence(
    source_id: str,
    source_type: str,
    supports: list[str],
    *,
    contradicts: list[str] | None = None,
    url: str | None = None,
) -> Evidence:
    return Evidence(
        source_id=source_id,
        title=f"Golden source {source_id}",
        url=url or f"https://example.test/{source_id}",
        source_type=source_type,
        excerpt="Human authorship and legal authority are discussed.",
        supports=supports,
        contradicts=contradicts or [],
        reliability=0.9,
    )
