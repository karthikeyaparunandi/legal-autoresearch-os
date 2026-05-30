from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
import argparse
import json
import re
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jason.context_broker import ContextBroker
from jason.harness import run_offline
from jason.memory import TruthRepo
from jason.agent import load_env_file


ArticleGenerator = Callable[["DeepResearchBenchCase", Path], dict[str, Any]]


@dataclass(frozen=True)
class DeepResearchBenchCase:
    case_id: int | str
    topic: str
    language: str
    prompt: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate DeepResearch Bench raw outputs from Jason.")
    parser.add_argument("--drb-root", type=Path, default=None, help="Path to a deep_research_bench checkout.")
    parser.add_argument("--query-file", type=Path, default=None, help="Override path to DRB query.jsonl.")
    parser.add_argument("--model-name", default="jason-autoresearch")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks" / "results" / "deepresearch_bench" / "jason-autoresearch.jsonl")
    parser.add_argument("--summary", type=Path, default=ROOT / "benchmarks" / "results" / "deepresearch_bench" / "latest.json")
    parser.add_argument("--runs-dir", type=Path, default=ROOT / "benchmarks" / "results" / "deepresearch_bench" / "runs")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--generator", choices=["offline", "latest-model"], default="offline")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--no-web-search", action="store_true")
    parser.add_argument("--reuse-output", action="store_true", help="Summarize an existing raw output file without regenerating articles.")
    parser.add_argument("--only-en", action="store_true")
    parser.add_argument("--only-zh", action="store_true")
    parser.add_argument("--copy-to-drb", action="store_true", help="Copy raw output into DRB data/test_data/raw_data.")
    parser.add_argument("--race-result", type=Path, default=None, help="Optional DRB RACE race_result.txt to parse.")
    parser.add_argument("--fact-result", type=Path, default=None, help="Optional DRB FACT fact_result.txt to parse.")
    args = parser.parse_args(argv)

    language = None
    if args.only_en and args.only_zh:
        raise SystemExit("--only-en and --only-zh are mutually exclusive")
    if args.only_en:
        language = "en"
    if args.only_zh:
        language = "zh"

    query_file = args.query_file or _default_query_file(args.drb_root)
    cases = load_drb_cases(query_file, language=language, limit=args.limit)
    if args.reuse_output:
        summary = summarize_existing_drb_output(
            cases,
            output_path=args.output,
            summary_path=args.summary,
            runs_dir=args.runs_dir,
            race_result_path=args.race_result,
            fact_result_path=args.fact_result,
        )
        print(json.dumps(_printable_summary(summary), indent=2, sort_keys=True))
        return 0

    article_generator = None
    if args.generator == "latest-model":
        article_generator = latest_model_article_generator(
            model=args.model,
            use_web_search=not args.no_web_search,
            max_iterations=args.max_iterations,
        )
    summary = run_drb_generation(
        cases,
        runs_dir=args.runs_dir,
        output_path=args.output,
        summary_path=args.summary,
        max_iterations=args.max_iterations,
        article_generator=article_generator,
        race_result_path=args.race_result,
        fact_result_path=args.fact_result,
    )
    if args.copy_to_drb:
        drb_root = args.drb_root
        if not drb_root:
            raise SystemExit("--copy-to-drb requires --drb-root")
        copy_output_to_drb(args.output, drb_root, args.model_name)

    print(json.dumps(_printable_summary(summary), indent=2, sort_keys=True))
    return 0


def load_drb_cases(path: Path, language: str | None = None, limit: int | None = None) -> list[DeepResearchBenchCase]:
    cases: list[DeepResearchBenchCase] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        item = json.loads(stripped)
        if language and item.get("language") != language:
            continue
        cases.append(
            DeepResearchBenchCase(
                case_id=item["id"],
                topic=item.get("topic", ""),
                language=item.get("language", ""),
                prompt=item["prompt"],
            )
        )
        if limit and len(cases) >= limit:
            break
    return cases


