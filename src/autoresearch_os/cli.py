from __future__ import annotations

import argparse
import json
from pathlib import Path

from .llm import LLMConfigurationError, LLMReasoningError
from .runtime import ResearchRuntime


DEMO_GOAL = (
    "Can AI-generated code be copyrighted in the United States, and what legal risks "
    "would a startup face if it relies heavily on AI-generated software?"
)


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoresearch", description="Run the AutoResearch OS control loop.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a research program for a goal.")
    run_parser.add_argument("goal")
    run_parser.add_argument("--out", default="gt_repo", type=Path)
    run_parser.add_argument("--max-iterations", default=4, type=int)
    run_parser.add_argument("--seed-text", action="append", default=[])
    run_parser.add_argument("--source-url", action="append", default=[], help="Additional live source URL to retrieve.")
    run_parser.add_argument("--offline", action="store_true", help="Disable live retrieval and use local fallback evidence.")
    run_parser.add_argument("--with-llm", action="store_true", help="Enable central LLM reasoning; requires OPENAI_API_KEY or OPEN_API_KEY.")

    demo_parser = subparsers.add_parser("demo", help="Run the built-in legal research demo.")
    demo_parser.add_argument("--out", default="demo_gt_repo", type=Path)
    demo_parser.add_argument("--max-iterations", default=4, type=int)
    demo_parser.add_argument("--source-url", action="append", default=[], help="Additional live source URL to retrieve.")
    demo_parser.add_argument("--offline", action="store_true", help="Disable live retrieval and use local fallback evidence.")
    demo_parser.add_argument("--with-llm", action="store_true", help="Enable central LLM reasoning; requires OPENAI_API_KEY or OPEN_API_KEY.")

    args = parser.parse_args(argv)

    if args.command == "demo":
        goal = DEMO_GOAL
        seed_texts: list[str] = []
    else:
        goal = args.goal
        seed_texts = args.seed_text

    runtime = ResearchRuntime(
        args.out,
        max_iterations=args.max_iterations,
        live_retrieval=not args.offline,
        source_urls=args.source_url,
        use_llm=args.with_llm,
    )
    try:
        evaluation = runtime.run(goal, seed_texts=seed_texts)
    except (LLMConfigurationError, LLMReasoningError) as exc:
        print(f"{BOLD}{RED}LLM reasoning failed{RESET}: {exc}")
        print(f"{DIM}Set OPENAI_API_KEY or OPEN_API_KEY, or omit --with-llm for deterministic fallback.{RESET}")
        return 2
    metrics_path = args.out / "metrics.json"
    html_path = (args.out / "final_report.html").resolve()
    pdf_path = (args.out / "final_report.pdf").resolve()
    md_path = (args.out / "final_report.md").resolve()
    print(f"{BOLD}{GREEN}Research complete{RESET} {DIM}overall_confidence={evaluation.overall_confidence:.0%}{RESET}")
    print(f"{CYAN}HTML report:{RESET} {_terminal_link(html_path, str(html_path))}")
    print(f"{DIM}Markdown:{RESET} {md_path}")
    print(f"{DIM}PDF:{RESET} {pdf_path}")
    print(f"{DIM}Truth-maintenance repo:{RESET} {args.out.resolve()}")
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        print(_format_metrics(metrics))
    return 0


