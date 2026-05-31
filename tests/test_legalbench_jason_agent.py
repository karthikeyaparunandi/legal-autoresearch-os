from __future__ import annotations

from scripts.legalbench import jason_agent


def test_build_jason_goal_includes_item_and_allowed_labels() -> None:
    task = jason_agent.TASKS["hearsay"]
    row = {
        "text": "The witness says that another person shouted the warning.",
        "answer": "Yes",
    }

    goal = jason_agent.build_jason_goal(task, row)

    assert "The witness says that another person shouted the warning." in goal
    assert "Allowed final labels: Yes / No" in goal
    assert "final answer label" in goal.lower()


def test_summarize_results_counts_scored_rows_and_balanced_accuracy() -> None:
    results = [
        {"idx": 0, "gold": "Yes", "pred": "Yes", "ok": True, "error": None},
        {"idx": 1, "gold": "No", "pred": "Yes", "ok": False, "error": None},
        {"idx": 2, "gold": "No", "pred": None, "ok": False, "error": "boom"},
    ]

    summary = jason_agent.summarize_results(
        task_config="hearsay",
        model="gpt-5.5",
        runner="offline",
        results=results,
        elapsed=12.34,
        tokens={"in": 100, "out": 20},
        cost_usd=0.0011,
    )

    assert summary["task"] == "hearsay"
    assert summary["mode"] == "jason_agent"
    assert summary["runner"] == "offline"
    assert summary["n"] == 2
    assert summary["errors"] == 1
    assert summary["accuracy"] == 0.5
    assert summary["balanced_accuracy"] == 0.5
    assert summary["per_class_recall"] == {"No": 0.0, "Yes": 1.0}
    assert summary["tokens"] == {"in": 100, "out": 20}
