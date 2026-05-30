from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from .evaluator import evaluate_state, snapshot_from_eval
from .harness import DEFAULT_STOP_CONDITIONS, run_offline
from .context_broker import ContextBroker
from .legal_skills import LEGAL_AUTHORITY_HIERARCHY, match_legal_skills
from .memory import ResearchTask, TruthRepo
from .program import build_program_seed
from .scheduler import schedule_from_evaluation
from .workers import run_worker


try:
    from agents import Agent, Runner, function_tool
except ImportError:  # pragma: no cover - exercised only without SDK dependency installed.
    Agent = None
    Runner = None

    def function_tool(func=None, **_kwargs):
        if func is None:
            return lambda wrapped: wrapped
        return func


DEFAULT_MODEL = "gpt-5.5"


@function_tool
def initialize_research_program(goal: str, repo_dir: str) -> str:
    """Create program, initial hypotheses/claims, and baseline memory state."""
    repo = TruthRepo(Path(repo_dir))
    if repo.load_state(include_events=False)["program"]:
        return json.dumps({"status": "already_initialized", "repo_dir": repo_dir})
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
    repo.record_agent_run("hypothesis_agent", "bootstrap", "Created initial competing hypotheses and claim map.")
    return json.dumps({"status": "initialized", "repo_dir": repo_dir})


@function_tool
def read_truth_repo(repo_dir: str) -> str:
    """Read the full Truth Maintenance Repo state as JSON. Use only for debugging small repos."""
    return json.dumps(TruthRepo(Path(repo_dir)).load_state())


@function_tool
def list_legal_skills(goal: str = "") -> str:
    """List Jason legal skills and the ones matched to a legal research goal."""
    matched = {skill.name for skill in match_legal_skills(goal)} if goal else set()
    skills = [
        {
            "name": skill.name,
            "description": skill.description,
            "matched": skill.name in matched,
            "required_source_types": list(skill.required_source_types),
            "output_checks": list(skill.output_checks),
        }
        for skill in match_legal_skills(goal)
    ]
    if not goal:
        from .legal_skills import LEGAL_SKILLS

        skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "matched": False,
                "required_source_types": list(skill.required_source_types),
                "output_checks": list(skill.output_checks),
            }
            for skill in LEGAL_SKILLS
        ]
    return json.dumps(
        {
            "authority_hierarchy": list(LEGAL_AUTHORITY_HIERARCHY),
            "matched_skill_names": sorted(matched),
            "skills": skills,
        }
    )


@function_tool
def read_control_slice(repo_dir: str, budget_bytes: int = 12_000) -> str:
    """Read the bounded parent-loop context slice from the Truth Repo."""
    repo = TruthRepo(Path(repo_dir))
    return json.dumps(ContextBroker(repo).control_slice(budget_bytes=budget_bytes))


@function_tool
def read_claim_context(repo_dir: str, claim_id: str, budget_bytes: int = 24_000) -> str:
    """Read scoped claim context with linked evidence and provenance."""
    repo = TruthRepo(Path(repo_dir))
    return json.dumps(ContextBroker(repo).claim_context(claim_id, budget_bytes=budget_bytes))


@function_tool
def read_contradiction_context(repo_dir: str, contradiction_id: str, budget_bytes: int = 24_000) -> str:
    """Read scoped contradiction context with linked claim/evidence provenance."""
    repo = TruthRepo(Path(repo_dir))
    return json.dumps(ContextBroker(repo).contradiction_context(contradiction_id, budget_bytes=budget_bytes))


@function_tool
def read_task_context(repo_dir: str, task_id: str, budget_bytes: int = 24_000) -> str:
    """Read scoped context for a specific worker task."""
    repo = TruthRepo(Path(repo_dir))
    return json.dumps(ContextBroker(repo).task_context(task_id, budget_bytes=budget_bytes))


def search_truth_repo_evidence_impl(
    repo_dir: str,
    query: str = "",
    source_types: list[str] | None = None,
    claim_id: str | None = None,
    accepted: bool | None = True,
    budget_bytes: int = 24_000,
    limit: int = 10,
) -> str:
    repo = TruthRepo(Path(repo_dir))
    return json.dumps(
        ContextBroker(repo).search_evidence(
            query=query,
            source_types=source_types,
            claim_id=claim_id,
            accepted=accepted,
            budget_bytes=budget_bytes,
            limit=limit,
        )
    )


search_truth_repo_evidence = function_tool(
    search_truth_repo_evidence_impl,
    name_override="search_truth_repo_evidence",
    description_override="Search scoped Truth Repo evidence by query, source type, claim, and acceptance status.",
)


@function_tool
def evaluate_truth_repo(repo_dir: str, iteration: int) -> str:
    """Evaluate research quality and append the score snapshot to memory."""
    repo = TruthRepo(Path(repo_dir))
    evaluation = evaluate_state(repo.load_state(include_events=False), iteration)
    repo.add_eval(evaluation)
    return json.dumps(evaluation)


