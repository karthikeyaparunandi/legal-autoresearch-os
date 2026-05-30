from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json


@dataclass
class ResearchTask:
    task_id: str
    agent_type: str
    goal: str
    priority: float
    expected_output: str
    status: str = "pending"
    supports_claim: str | None = None
    blocks_contradiction: str | None = None


@dataclass
class EvidenceRecord:
    evidence_id: str
    source_type: str
    title: str
    url: str
    excerpt: str
    supports_claims: list[str] = field(default_factory=list)
    contradicts_claims: list[str] = field(default_factory=list)
    reliability: float = 0.7
    accepted: bool = True


class TruthRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def write_program(self, objective: str, subquestions: list[str], stop_conditions: dict[str, Any]) -> None:
        program = {
            "objective": objective,
            "subquestions": subquestions,
            "stop_conditions": stop_conditions,
        }
        self._write_json("program.json", program)
        lines = [
            "# Research Program",
            "",
            "## Objective",
            objective,
            "",
            "## Subquestions",
            *[f"- {item}" for item in subquestions],
            "",
            "## Stop Conditions",
            *[f"- {key}: {value}" for key, value in stop_conditions.items()],
            "",
        ]
        (self.root / "program.md").write_text("\n".join(lines), encoding="utf-8")
        self.append_event("program_written", {"objective": objective, "subquestion_count": len(subquestions)})

    def add_task(self, task: ResearchTask) -> None:
        tasks = self._read_json("tasks.json", [])
        if not any(item["goal"] == task.goal and item["agent_type"] == task.agent_type for item in tasks):
            existing_ids = {item["task_id"] for item in tasks}
            if task.task_id in existing_ids:
                task.task_id = f"t{len(tasks) + 1:03d}"
            tasks.append(asdict(task))
            self._write_json("tasks.json", tasks)
            self.append_event("task_created", asdict(task))

    def mark_task(self, task_id: str, status: str) -> None:
        tasks = self._read_json("tasks.json", [])
        for task in tasks:
            if task["task_id"] == task_id:
                task["status"] = status
                self.append_event("task_updated", {"task_id": task_id, "status": status})
                break
        self._write_json("tasks.json", tasks)

    def next_pending_tasks(self, limit: int = 3) -> list[ResearchTask]:
        tasks = [ResearchTask(**item) for item in self._read_json("tasks.json", []) if item["status"] == "pending"]
        ranked = sorted(tasks, key=lambda item: item.priority, reverse=True)
        selected: list[ResearchTask] = []
        seen_agent_types: set[str] = set()
        for task in ranked:
            if task.agent_type in seen_agent_types:
                continue
            selected.append(task)
            seen_agent_types.add(task.agent_type)
            if len(selected) == limit:
                return selected
        for task in ranked:
            if task not in selected:
                selected.append(task)
            if len(selected) == limit:
                break
        return selected

    def upsert_claim(self, claim_id: str, claim: str, confidence: float = 0.0) -> None:
        claims = self._read_json("claims.json", {})
        existing = claims.get(claim_id, {})
        claims[claim_id] = {
            "claim_id": claim_id,
            "claim": claim,
            "confidence": confidence,
            "supporting_evidence": existing.get("supporting_evidence", []),
            "contradicting_evidence": existing.get("contradicting_evidence", []),
            "status": "supported" if confidence >= 0.75 else "weak",
        }
        self._write_json("claims.json", claims)
        self.append_event("claim_upserted", claims[claim_id])

    def add_evidence(self, evidence: EvidenceRecord) -> None:
        evidence_items = self._read_json("evidence.json", {})
        evidence_items[evidence.evidence_id] = asdict(evidence)
        self._write_json("evidence.json", evidence_items)

        claims = self._read_json("claims.json", {})
        for claim_id in evidence.supports_claims:
            if claim_id in claims and evidence.evidence_id not in claims[claim_id]["supporting_evidence"]:
                claims[claim_id]["supporting_evidence"].append(evidence.evidence_id)
        for claim_id in evidence.contradicts_claims:
            if claim_id in claims and evidence.evidence_id not in claims[claim_id]["contradicting_evidence"]:
                claims[claim_id]["contradicting_evidence"].append(evidence.evidence_id)
        self._write_json("claims.json", claims)
        self.append_event("evidence_added", asdict(evidence))

    def add_contradiction(self, contradiction_id: str, claim_id: str, note: str, resolved: bool = False) -> None:
        contradictions = self._read_json("contradictions.json", {})
        contradictions[contradiction_id] = {
            "contradiction_id": contradiction_id,
            "claim_id": claim_id,
            "note": note,
            "resolved": resolved,
        }
        self._write_json("contradictions.json", contradictions)
        self.append_event("contradiction_recorded", contradictions[contradiction_id])

    def add_eval(self, evaluation: dict[str, Any]) -> None:
        evals = self._read_json("evals.json", [])
        evals.append(evaluation)
        self._write_json("evals.json", evals)
        self.append_event("eval_completed", evaluation)

    def record_agent_run(self, agent_type: str, task_id: str, output_summary: str) -> None:
        record = {
            "agent_type": agent_type,
            "task_id": task_id,
            "output_summary": output_summary,
            "created_at": _now(),
        }
        with (self.root / "agent_runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.append_event("agent_run_completed", record)

    def write_final_report(self) -> Path:
        state = self.load_state(include_events=False)
        report_path = self.root / "final_report.md"
        lines = [
            "# Jason AutoResearch Report",
            "",
            "## Objective",
            state["program"].get("objective", ""),
            "",
            "## Claims",
        ]
        for claim in state["claims"].values():
            lines.extend(
                [
                    f"- {claim['claim_id']}: {claim['claim']}",
                    f"  - Confidence: {claim['confidence']:.0%}",
                    f"  - Evidence: {', '.join(claim['supporting_evidence']) or 'none'}",
                ]
            )
        lines.extend(["", "## Latest Evaluation"])
        latest_eval = state["evals"][-1] if state["evals"] else {}
        for key, value in latest_eval.items():
            lines.append(f"- {key}: {value}")
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._write_json("final_report.json", {"path": str(report_path)})
        self.append_event("final_report_written", {"path": str(report_path)})
        return report_path

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        record = {"type": event_type, "created_at": _now(), **payload}
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def load_state(self, include_events: bool = True) -> dict[str, Any]:
        return {
            "program": self._read_json("program.json", {}),
            "tasks": self._read_json("tasks.json", []),
            "claims": self._read_json("claims.json", {}),
            "evidence": self._read_json("evidence.json", {}),
            "contradictions": self._read_json("contradictions.json", {}),
            "evals": self._read_json("evals.json", []),
            "agent_runs": self._read_jsonl("agent_runs.jsonl"),
            "events": self._read_jsonl("events.jsonl") if include_events else [],
            "final_report": self._read_json("final_report.json", {}),
        }

    def existing_task_goals(self) -> set[str]:
        return {item["goal"] for item in self._read_json("tasks.json", [])}

    def _ensure_files(self) -> None:
        defaults: dict[str, Any] = {
            "tasks.json": [],
            "claims.json": {},
            "evidence.json": {},
            "contradictions.json": {},
            "evals.json": [],
            "program.json": {},
            "final_report.json": {},
        }
        for name, value in defaults.items():
            path = self.root / name
            if not path.exists():
                self._write_json(name, value)
        for name in ["events.jsonl", "agent_runs.jsonl"]:
            path = self.root / name
            if not path.exists():
                path.write_text("", encoding="utf-8")

    def _read_json(self, name: str, default: Any) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, name: str, value: Any) -> None:
        (self.root / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _now() -> str:
    return datetime.now(UTC).isoformat()
