"""Drive AutoResearch OS over LegalBench examples and score it.

For each example we:
  1. Run the FULL agent: ResearchRuntime(...).run(goal, seed_texts=[text]) offline,
     so the example's legal text is the agent's evidence.
  2. Adapter: one constrained LLM call maps the agent's research report to exactly
     one of the task's allowed labels.
  3. Score predicted vs gold; aggregate per-task and overall accuracy.

This repurposes a research runtime as a classifier via the adapter — see findings.md
for the caveats. Examples run concurrently (thread pool); each call has retry/backoff.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/run_benchmark.py \
        --concurrency 6 --max-iterations 1 --feedback-rounds 2
    # smoke test a single example:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/run_benchmark.py \
        --only abercrombie --limit 1 --concurrency 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sys

sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from autoresearch_os.llm import CentralReasoner  # noqa: E402
from autoresearch_os.runtime import ResearchRuntime  # noqa: E402
from tasks import TASKS, LegalBenchTask  # noqa: E402

DATA_DIR = Path("legalbench_data")
RUNS_DIR = Path("legalbench_runs")

_print_lock = threading.Lock()
_results_lock = threading.Lock()
_reasoner = CentralReasoner(workspace=Path("."), required=True)


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _ensure_event_loop() -> None:
    """Agents SDK Runner.run_sync needs an event loop in the calling thread."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _retry(fn, what: str, attempts: int = 3, base_delay: float = 4.0):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - want to retry transient API errors
            last = exc
            msg = str(exc).lower()
            transient = any(s in msg for s in ("429", "rate limit", "timeout", "timed out", "503", "502", "overloaded", "connection"))
            if i == attempts or not transient:
                raise
            delay = base_delay * (2 ** (i - 1))
            _log(f"   ! {what}: transient error ({type(exc).__name__}); retry {i}/{attempts - 1} in {delay:.0f}s")
            time.sleep(delay)
    raise last  # pragma: no cover


def _match_label(raw: str | None, labels: list[str]) -> str | None:
    if not raw:
        return None
    norm = raw.strip().strip(".").lower()
    for label in labels:
        if norm == label.lower():
            return label
    for label in labels:  # tolerate "answer: Yes", "generic mark", etc.
        if label.lower() in norm or norm in label.lower():
            return label
    return None


def _adapt_label(task: LegalBenchTask, goal: str, report_md: str) -> tuple[str | None, str]:
    instruction = (
        f"An autonomous legal-research agent produced the analysis below for a "
        f"{task.answer_noun} task. Based strictly on that analysis, choose the single "
        f"best answer. Allowed labels (return one verbatim): {task.label_instruction()}. "
        'Return JSON {"label": "<one allowed label>", "rationale": "<one sentence>"}.'
    )
    payload = {
        "task": task.config,
        "allowed_labels": task.labels,
        "item": goal[:2000],
        "agent_research_report": report_md[:5000],
    }
    out = _retry(lambda: _reasoner.reason_json("legalbench_adapter", instruction, payload), f"adapter[{task.config}]")
    label = _match_label((out or {}).get("label"), task.labels)
    rationale = str((out or {}).get("rationale", ""))[:200]
    return label, rationale


def run_example(task_name: str, task: LegalBenchTask, idx: int, row: dict, args) -> dict:
    _ensure_event_loop()
    goal = task.build_goal(row)
    seed = task.seed_text(row)
    gold = str(row.get("answer"))
    out_dir = RUNS_DIR / task.config / f"ex_{idx:02d}"
    result = {"task": task.config, "idx": idx, "gold": gold, "predicted": None, "correct": False,
              "confidence": None, "rationale": "", "error": None}
    t0 = time.perf_counter()
    try:
        rt = ResearchRuntime(
            out_dir,
            max_iterations=args.max_iterations,
            live_retrieval=False,
            use_llm=True,
            feedback_rounds=args.feedback_rounds,
        )
        evaluation = _retry(lambda: rt.run(goal, seed_texts=[seed]), f"run[{task.config}#{idx}]")
        result["confidence"] = round(evaluation.overall_confidence, 3)
        report_md = (out_dir / "final_report.md").read_text(encoding="utf-8")
        pred, rationale = _adapt_label(task, goal, report_md)
        result["predicted"] = pred
        result["rationale"] = rationale
        result["correct"] = pred is not None and pred.lower() == gold.lower()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["seconds"] = round(time.perf_counter() - t0, 1)
    mark = "ok " if result["correct"] else ("ERR" if result["error"] else "xx ")
    _log(f"  [{mark}] {task.config}#{idx:02d} gold={gold!r} pred={result['predicted']!r} "
         f"conf={result['confidence']} {result['seconds']}s"
         + (f"  ERROR={result['error']}" if result["error"] else ""))
    return result


