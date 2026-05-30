from __future__ import annotations

from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jason.harness import run_offline
from jason.memory import TruthRepo


def main() -> int:
    cases_path = ROOT / "evals" / "cases.jsonl"
    results = []
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        repo_dir = ROOT / "evals" / "results" / case["id"]
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        result = run_offline(case["goal"], repo_dir, max_iterations=3)
        state = TruthRepo(repo_dir).load_state()
        spawned_agents = {run["agent_type"] for run in state["agent_runs"]}
        passed = (
            result["iterations"] >= case["min_iterations"]
            and set(case["required_agents"]).issubset(spawned_agents)
            and bool(state["final_report"].get("path"))
        )
        results.append({"id": case["id"], "passed": passed, "spawned_agents": sorted(spawned_agents), "result": result})

    output_path = ROOT / "evals" / "results" / "latest.json"
    output_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
