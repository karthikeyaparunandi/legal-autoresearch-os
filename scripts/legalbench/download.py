"""Download a small, LABEL-BALANCED sample from LegalBench via the HF
datasets-server JSON API (no auth, no `datasets` library).

LegalBench test splits are sorted by label, so naive head-sampling yields one
class only. We pull from the head and tail (and, for the small 5-way abercrombie
task, the whole split), group by gold label, and take an even slice per label.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/legalbench/download.py --per-task 10
Saves legalbench_data/<config>.json
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tasks import TASKS  # noqa: E402

BASE = "https://datasets-server.huggingface.co"
DATASET = "nguha/legalbench"
DATA_DIR = Path("legalbench_data")


def _get(path: str, params: dict) -> dict:
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "autoresearch-legalbench/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rows(config: str, offset: int, length: int) -> list[dict]:
    data = _get("rows", {"dataset": DATASET, "config": config, "split": "test", "offset": offset, "length": length})
    return [item["row"] for item in data.get("rows", [])]


def _test_size(config: str) -> int:
    data = _get("size", {"dataset": DATASET, "config": config})
    for split in data.get("size", {}).get("splits", []):
        if split.get("split") == "test":
            return int(split.get("num_rows", 0))
    return 0


def _balanced_sample(config: str, per_task: int) -> list[dict]:
    total = _test_size(config)
    window = max(per_task * 6, 60)
    if total <= 100:
        pool = _rows(config, 0, total)
        if per_task >= total:  # caller wants the whole split
            return pool
    else:
        head = _rows(config, 0, min(window, 100))
        tail = _rows(config, max(0, total - window), min(window, 100))
        pool = head + tail

    by_label: dict[str, list[dict]] = {}
    for row in pool:
        by_label.setdefault(str(row.get("answer")), []).append(row)

    labels = sorted(by_label)
    if not labels:
        return []
    # distribute per_task across labels as evenly as possible
    base, extra = divmod(per_task, len(labels))
    sample: list[dict] = []
    for i, label in enumerate(labels):
        take = base + (1 if i < extra else 0)
        sample.extend(by_label[label][:take])
    return sample


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-task", type=int, default=10)
    parser.add_argument("--only", action="append", default=[], help="Restrict to these task configs/names.")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    selected = {k: v for k, v in TASKS.items() if not args.only or v.config in args.only or k in args.only}
    for name, task in selected.items():
        sample = _balanced_sample(task.config, args.per_task)
        dist: dict[str, int] = {}
        for row in sample:
            dist[str(row.get("answer"))] = dist.get(str(row.get("answer")), 0) + 1
        out = {
            "config": task.config,
            "labels": task.labels,
            "count": len(sample),
            "label_distribution": dist,
            "examples": sample,
        }
        path = DATA_DIR / f"{task.config}.json"
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"{name}: {len(sample)} examples  dist={dist}  -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