def _load_examples(task: LegalBenchTask, limit: int | None) -> list[dict]:
    data = json.loads((DATA_DIR / f"{task.config}.json").read_text(encoding="utf-8"))
    rows = data["examples"]
    return rows[:limit] if limit else rows


def _write_summary(results: list[dict]) -> dict:
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)

    per_task = {}
    for task, rs in by_task.items():
        scored = [r for r in rs if r["error"] is None]
        correct = sum(1 for r in scored if r["correct"])
        confs = [r["confidence"] for r in scored if r["confidence"] is not None]
        per_task[task] = {
            "n": len(rs),
            "scored": len(scored),
            "errors": sum(1 for r in rs if r["error"]),
            "correct": correct,
            "accuracy": round(correct / len(scored), 3) if scored else None,
            "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
        }
    all_scored = [r for r in results if r["error"] is None]
    overall = {
        "total": len(results),
        "scored": len(all_scored),
        "errors": sum(1 for r in results if r["error"]),
        "correct": sum(1 for r in all_scored if r["correct"]),
        "accuracy": round(sum(1 for r in all_scored if r["correct"]) / len(all_scored), 3) if all_scored else None,
    }
    summary = {"overall": overall, "per_task": per_task}
    RUNS_DIR.mkdir(exist_ok=True)
    (RUNS_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RUNS_DIR / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n", encoding="utf-8")
    _write_findings(summary, results)
    return summary


def _write_findings(summary: dict, results: list[dict]) -> None:
    lines = ["# LegalBench × AutoResearch OS — Findings", ""]
    o = summary["overall"]
    lines += [
        f"**Overall accuracy: {o['accuracy']} ({o['correct']}/{o['scored']} scored, {o['errors']} errors)**",
        "",
        "Each item ran the full AutoResearch OS agent (offline; the LegalBench text is the",
        "agent's evidence), then an LLM adapter mapped the agent's report to the task's",
        "label set. This is a research runtime repurposed as a classifier via the adapter —",
        "NOT a leaderboard-comparable score (extra agent+adapter layer; 40-item balanced subset).",
        "",
        "## Per-task accuracy",
        "",
        "| Task | Accuracy | Correct/Scored | Errors | Mean agent confidence |",
        "|------|----------|----------------|--------|-----------------------|",
    ]
    for task, m in summary["per_task"].items():
        lines.append(f"| {task} | {m['accuracy']} | {m['correct']}/{m['scored']} | {m['errors']} | {m['mean_confidence']} |")
    lines += ["", "## Per-task gold vs predicted", ""]
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)
    for task, rs in by_task.items():
        lines.append(f"### {task}")
        lines.append("")
        lines.append("| idx | gold | predicted | correct | conf | rationale |")
        lines.append("|-----|------|-----------|---------|------|-----------|")
        for r in sorted(rs, key=lambda x: x["idx"]):
            rat = (r["rationale"] or r["error"] or "").replace("|", "\\|")[:90]
            lines.append(f"| {r['idx']} | {r['gold']} | {r['predicted']} | {'Y' if r['correct'] else ''} | {r['confidence']} | {rat} |")
        lines.append("")
    (RUNS_DIR / "findings.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", action="append", default=[], help="Restrict to these task configs.")
    parser.add_argument("--limit", type=int, default=None, help="Max examples per task.")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--feedback-rounds", type=int, default=2)
    args = parser.parse_args()

    selected = {k: v for k, v in TASKS.items() if not args.only or v.config in args.only or k in args.only}
    jobs = []
    for name, task in selected.items():
        for idx, row in enumerate(_load_examples(task, args.limit)):
            jobs.append((name, task, idx, row))
    _log(f"Running {len(jobs)} examples across {len(selected)} task(s), "
         f"concurrency={args.concurrency}, max_iterations={args.max_iterations}, feedback_rounds={args.feedback_rounds}")

    results: list[dict] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(run_example, *job, args) for job in jobs]
        for fut in as_completed(futures):
            with _results_lock:
                results.append(fut.result())

    summary = _write_summary(results)
    elapsed = time.perf_counter() - started
    _log("")
    _log(f"DONE in {elapsed:.0f}s. Overall accuracy={summary['overall']['accuracy']} "
         f"({summary['overall']['correct']}/{summary['overall']['scored']}, errors={summary['overall']['errors']})")
    for task, m in summary["per_task"].items():
        _log(f"  {task}: acc={m['accuracy']} ({m['correct']}/{m['scored']}) errors={m['errors']} conf={m['mean_confidence']}")
    _log(f"Artifacts: {RUNS_DIR}/findings.md, summary.json, results.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
