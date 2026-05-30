from __future__ import annotations

import json

from autoresearch_os.cli import _format_metrics
from autoresearch_os.runtime import ResearchRuntime


def test_runtime_writes_truth_maintenance_repo(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=2)

    evaluation = runtime.run("Can AI-generated code be copyrighted in the United States?")

    assert evaluation.citation_grounding >= 0.9
    program = (tmp_path / "gt_repo" / "program.md").read_text(encoding="utf-8")
    assert "## Legal Metadata" in program
    assert "## Legal Authority Hierarchy" in program
    assert (tmp_path / "gt_repo" / "legal_metadata.json").exists()
    assert (tmp_path / "gt_repo" / "tuning_params.json").exists()
    metrics = json.loads((tmp_path / "gt_repo" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["agents_spun_off"] >= 14
    assert metrics["hypotheses_count"] == 4
    assert metrics["total_runtime_seconds"] >= 0
    assert (tmp_path / "gt_repo" / "claims.json").exists()
    assert (tmp_path / "gt_repo" / "evidence" / "iteration_001.json").exists()
    report = (tmp_path / "gt_repo" / "final_report.md").read_text(encoding="utf-8")
    assert report.startswith("# Grounded Research Report")
    assert "## Run Metrics" in report
    assert (tmp_path / "gt_repo" / "final_report.pdf").read_bytes().startswith(b"%PDF")


def test_runtime_auto_tunes_params_for_weak_research_state(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1)

    runtime.run("Assess a novel unresolved legal question with no provided sources")

    params = json.loads((tmp_path / "gt_repo" / "tuning_params.json").read_text(encoding="utf-8"))
    assert params["supported_claim_threshold"] > 0.70
    assert params["min_primary_sources"] > 2


def test_cli_metrics_formatter_shows_full_summary():
    output = _format_metrics(
        {
            "generated_at": "2026-05-30T00:00:00+00:00",
            "total_runtime_seconds": 1.23,
            "iterations_completed": 2,
            "agents_spun_off": 24,
            "tasks_count": 5,
            "hypotheses_count": 4,
            "evidence_count": 8,
            "source_type_count": 3,
            "claims_count": 4,
            "supported_claims_count": 3,
            "contradictions_count": 1,
            "resolved_contradictions_count": 1,
            "open_questions_count": 0,
            "final_confidence": 0.87,
            "stop_conditions_met": True,
            "agent_breakdown": {"legal_agent": 2, "critic_agent": 2},
        }
    )

    assert "Final Metrics" in output
    assert "Agents spun off: 24" in output
    assert "Hypotheses generated: 4" in output
    assert "Runtime: 1.230s" in output
    assert "legal_agent: 2" in output
