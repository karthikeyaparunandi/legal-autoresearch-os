from __future__ import annotations

import json

from jason.benchmarks.run_benchmark import BenchmarkCase, run_benchmark, run_case


def test_context_pressure_case_measures_full_repo_read_cost(tmp_path):
    case = BenchmarkCase(
        case_id="scale_probe",
        goal="Can AI-generated code be copyrighted in the United States?",
        max_iterations=2,
        required_agents=["hypothesis_agent", "citation_verifier_agent"],
        min_quality_score=0.1,
        scale_records=30,
        max_context_bytes=1_000,
        enforce_context_budget=False,
    )

    result = run_case(case, tmp_path / "runs")

    assert result["passed"] is True
    assert result["quality"]["quality_passed"] is True
    assert result["context"]["evidence_count"] >= 30
    assert result["context"]["events_count"] >= 30
    assert result["context"]["full_state_bytes"] > result["context"]["control_slice_bytes"]
    assert result["context"]["context_budget_passed"] is False
    assert "citation_verifier_agent" in result["quality"]["spawned_agents"]


def test_benchmark_writes_repeatable_json_and_markdown_outputs(tmp_path):
    case = BenchmarkCase(
        case_id="quality_probe",
        goal="Can AI-generated code be copyrighted in the United States?",
        max_iterations=2,
        required_agents=["hypothesis_agent"],
        min_quality_score=0.1,
        scale_records=0,
        max_context_bytes=200_000,
        enforce_context_budget=True,
    )
    output_path = tmp_path / "latest.json"

    summary = run_benchmark([case], tmp_path / "runs", output_path)

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    markdown = output_path.with_suffix(".md").read_text(encoding="utf-8")
    assert summary["passed"] is True
    assert saved["cases"][0]["id"] == "quality_probe"
    assert saved["aggregate"]["case_count"] == 1
    assert "Jason Agent Benchmark" in markdown
