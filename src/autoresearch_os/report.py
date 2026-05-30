from __future__ import annotations

from .models import Claim, Contradiction, Evaluation, Evidence, ResearchProgram, RunMetrics


def build_report(
    program: ResearchProgram,
    claims: list[Claim],
    evidence: list[Evidence],
    contradictions: list[Contradiction],
    open_questions: list[str],
    evaluation: Evaluation,
    metrics: RunMetrics | None = None,
) -> str:
    evidence_by_id = {item.source_id: item for item in evidence}
    supported_claims = [claim for claim in claims if claim.status == "supported"]
    lines = [
        "# Legal Research Report",
        "",
        "## Question Presented",
        program.objective,
        "",
        "## Short Answer",
        _executive_summary(claims, evaluation),
        "",
        "## Key Findings",
    ]

    display_claims = supported_claims or claims
    for index, claim in enumerate(display_claims, start=1):
        citations = ", ".join(f"[{_citation_label(source_id)}]" for source_id in claim.supporting_sources) or "no citation"
        lines.append(f"{index}. {claim.claim} ({claim.confidence:.0%} confidence; {citations}).")

    lines.extend(
        [
            "",
            "## Reasoning Rationale",
            (
                "The system generated hypotheses, collected legal evidence, criticized the claims for "
                "contradictions, evaluated citation grounding and source quality, then repeated the loop "
                "until the research state stopped improving or satisfied the configured objectives."
            ),
            "",
            "## Sources",
        ]
    )
    for source_id, item in evidence_by_id.items():
        lines.append(f"- [{_citation_label(source_id)}] {item.title}. {item.url}")

    lines.extend(
        [
            "",
            "## Open Questions",
        ]
    )
    lines.extend([f"- {question}" for question in open_questions] or ["- None."])

    if metrics and metrics.raindrop_feedback:
        feedback = metrics.raindrop_feedback
        lines.extend(
            [
                "",
                "## Raindrop Feedback",
                f"- Verdict: {feedback.get('verdict', 'unknown')}",
                f"- Summary: {feedback.get('summary', 'No feedback summary available.')}",
                f"- Trace focus: {', '.join(feedback.get('trace_focus', [])) or 'none'}",
                "",
                "### Recommended Next Steps",
            ]
        )
        lines.extend([f"- {item}" for item in feedback.get("recommendations", [])] or ["- None."])

    lines.extend(
        [
            "",
            "## Appendix: Research Trace",
            f"- Overall confidence: {evaluation.overall_confidence:.0%}",
            f"- Deterministic confidence: {evaluation.deterministic_confidence:.0%}",
            f"- LLM scoring adjustment: {evaluation.llm_score_adjustment:+.0%}" if evaluation.llm_scoring_enabled else "- LLM scoring adjustment: not used",
            f"- Objective completion: {evaluation.objective_completion:.0%}",
            f"- Evidence coverage: {evaluation.evidence_coverage:.0%}",
            f"- Citation grounding: {evaluation.citation_grounding:.0%}",
            f"- Primary authority coverage: {evaluation.primary_authority_coverage:.0%}",
            f"- Contradiction resolution: {evaluation.contradiction_resolution:.0%}",
            f"- Mean claim confidence: {evaluation.mean_claim_confidence:.0%}",
        ]
    )

    if evaluation.llm_scoring_enabled and evaluation.llm_score_rationale:
        lines.extend(["", "### LLM Scoring Audit", evaluation.llm_score_rationale])

    if contradictions:
        lines.extend(["", "### Contradictions"])
        for item in contradictions:
            lines.append(f"- {item.claim}: {item.resolution_status}. {item.note}")
    else:
        lines.extend(["", "### Contradictions", "- No explicit contradictions detected."])

    lines.extend(["", "### All Claims"])
    for claim in claims:
        lines.extend(
            [
                f"- {claim.claim_id}: {claim.claim}",
                f"  Status: {claim.status}; confidence: {claim.confidence:.0%}; supporting sources: {', '.join(f'[{_citation_label(source_id)}]' for source_id in claim.supporting_sources) or 'none'}.",
            ]
        )

    lines.extend(["", "### Metrics"])
    if metrics:
        lines.extend(
            [
                f"- Total runtime: {metrics.total_runtime_seconds:.3f} seconds",
                f"- Iterations completed: {metrics.iterations_completed}",
                f"- Agents spun off: {metrics.agents_spun_off}",
                f"- Tasks generated: {metrics.tasks_count}",
                f"- Hypotheses generated: {metrics.hypotheses_count}",
                f"- Evidence records collected: {metrics.evidence_count}",
                f"- Source categories: {metrics.source_type_count}",
                f"- Claims evaluated: {metrics.claims_count}",
                f"- Supported claims: {metrics.supported_claims_count}",
                f"- Contradictions detected: {metrics.contradictions_count}",
                f"- Contradictions resolved: {metrics.resolved_contradictions_count}",
                f"- Open questions remaining: {metrics.open_questions_count}",
                f"- Stop conditions met: {metrics.stop_conditions_met}",
                f"- Raindrop tracing: {'enabled' if metrics.raindrop_tracing_enabled else 'disabled'}",
                "",
                "### Agent Breakdown",
            ]
        )
        lines.extend([f"- {name}: {count}" for name, count in metrics.agent_breakdown.items()])
    else:
        lines.append("- Metrics unavailable.")

    lines.extend(
        [
            "",
            "## Legal Metadata",
            f"- Jurisdiction: {program.legal_metadata.jurisdiction}",
            f"- Practice area: {program.legal_metadata.practice_area}",
            f"- Risk posture: {program.legal_metadata.risk_posture}",
            f"- Authority hierarchy: {', '.join(program.legal_metadata.authority_hierarchy)}",
            f"- Required source types: {', '.join(program.legal_metadata.required_source_types)}",
        ]
    )

    return "\n".join(lines) + "\n"

def _executive_summary(claims: list[Claim], evaluation: Evaluation) -> str:
    supported = [claim for claim in claims if claim.status == "supported"]
    if not supported:
        return "The runtime did not reach a well-supported conclusion yet."
    answer = " ".join(_claim_with_citations(claim) for claim in supported[:2])
    return (
        f"Based on the cited authorities, the answer is supported at "
        f"{evaluation.overall_confidence:.0%} confidence: {answer}"
    )


def _claim_with_citations(claim: Claim) -> str:
    citations = " ".join(f"[{_citation_label(source_id)}]" for source_id in claim.supporting_sources[:3])
    return f"{claim.claim} {citations}".strip()


def _citation_label(source_id: str) -> str:
    if source_id.startswith("source_"):
        return str(int(source_id.removeprefix("source_")))
    return source_id
