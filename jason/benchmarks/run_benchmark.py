from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable
import argparse
import json
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jason.context_broker import ContextBroker
from jason.harness import run_offline
from jason.memory import TruthRepo


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    goal: str
    max_iterations: int
    required_agents: list[str]
    min_quality_score: float
    scale_records: int
    max_context_bytes: int
    enforce_context_budget: bool

    @classmethod
    def from_json(cls, item: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            case_id=item["id"],
            goal=item["goal"],
            max_iterations=int(item.get("max_iterations", 3)),
            required_agents=list(item.get("required_agents", [])),
            min_quality_score=float(item.get("min_quality_score", 0.0)),
            scale_records=int(item.get("scale_records", 0)),
            max_context_bytes=int(item.get("max_context_bytes", 200_000)),
            enforce_context_budget=bool(item.get("enforce_context_budget", True)),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Jason autoresearch agent benchmarks.")
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmarks" / "cases.jsonl")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "benchmarks" / "results" / "runs")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "results" / "latest.json")
    parser.add_argument(
        "--enforce-context-budget",
        action="store_true",
        help="Fail the process when a case exceeds its full truth-repo read budget.",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.enforce_context_budget:
        cases = [
            BenchmarkCase(
                case_id=case.case_id,
                goal=case.goal,
                max_iterations=case.max_iterations,
                required_agents=case.required_agents,
                min_quality_score=case.min_quality_score,
                scale_records=case.scale_records,
                max_context_bytes=case.max_context_bytes,
                enforce_context_budget=True,
            )
            for case in cases
        ]
    summary = run_benchmark(cases, args.runs_dir, args.output)
    return 0 if summary["passed"] else 1


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            cases.append(BenchmarkCase.from_json(json.loads(stripped)))
    return cases


def run_benchmark(cases: Iterable[BenchmarkCase], runs_dir: Path, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)

    results = [run_case(case, runs_dir) for case in cases]
    summary = {
        "benchmark": "jason-autoresearch-agent",
        "created_at": _now(),
        "passed": all(item["passed"] for item in results),
        "aggregate": _aggregate(results),
        "cases": results,
    }
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_path.with_suffix(".md").write_text(_markdown_summary(summary), encoding="utf-8")
    return summary


def run_case(case: BenchmarkCase, runs_dir: Path) -> dict[str, Any]:
    repo_dir = runs_dir / case.case_id
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    started = perf_counter()
    agent_result = run_offline(case.goal, repo_dir, max_iterations=case.max_iterations)
    agent_runtime_ms = round((perf_counter() - started) * 1000, 3)

    repo = TruthRepo(repo_dir)
    if case.scale_records:
        seed_context_pressure(repo, case.scale_records)

    state = repo.load_state(include_events=True)
    latest_eval = state["evals"][-1] if state["evals"] else {}
    quality = _quality_metrics(case, state, latest_eval)
    context = _context_metrics(repo, case)
    passed = quality["quality_passed"] and (context["context_budget_passed"] or not case.enforce_context_budget)

    return {
        "id": case.case_id,
        "passed": passed,
        "agent_runtime_ms": agent_runtime_ms,
        "agent_result": agent_result,
        "quality": quality,
        "context": context,
        "gates": {
            "min_quality_score": case.min_quality_score,
            "max_context_bytes": case.max_context_bytes,
            "context_budget_enforced": case.enforce_context_budget,
        },
    }


def seed_context_pressure(repo: TruthRepo, record_count: int) -> None:
    evidence_path = repo.root / "evidence.json"
    evidence_items = json.loads(evidence_path.read_text(encoding="utf-8"))
    for index in range(record_count):
        evidence_id = f"noise_{index:05d}"
        evidence_items[evidence_id] = {
            "evidence_id": evidence_id,
            "source_type": "background_noise",
            "title": f"Irrelevant archived research note {index}",
            "url": f"https://example.invalid/archive/{index}",
            "excerpt": (
                "Synthetic benchmark filler that represents stale, unrelated truth-repo memory. "
                "It should not be sent to the model unless a retrieval policy explicitly asks for it."
            ),
            "supports_claims": [],
            "contradicts_claims": [],
            "reliability": 0.1,
            "accepted": False,
        }
    evidence_path.write_text(json.dumps(evidence_items, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    event_path = repo.root / "events.jsonl"
    with event_path.open("a", encoding="utf-8") as handle:
        for index in range(record_count):
            handle.write(
                json.dumps(
                    {
                        "type": "benchmark_noise_recorded",
                        "created_at": _now(),
                        "evidence_id": f"noise_{index:05d}",
                        "note": "Synthetic scale-pressure event for truth-repo context benchmarks.",
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def _quality_metrics(case: BenchmarkCase, state: dict[str, Any], latest_eval: dict[str, Any]) -> dict[str, Any]:
    spawned_agents = sorted({run["agent_type"] for run in state["agent_runs"]})
    required_agents_present = set(case.required_agents).issubset(spawned_agents)
    open_question_score = max(0.0, 1.0 - (float(latest_eval.get("open_critical_questions", 0)) / 5.0))
    component_scores = [
        float(latest_eval.get("objective_coverage", 0.0)),
        float(latest_eval.get("citation_grounding", 0.0)),
        float(latest_eval.get("primary_source_coverage", 0.0)),
        float(latest_eval.get("contradiction_resolution", 0.0)),
        open_question_score,
    ]
    quality_score = round(sum(component_scores) / len(component_scores), 4)
    quality_passed = (
        quality_score >= case.min_quality_score
        and required_agents_present
        and bool(state["final_report"].get("path"))
    )
    return {
        "quality_score": quality_score,
        "quality_passed": quality_passed,
        "latest_eval": latest_eval,
        "spawned_agents": spawned_agents,
        "required_agents_present": required_agents_present,
        "agent_run_count": len(state["agent_runs"]),
        "parent_decision_count": sum(1 for event in state["events"] if event.get("type") == "parent_decision"),
        "final_report_written": bool(state["final_report"].get("path")),
    }


def _context_metrics(repo: TruthRepo, case: BenchmarkCase) -> dict[str, Any]:
    full_started = perf_counter()
    full_state = repo.load_state(include_events=True)
    full_read_ms = round((perf_counter() - full_started) * 1000, 3)

    projection_started = perf_counter()
    projected_state = repo.load_state(include_events=False)
    projection_read_ms = round((perf_counter() - projection_started) * 1000, 3)

    control_slice = ContextBroker(repo).control_slice()
    full_state_bytes = _json_size(full_state)
    projected_state_bytes = _json_size(projected_state)
    control_slice_bytes = _json_size(control_slice)
    ratio = round(full_state_bytes / max(control_slice_bytes, 1), 3)
    return {
        "scale_records": case.scale_records,
        "context_budget_passed": control_slice_bytes <= case.max_context_bytes,
        "legacy_full_context_budget_passed": full_state_bytes <= case.max_context_bytes,
        "full_state_bytes": full_state_bytes,
        "projected_state_bytes": projected_state_bytes,
        "control_slice_bytes": control_slice_bytes,
        "full_to_control_ratio": ratio,
        "full_read_ms": full_read_ms,
        "projection_read_ms": projection_read_ms,
        "claim_count": len(full_state["claims"]),
        "evidence_count": len(full_state["evidence"]),
        "events_count": len(full_state["events"]),
        "task_count": len(full_state["tasks"]),
        "eval_count": len(full_state["evals"]),
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "case_count": 0,
            "passed_count": 0,
            "max_full_state_bytes": 0,
            "max_full_to_control_ratio": 0.0,
            "average_quality_score": 0.0,
        }
    return {
        "case_count": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "max_full_state_bytes": max(item["context"]["full_state_bytes"] for item in results),
        "max_full_to_control_ratio": max(item["context"]["full_to_control_ratio"] for item in results),
        "average_quality_score": round(
            sum(item["quality"]["quality_score"] for item in results) / len(results),
            4,
        ),
    }


def _markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Jason Agent Benchmark",
        "",
        f"- Created: {summary['created_at']}",
        f"- Passed: {summary['passed']}",
        f"- Cases: {summary['aggregate']['passed_count']}/{summary['aggregate']['case_count']}",
        f"- Max full truth-repo read: {summary['aggregate']['max_full_state_bytes']} bytes",
        f"- Max full/control context ratio: {summary['aggregate']['max_full_to_control_ratio']}",
        f"- Average quality score: {summary['aggregate']['average_quality_score']}",
        "",
        "## Cases",
    ]
    for item in summary["cases"]:
        lines.extend(
            [
                "",
                f"### {item['id']}",
                "",
                f"- Passed: {item['passed']}",
                f"- Quality score: {item['quality']['quality_score']}",
                f"- Spawned agents: {', '.join(item['quality']['spawned_agents'])}",
                f"- Full truth-repo read: {item['context']['full_state_bytes']} bytes",
                f"- Control slice: {item['context']['control_slice_bytes']} bytes",
                f"- Full/control ratio: {item['context']['full_to_control_ratio']}",
                f"- Context budget passed: {item['context']['context_budget_passed']}",
            ]
        )
    return "\n".join(lines) + "\n"


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
