from __future__ import annotations

import json

from jason.benchmarks.deepresearch_bench import (
    load_drb_cases,
    parse_fact_result,
    parse_race_result,
    run_drb_generation,
    summarize_existing_drb_output,
)


def test_drb_adapter_generates_official_raw_article_format(tmp_path):
    query_file = tmp_path / "query.jsonl"
    query_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": 51,
                        "topic": "Finance & Business",
                        "language": "en",
                        "prompt": "Write a market size report for Japan elderly consumers.",
                    }
                ),
                json.dumps(
                    {
                        "id": 1,
                        "topic": "Finance & Business",
                        "language": "zh",
                        "prompt": "整理中国中产阶层收入状况。",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_drb_cases(query_file, language="en", limit=1)
    summary = run_drb_generation(
        cases,
        runs_dir=tmp_path / "runs",
        output_path=tmp_path / "jason-autoresearch.jsonl",
        summary_path=tmp_path / "summary.json",
        max_iterations=1,
    )

    raw_rows = [json.loads(line) for line in (tmp_path / "jason-autoresearch.jsonl").read_text().splitlines()]
    saved_summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert summary["generation_accuracy"] == 1.0
    assert saved_summary["case_count"] == 1
    assert raw_rows[0]["id"] == 51
    assert raw_rows[0]["prompt"] == "Write a market size report for Japan elderly consumers."
    assert raw_rows[0]["article"].startswith("# Jason AutoResearch Report")
    assert saved_summary["memory_management"]["average_managed_control_bytes"] > 0
    assert saved_summary["cases"][0]["context"]["full_state_bytes"] > saved_summary["cases"][0]["context"]["managed_control_bytes"]
    assert saved_summary["cases"][0]["context"]["projected_state_bytes"] > saved_summary["cases"][0]["context"]["managed_control_bytes"]


def test_drb_adapter_supports_latest_model_article_generator_contract(tmp_path):
    def fake_latest_model_generator(case, repo_dir):
        repo_dir.mkdir(parents=True, exist_ok=True)
        report_path = repo_dir / "final_report.md"
        article = "# Report\n\nPopulation projection claim [1].\n\n## References\n[1] https://example.com/source"
        report_path.write_text(article + "\n", encoding="utf-8")
        return {
            "article": article,
            "final_report": str(report_path),
            "repo_dir": str(repo_dir),
            "generator": "latest-model",
            "model": "gpt-5.5",
            "web_search": True,
        }

    query_file = tmp_path / "query.jsonl"
    query_file.write_text(
        json.dumps(
            {
                "id": 51,
                "topic": "Finance & Business",
                "language": "en",
                "prompt": "Write a market size report for Japan elderly consumers.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_drb_generation(
        load_drb_cases(query_file, language="en", limit=1),
        runs_dir=tmp_path / "runs",
        output_path=tmp_path / "jason-autoresearch.jsonl",
        summary_path=tmp_path / "summary.json",
        article_generator=fake_latest_model_generator,
    )

    case = summary["cases"][0]
    assert summary["average_jason_quality_score"] is None
    assert case["generator"] == "latest-model"
    assert case["model"] == "gpt-5.5"
    assert case["citation_like_count"] == 2


def test_drb_result_parsers_extract_official_scores(tmp_path):
    race_result = tmp_path / "race_result.txt"
    race_result.write_text(
        "\n".join(
            [
                "Comprehensiveness: 0.4110",
                "Insight: 0.4051",
                "Instruction Following: 0.4621",
                "Readability: 0.4172",
                "Overall Score: 0.4218",
            ]
        ),
        encoding="utf-8",
    )
    fact_result = tmp_path / "fact_result.txt"
    fact_result.write_text(
        "\n".join(
            [
                "total_citations: 28.07",
                "total_valid_citations: 24.51",
                "valid_rate: 0.8731742073387959",
            ]
        ),
        encoding="utf-8",
    )

    assert parse_race_result(race_result)["overall_score"] == 0.4218
    assert parse_fact_result(fact_result)["valid_rate"] == 0.8731742073387959


def test_drb_adapter_can_attach_scores_without_regenerating(tmp_path):
    query_file = tmp_path / "query.jsonl"
    query_file.write_text(
        json.dumps(
            {
                "id": 51,
                "topic": "Finance & Business",
                "language": "en",
                "prompt": "Write a market size report for Japan elderly consumers.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    raw_output = tmp_path / "existing.jsonl"
    raw_output.write_text(
        json.dumps({"id": 51, "prompt": "Write a market size report for Japan elderly consumers.", "article": "Report [1]"})
        + "\n",
        encoding="utf-8",
    )
    race_result = tmp_path / "race_result.txt"
    race_result.write_text("Overall Score: 0.5324\n", encoding="utf-8")

    summary = summarize_existing_drb_output(
        load_drb_cases(query_file, language="en", limit=1),
        output_path=raw_output,
        summary_path=tmp_path / "summary.json",
        runs_dir=tmp_path / "runs",
        race_result_path=race_result,
    )

    assert summary["generation_accuracy"] == 1.0
    assert summary["official_scores"]["race"]["overall_score"] == 0.5324
