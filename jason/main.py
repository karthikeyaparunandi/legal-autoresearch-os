from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .agent import run_agent
from .harness import run_offline


DEFAULT_GOAL = (
    "Can AI-generated code be copyrighted in the United States, and what legal risks "
    "would a startup face if it relies heavily on AI-generated software?"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Jason, the state-driven AutoResearch agent.")
    parser.add_argument("goal", nargs="?", default=DEFAULT_GOAL)
    parser.add_argument("--repo", type=Path, default=Path("jason/truth_repo/run"))
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--offline", action="store_true", help="Run deterministic no-API harness.")
    args = parser.parse_args(argv)

    if args.offline:
        result = run_offline(args.goal, args.repo, max_iterations=args.max_iterations)
        print(result)
        return 0

    output = asyncio.run(run_agent(args.goal, args.repo, max_iterations=args.max_iterations))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
