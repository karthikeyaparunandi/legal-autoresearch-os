"""Run Jason over LegalBench examples and score labels with a constrained adapter.

This is the Jason-agent counterpart to ``single_shot.py``.  The existing
single-shot benchmark is a direct model baseline; this runner first executes the
Jason truth-repo loop for each item, then asks the requested model to map
Jason's report to one allowed LegalBench label.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/jason_agent.py \
        --task hearsay --model gpt-5.5 --concurrency 24
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from autoresearch_os.llm import _load_api_key  # noqa: E402
from tasks import TASKS, LegalBenchTask  # noqa: E402

DATA_DIR = Path("legalbench_data")
RUNS_DIR = Path("legalbench_runs")
PRICE = {"gpt-5.5": (5.0, 30.0), "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0)}

_print_lock = threading.Lock()
_token_lock = threading.Lock()
_tokens = {"in": 0, "out": 0}


def build_jason_goal(task: LegalBenchTask, row: dict[str, Any]) -> str:
    return (
        f"{task.build_goal(row)}\n\n"
        "Benchmark constraint: this is a LegalBench classification item. "
        f"Allowed final labels: {task.label_instruction()}. "
        "Run Jason's state-driven research loop, but make the final report "
        'state "Final answer label: <one allowed label>" based only on the item above.'
    )


def summarize_results(
    task_config: str,
    model: str,
    runner: str,
    results: list[dict[str, Any]],
    elapsed: float,
    tokens: dict[str, int],
    cost_usd: float,
) -> dict[str, Any]:
    scored = [r for r in results if r.get("error") is None]
    n = len(scored)
    correct = sum(bool(r.get("ok")) for r in scored)
    accuracy = correct / n if n else None

    golds = [str(r.get("gold")) for r in scored]
    classes = sorted(set(golds))
    recalls: list[float] = []
    for cls in classes:
        cls_rows = [r for r in scored if str(r.get("gold")) == cls]
        recalls.append(sum(bool(r.get("ok")) for r in cls_rows) / len(cls_rows))
    balanced_accuracy = sum(recalls) / len(recalls) if recalls else None
    majority = max(classes, key=golds.count) if classes else None
    majority_acc = golds.count(majority) / n if majority else None

    return {
        "task": task_config,
        "model": model,
        "mode": "jason_agent",
        "runner": runner,
        "n": n,
        "errors": len(results) - n,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "balanced_accuracy": round(balanced_accuracy, 4) if balanced_accuracy is not None else None,
        "majority_class": majority,
        "majority_floor": round(majority_acc, 4) if majority_acc is not None else None,
        "per_class_recall": {cls: round(recall, 4) for cls, recall in zip(classes, recalls)},
        "wall_clock_seconds": round(elapsed, 1),
        "tokens": dict(tokens),
        "cost_usd": round(cost_usd, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Jason on a LegalBench task.")
    parser.add_argument("--task", default="hearsay")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--concurrency", type=int, default=24)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--runner", choices=["offline", "sdk"], default="offline")
    args = parser.parse_args()

    os.environ["AUTORESEARCH_MODEL"] = args.model
    task = TASKS[args.task]
    pin, pout = PRICE.get(args.model, (5.0, 30.0))

    key = _load_api_key(Path("."))
    if not key:
        raise SystemExit("Set OPENAI_API_KEY or .env.local before running the Jason LegalBench adapter.")

    data = json.loads((DATA_DIR / f"{task.config}.json").read_text(encoding="utf-8"))
    rows = data["examples"][: args.limit] if args.limit else data["examples"]

    _log(
        f"Jason LegalBench {task.config}: {len(rows)} questions, runner={args.runner}, "
        f"model={args.model}, concurrency={args.concurrency}"
    )
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_run_one, idx, row, task, args, key) for idx, row in enumerate(rows)]
        done = 0
        for future in as_completed(futures):
            results.append(future.result())
            done += 1
            if done % 20 == 0:
                _log(f"  ... {done}/{len(rows)}")

    results.sort(key=lambda r: int(r["idx"]))
    elapsed = time.perf_counter() - started
    cost = _tokens["in"] / 1e6 * pin + _tokens["out"] / 1e6 * pout
    summary = summarize_results(task.config, args.model, args.runner, results, elapsed, dict(_tokens), cost)
    _write_outputs(task, summary, results)

    scored = [r for r in results if r.get("error") is None]
    _log("")
    _log(f"=== {task.config} Jason agent ({args.runner}, {args.model}) ===")
    _log(f"  accuracy            : {summary['accuracy']}  ({sum(r['ok'] for r in scored)}/{summary['n']})")
    _log(f"  balanced accuracy   : {summary['balanced_accuracy']}  per-class={summary['per_class_recall']}")
    _log(f"  majority-class floor: {summary['majority_floor']} (always '{summary['majority_class']}')")
    _log(f"  errors              : {summary['errors']}")
    _log(f"  time / cost         : {summary['wall_clock_seconds']}s / ${summary['cost_usd']}")
    _log(f"  artifacts           : {RUNS_DIR}/jason_agent/summary_{task.config}.json")
    return 0


def _run_one(idx: int, row: dict[str, Any], task: LegalBenchTask, args: argparse.Namespace, api_key: str) -> dict[str, Any]:
    gold = str(row.get("answer"))
    repo_dir = RUNS_DIR / "jason_agent" / task.config / f"ex_{idx:02d}"
    rec: dict[str, Any] = {
        "idx": idx,
        "gold": gold,
        "pred": None,
        "ok": False,
        "error": None,
        "seconds": None,
        "truth_repo": str(repo_dir),
    }
    started = time.perf_counter()
    try:
        goal = build_jason_goal(task, row)
        report, agent_output = _run_jason(goal, repo_dir, args.runner, args.max_iterations, args.model)
        pred = _adapt_label(task, row, report, agent_output, args.model, api_key)
        rec["pred"] = pred
        rec["ok"] = pred is not None and pred.lower() == gold.lower()
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {exc}"
    rec["seconds"] = round(time.perf_counter() - started, 1)
    mark = "Y" if rec["ok"] else ("ERR" if rec["error"] else ".")
    _log(f"  #{idx:02d} gold={gold:<3} pred={str(rec['pred']):<4} ({mark}) {rec['seconds']}s")
    return rec


def _run_jason(goal: str, repo_dir: Path, runner: str, max_iterations: int, model: str) -> tuple[str, str]:
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    if runner == "sdk":
        from jason.agent import run_agent

        output = asyncio.run(run_agent(goal, repo_dir, max_iterations=max_iterations, model=model))
    else:
        from jason.harness import run_offline

        output = json.dumps(run_offline(goal, repo_dir, max_iterations=max_iterations), sort_keys=True)
    report_path = repo_dir / "final_report.md"
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    return report, output


def _adapt_label(
    task: LegalBenchTask,
    row: dict[str, Any],
    report: str,
    agent_output: str,
    model: str,
    api_key: str,
) -> str | None:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = (
        "You are scoring a LegalBench classification item from Jason AutoResearch output.\n"
        f"Allowed labels: {task.label_instruction()}.\n"
        "Return exactly one allowed label and no other text.\n\n"
        f"LegalBench item:\n{task.seed_text(row)[:2500]}\n\n"
        f"Jason final output:\n{agent_output[:1500]}\n\n"
        f"Jason report:\n{report[:6000]}"
    )
    response = _retry(lambda: client.responses.create(model=model, input=prompt), f"adapter#{task.config}")
    usage = getattr(response, "usage", None)
    with _token_lock:
        _tokens["in"] += int(getattr(usage, "input_tokens", 0) or 0)
        _tokens["out"] += int(getattr(usage, "output_tokens", 0) or 0)
    return _match_label(getattr(response, "output_text", ""), task.labels)


def _match_label(raw: str | None, labels: list[str]) -> str | None:
    if not raw:
        return None
    norm = str(raw).strip().strip(".").strip('"').strip("'").lower()
    for label in labels:
        if norm == label.lower():
            return label
    for label in labels:
        if label.lower() in norm:
            return label
    return None


def _retry(fn, what: str, attempts: int = 3, base_delay: float = 5.0):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            msg = str(exc).lower()
            transient = any(
                token in msg
                for token in ("429", "rate limit", "timeout", "timed out", "503", "502", "overloaded", "connection", "reset")
            )
            if attempt == attempts or not transient:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            _log(f"   ! {what}: transient {type(exc).__name__}; retry in {delay:.0f}s")
            time.sleep(delay)
    raise last  # pragma: no cover


def _write_outputs(task: LegalBenchTask, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    out = RUNS_DIR / "jason_agent"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"summary_{task.config}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / f"results_{task.config}.jsonl").write_text(
        "\n".join(json.dumps(result, sort_keys=True) for result in results) + "\n",
        encoding="utf-8",
    )
    (out / f"findings_{task.config}.md").write_text(_findings_markdown(task, summary, results), encoding="utf-8")


def _findings_markdown(task: LegalBenchTask, summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = [
        f"# {task.config}: Jason LegalBench agent ({summary['model']})",
        "",
        f"**Accuracy: {summary['accuracy']}** ({sum(bool(r.get('ok')) for r in results if r.get('error') is None)}/{summary['n']} scored, {summary['errors']} errors).",
        "",
        f"Runner: `{summary['runner']}`. Adapter model: `{summary['model']}`. Cost: `${summary['cost_usd']}`.",
        "",
        "| idx | gold | predicted | correct | seconds | truth repo |",
        "|-----|------|-----------|---------|---------|------------|",
    ]
    for result in results:
        truth_repo = str(result.get("truth_repo", "")).replace("|", "\\|")
        lines.append(
            f"| {result['idx']} | {result['gold']} | {result.get('pred')} | "
            f"{'Y' if result.get('ok') else ''} | {result.get('seconds')} | {truth_repo} |"
        )
    return "\n".join(lines) + "\n"


def _log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
