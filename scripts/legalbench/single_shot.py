"""Single-shot LegalBench benchmark: one model call per question, scored vs gold.

Fast and standard: each question gets ONE direct model call (zero-shot) -> label.
Direct API calls parallelize cleanly (unlike the agent loop), so all 94 finish in
well under a minute.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/single_shot.py \
        --task hearsay --model gpt-5.5 --concurrency 24
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI  # noqa: E402
from autoresearch_os.llm import _load_api_key  # noqa: E402
from tasks import TASKS  # noqa: E402

DATA_DIR = Path("legalbench_data")
RUNS_DIR = Path("legalbench_runs")
PRICE = {"gpt-5.5": (5.0, 30.0), "gpt-5": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0)}

_lock = threading.Lock()
_tok = {"in": 0, "out": 0}
_print_lock = threading.Lock()


def _log(m):
    with _print_lock:
        print(m, flush=True)


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


# Task-specific single-shot instruction (legal grounding kept tight).
INSTRUCTIONS = {
    "hearsay": (
        "You apply the U.S. Federal Rules of Evidence. Hearsay is an out-of-court "
        "statement offered to prove the truth of the matter asserted. Many statements "
        "are NOT hearsay: non-assertive conduct, statements offered for a non-truth "
        "purpose, effect on the listener, legally operative words, or a declarant's own "
        "prior statement under some rules.\n"
        "For the item below, answer with EXACTLY one word: Yes (it is hearsay) or No "
        "(it is not hearsay).\n\nItem: {text}\nAnswer:"
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="hearsay")
    ap.add_argument("--model", default="gpt-5.5")
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    task = TASKS[args.task]
    pin, pout = PRICE.get(args.model, (5.0, 30.0))
    client = OpenAI(api_key=_load_api_key(Path(".")))
    instr_tmpl = INSTRUCTIONS.get(args.task)
    if instr_tmpl is None:
        instr_tmpl = (f"Answer with exactly one of: {task.label_instruction()}.\n\n"
                      "Item: {text}\nAnswer:")

    data = json.loads((DATA_DIR / f"{task.config}.json").read_text())
    rows = data["examples"][: args.limit] if args.limit else data["examples"]

    def one(idx, row):
        gold = str(row.get("answer"))
        prompt = instr_tmpl.format(text=task.seed_text(row))
        rec = {"idx": idx, "gold": gold, "pred": None, "ok": False, "error": None}
        try:
            for attempt in range(3):
                try:
                    resp = client.responses.create(model=args.model, input=prompt)
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    time.sleep(3 * (attempt + 1))
            u = resp.usage
            with _lock:
                _tok["in"] += int(u.input_tokens or 0)
                _tok["out"] += int(u.output_tokens or 0)
            rec["pred"] = _match(resp.output_text, task.labels)
            rec["ok"] = rec["pred"] is not None and rec["pred"].lower() == gold.lower()
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"
        return rec

    _log(f"Single-shot {task.config}: {len(rows)} questions, model={args.model}, concurrency={args.concurrency}")
    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(one, i, r) for i, r in enumerate(rows)]
        done = 0
        for f in as_completed(futs):
            results.append(f.result())
            done += 1
            if done % 20 == 0:
                _log(f"  ... {done}/{len(rows)}")
    results.sort(key=lambda r: r["idx"])
    elapsed = time.perf_counter() - t0

    scored = [r for r in results if r["error"] is None]
    n = len(scored)
    acc = sum(r["ok"] for r in scored) / n if n else None
    golds = [r["gold"] for r in scored]
    maj = max(set(golds), key=golds.count) if golds else None
    maj_acc = golds.count(maj) / n if n else None
    # balanced accuracy (per-class recall average)
    classes = sorted(set(golds))
    recalls = []
    for c in classes:
        cls = [r for r in scored if r["gold"] == c]
        if cls:
            recalls.append(sum(r["ok"] for r in cls) / len(cls))
    bal_acc = sum(recalls) / len(recalls) if recalls else None
    cost = _tok["in"] / 1e6 * pin + _tok["out"] / 1e6 * pout

    summary = {
        "task": task.config, "model": args.model, "mode": "single_shot",
        "n": n, "errors": len(results) - n,
        "accuracy": round(acc, 4) if acc is not None else None,
        "balanced_accuracy": round(bal_acc, 4) if bal_acc is not None else None,
        "majority_class": maj, "majority_floor": round(maj_acc, 4) if maj_acc is not None else None,
        "per_class_recall": {c: round(r, 3) for c, r in zip(classes, recalls)},
        "wall_clock_seconds": round(elapsed, 1),
        "tokens": dict(_tok), "cost_usd": round(cost, 4),
    }
    out = RUNS_DIR / "single_shot"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"summary_{task.config}.json").write_text(json.dumps(summary, indent=2))
    (out / f"results_{task.config}.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")

    _log("")
    _log(f"=== {task.config} single-shot ({args.model}) ===")
    _log(f"  accuracy            : {summary['accuracy']}  ({sum(r['ok'] for r in scored)}/{n})")
    _log(f"  balanced accuracy   : {summary['balanced_accuracy']}  per-class={summary['per_class_recall']}")
    _log(f"  majority-class floor: {summary['majority_floor']} (always '{maj}')")
    _log(f"  errors              : {summary['errors']}")
    _log(f"  time / cost         : {summary['wall_clock_seconds']}s / ${summary['cost_usd']}")
    _log(f"  artifacts           : {out}/summary_{task.config}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
