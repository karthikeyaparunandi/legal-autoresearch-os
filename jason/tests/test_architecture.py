from __future__ import annotations

import json

from jason.harness import run_offline
from jason.memory import EvidenceRecord, ResearchTask, TruthRepo
from jason.scheduler import EvaluationSnapshot, schedule_from_evaluation


def test_truth_repo_uses_append_only_events_and_current_state(tmp_path):
    repo = TruthRepo(tmp_path / "truth_repo")
    repo.write_program(
        objective="Can AI-generated code be copyrighted in the United States?",
        subquestions=["What requires human authorship?"],
        stop_conditions={"citation_grounding": 0.9},
    )
    repo.add_task(
        ResearchTask(
            task_id="t001",
            agent_type="legal_authority_agent",
            goal="Find primary authority on human authorship.",
            priority=0.91,
            expected_output="2 primary-source evidence records",
        )
    )
    repo.upsert_claim("c001", "Pure AI-generated code is unlikely to be copyrightable.", confidence=0.42)
    repo.add_evidence(
        EvidenceRecord(
            evidence_id="e001",
            source_type="agency_guidance",
            title="Copyright Office AI guidance",
            url="https://www.copyright.gov/ai/",
            excerpt="Human authorship is required.",
            supports_claims=["c001"],
            reliability=0.95,
        )
    )

    events = [json.loads(line) for line in (repo.root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    state = repo.load_state()

    assert [event["type"] for event in events] == [
        "program_written",
        "task_created",
        "claim_upserted",
        "evidence_added",
    ]
    assert state["program"]["objective"].startswith("Can AI-generated code")
    assert state["tasks"][0]["agent_type"] == "legal_authority_agent"
    assert state["claims"]["c001"]["supporting_evidence"] == ["e001"]


def test_scheduler_turns_eval_weaknesses_into_targeted_agent_tasks():
    evaluation = EvaluationSnapshot(
        objective_coverage=0.72,
        citation_grounding=0.41,
        primary_source_coverage=0.35,
        contradiction_resolution=0.4,
        open_critical_questions=3,
        weak_claim_ids=["c004"],
        unresolved_contradiction_ids=["k002"],
    )

    tasks = schedule_from_evaluation(evaluation, existing_task_goals=set())

    agent_types = [task.agent_type for task in tasks]
    assert agent_types[:3] == ["citation_verifier_agent", "legal_authority_agent", "contradiction_resolver_agent"]
    assert tasks[0].priority > tasks[-1].priority
    assert any("c004" in task.goal for task in tasks)
    assert any("k002" in task.goal for task in tasks)


def test_offline_parent_loop_spawns_workers_from_measured_state(tmp_path):
    result = run_offline(
        "Can AI-generated code be copyrighted in the United States, and what risks would a startup face?",
        repo_dir=tmp_path / "truth_repo",
        max_iterations=3,
    )

    state = TruthRepo(tmp_path / "truth_repo").load_state()
    spawned_agents = [run["agent_type"] for run in state["agent_runs"]]
    decisions = [event for event in state["events"] if event["type"] == "parent_decision"]

    assert result["iterations"] >= 2
    assert "citation_verifier_agent" in spawned_agents
    assert "legal_authority_agent" in spawned_agents
    assert "startup_risk_agent" in spawned_agents
    assert decisions
    assert state["evals"][-1]["citation_grounding"] >= state["evals"][0]["citation_grounding"]
    assert state["final_report"]["path"].endswith("final_report.md")
