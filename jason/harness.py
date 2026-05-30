from __future__ import annotations

from pathlib import Path

from .evaluator import evaluate_state, snapshot_from_eval
from .memory import ResearchTask, TruthRepo
from .program import build_program_seed
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
    repo.append_event("control_state_entered", {"state": "initialize", "iteration": 0})
    _initialize_research(repo, goal)

    for iteration in range(1, max_iterations + 1):
        repo.append_event("control_state_entered", {"state": "sense", "iteration": iteration})
        state = repo.load_state(include_events=False)

        repo.append_event("control_state_entered", {"state": "evaluate", "iteration": iteration})
        evaluation = evaluate_state(state, iteration)
        repo.add_eval(evaluation)
        if evaluation["status"] == "stop" and not _has_actionable_gaps(evaluation):
            break

        repo.append_event("control_state_entered", {"state": "plan", "iteration": iteration})
        tasks = schedule_from_evaluation(snapshot_from_eval(evaluation), repo.existing_task_goals())
        repo.record_planner_run(iteration, evaluation, tasks)
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

        pending = repo.next_pending_tasks(limit=4)
        for task in pending:
            repo.append_event("control_state_entered", {"state": "act", "iteration": iteration, "task_id": task.task_id})
            before_eval = evaluate_state(repo.load_state(include_events=False), iteration)
            repo.mark_task(task.task_id, "running")
            summary = run_worker(repo, task)
            repo.record_agent_run(task.agent_type, task.task_id, summary)
            repo.mark_task(task.task_id, "completed")
            repo.append_event("control_state_entered", {"state": "validate", "iteration": iteration, "task_id": task.task_id})
            after_eval = evaluate_state(repo.load_state(include_events=False), iteration)
            repo.append_event(
                "task_outcome_recorded",
                {
                    "iteration": iteration,
                    "task_id": task.task_id,
                    "agent_type": task.agent_type,
                    "target_metric": task.target_metric,
                    "expected_delta": task.expected_delta,
                    "score_before": _quality_score(before_eval),
                    "score_after": _quality_score(after_eval),
                    "target_before": before_eval.get(task.target_metric) if task.target_metric else None,
                    "target_after": after_eval.get(task.target_metric) if task.target_metric else None,
                },
            )

    final_eval = evaluate_state(repo.load_state(include_events=False), max_iterations + 1)
    repo.add_eval(final_eval)
    repo.append_event("control_state_entered", {"state": "stop", "iteration": max_iterations})
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
    seed = build_program_seed(goal)
    repo.write_program(
        objective=seed.objective,
        subquestions=seed.subquestions,
        stop_conditions=seed.stop_conditions,
    )
    for claim in seed.claims:
        repo.upsert_claim(claim.claim_id, claim.claim, confidence=claim.confidence)
    for contradiction in seed.contradictions:
        repo.add_contradiction(
            contradiction.contradiction_id,
            contradiction.claim_id,
            contradiction.note,
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


def _quality_score(evaluation: dict) -> float:
    open_question_score = max(0.0, 1.0 - (float(evaluation.get("open_critical_questions", 0)) / 5.0))
    components = [
        float(evaluation.get("objective_coverage", 0.0)),
        float(evaluation.get("citation_grounding", 0.0)),
        float(evaluation.get("primary_source_coverage", 0.0)),
        float(evaluation.get("contradiction_resolution", 0.0)),
        open_question_score,
    ]
    return round(sum(components) / len(components), 4)


def _has_actionable_gaps(evaluation: dict) -> bool:
    return bool(evaluation.get("weak_claim_ids") or evaluation.get("unresolved_contradiction_ids"))
