from __future__ import annotations

from typing import Any

from .models import RunMetrics


def build_raindrop_feedback(metrics: RunMetrics) -> dict[str, Any]:
    """Convert trace-shaped run metrics into concrete next-step feedback."""
    history = metrics.iteration_history
    retrieval = metrics.retrieval_metrics
    recommendations: list[str] = []
    findings: list[str] = []

    if metrics.stop_conditions_met:
        verdict = "converged"
        summary = "The run satisfied the configured stop conditions."
    elif history and history[-1].get("status") == "Plateau":
        verdict = "plateaued"
        summary = "The run stopped because confidence and evidence coverage stopped improving."
    else:
        verdict = "needs_iteration"
        summary = "The run ended before meeting the configured stop conditions."

    if metrics.evidence_count == 0:
        findings.append("No evidence records were collected.")
        recommendations.append("Enable live retrieval or provide seed text/source URLs before trusting the answer.")
    elif retrieval.get("fallback_used"):
        findings.append("The run used fallback evidence.")
        recommendations.append("Run with live retrieval and primary-source URLs to replace fallback evidence with fresh authority.")

    if metrics.supported_claims_count < metrics.claims_count:
        unsupported = metrics.claims_count - metrics.supported_claims_count
        findings.append(f"{unsupported} claim(s) were not supported.")
        recommendations.append("Use the open questions to add targeted retrieval tasks before generating the final report.")

    if metrics.open_questions_count > 0:
        findings.append(f"{metrics.open_questions_count} open question(s) remained.")
        recommendations.append("Increase max iterations or add seed/source material for the unresolved gaps.")

    blocked_sources = int(retrieval.get("blocked_sources", 0) or 0)
    if blocked_sources:
        findings.append(f"{blocked_sources} source(s) were blocked.")
        recommendations.append("Replace blocked URLs with accessible primary sources or cached copies.")

    if metrics.final_confidence < 0.85:
        findings.append(f"Final confidence was {metrics.final_confidence:.0%}, below the default 85% target.")
        recommendations.append("Inspect evaluator_agent and knowledge_gap_detector spans to see which quality gate failed.")

    if not recommendations:
        recommendations.append("Use the report as the decision artifact and keep the Raindrop trace for auditability.")

    return {
        "agent": "raindrop_feedback_agent",
        "verdict": verdict,
        "summary": summary,
        "trace_focus": _trace_focus(metrics),
        "findings": findings or ["No blocking trace issues detected."],
        "recommendations": recommendations,
        "next_run": _next_run_suggestion(metrics),
    }


def _trace_focus(metrics: RunMetrics) -> list[str]:
    focus = ["evaluator_agent", "knowledge_gap_detector", "auto_tuner"]
    if metrics.evidence_count == 0 or metrics.retrieval_metrics.get("fallback_used"):
        focus.insert(0, "knowledge_agent_pool")
    if metrics.supported_claims_count < metrics.claims_count:
        focus.insert(1, "claim_synthesis")
    if metrics.contradictions_count:
        focus.append("critic_agent")
    return list(dict.fromkeys(focus))


def _next_run_suggestion(metrics: RunMetrics) -> dict[str, Any]:
    return {
        "enable_live_retrieval": metrics.evidence_count == 0 or bool(metrics.retrieval_metrics.get("fallback_used")),
        "increase_max_iterations": not metrics.stop_conditions_met and metrics.open_questions_count > 0,
        "add_source_urls": metrics.evidence_count == 0 or int(metrics.retrieval_metrics.get("blocked_sources", 0) or 0) > 0,
        "inspect_spans": _trace_focus(metrics),
    }