def run_drb_generation(
    cases: Iterable[DeepResearchBenchCase],
    runs_dir: Path,
    output_path: Path,
    summary_path: Path,
    max_iterations: int = 3,
    article_generator: ArticleGenerator | None = None,
    race_result_path: Path | None = None,
    fact_result_path: Path | None = None,
) -> dict[str, Any]:
    case_list = list(cases)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if runs_dir.exists():
        shutil.rmtree(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []
    for case in case_list:
        repo_dir = runs_dir / str(case.case_id)
        generated = (
            article_generator(case, repo_dir)
            if article_generator
            else offline_article_generator(max_iterations=max_iterations)(case, repo_dir)
        )
        article = generated["article"]
        rows.append({"id": case.case_id, "prompt": case.prompt, "article": article})
        case_summaries.append(_case_summary(case, repo_dir, generated, article))

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    generated_count = len(rows)
    summary = {
        "benchmark": "deepresearch-bench-adapter",
        "created_at": _now(),
        "case_count": len(case_list),
        "generated_count": generated_count,
        "generation_accuracy": round(generated_count / len(case_list), 4) if case_list else 0.0,
        "average_jason_quality_score": _average(
            [item["jason_quality_score"] for item in case_summaries if item["jason_quality_score"] is not None]
        ),
        "memory_management": _memory_management_summary(case_summaries),
        "raw_output_path": str(output_path),
        "runs_dir": str(runs_dir),
        "official_scores": _official_scores(race_result_path, fact_result_path),
        "cases": case_summaries,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.with_suffix(".md").write_text(_markdown_summary(summary), encoding="utf-8")
    return summary


def summarize_existing_drb_output(
    cases: Iterable[DeepResearchBenchCase],
    output_path: Path,
    summary_path: Path,
    runs_dir: Path,
    race_result_path: Path | None = None,
    fact_result_path: Path | None = None,
) -> dict[str, Any]:
    case_list = list(cases)
    rows_by_id = {
        str(row["id"]): row
        for row in _read_jsonl(output_path)
    }
    case_summaries: list[dict[str, Any]] = []
    generated_count = 0
    for case in case_list:
        row = rows_by_id.get(str(case.case_id))
        if not row:
            continue
        generated_count += 1
        repo_dir = runs_dir / str(case.case_id)
        report_path = repo_dir / "final_report.md"
        case_summaries.append(
            _case_summary(
                case,
                repo_dir,
                {
                    "final_report": str(report_path) if report_path.exists() else "",
                    "generator": "existing-output",
                },
                row.get("article", ""),
            )
        )

    summary = {
        "benchmark": "deepresearch-bench-adapter",
        "created_at": _now(),
        "case_count": len(case_list),
        "generated_count": generated_count,
        "generation_accuracy": round(generated_count / len(case_list), 4) if case_list else 0.0,
        "average_jason_quality_score": _average(
            [item["jason_quality_score"] for item in case_summaries if item["jason_quality_score"] is not None]
        ),
        "memory_management": _memory_management_summary(case_summaries),
        "raw_output_path": str(output_path),
        "runs_dir": str(runs_dir),
        "official_scores": _official_scores(race_result_path, fact_result_path),
        "cases": case_summaries,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.with_suffix(".md").write_text(_markdown_summary(summary), encoding="utf-8")
    return summary


def offline_article_generator(max_iterations: int = 3) -> ArticleGenerator:
    def generate(case: DeepResearchBenchCase, repo_dir: Path) -> dict[str, Any]:
        result = run_offline(case.prompt, repo_dir, max_iterations=max_iterations)
        article = Path(result["final_report"]).read_text(encoding="utf-8")
        return {
            "article": article,
            "final_report": result["final_report"],
            "repo_dir": str(repo_dir),
            "generator": "offline",
            "agent_result": result,
        }

    return generate


def latest_model_article_generator(
    model: str = "gpt-5.5",
    use_web_search: bool = True,
    max_iterations: int = 3,
) -> ArticleGenerator:
    def generate(case: DeepResearchBenchCase, repo_dir: Path) -> dict[str, Any]:
        load_env_file()
        from openai import OpenAI

        agent_result = run_offline(case.prompt, repo_dir, max_iterations=max_iterations)
        repo = TruthRepo(repo_dir)
        memory_context = _managed_memory_context(repo)
        client = OpenAI()
        response = client.responses.create(
            model=model,
            instructions=_deepresearch_report_instructions(case.language),
            input=_deepresearch_report_prompt(case, memory_context),
            tools=[{"type": "web_search_preview"}] if use_web_search else [],
            max_output_tokens=10_000,
            reasoning={"effort": "medium"},
        )
        article = response.output_text.strip()
        report_path = repo_dir / "final_report.md"
        report_path.write_text(article + "\n", encoding="utf-8")
        return {
            "article": article,
            "final_report": str(report_path),
            "repo_dir": str(repo_dir),
            "generator": "latest-model",
            "model": model,
            "web_search": use_web_search,
            "agent_result": agent_result,
            "response_id": response.id,
        }

    return generate


def copy_output_to_drb(output_path: Path, drb_root: Path, model_name: str) -> Path:
    target_dir = drb_root / "data" / "test_data" / "raw_data"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{model_name}.jsonl"
    shutil.copyfile(output_path, target_path)
    return target_path


def parse_race_result(path: Path) -> dict[str, float]:
    labels = {
        "Comprehensiveness": "comprehensiveness",
        "Insight": "insight",
        "Instruction Following": "instruction_following",
        "Readability": "readability",
        "Overall Score": "overall_score",
    }
    return _parse_score_file(path, labels)


def parse_fact_result(path: Path) -> dict[str, float]:
    labels = {
        "total_citations": "total_citations",
        "total_valid_citations": "total_valid_citations",
        "valid_rate": "valid_rate",
    }
    return _parse_score_file(path, labels)


def _case_summary(
    case: DeepResearchBenchCase,
    repo_dir: Path,
    generated: dict[str, Any],
    article: str,
) -> dict[str, Any]:
    state = _load_optional_truth_repo(repo_dir)
    latest_eval = state["evals"][-1] if state and state["evals"] else {}
    return {
        **asdict(case),
        "repo_dir": str(repo_dir),
        "final_report": generated["final_report"],
        "generator": generated.get("generator", "unknown"),
        "model": generated.get("model"),
        "web_search": generated.get("web_search"),
        "article_chars": len(article),
        "citation_like_count": _citation_like_count(article),
        "spawned_agents": sorted({run["agent_type"] for run in state["agent_runs"]}) if state else [],
        "jason_quality_score": _jason_quality_score(latest_eval) if latest_eval else None,
        "jason_latest_eval": latest_eval,
        "context": _context_metrics(repo_dir, state),
    }


def _load_optional_truth_repo(repo_dir: Path) -> dict[str, Any] | None:
    required = ["program.json", "tasks.json", "claims.json", "evidence.json", "evals.json"]
    if not all((repo_dir / name).exists() for name in required):
        return None
    return TruthRepo(repo_dir).load_state(include_events=True)


def _jason_quality_score(latest_eval: dict[str, Any]) -> float:
    open_question_score = max(0.0, 1.0 - (float(latest_eval.get("open_critical_questions", 0)) / 5.0))
    component_scores = [
        float(latest_eval.get("objective_coverage", 0.0)),
        float(latest_eval.get("citation_grounding", 0.0)),
        float(latest_eval.get("primary_source_coverage", 0.0)),
        float(latest_eval.get("contradiction_resolution", 0.0)),
        open_question_score,
    ]
    return round(sum(component_scores) / len(component_scores), 4)


def _official_scores(race_result_path: Path | None, fact_result_path: Path | None) -> dict[str, Any]:
    scores: dict[str, Any] = {"race": None, "fact": None}
    if race_result_path and race_result_path.exists():
        scores["race"] = parse_race_result(race_result_path)
    if fact_result_path and fact_result_path.exists():
        scores["fact"] = parse_fact_result(fact_result_path)
    return scores


def _context_metrics(repo_dir: Path, full_state: dict[str, Any] | None) -> dict[str, Any]:
    if not full_state:
        return {
            "full_state_bytes": 0,
            "projected_state_bytes": 0,
            "managed_control_bytes": 0,
            "full_to_managed_ratio": 0.0,
            "projected_to_managed_ratio": 0.0,
            "claim_count": 0,
            "evidence_count": 0,
            "event_count": 0,
        }
    repo = TruthRepo(repo_dir)
    projected_state = dict(full_state)
    projected_state["events"] = []
    managed_control = ContextBroker(repo).control_slice()
    full_state_bytes = _json_size(full_state)
    projected_state_bytes = _json_size(projected_state)
    managed_control_bytes = _json_size(managed_control)
    return {
        "full_state_bytes": full_state_bytes,
        "projected_state_bytes": projected_state_bytes,
        "managed_control_bytes": managed_control_bytes,
        "full_to_managed_ratio": round(full_state_bytes / max(managed_control_bytes, 1), 3),
        "projected_to_managed_ratio": round(projected_state_bytes / max(managed_control_bytes, 1), 3),
        "claim_count": len(full_state["claims"]),
        "evidence_count": len(full_state["evidence"]),
        "event_count": len(full_state["events"]),
    }


def _memory_management_summary(case_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    contexts = [item["context"] for item in case_summaries]
    if not contexts:
        return {
            "average_full_state_bytes": 0.0,
            "average_projected_state_bytes": 0.0,
            "average_managed_control_bytes": 0.0,
            "average_full_to_managed_ratio": 0.0,
            "max_full_state_bytes": 0,
            "max_managed_control_bytes": 0,
        }
    return {
        "average_full_state_bytes": _average([float(item["full_state_bytes"]) for item in contexts]),
        "average_projected_state_bytes": _average([float(item["projected_state_bytes"]) for item in contexts]),
        "average_managed_control_bytes": _average([float(item["managed_control_bytes"]) for item in contexts]),
        "average_full_to_managed_ratio": _average([float(item["full_to_managed_ratio"]) for item in contexts]),
        "max_full_state_bytes": max(item["full_state_bytes"] for item in contexts),
        "max_managed_control_bytes": max(item["managed_control_bytes"] for item in contexts),
    }


def _parse_score_file(path: Path, labels: dict[str, str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        raw_key, raw_value = line.split(":", 1)
        key = raw_key.strip()
        if key not in labels:
            continue
        values[labels[key]] = float(raw_value.strip())
    return values


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _default_query_file(drb_root: Path | None) -> Path:
    if drb_root:
        return drb_root / "data" / "prompt_data" / "query.jsonl"
    candidate = Path("/tmp/deep_research_bench_inspect/data/prompt_data/query.jsonl")
    if candidate.exists():
        return candidate
    raise SystemExit("Pass --drb-root or --query-file for DeepResearch Bench query.jsonl")


def _citation_like_count(text: str) -> int:
    url_count = len(re.findall(r"https?://", text))
    bracket_count = len(re.findall(r"\[\d+\]", text))
    return max(url_count, bracket_count)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4) if values else 0.0


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _deepresearch_report_instructions(language: str) -> str:
    if language == "zh":
        return (
            "你是一个深度研究智能体。请用中文撰写完整、结构化、可审阅的研究报告。"
            "必须直接回答任务，给出方法、关键假设、分项分析、表格、风险和结论。"
            "尽量使用权威来源，并在正文中用[1]格式引用，在末尾列出带URL的参考资料。"
        )
    return (
        "You are a deep research agent. Write a complete, structured research report that directly answers the task. "
        "Include methodology, key assumptions, quantitative tables, segment analysis, risks, and an actionable conclusion. "
        "Use authoritative sources where possible. Cite claims inline with [1]-style markers and include a References "
        "section with source titles and URLs."
    )


def _managed_memory_context(repo: TruthRepo) -> dict[str, Any]:
    broker = ContextBroker(repo)
    state = repo.load_state(include_events=False)
    claim_contexts = {
        claim_id: broker.claim_context(claim_id, budget_bytes=8_000)
        for claim_id in state.get("claims", {}).keys()
    }
    return {
        "control_slice": broker.control_slice(budget_bytes=10_000),
        "claim_contexts": claim_contexts,
        "latest_eval": state.get("evals", [])[-1] if state.get("evals") else {},
    }


def _deepresearch_report_prompt(case: DeepResearchBenchCase, memory_context: dict[str, Any] | None = None) -> str:
    prompt = (
        f"DeepResearch Bench task id: {case.case_id}\n"
        f"Topic: {case.topic}\n"
        f"Language: {case.language}\n\n"
        f"Task:\n{case.prompt}\n\n"
    )
    if memory_context:
        prompt += (
            "Jason managed-memory context from the planning/control loop:\n"
            f"{json.dumps(memory_context, ensure_ascii=False, sort_keys=True)}\n\n"
            "Use this agent memory as scaffolding for claims, gaps, and source priorities, but verify and improve "
            "the final answer with authoritative sources. Do not mention internal memory files in the report.\n\n"
        )
    return prompt + "Produce the final research article only. Do not describe your process or say you are unable to browse."


def _markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Jason DeepResearch Bench Adapter",
        "",
        f"- Cases: {summary['generated_count']}/{summary['case_count']}",
        f"- Generation accuracy: {summary['generation_accuracy']}",
        f"- Average Jason internal quality: {summary['average_jason_quality_score']}",
        f"- Average full state bytes: {summary['memory_management']['average_full_state_bytes']}",
        f"- Average managed control bytes: {summary['memory_management']['average_managed_control_bytes']}",
        f"- Raw output: {summary['raw_output_path']}",
    ]
    race = summary["official_scores"]["race"]
    fact = summary["official_scores"]["fact"]
    if race:
        lines.append(f"- RACE overall score: {race.get('overall_score', 0.0)}")
    if fact:
        lines.append(f"- FACT citation valid rate: {fact.get('valid_rate', 0.0)}")
    lines.extend(["", "## Cases"])
    for item in summary["cases"]:
        lines.extend(
            [
                "",
                f"### {item['case_id']}",
                "",
                f"- Language: {item['language']}",
                f"- Topic: {item['topic']}",
                f"- Article chars: {item['article_chars']}",
                f"- Citation-like markers: {item['citation_like_count']}",
                f"- Jason internal quality: {item['jason_quality_score']}",
                f"- Full state bytes: {item['context']['full_state_bytes']}",
                f"- Managed control bytes: {item['context']['managed_control_bytes']}",
            ]
        )
    return "\n".join(lines) + "\n"


def _printable_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": summary["case_count"],
        "generated_count": summary["generated_count"],
        "generation_accuracy": summary["generation_accuracy"],
        "average_jason_quality_score": summary["average_jason_quality_score"],
        "memory_management": summary["memory_management"],
        "official_scores": summary["official_scores"],
        "raw_output_path": summary["raw_output_path"],
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