@function_tool
def schedule_targeted_workers(repo_dir: str, evaluation_json: str) -> str:
    """Turn measured weaknesses into executable worker tasks."""
    repo = TruthRepo(Path(repo_dir))
    evaluation = json.loads(evaluation_json)
    tasks = schedule_from_evaluation(snapshot_from_eval(evaluation), repo.existing_task_goals())
    repo.record_planner_run(int(evaluation.get("iteration", 0)), evaluation, tasks)
    repo.append_event(
        "parent_decision",
        {
            "decision": "spawn_workers" if tasks else "no_new_tasks",
            "reason": _decision_reason(evaluation),
            "alternatives_considered": ["stop", "retry_same_worker", "spawn_targeted_workers"],
            "task_count": len(tasks),
        },
    )
    for task in tasks:
        repo.add_task(task)
    return json.dumps({"created_tasks": [task.__dict__ for task in tasks]})


@function_tool
def run_pending_workers(repo_dir: str, limit: int = 3) -> str:
    """Run the highest-priority pending workers and write outputs to memory."""
    repo = TruthRepo(Path(repo_dir))
    summaries: list[dict[str, Any]] = []
    for task in repo.next_pending_tasks(limit=limit):
        repo.mark_task(task.task_id, "running")
        summary = run_worker(repo, task)
        repo.record_agent_run(task.agent_type, task.task_id, summary)
        repo.mark_task(task.task_id, "completed")
        summaries.append({"task_id": task.task_id, "agent_type": task.agent_type, "summary": summary})
    return json.dumps({"worker_runs": summaries})


@function_tool
def write_final_report(repo_dir: str) -> str:
    """Write the final grounded report from current Truth Repo state."""
    report_path = TruthRepo(Path(repo_dir)).write_final_report()
    return json.dumps({"final_report": str(report_path)})


@function_tool
def run_deterministic_reference_loop(goal: str, repo_dir: str, max_iterations: int = 3) -> str:
    """Run the same state-driven harness without API-dependent model choices."""
    return json.dumps(run_offline(goal, Path(repo_dir), max_iterations=max_iterations))


def build_parent_agent(model: str | None = None):
    if Agent is None:
        raise RuntimeError("Install openai-agents to run the Jason parent agent.")
    return Agent(
        name="Jason Parent Research Agent",
        model=model or os.environ.get("AUTORESEARCH_MODEL", DEFAULT_MODEL),
        instructions=_parent_instructions(),
        tools=[
            initialize_research_program,
            list_legal_skills,
            read_control_slice,
            read_claim_context,
            read_contradiction_context,
            read_task_context,
            search_truth_repo_evidence,
            evaluate_truth_repo,
            schedule_targeted_workers,
            run_pending_workers,
            write_final_report,
            run_deterministic_reference_loop,
        ],
    )


async def run_agent(goal: str, repo_dir: Path, max_iterations: int = 3, model: str | None = None) -> str:
    load_env_file()
    agent = build_parent_agent(model=model)
    prompt = (
        f"Research goal: {goal}\n"
        f"Truth repo directory: {repo_dir}\n"
        f"Maximum iterations: {max_iterations}\n\n"
        "Run the state-driven autoresearch loop. Initialize memory, read the bounded "
        "control slice, evaluate state, spawn targeted workers based on measured weaknesses, run workers, repeat until "
        "stop conditions pass or max iterations is reached, then write the final report. "
        "Return a concise JSON summary with repo path, iterations, final status, and report path."
    )
    result = await Runner.run(agent, prompt)
    return result.final_output


def load_env_file(path: Path | None = None) -> bool:
    candidates = [path] if path else [Path(".env.local"), Path("..") / ".env.local"]
    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        loaded = False
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key == "OPENAI_API_KEY" and value.strip() and not os.environ.get(key):
                os.environ[key] = value.strip().strip('"').strip("'")
                loaded = True
        if loaded:
            return True
    return bool(os.environ.get("OPENAI_API_KEY"))


def _parent_instructions() -> str:
    return """You are Jason, a state-driven autoresearch parent agent.

Your job is not to write an answer immediately. Your job is to drive a Truth
Maintenance Repo toward convergence.

Control loop:
1. Initialize the research program and memory.
2. Evaluate the current research state.
3. If stop conditions fail, schedule targeted workers from measured weaknesses.
4. Run pending workers and inspect how memory changed.
5. Repeat until stop conditions pass or the max iteration budget is reached.
6. Write a final report grounded in the Truth Repo.

Important:
- Use read_control_slice for parent-loop state. Use read_claim_context,
  read_contradiction_context, or read_task_context when a decision needs
  detailed evidence. Use search_truth_repo_evidence to find prior evidence
  before spawning duplicate work. Do not read the full repo unless debugging a small run.
- Spawn workers from concrete gaps, not vibes.
- Do not claim a source supports a claim unless an evidence record says so.
- For legal goals, activate Jason's legal skills: scope jurisdiction and authority
  hierarchy first, distinguish binding authority from guidance or commentary,
  preserve date sensitivity, and flag human-review gates instead of presenting
  the output as legal advice. Use list_legal_skills when you need the matched
  practice-area checks.
- Return concise JSON at the end.
"""


def _decision_reason(evaluation: dict) -> str:
    if evaluation["citation_grounding"] < 0.9:
        return "citation grounding below threshold"
    if evaluation["primary_source_coverage"] < 0.75:
        return "primary source coverage below threshold"
    if evaluation["contradiction_resolution"] < 0.8:
        return "unresolved contradictions remain"
    if evaluation["open_critical_questions"] > 1:
        return "too many open critical questions"
    return "research state has not converged"
