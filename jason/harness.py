from __future__ import annotations

from pathlib import Path

from .evaluator import evaluate_state, snapshot_from_eval
from .memory import ResearchTask, TruthRepo
from .scheduler import schedule_from_evaluation
from .workers import run_worker


DEFAULT_STOP_CONDITIONS = {
    "objective_coverage": 0.9,
    "citation_grounding": 0.9,
    "primary_source_coverage": 0.75,
    "contradiction_resolution": 0.8,
    "open_critical_questions": 1,
}


def run_offline(goal: str, repo_dir: Path, max_iterations: int = 3) -> dict:
    repo = TruthRepo(repo_dir)
    _initialize_research(repo, goal)

    for iteration in range(1, max_iterations + 1):
        evaluation = evaluate_state(repo.load_state(include_events=False), iteration)
        repo.add_eval(evaluation)
        if evaluation["status"] == "stop":
            break

        tasks = schedule_from_evaluation(snapshot_from_eval(evaluation), repo.existing_task_goals())
        decision = {
            "iteration": iteration,
            "decision": "spawn_workers" if tasks else "no_new_tasks",
            "reason": _decision_reason(evaluation),
            "alternatives_considered": ["retry_same_worker", "stop_early", "spawn_targeted_worker"],
            "task_count": len(tasks),
        }
        repo.append_event("parent_decision", decision)
        for task in tasks:
            repo.add_task(task)

        pending = repo.next_pending_tasks(limit=3)
        for task in pending:
            repo.mark_task(task.task_id, "running")
            summary = run_worker(repo, task)
            repo.record_agent_run(task.agent_type, task.task_id, summary)
            repo.mark_task(task.task_id, "completed")

    final_eval = evaluate_state(repo.load_state(include_events=False), max_iterations + 1)
    repo.add_eval(final_eval)
    report_path = repo.write_final_report()
    return {
        "iterations": max_iterations,
        "status": final_eval["status"],
        "final_report": str(report_path),
        "truth_repo": str(repo.root),
    }


def _initialize_research(repo: TruthRepo, goal: str) -> None:
    state = repo.load_state(include_events=False)
    if state["program"]:
        return
    repo.write_program(
        objective=goal,
        subquestions=[
            "What primary authority controls AI-generated code copyrightability?",
            "Which hypotheses distinguish pure AI output from AI-assisted human authorship?",
            "What contradictions or unsettled issues remain?",
            "What startup risks arise from heavy AI-generated code reliance?",
        ],
        stop_conditions=DEFAULT_STOP_CONDITIONS,
    )
    repo.upsert_claim("c001", "Pure AI-generated code is unlikely to be copyrightable without human authorship.", confidence=0.38)
    repo.upsert_claim("c002", "AI-assisted code may be copyrightable when humans contribute expressive control.", confidence=0.48)
    repo.upsert_claim("c003", "The legal boundary depends on prompting versus human selection, arrangement, and editing.", confidence=0.44)
    repo.upsert_claim("c004", "Startups face provenance, licensing, and diligence risks from AI-generated code.", confidence=0.35)
    repo.add_contradiction(
        "k001",
        "c001",
        "Pure AI output is not protectable, but AI-assisted output can contain human-authored expression.",
        resolved=False,
    )
    repo.add_task(
        ResearchTask(
            task_id="t000",
            agent_type="hypothesis_agent",
            goal="Create initial competing hypotheses for the research program.",
            priority=1.0,
            expected_output="initial hypotheses and claim map",
            status="completed",
        )
    )
    repo.record_agent_run("hypothesis_agent", "t000", "Created four initial hypotheses mapped to claims c001-c004.")


def _decision_reason(evaluation: dict) -> str:
    if evaluation["citation_grounding"] < 0.9:
        return "citation grounding below stop condition"
    if evaluation["primary_source_coverage"] < 0.75:
        return "primary source coverage below stop condition"
    if evaluation["contradiction_resolution"] < 0.8:
        return "unresolved contradiction remains"
    if evaluation["open_critical_questions"] > 1:
        return "too many open critical questions"
    return "research state has not converged"
