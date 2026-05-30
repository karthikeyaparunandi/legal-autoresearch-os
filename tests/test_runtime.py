from __future__ import annotations

import json

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
    assert (tmp_path / "gt_repo" / "claims.json").exists()
    assert (tmp_path / "gt_repo" / "evidence" / "iteration_001.json").exists()
    assert (tmp_path / "gt_repo" / "final_report.md").read_text(encoding="utf-8").startswith("# Grounded Research Report")


def test_runtime_auto_tunes_params_for_weak_research_state(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1)

    runtime.run("Assess a novel unresolved legal question with no provided sources")

    params = json.loads((tmp_path / "gt_repo" / "tuning_params.json").read_text(encoding="utf-8"))
    assert params["supported_claim_threshold"] > 0.70
    assert params["min_primary_sources"] > 2
