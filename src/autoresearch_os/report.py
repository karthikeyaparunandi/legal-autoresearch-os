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
    lines = [
        "# Grounded Research Report",
        "",
        "## Executive Summary",
        _executive_summary(claims, evaluation),
        "",
        "## Objective",
        program.objective,
        "",
        "## Findings",
    ]

    for claim in claims:
        lines.extend(
            [
                f"### {claim.claim_id}: {claim.claim}",
                f"- Status: {claim.status}",
                f"- Confidence: {claim.confidence:.0%}",
                f"- Supporting sources: {', '.join(claim.supporting_sources) or 'None'}",
                f"- Contradicting sources: {', '.join(claim.contradicting_sources) or 'None'}",
                "",
            ]
        )

    lines.extend(["## Evidence Table", "| Source | Type | Reliability | Excerpt |", "| --- | --- | ---: | --- |"])
    for item in evidence:
        lines.append(f"| {item.source_id}: [{item.title}]({item.url}) | {item.source_type} | {item.reliability:.0%} | {item.excerpt} |")

    lines.extend(["", "## Contradictions"])
    if contradictions:
        for item in contradictions:
            lines.append(f"- {item.claim}: {item.resolution_status}. {item.note}")
    else:
        lines.append("- No explicit contradictions detected.")

    lines.extend(
        [
            "",
            "## Confidence Scores",
            f"- Objective completion: {evaluation.objective_completion:.0%}",
            f"- Evidence coverage: {evaluation.evidence_coverage:.0%}",
            f"- Source diversity: {evaluation.source_diversity:.0%}",
            f"- Primary authority coverage: {evaluation.primary_authority_coverage:.0%}",
            f"- Contradiction resolution: {evaluation.contradiction_resolution:.0%}",
            f"- Citation grounding: {evaluation.citation_grounding:.0%}",
            f"- Mean claim confidence: {evaluation.mean_claim_confidence:.0%}",
            f"- Weakest claim confidence: {evaluation.weakest_claim_confidence:.0%}",
            f"- Confidence stability: {evaluation.confidence_stability:.0%}",
            f"- Open-question penalty: -{evaluation.open_question_penalty:.0%}",
            f"- Blocked-source penalty: -{evaluation.blocked_source_penalty:.0%}",
            f"- Confidence cap: {evaluation.confidence_cap:.0%}",
            f"- Overall confidence: {evaluation.overall_confidence:.0%}",
            "",
            "## Run Metrics",
        ]
    )
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
            "## Limitations",
            "- This prototype uses deterministic baseline agents and a small built-in evidence fixture for the demo domain.",
            "- A production deployment should replace the fixture with live legal, academic, web, and company-intelligence search agents.",
            "",
            "## Open Questions",
        ]
    )
    lines.extend([f"- {question}" for question in open_questions] or ["- None."])

    lines.extend(["", "## Source List"])
    for source_id, item in evidence_by_id.items():
        lines.append(f"- {source_id}: {item.title}. {item.url}")

    return "\n".join(lines) + "\n"


def _executive_summary(claims: list[Claim], evaluation: Evaluation) -> str:
    supported = [claim.claim for claim in claims if claim.status == "supported"]
    if not supported:
        return "The runtime did not reach a well-supported conclusion yet."
    return (
        f"The current research state supports {len(supported)} core findings with "
        f"{evaluation.overall_confidence:.0%} overall confidence. The strongest answer is: "
        + " ".join(supported[:2])
    )
