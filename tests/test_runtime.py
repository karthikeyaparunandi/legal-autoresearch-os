from __future__ import annotations

import json

from autoresearch_os.cli import _format_metrics, _terminal_link
from autoresearch_os.retrieval import fetch_url_text
from autoresearch_os.runtime import ResearchRuntime


def test_runtime_writes_truth_maintenance_repo(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=2, live_retrieval=False)

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
    assert metrics["component_metrics"]["evidence_collection"]["agents"] > 0
    assert metrics["iteration_history"]
    assert metrics["iteration_history"][-1]["status"] in {"Continue", "Converged"}
    assert metrics["retrieval_metrics"]["enabled"] is False
    assert (tmp_path / "gt_repo" / "claims.json").exists()
    assert (tmp_path / "gt_repo" / "evidence" / "iteration_001.json").exists()
    report = (tmp_path / "gt_repo" / "final_report.md").read_text(encoding="utf-8")
    assert report.startswith("# Grounded Research Report")
    assert "## Run Metrics" in report
    html = (tmp_path / "gt_repo" / "final_report.html").read_text(encoding="utf-8")
    assert "<title>AutoResearch OS Grounded Legal Research Report</title>" in html
    assert "Reasoning and rationale path" in html
    assert "<h2>Convergence Progress</h2>" in html
    assert "<h2>Component Metrics</h2>" in html
    assert "<h2>Live Retrieval</h2>" in html
    assert 'href="#source_001"' in html
    assert 'id="source_001"' in html
    assert (tmp_path / "gt_repo" / "final_report.pdf").read_bytes().startswith(b"%PDF")


def test_runtime_auto_tunes_params_for_weak_research_state(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=False)

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
            "retrieval_metrics": {
                "enabled": True,
                "attempted_urls": 3,
                "successful_urls": 2,
                "failed_urls": 1,
                "fallback_used": False,
                "retrieved_urls": ["https://example.test"],
                "errors": {},
            },
            "iteration_history": [
                {
                    "iteration": 1,
                    "overall_confidence": 0.54,
                    "objective_completion": 0.5,
                    "citation_grounding": 0.9,
                    "open_questions": 3,
                    "status": "Continue",
                },
                {
                    "iteration": 2,
                    "overall_confidence": 0.87,
                    "objective_completion": 0.9,
                    "citation_grounding": 1.0,
                    "open_questions": 0,
                    "status": "Converged",
                },
            ],
            "agent_breakdown": {"legal_agent": 2, "critic_agent": 2},
        }
    )

    assert "Final Metrics" in output
    assert "Agent Breakdown" in output
    assert "Convergence Progress" in output
    assert "Live Retrieval" in output
    assert "Agents spun off" in output
    assert "24" in output
    assert "Hypotheses" in output
    assert "1.230s" in output
    assert "legal_agent" in output


def test_terminal_link_points_to_file(tmp_path):
    path = tmp_path / "final_report.html"
    link = _terminal_link(path, str(path))

    assert path.as_uri() in link
    assert "final_report.html" in link


def test_fetch_url_text_extracts_local_html(tmp_path):
    html = tmp_path / "source.html"
    html.write_text(
        "<html><head><title>Legal Source</title><style>bad</style></head>"
        "<body><h1>Copyright authorship</h1><p>Human authorship matters.</p></body></html>",
        encoding="utf-8",
    )

    title, text = fetch_url_text(html.as_uri())

    assert title == "Legal Source"
    assert "Human authorship matters." in text
    assert "bad" not in text
