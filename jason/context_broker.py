from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any
import json

from .evaluator import PRIMARY_SOURCE_TYPES
from .memory import TruthRepo


DEFAULT_CONTROL_BUDGET_BYTES = 12_000
DEFAULT_CLAIM_BUDGET_BYTES = 24_000


class ContextBroker:
    """Budgeted read API for Truth Repo state.

    The broker is intentionally separate from the model-facing agent. It turns
    large repo state into typed, provenance-preserving slices that can be sent
    to a model without dumping stale evidence or append-only logs.
    """

    def __init__(self, repo: TruthRepo) -> None:
        self.repo = repo

    def control_slice(
        self,
        recent_events_limit: int = 10,
        active_task_limit: int = 10,
        budget_bytes: int = DEFAULT_CONTROL_BUDGET_BYTES,
    ) -> dict[str, Any]:
        program = self._read_json("program.json", {})
        tasks = self._read_json("tasks.json", [])
        claims = self._read_json("claims.json", {})
        contradictions = self._read_json("contradictions.json", {})
        evals = self._read_json("evals.json", [])
        events = self._read_jsonl_tail("events.jsonl", recent_events_limit)

        latest_eval = evals[-1] if evals else {}
        active_tasks = [task for task in tasks if task.get("status") in {"pending", "running"}][:active_task_limit]
        unresolved = {
            key: value
            for key, value in contradictions.items()
            if not value.get("resolved")
        }
        weak_claim_ids = latest_eval.get("weak_claim_ids") or [
            claim["claim_id"]
            for claim in claims.values()
            if len(claim.get("supporting_evidence", [])) < 2 or claim.get("confidence", 0.0) < 0.82
        ]

        payload: dict[str, Any] = {
            "program": program,
            "latest_eval": latest_eval,
            "active_tasks": active_tasks,
            "weak_claim_ids": weak_claim_ids,
            "unresolved_contradictions": unresolved,
            "recent_events": events,
            "counts": {
                "claims": len(claims),
                "evidence": self._evidence_count(),
                "tasks": len(tasks),
                "events": self._jsonl_count("events.jsonl"),
                "evals": len(evals),
            },
        }
        return self._fit_control_payload(payload, budget_bytes)

    def claim_context(
        self,
        claim_id: str,
        budget_bytes: int = DEFAULT_CLAIM_BUDGET_BYTES,
        max_evidence: int = 12,
    ) -> dict[str, Any]:
        claims = self._read_json("claims.json", {})
        claim = claims.get(claim_id)
        if not claim:
            return {
                "claim": None,
                "evidence": [],
                "graph": {"center": claim_id, "edges": []},
                "provenance": {"raw_evidence_ids": [], "omitted_evidence_ids": []},
            }

        indexed_ids = self._claim_evidence_ids(claim_id, claim)
        evidence_items = [item for item in self._read_evidence_records(indexed_ids) if item]
        ranked = sorted(evidence_items, key=self._evidence_rank, reverse=True)
        selected = ranked[:max_evidence]
        payload = {
            "claim": claim,
            "evidence": selected,
            "graph": {
                "center": claim_id,
                "edges": self._claim_edges(claim_id, selected),
            },
            "provenance": {
                "raw_evidence_ids": [item["evidence_id"] for item in selected],
                "omitted_evidence_ids": [item["evidence_id"] for item in ranked[max_evidence:]],
            },
        }
        return self._fit_evidence_payload(payload, budget_bytes)

    def contradiction_context(
        self,
        contradiction_id: str,
        budget_bytes: int = DEFAULT_CLAIM_BUDGET_BYTES,
    ) -> dict[str, Any]:
        contradictions = self._read_json("contradictions.json", {})
        contradiction = contradictions.get(contradiction_id)
        if not contradiction:
            return {
                "contradiction": None,
                "claim_context": None,
                "provenance": {"raw_evidence_ids": []},
            }
        claim_context = self.claim_context(contradiction["claim_id"], budget_bytes=budget_bytes)
        return {
            "contradiction": contradiction,
            "claim_context": claim_context,
            "provenance": claim_context.get("provenance", {"raw_evidence_ids": []}),
        }

    def task_context(
        self,
        task_id: str,
        budget_bytes: int = DEFAULT_CLAIM_BUDGET_BYTES,
    ) -> dict[str, Any]:
        tasks = self._read_json("tasks.json", [])
        task = next((item for item in tasks if item.get("task_id") == task_id), None)
        if not task:
            return {"task": None, "context": None}
        if task.get("supports_claim"):
            return {"task": task, "context": self.claim_context(task["supports_claim"], budget_bytes=budget_bytes)}
        if task.get("blocks_contradiction"):
            return {
                "task": task,
                "context": self.contradiction_context(task["blocks_contradiction"], budget_bytes=budget_bytes),
            }
        return {"task": task, "context": self.control_slice(budget_bytes=budget_bytes)}

    def search_evidence(
        self,
        query: str = "",
        source_types: Iterable[str] | None = None,
        claim_id: str | None = None,
        accepted: bool | None = None,
        budget_bytes: int = DEFAULT_CLAIM_BUDGET_BYTES,
        limit: int = 10,
    ) -> dict[str, Any]:
        candidate_ids: list[str]
        if claim_id:
            claims = self._read_json("claims.json", {})
            candidate_ids = self._claim_evidence_ids(claim_id, claims.get(claim_id, {}))
        elif source_types:
            candidate_ids = []
            for source_type in source_types:
                candidate_ids.extend(self._read_json(str(Path("indexes") / "by_source_type" / f"{source_type}.json"), []))
        else:
            candidate_ids = self._all_record_ids()

        query_lower = query.lower()
        source_type_set = set(source_types or [])
        matches = []
        for item in self._read_evidence_records(candidate_ids):
            if not item:
                continue
            if accepted is not None and item.get("accepted", False) is not accepted:
                continue
            if source_type_set and item.get("source_type") not in source_type_set:
                continue
            searchable = " ".join([item.get("title", ""), item.get("excerpt", ""), item.get("url", "")]).lower()
            if query_lower and query_lower not in searchable:
                continue
            matches.append(item)

        selected = sorted(matches, key=self._evidence_rank, reverse=True)[:limit]
        payload = {
            "query": query,
            "filters": {
                "source_types": sorted(source_type_set),
                "claim_id": claim_id,
                "accepted": accepted,
            },
            "evidence": selected,
            "provenance": {
                "raw_evidence_ids": [item["evidence_id"] for item in selected],
                "omitted_evidence_ids": [item["evidence_id"] for item in matches[limit:]],
            },
        }
        return self._fit_evidence_payload(payload, budget_bytes)

    def _read_json(self, name: str, default: Any) -> Any:
        path = self.repo.root / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_jsonl_tail(self, name: str, limit: int) -> list[dict[str, Any]]:
        path = self.repo.root / name
        if not path.exists() or limit <= 0:
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines[-limit:]]

    def _jsonl_count(self, name: str) -> int:
        path = self.repo.root / name
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def _evidence_count(self) -> int:
        records_dir = self.repo.root / "evidence_records"
        records_count = len(list(records_dir.glob("*.json"))) if records_dir.exists() else 0
        evidence_path = self.repo.root / "evidence.json"
        if not evidence_path.exists():
            return records_count
        return max(records_count, len(json.loads(evidence_path.read_text(encoding="utf-8"))))

    def _claim_evidence_ids(self, claim_id: str, claim: dict[str, Any]) -> list[str]:
        index_path = self.repo.root / "indexes" / "by_claim" / f"{claim_id}.json"
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            return _unique([*index.get("supports", []), *index.get("contradicts", [])])
        return _unique([*claim.get("supporting_evidence", []), *claim.get("contradicting_evidence", [])])

    def _read_evidence_records(self, evidence_ids: Iterable[str]) -> list[dict[str, Any]]:
        fallback: dict[str, Any] | None = None
        records = []
        for evidence_id in _unique(list(evidence_ids)):
            record_path = self.repo.root / "evidence_records" / f"{evidence_id}.json"
            if record_path.exists():
                records.append(json.loads(record_path.read_text(encoding="utf-8")))
                continue
            if fallback is None:
                fallback = self._read_json("evidence.json", {})
            if evidence_id in fallback:
                records.append(fallback[evidence_id])
        return records

    def _all_record_ids(self) -> list[str]:
        records_dir = self.repo.root / "evidence_records"
        if records_dir.exists():
            return sorted(path.stem for path in records_dir.glob("*.json"))
        return sorted(self._read_json("evidence.json", {}).keys())

    def _claim_edges(self, claim_id: str, evidence_items: list[dict[str, Any]]) -> list[dict[str, str]]:
        edges = []
        for item in evidence_items:
            evidence_id = item["evidence_id"]
            if claim_id in item.get("supports_claims", []):
                edges.append({"from": evidence_id, "to": claim_id, "type": "supports"})
            if claim_id in item.get("contradicts_claims", []):
                edges.append({"from": evidence_id, "to": claim_id, "type": "contradicts"})
        return edges

    def _evidence_rank(self, item: dict[str, Any]) -> tuple[float, float, float]:
        accepted_score = 1.0 if item.get("accepted", False) else 0.0
        primary_score = 1.0 if item.get("source_type") in PRIMARY_SOURCE_TYPES else 0.0
        return (accepted_score, primary_score, float(item.get("reliability", 0.0)))

    def _fit_control_payload(self, payload: dict[str, Any], budget_bytes: int) -> dict[str, Any]:
        if _json_size(payload) <= budget_bytes:
            return payload
        trimmed = dict(payload)
        trimmed["recent_events"] = trimmed.get("recent_events", [])[-3:]
        if _json_size(trimmed) <= budget_bytes:
            trimmed["_truncated"] = True
            return trimmed
        trimmed["active_tasks"] = trimmed.get("active_tasks", [])[:3]
        if _json_size(trimmed) <= budget_bytes:
            trimmed["_truncated"] = True
            return trimmed
        trimmed["recent_events"] = []
        trimmed["_truncated"] = True
        return trimmed

    def _fit_evidence_payload(self, payload: dict[str, Any], budget_bytes: int) -> dict[str, Any]:
        fitted = json.loads(json.dumps(payload))
        fitted["evidence"] = [self._compress_evidence_item(item) for item in fitted.get("evidence", [])]
        omitted = fitted.setdefault("provenance", {}).setdefault("omitted_evidence_ids", [])
        while _json_size(fitted) > budget_bytes and fitted.get("evidence"):
            removed = fitted["evidence"].pop()
            omitted.append(removed["evidence_id"])
            fitted["provenance"]["raw_evidence_ids"] = [item["evidence_id"] for item in fitted["evidence"]]
        if _json_size(fitted) > budget_bytes:
            fitted["evidence"] = []
            fitted["provenance"]["raw_evidence_ids"] = []
            fitted["_truncated"] = True
        elif len(fitted.get("evidence", [])) != len(payload.get("evidence", [])):
            fitted["_truncated"] = True
        return fitted

    def _compress_evidence_item(self, item: dict[str, Any]) -> dict[str, Any]:
        compressed = dict(item)
        excerpt = compressed.get("excerpt", "")
        if len(excerpt) > 360:
            compressed["excerpt"] = excerpt[:357].rstrip() + "..."
        return compressed


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique_items.append(item)
    return unique_items


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
