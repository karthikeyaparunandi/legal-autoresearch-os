from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import ResearchRuntime


DEMO_GOAL = (
    "Can AI-generated code be copyrighted in the United States, and what legal risks "
    "would a startup face if it relies heavily on AI-generated software?"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch", description="Run the AutoResearch OS control loop.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a research program for a goal.")
    run_parser.add_argument("goal")
    run_parser.add_argument("--out", default="gt_repo", type=Path)
    run_parser.add_argument("--max-iterations", default=4, type=int)
    run_parser.add_argument("--seed-text", action="append", default=[])

    demo_parser = subparsers.add_parser("demo", help="Run the built-in legal research demo.")
    demo_parser.add_argument("--out", default="demo_gt_repo", type=Path)
    demo_parser.add_argument("--max-iterations", default=4, type=int)

    args = parser.parse_args(argv)

    if args.command == "demo":
        goal = DEMO_GOAL
        seed_texts: list[str] = []
    else:
        goal = args.goal
        seed_texts = args.seed_text

    runtime = ResearchRuntime(args.out, max_iterations=args.max_iterations)
    evaluation = runtime.run(goal, seed_texts=seed_texts)
    print(f"Research complete: overall_confidence={evaluation.overall_confidence:.0%}")
    print(f"Truth-maintenance repo: {args.out.resolve()}")
    print(f"Final report: {(args.out / 'final_report.md').resolve()}")
    print(f"PDF report: {(args.out / 'final_report.pdf').resolve()}")
    metrics_path = args.out / "metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        print(
            "Metrics: "
            f"agents={metrics['agents_spun_off']}, "
            f"hypotheses={metrics['hypotheses_count']}, "
            f"runtime={metrics['total_runtime_seconds']:.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
