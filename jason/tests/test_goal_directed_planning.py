from __future__ import annotations

import json

from jason.harness import run_offline
from jason.memory import TruthRepo
from jason.scheduler import EvaluationSnapshot, schedule_from_evaluation


JAPAN_ELDERLY_PROMPT = (
    "From 2020 to 2050, how many elderly people will there be in Japan? "
    "What is their consumption potential across clothing, food, housing, "
    "and transportation? Produce a market size analysis report."
)


def test_program_initialization_is_goal_specific_not_copyright_fixture(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=1)

    state = TruthRepo(tmp_path / "truth_repo").load_state(include_events=False)
    claims_text = "\n".join(claim["claim"] for claim in state["claims"].values()).lower()

    assert "japan" in claims_text
    assert "elderly" in claims_text or "65" in claims_text
    assert "copyright" not in claims_text
    assert "ai-generated code" not in claims_text


def test_scheduler_attaches_expected_delta_planning_metadata():
    evaluation = EvaluationSnapshot(
        objective_coverage=0.25,
        citation_grounding=0.2,
        primary_source_coverage=0.1,
        contradiction_resolution=1.0,
        open_critical_questions=3,
        weak_claim_ids=["c001"],
        unresolved_contradiction_ids=[],
    )

    tasks = schedule_from_evaluation(evaluation, existing_task_goals=set())

    assert tasks
    assert tasks[0].target_metric in {"citation_grounding", "primary_source_coverage", "objective_coverage"}
    assert tasks[0].expected_delta > 0
    assert tasks[0].done_condition


def test_parent_records_planner_runs_with_selected_and_rejected_candidates(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=1)

    planner_runs_path = tmp_path / "truth_repo" / "planner_runs.jsonl"
    planner_runs = [json.loads(line) for line in planner_runs_path.read_text(encoding="utf-8").splitlines()]

    assert planner_runs
    assert planner_runs[0]["selected_task_ids"]
    assert planner_runs[0]["candidate_count"] >= len(planner_runs[0]["selected_task_ids"])
    assert planner_runs[0]["expected_score_delta"] > 0


def test_final_report_is_grounded_with_inline_citations_and_references(tmp_path):
    result = run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=3)

    report = (tmp_path / "truth_repo" / "final_report.md").read_text(encoding="utf-8")

    assert result["status"] == "stop"
    assert "## References" in report
    assert "[1]" in report
    assert "Japan" in report
    assert "elderly" in report or "65+" in report
    assert "copyright" not in report.lower()


def test_final_report_deduplicates_repeated_reference_urls(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=3)

    report = (tmp_path / "truth_repo" / "final_report.md").read_text(encoding="utf-8")
    reference_lines = [line for line in report.splitlines() if line.startswith("[")]
    urls = [line.rsplit(" ", 1)[-1] for line in reference_lines]

    assert len(urls) == len(set(urls))


def test_final_report_contains_substantive_research_sections(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=3)

    report = (tmp_path / "truth_repo" / "final_report.md").read_text(encoding="utf-8")

    assert "## Methodology" in report
    assert "## Quantitative Model" in report
    assert "| Year |" in report
    assert "## Segment Analysis" in report
    assert "## Actionable Conclusion" in report


def test_worker_evidence_is_validated_before_it_counts(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=1)

    state = TruthRepo(tmp_path / "truth_repo").load_state()
    accepted_evidence = [item for item in state["evidence"].values() if item["accepted"]]
    review_events = [event for event in state["events"] if event["type"] == "evidence_reviewed"]

    assert accepted_evidence
    assert review_events
    assert all(item["validation_status"] == "accepted" for item in accepted_evidence)
    assert all(item["validation_notes"] for item in accepted_evidence)


def test_control_loop_records_states_and_task_outcome_deltas(tmp_path):
    run_offline(JAPAN_ELDERLY_PROMPT, tmp_path / "truth_repo", max_iterations=1)

    state = TruthRepo(tmp_path / "truth_repo").load_state()
    entered_states = [event["state"] for event in state["events"] if event["type"] == "control_state_entered"]
    task_outcomes = [event for event in state["events"] if event["type"] == "task_outcome_recorded"]

    assert entered_states[:4] == ["initialize", "sense", "evaluate", "plan"]
    assert "act" in entered_states
    assert "validate" in entered_states
    assert task_outcomes
    assert all(outcome["score_after"] >= outcome["score_before"] for outcome in task_outcomes)