def _format_metrics(metrics: dict) -> str:
    summary_rows = [
        ("Generated at", metrics["generated_at"]),
        ("Runtime", f"{metrics['total_runtime_seconds']:.3f}s"),
        ("Iterations", metrics["iterations_completed"]),
        ("Agents spun off", metrics["agents_spun_off"]),
        ("Hypotheses", metrics["hypotheses_count"]),
        ("Tasks", metrics["tasks_count"]),
        ("Evidence records", metrics["evidence_count"]),
        ("Source categories", metrics["source_type_count"]),
        ("Claims", f"{metrics['supported_claims_count']} supported / {metrics['claims_count']} total"),
        (
            "Contradictions",
            f"{metrics['resolved_contradictions_count']} resolved / {metrics['contradictions_count']} detected",
        ),
        ("Open questions", metrics["open_questions_count"]),
        ("Final confidence", f"{metrics['final_confidence']:.0%}"),
        ("Stop conditions met", metrics["stop_conditions_met"]),
        ("LLM reasoning", "enabled" if metrics.get("llm_reasoning_enabled") else "fallback"),
        ("LLM model", metrics.get("llm_model") or "none"),
    ]
    retrieval = metrics.get("retrieval_metrics", {})
    retrieval_rows = [
        ("Live retrieval", "enabled" if retrieval.get("enabled") else "disabled"),
        ("URLs attempted", retrieval.get("attempted_urls", 0)),
        ("URLs retrieved", retrieval.get("successful_urls", 0)),
        ("Fallback used", retrieval.get("fallback_used", False)),
    ]
    agent_rows = [(name, count) for name, count in metrics["agent_breakdown"].items()]
    trace_rows = [
        (
            trace["name"],
            ", ".join(trace["tools"]),
            len(trace["steps"]),
            "yes" if trace["used_llm"] else "no",
        )
        for trace in metrics.get("agent_traces", [])
    ]
    history_rows = [
        (
            item["iteration"],
            f"{item['overall_confidence']:.0%}",
            f"{item['objective_completion']:.0%}",
            f"{item['citation_grounding']:.0%}",
            f"{item.get('primary_authority_coverage', 0):.0%}",
            f"{item.get('mean_claim_confidence', 0):.0%}",
            item["open_questions"],
            item["status"],
        )
        for item in metrics.get("iteration_history", [])
    ]
    return "\n".join(
        [
            "",
            f"{BOLD}{CYAN}Final Metrics{RESET}",
            _table(("Metric", "Value"), summary_rows),
            "",
            f"{BOLD}{CYAN}Convergence Progress{RESET}",
            _wide_table(
                ("Iter", "Confidence", "Objective", "Citations", "Primary", "Claim Conf", "Open Qs", "Status"),
                history_rows,
            ),
            "",
            f"{BOLD}{CYAN}Live Retrieval{RESET}",
            _table(("Metric", "Value"), retrieval_rows),
            "",
            f"{BOLD}{YELLOW}Agent Breakdown{RESET}",
            _table(("Agent", "Count"), agent_rows),
            "",
            f"{BOLD}{YELLOW}Agent Tool Loops{RESET}",
            _wide_table(("Agent", "Tools", "Steps", "LLM"), trace_rows),
        ]
    )


def _table(headers: tuple[str, str], rows: list[tuple[str, object]]) -> str:
    text_rows = [(str(left), str(right)) for left, right in rows]
    left_width = max(len(headers[0]), *(len(row[0]) for row in text_rows))
    right_width = max(len(headers[1]), *(len(row[1]) for row in text_rows))
    rule = f"+-{'-' * left_width}-+-{'-' * right_width}-+"
    lines = [
        rule,
        f"| {BOLD}{headers[0].ljust(left_width)}{RESET} | {BOLD}{headers[1].ljust(right_width)}{RESET} |",
        rule,
    ]
    for left, right in text_rows:
        lines.append(f"| {left.ljust(left_width)} | {right.rjust(right_width)} |")
    lines.append(rule)
    return "\n".join(lines)


def _wide_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    if not rows:
        return f"{DIM}No iteration history available.{RESET}"
    text_rows = [tuple(str(cell) for cell in row) for row in rows]
    widths = [len(header) for header in headers]
    for row in text_rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]
    rule = "+-" + "-+-".join("-" * width for width in widths) + "-+"
    header = "| " + " | ".join(f"{BOLD}{text.ljust(width)}{RESET}" for text, width in zip(headers, widths)) + " |"
    lines = [rule, header, rule]
    for row in text_rows:
        lines.append("| " + " | ".join(cell.rjust(width) for cell, width in zip(row, widths)) + " |")
    lines.append(rule)
    return "\n".join(lines)


def _terminal_link(path: Path, label: str) -> str:
    uri = path.as_uri()
    return f"\033]8;;{uri}\033\\{BOLD}{label}{RESET}\033]8;;\033\\"


if __name__ == "__main__":
    raise SystemExit(main())
