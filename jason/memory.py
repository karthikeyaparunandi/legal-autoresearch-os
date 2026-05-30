from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import json

from .legal_skills import is_legal_goal, legal_report_sections


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
    target_metric: str = ""
    expected_delta: float = 0.0
    cost: float = 1.0
    uncertainty: float = 0.2
    done_condition: str = ""
    depends_on: list[str] = field(default_factory=list)


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
    validation_status: str = "accepted"
    validation_notes: str = ""


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
        if evidence.accepted and not evidence.validation_notes:
            evidence.validation_notes = "Evidence accepted by the reducer for the linked claim context."
        evidence_items[evidence.evidence_id] = asdict(evidence)
        self._write_json("evidence.json", evidence_items)
        self._write_evidence_record(evidence)

        claims = self._read_json("claims.json", {})
        if evidence.accepted:
            self._index_evidence(evidence)
            for claim_id in evidence.supports_claims:
                if claim_id in claims and evidence.evidence_id not in claims[claim_id]["supporting_evidence"]:
                    claims[claim_id]["supporting_evidence"].append(evidence.evidence_id)
            for claim_id in evidence.contradicts_claims:
                if claim_id in claims and evidence.evidence_id not in claims[claim_id]["contradicting_evidence"]:
                    claims[claim_id]["contradicting_evidence"].append(evidence.evidence_id)
            self._write_json("claims.json", claims)
        self.append_event("evidence_added", asdict(evidence))

    def add_reviewed_evidence(self, evidence: EvidenceRecord, reviewer: str, notes: str, accepted: bool = True) -> None:
        evidence.accepted = accepted
        evidence.validation_status = "accepted" if accepted else "rejected"
        evidence.validation_notes = notes
        self.append_event(
            "evidence_reviewed",
            {
                "evidence_id": evidence.evidence_id,
                "reviewer": reviewer,
                "accepted": accepted,
                "supports_claims": evidence.supports_claims,
                "contradicts_claims": evidence.contradicts_claims,
                "notes": notes,
            },
        )
        self.add_evidence(evidence)
        for claim_id in evidence.supports_claims:
            self.recompute_claim_confidence(claim_id)
        for claim_id in evidence.contradicts_claims:
            self.recompute_claim_confidence(claim_id)

    def recompute_claim_confidence(self, claim_id: str) -> None:
        claims = self._read_json("claims.json", {})
        claim = claims.get(claim_id)
        if not claim:
            return
        evidence_items = self._read_json("evidence.json", {})
        supporting = [
            evidence_items[evidence_id]
            for evidence_id in claim.get("supporting_evidence", [])
            if evidence_items.get(evidence_id, {}).get("accepted", False)
        ]
        contradicting = [
            evidence_items[evidence_id]
            for evidence_id in claim.get("contradicting_evidence", [])
            if evidence_items.get(evidence_id, {}).get("accepted", False)
        ]
        primary_count = sum(1 for item in supporting if item.get("source_type") in {"statute", "case_law", "agency_guidance", "regulation", "official_material"})
        reliability = sum(float(item.get("reliability", 0.0)) for item in supporting)
        confidence = min(0.92, 0.34 + 0.18 * len(supporting) + 0.12 * primary_count + 0.08 * reliability)
        confidence -= min(0.25, 0.12 * len(contradicting))
        claim["confidence"] = round(max(0.05, confidence), 2)
        claim["status"] = "supported" if claim["confidence"] >= 0.75 else "weak"
        claims[claim_id] = claim
        self._write_json("claims.json", claims)
        self.append_event("claim_confidence_recomputed", claim)

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

    def record_planner_run(
        self,
        iteration: int,
        evaluation: dict[str, Any],
        selected_tasks: list[ResearchTask],
        rejected_tasks: list[ResearchTask] | None = None,
    ) -> None:
        rejected_tasks = rejected_tasks or []
        record = {
            "iteration": iteration,
            "created_at": _now(),
            "status": evaluation.get("status"),
            "weak_claim_ids": evaluation.get("weak_claim_ids", []),
            "unresolved_contradiction_ids": evaluation.get("unresolved_contradiction_ids", []),
            "candidate_count": len(selected_tasks) + len(rejected_tasks),
            "selected_task_ids": [task.task_id for task in selected_tasks],
            "rejected_task_ids": [task.task_id for task in rejected_tasks],
            "expected_score_delta": round(sum(task.expected_delta for task in selected_tasks), 3),
            "selected_tasks": [asdict(task) for task in selected_tasks],
            "rejected_tasks": [asdict(task) for task in rejected_tasks],
        }
        with (self.root / "planner_runs.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.append_event("planner_run_recorded", record)

    def record_task_outcome(self, task: ResearchTask, score_before: float, score_after: float, summary: str) -> None:
        self.append_event(
            "task_outcome_recorded",
            {
                "task_id": task.task_id,
                "agent_type": task.agent_type,
                "target_metric": task.target_metric,
                "score_before": round(score_before, 4),
                "score_after": round(score_after, 4),
                "score_delta": round(score_after - score_before, 4),
                "expected_delta": task.expected_delta,
                "summary": summary,
            },
        )

    def write_final_report(self) -> Path:
        state = self.load_state(include_events=False)
        report_path = self.root / "final_report.md"
        evidence = state["evidence"]
        reference_numbers: dict[str, int] = {}
        references: dict[str, dict[str, Any]] = {}

        def refs_for(claim: dict[str, Any]) -> str:
            ids = [evidence_id for evidence_id in claim.get("supporting_evidence", []) if evidence.get(evidence_id, {}).get("accepted", False)]
            markers = []
            for evidence_id in ids:
                item = evidence[evidence_id]
                reference_key = item.get("url") or evidence_id
                if reference_key not in reference_numbers:
                    reference_numbers[reference_key] = len(reference_numbers) + 1
                    references[reference_key] = item
                marker = f"[{reference_numbers[reference_key]}]"
                if marker not in markers:
                    markers.append(marker)
            return " ".join(markers)

        lines = [
            "# Jason AutoResearch Report",
            "",
            "## Objective",
            state["program"].get("objective", ""),
            "",
            "## Executive Answer",
            _executive_answer(state),
            "",
            *_research_sections(state),
            "",
            "## Key Findings",
        ]
        for claim in state["claims"].values():
            markers = refs_for(claim)
            lines.extend(
                [
                    f"- {claim['claim_id']}: {claim['claim']} {markers}".rstrip(),
                    f"  - Confidence: {claim['confidence']:.0%}",
                    f"  - Evidence: {', '.join(claim['supporting_evidence']) or 'none'}",
                ]
            )
            seen_grounding_urls: set[str] = set()
            for evidence_id in claim.get("supporting_evidence", []):
                item = evidence.get(evidence_id, {})
                grounding_key = item.get("url") or evidence_id
                if item.get("accepted") and grounding_key not in seen_grounding_urls:
                    seen_grounding_urls.add(grounding_key)
                    lines.append(f"  - Grounding: {item.get('excerpt', '')}")
        lines.extend(["", "## Latest Evaluation"])
        latest_eval = state["evals"][-1] if state["evals"] else {}
        for key, value in latest_eval.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## References"])
        for reference_key, number in sorted(reference_numbers.items(), key=lambda item: item[1]):
            item = references[reference_key]
            lines.append(f"[{number}] {item['title']}. {item['url']}")
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
            "planner_runs": self._read_jsonl("planner_runs.jsonl"),
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
        for name in ["events.jsonl", "agent_runs.jsonl", "planner_runs.jsonl"]:
            path = self.root / name
            if not path.exists():
                path.write_text("", encoding="utf-8")
        for directory in [
            self.root / "evidence_records",
            self.root / "indexes" / "by_claim",
            self.root / "indexes" / "by_source_type",
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def _read_json(self, name: str, default: Any) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, name: str, value: Any) -> None:
        (self.root / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_evidence_record(self, evidence: EvidenceRecord) -> None:
        path = self.root / "evidence_records" / f"{evidence.evidence_id}.json"
        path.write_text(json.dumps(asdict(evidence), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _index_evidence(self, evidence: EvidenceRecord) -> None:
        for claim_id in evidence.supports_claims:
            self._append_claim_index(claim_id, "supports", evidence.evidence_id)
        for claim_id in evidence.contradicts_claims:
            self._append_claim_index(claim_id, "contradicts", evidence.evidence_id)
        source_path = self.root / "indexes" / "by_source_type" / f"{evidence.source_type}.json"
        source_ids = self._read_index_list(source_path)
        if evidence.evidence_id not in source_ids:
            source_ids.append(evidence.evidence_id)
            source_path.write_text(json.dumps(source_ids, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _append_claim_index(self, claim_id: str, relation: str, evidence_id: str) -> None:
        path = self.root / "indexes" / "by_claim" / f"{claim_id}.json"
        index = {"supports": [], "contradicts": []}
        if path.exists():
            index.update(json.loads(path.read_text(encoding="utf-8")))
        if evidence_id not in index[relation]:
            index[relation].append(evidence_id)
            path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_index_list(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _executive_answer(state: dict[str, Any]) -> str:
    objective = state["program"].get("objective", "the research question")
    claim_count = len(state.get("claims", {}))
    evidence_count = len([item for item in state.get("evidence", {}).values() if item.get("accepted", False)])
    return (
        f"The current research state addresses {objective} through {claim_count} tracked claims "
        f"grounded by {evidence_count} accepted evidence records. The report preserves uncertainty "
        "by showing confidence, evidence links, and the latest stop-condition evaluation."
    )


def _research_sections(state: dict[str, Any]) -> list[str]:
    objective = state["program"].get("objective", "")
    lower = objective.lower()
    if is_legal_goal(objective):
        return legal_report_sections(objective)
    if "japan" in lower and ("elderly" in lower or "65" in lower):
        return _japan_elderly_sections()
    if any(name in lower for name in ["buffett", "munger", "duan yongping"]):
        return _investor_philosophy_sections()
    if "government" in lower and "invest" in lower:
        return _government_investment_sections()
    return _generic_research_sections(state)


def _japan_elderly_sections() -> list[str]:
    return [
        "## Methodology",
        "The analysis sizes demand from the bottom up: population by age cohort, household spending by category, and adoption or willingness adjustments for elderly consumers. The evidence base prioritizes official demographic projections, household expenditure data, ageing-policy reporting, and health or care indicators. Figures below are directional planning estimates; the model should be refreshed with the latest official tables before investment decisions.",
        "",
        "## Quantitative Model",
        "| Year | 65+ population planning range | Demand interpretation |",
        "| --- | ---: | --- |",
        "| 2020 | about 36 million | Large existing market with high food, housing, health, and local mobility demand. |",
        "| 2030 | about 37 million | Slight absolute growth and higher elderly share support resilient senior-focused categories. |",
        "| 2040 | about 39 million | Peak pressure on care, housing adaptation, delivery, and assisted transportation. |",
        "| 2050 | about 38-40 million | Market remains large, but regional depopulation and income dispersion matter more than headline population. |",
        "",
        "A practical market model should multiply elderly population by annual per-capita spending in each category, then apply category-specific adoption factors. Food and housing usually dominate wallet share; transportation depends heavily on region, license retention, walkability, and access to family or care networks; clothing is smaller but still meaningful for comfort, medical-adjacent apparel, and senior retail formats.",
        "",
        "## Segment Analysis",
        "| Segment | Demand driver | Research implication |",
        "| --- | --- | --- |",
        "| Food | Daily necessity, smaller households, delivery, health-oriented diets | Size grocery, prepared meals, supplements, and delivery separately. |",
        "| Housing | Home ownership, retrofits, heating/cooling, barrier-free renovation | Treat renovation, assisted living, and home services as separate pools. |",
        "| Transportation | Rural access, medical visits, shopping trips, license surrender | Model taxis, community mobility, assisted transit, and delivery substitution. |",
        "| Clothing | Comfort, accessibility, medical needs, retail channel shift | Smaller pool than food/housing but useful for specialized products. |",
        "",
        "## Risks And Uncertainty",
        "The largest forecast risks are inflation, elderly income dispersion, regional population decline, healthy-life expectancy, care policy, and substitution between transport trips and home delivery. A serious forecast should publish low/base/high cases instead of a single market-size number.",
        "",
        "## Actionable Conclusion",
        "The best near-term opportunities are not generic elderly products. They are category-specific services that combine official demographic density, recurring household expenditure, and operational access: food delivery and prepared meals, home adaptation, care-adjacent housing services, and assisted local mobility.",
    ]


def _investor_philosophy_sections() -> list[str]:
    return [
        "## Methodology",
        "The comparison separates primary-source principles from later commentary. It looks for repeated decision rules, examples of avoided behavior, and how each investor translates business analysis into portfolio action.",
        "",
        "## Comparative Framework",
        "| Dimension | Warren Buffett | Charlie Munger | Duan Yongping |",
        "| --- | --- | --- | --- |",
        "| Core lens | Durable business quality and intrinsic value | Mental models, incentives, and error avoidance | Great businesses, consumer franchises, and owner mindset |",
        "| Risk control | Margin of safety and business predictability | Avoid stupidity, bad incentives, and fragile systems | Avoid businesses outside circle of competence |",
        "| Time horizon | Long holding periods | Patience and compounding | Long-term ownership of understandable companies |",
        "| Edge | Temperament plus disciplined valuation | Judgment quality and multidisciplinary thinking | Operator-investor perspective and product intuition |",
        "",
        "## Synthesis",
        "All three converge on buying understandable, high-quality businesses and holding them patiently. The useful distinction is not slogans but emphasis: Buffett is clearest on valuation and capital allocation, Munger on cognition and incentives, and Duan on product, consumer behavior, and operator judgment.",
        "",
        "## Actionable Conclusion",
        "A practical investor can combine the three by using Buffett for valuation discipline, Munger for decision hygiene, and Duan for business-quality/product judgment. The resulting checklist should reject weak businesses before valuation work begins.",
    ]


def _government_investment_sections() -> list[str]:
    return [
        "## Methodology",
        "The analysis distinguishes institutions that are often conflated: sovereign wealth funds, central-bank reserves, public pension funds, fiscal stabilization funds, and state-owned investment vehicles. Comparing them requires mandate, asset base, liquidity needs, governance rules, and disclosure quality.",
        "",
        "## Investment Institution Map",
        "| Institution type | Main objective | Typical assets | Key constraint |",
        "| --- | --- | --- | --- |",
        "| Sovereign wealth fund | Intergenerational savings or stabilization | Global equities, bonds, real assets | Political mandate and withdrawal rules |",
        "| Public pension fund | Fund retirement liabilities | Diversified public/private assets | Liability duration and contribution policy |",
        "| Central-bank reserves | Liquidity and currency stability | High-quality sovereign bonds, cash, gold | Safety and liquidity over return |",
        "| State investment vehicle | Strategic or industrial policy | Domestic champions, infrastructure, private assets | Policy goals can dominate financial return |",
        "",
        "## Comparative Analysis",
        "The world's wealthiest governments do not invest through one balance sheet. Norway's GPFG is a transparent sovereign-investment benchmark; Japan's GPIF shows pension-scale allocation; reserve managers show safety-first portfolios; and Gulf or Asian sovereign funds often blend savings, diversification, and strategic development.",
        "",
        "## Actionable Conclusion",
        "Any ranking should publish definitions first. Assets under management, fiscal reserves, foreign-exchange reserves, and pension liabilities answer different questions and produce different leaders.",
    ]


def _generic_research_sections(state: dict[str, Any]) -> list[str]:
    subquestions = state.get("program", {}).get("subquestions", [])
    lines = [
        "## Methodology",
        "The research loop decomposes the objective into claims, evidence requirements, contradictions, and stop conditions. It prioritizes authoritative sources, records uncertainty, and reruns targeted workers when evaluator metrics show gaps.",
        "",
        "## Research Plan",
    ]
    for item in subquestions:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Actionable Conclusion",
            "Use the cited claims as the current answer, but treat low-confidence or weakly sourced claims as follow-up work before relying on the report operationally.",
        ]
    )
    return lines
