"""Consolidated final report for the hearsay experiment.

Merges:
  - no-research single-shot   (legalbench_runs/single_shot/summary_<task>.json)
  - with-research comparison  (legalbench_runs/compare/summary_<task>.json)
into one markdown report + console table.

Usage:
    .venv/bin/python scripts/legalbench/final_report.py            # task=hearsay
    .venv/bin/python scripts/legalbench/final_report.py --task hearsay
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RUNS = Path("legalbench_runs")


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="hearsay")
    args = ap.parse_args()
    t = args.task

    ss = _load(RUNS / "single_shot" / f"summary_{t}.json")          # no-research
    cmp = _load(RUNS / "compare" / f"summary_{t}.json")             # with-research

    if ss is None:
        print(f"!! no-research summary missing: {RUNS}/single_shot/summary_{t}.json")
    if cmp is None:
        print(f"!! with-research summary missing: {RUNS}/compare/summary_{t}.json "
              "(the with-research run hasn't finished yet — re-run this when it completes)")

    lines = [f"# LegalBench `{t}` — final report (GPT-5.5)", ""]
    lines += ["| Condition | Accuracy | Balanced | Cost | Notes |",
              "|-----------|----------|----------|------|-------|"]

    if ss:
        lines.append(f"| **No research** (single-shot, n={ss['n']}) | "
                     f"**{ss['accuracy']:.3f}** | {ss.get('balanced_accuracy')} | "
                     f"${ss['cost_usd']:.2f} | zero-shot, 1 call/item |")
    if cmp:
        lines.append(f"| Baseline inside compare (n={cmp['n']}) | {cmp['baseline_accuracy']:.3f} | — | "
                     f"${cmp['cost_usd']['baseline']:.2f} | direct call |")
        lines.append(f"| **With research** (AutoResearch OS, n={cmp['n']}) | "
                     f"**{cmp['agent_accuracy']:.3f}** | — | ${cmp['cost_usd']['agent']:.2f} | "
                     f"~7→4 calls/item + adapter |")
    if ss:
        lines.append(f"| Majority-class floor | {ss['majority_floor']:.3f} | — | $0 | always '{ss['majority_class']}' |")
    lines.append("")

    if cmp:
        delta = cmp["agent_accuracy"] - cmp["baseline_accuracy"]
        verdict = ("research HELPED" if delta > 0.005 else
                   "research HURT" if delta < -0.005 else "research made ~no difference")
        lines += [
            "## Head-to-head (same items, with vs without research)", "",
            f"- baseline: **{cmp['baseline_accuracy']:.3f}**, with-research: **{cmp['agent_accuracy']:.3f}** "
            f"(Δ {delta:+.3f}) → **{verdict}**",
            f"- agreement: **{cmp['agreement']:.3f}** (they pick the same answer this often)",
            f"- cost: baseline ${cmp['cost_usd']['baseline']:.2f} vs research ${cmp['cost_usd']['agent']:.2f} "
            f"(~{cmp['cost_usd']['agent']/max(cmp['cost_usd']['baseline'],0.01):.0f}× more for the research loop)",
            "",
        ]
    if ss:
        lines += ["## Context", "",
                  "- LegalBench suite-wide SOTA ≈ 87% (vals.ai); frontier models on hearsay specifically reach high-80s/low-90s with few-shot.",
                  f"- per-class recall (no-research): {ss.get('per_class_recall')}", ""]

    report = "\n".join(lines)
    out = RUNS / f"FINAL_REPORT_{t}.md"
    out.write_text(report)
    print(report)
    print(f"\n(written to {out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
