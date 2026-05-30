"""Compare AutoResearch OS (agent) vs a direct-prompt baseline on a LegalBench task.

For each item, runs BOTH conditions with the same model:
  - baseline : one direct model call -> Yes/No
  - agent    : full AutoResearch OS run (offline) + adapter -> label
Scores both against gold, tracks real token spend, writes a comparison report.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/compare_hearsay.py \
        --task hearsay --model gpt-5.5 --concurrency 6
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).resolve().parent))

DATA_DIR = Path("legalbench_data")
RUNS_DIR = Path("legalbench_runs")

# Pricing per 1M tokens (gpt-5.5 standard).
PRICE = {"gpt-5.5": (5.0, 30.0), "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0)}

_print_lock = threading.Lock()
_tok_lock = threading.Lock()
_tokens = {"agent_in": 0, "agent_out": 0, "base_in": 0, "base_out": 0}


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _ensure_event_loop() -> None:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _retry(fn, what: str, attempts: int = 3, base_delay: float = 5.0):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            msg = str(exc).lower()
            transient = any(s in msg for s in ("429", "rate limit", "timeout", "timed out", "503", "502", "overloaded", "connection", "reset"))
            if i == attempts or not transient:
                raise
            delay = base_delay * (2 ** (i - 1))
            _log(f"   ! {what}: transient ({type(exc).__name__}); retry in {delay:.0f}s")
            time.sleep(delay)
    raise last  # pragma: no cover


def _match(raw, labels):
    if not raw:
        return None
    norm = str(raw).strip().strip(".").lower()
    for label in labels:
        if norm == label.lower():
            return label
    for label in labels:
        if label.lower() in norm:
            return label
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="hearsay")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--feedback-rounds", type=int, default=2)
    args = parser.parse_args()

    # Model must be set BEFORE importing modules that build a CentralReasoner.
    os.environ["AUTORESEARCH_MODEL"] = args.model

    from agents import Runner
    from openai import OpenAI
    from autoresearch_os.llm import CentralReasoner, _load_api_key
    from autoresearch_os.runtime import ResearchRuntime
    from tasks import TASKS

    task = TASKS[args.task]
    pin, pout = PRICE.get(args.model, (5.0, 30.0))
    key = _load_api_key(Path("."))
    client = OpenAI(api_key=key)
    reasoner = CentralReasoner(workspace=Path("."), required=True)

    # Patch Runner.run_sync to accumulate agent-side token usage.
    _orig = Runner.run_sync
    def _wrap(*a, **k):
        r = _orig(*a, **k)
        try:
            u = r.context_wrapper.usage
            with _tok_lock:
                _tokens["agent_in"] += int(getattr(u, "input_tokens", 0) or 0)
                _tokens["agent_out"] += int(getattr(u, "output_tokens", 0) or 0)
        except Exception:
            pass
        return r
    Runner.run_sync = _wrap

    data = __import__("json").loads((DATA_DIR / f"{task.config}.json").read_text())
    rows = data["examples"][: args.limit] if args.limit else data["examples"]

    def baseline(row) -> str | None:
        instr = (
            "Decide whether the following evidence is HEARSAY under the U.S. Federal Rules "
            "of Evidence (an out-of-court statement offered to prove the truth of the matter "
            f"asserted). Answer with exactly one word, one of: {task.label_instruction()}.\n\n"
            f"Evidence: {task.seed_text(row)}"
        )
        resp = _retry(lambda: client.responses.create(model=args.model, input=instr), "baseline")
        u = resp.usage
        with _tok_lock:
            _tokens["base_in"] += int(u.input_tokens or 0)
            _tokens["base_out"] += int(u.output_tokens or 0)
        return _match(resp.output_text, task.labels)

    def agent(row, idx) -> tuple[str | None, float | None]:
        out_dir = RUNS_DIR / "compare" / task.config / f"ex_{idx:02d}"
        rt = ResearchRuntime(out_dir, max_iterations=args.max_iterations, live_retrieval=False,
                             use_llm=True, feedback_rounds=args.feedback_rounds)
        ev = _retry(lambda: rt.run(task.build_goal(row), seed_texts=[task.seed_text(row)]), f"agent#{idx}")
        report = (out_dir / "final_report.md").read_text(encoding="utf-8")
        instr = (f'Based on the agent analysis, choose one: {task.label_instruction()}. '
                 'Return {"label": "<one allowed label>"}.')
        out = _retry(lambda: reasoner.reason_json("legalbench_adapter", instr,
                     {"allowed_labels": task.labels, "item": task.build_goal(row)[:1500],
                      "agent_report": report[:5000]}), f"adapter#{idx}")
        return _match((out or {}).get("label"), task.labels), round(ev.overall_confidence, 3)

    def worker(idx, row) -> dict:
        _ensure_event_loop()
        gold = str(row.get("answer"))
        rec = {"idx": idx, "gold": gold, "baseline": None, "agent": None,
               "agent_conf": None, "base_ok": False, "agent_ok": False, "error": None}
        t0 = time.perf_counter()
        try:
            bp = baseline(row)
            rec["baseline"] = bp
            rec["base_ok"] = bp is not None and bp.lower() == gold.lower()
            ap, conf = agent(row, idx)
            rec["agent"] = ap
            rec["agent_conf"] = conf
            rec["agent_ok"] = ap is not None and ap.lower() == gold.lower()
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["seconds"] = round(time.perf_counter() - t0, 1)
        _log(f"  #{idx:02d} gold={gold:<3} base={rec['baseline']!s:<4}({'Y' if rec['base_ok'] else '.'}) "
             f"agent={rec['agent']!s:<4}({'Y' if rec['agent_ok'] else '.'}) {rec['seconds']}s"
             + (f" ERR={rec['error']}" if rec["error"] else ""))
        return rec

    from concurrent.futures import ThreadPoolExecutor, as_completed
    _log(f"Comparing baseline vs AutoResearch OS on {task.config}: {len(rows)} items, "
         f"model={args.model}, concurrency={args.concurrency}, max_iter={args.max_iterations}, fb={args.feedback_rounds}")
    started = time.perf_counter()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(worker, i, r) for i, r in enumerate(rows)]
        for f in as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: r["idx"])
    elapsed = time.perf_counter() - started

    scored = [r for r in results if r["error"] is None]
    n = len(scored)
    base_acc = sum(r["base_ok"] for r in scored) / n if n else None
    agent_acc = sum(r["agent_ok"] for r in scored) / n if n else None
    golds = [r["gold"] for r in scored]
    majority = max(set(golds), key=golds.count) if golds else None
    majority_acc = (golds.count(majority) / n) if n else None
    agree = sum(1 for r in scored if r["baseline"] == r["agent"]) / n if n else None

    cost = (_tokens["agent_in"] + _tokens["base_in"]) / 1e6 * pin + (_tokens["agent_out"] + _tokens["base_out"]) / 1e6 * pout
    base_cost = _tokens["base_in"] / 1e6 * pin + _tokens["base_out"] / 1e6 * pout
    agent_cost = _tokens["agent_in"] / 1e6 * pin + _tokens["agent_out"] / 1e6 * pout

    import json
    summary = {
        "task": task.config, "model": args.model, "n": n, "errors": len(results) - n,
        "baseline_accuracy": base_acc, "agent_accuracy": agent_acc,
        "majority_class": majority, "majority_baseline_accuracy": majority_acc,
        "agreement": agree, "wall_clock_seconds": round(elapsed, 0),
        "tokens": dict(_tokens),
        "cost_usd": {"total": round(cost, 2), "baseline": round(base_cost, 2), "agent": round(agent_cost, 2)},
    }
    (RUNS_DIR / "compare").mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / "compare" / f"summary_{task.config}.json").write_text(json.dumps(summary, indent=2))
    (RUNS_DIR / "compare" / f"results_{task.config}.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
    _write_findings(task, summary, results)

    _log("")
    _log(f"DONE in {elapsed:.0f}s  cost=${cost:.2f} (baseline ${base_cost:.2f} + agent ${agent_cost:.2f})")
    _log(f"  baseline (direct {args.model}):  acc={base_acc}")
    _log(f"  AutoResearch OS ({args.model}):  acc={agent_acc}")
    _log(f"  majority-class floor:            acc={majority_acc} (always '{majority}')")
    _log(f"  baseline/agent agreement:        {agree}")
    _log(f"Artifacts: {RUNS_DIR}/compare/findings_{task.config}.md")
    return 0


def _write_findings(task, summary, results) -> None:
    s = summary
    lines = [
        f"# {task.config}: AutoResearch OS vs direct baseline ({s['model']})", "",
        f"**{s['n']} items scored** ({s['errors']} errors), {int(s['wall_clock_seconds'])}s, "
        f"spend **${s['cost_usd']['total']}**.", "",
        "| Condition | Accuracy |",
        "|-----------|----------|",
        f"| Direct {s['model']} baseline | **{s['baseline_accuracy']}** |",
        f"| AutoResearch OS ({s['model']}) | **{s['agent_accuracy']}** |",
        f"| Majority-class floor (always '{s['majority_class']}') | {s['majority_baseline_accuracy']} |",
        "",
        f"Baseline/agent agreement: {s['agreement']}. "
        f"Cost split: baseline ${s['cost_usd']['baseline']}, agent ${s['cost_usd']['agent']}.",
        "",
        "## Per-item", "",
        "| idx | gold | baseline | agent | agent conf | both? |",
        "|-----|------|----------|-------|------------|-------|",
    ]
    for r in results:
        flag = "ERR" if r["error"] else ("==" if r["baseline"] == r["agent"] else "≠")
        lines.append(f"| {r['idx']} | {r['gold']} | {r['baseline']}{' ✓' if r['base_ok'] else ''} | "
                     f"{r['agent']}{' ✓' if r['agent_ok'] else ''} | {r['agent_conf']} | {flag} |")
    (RUNS_DIR / "compare" / f"findings_{task.config}.md").write_text("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
