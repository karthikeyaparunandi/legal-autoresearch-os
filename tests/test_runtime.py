from __future__ import annotations

from autoresearch_os.runtime import ResearchRuntime


def test_runtime_writes_truth_maintenance_repo(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=2)

    evaluation = runtime.run("Can AI-generated code be copyrighted in the United States?")

    assert evaluation.citation_grounding >= 0.9
    assert (tmp_path / "gt_repo" / "program.md").exists()
    assert (tmp_path / "gt_repo" / "claims.json").exists()
    assert (tmp_path / "gt_repo" / "evidence" / "iteration_001.json").exists()
    assert (tmp_path / "gt_repo" / "final_report.md").read_text(encoding="utf-8").startswith("# Grounded Research Report")
