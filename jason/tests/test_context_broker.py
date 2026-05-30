from __future__ import annotations

import json

from jason.agent import search_truth_repo_evidence_impl
from jason.context_broker import ContextBroker
from jason.memory import EvidenceRecord, TruthRepo


def test_control_slice_excludes_bulk_evidence_and_events(tmp_path):
    repo = TruthRepo(tmp_path / "truth_repo")
    repo.write_program(
        objective="Can AI-generated code be copyrighted?",
        subquestions=["What requires human authorship?"],
        stop_conditions={"citation_grounding": 0.9},
    )
    repo.upsert_claim("c001", "Pure AI-generated code needs human authorship.", confidence=0.4)
    repo.add_evidence(
        EvidenceRecord(
            evidence_id="e001",
            source_type="agency_guidance",
            title="Copyright Office AI guidance",
            url="https://www.copyright.gov/ai/",
            excerpt="Human authorship is required.",
            supports_claims=["c001"],
            reliability=0.95,
        )
    )

    evidence_path = repo.root / "evidence.json"
    evidence_items = json.loads(evidence_path.read_text(encoding="utf-8"))
    for index in range(200):
        evidence_items[f"noise_{index:03d}"] = {
            "evidence_id": f"noise_{index:03d}",
            "source_type": "background_noise",
            "title": f"Archived irrelevant note {index}",
            "url": f"https://example.invalid/{index}",
            "excerpt": "Synthetic stale memory that should not enter control context.",
            "supports_claims": [],
            "contradicts_claims": [],
            "reliability": 0.1,
            "accepted": False,
        }
        repo.append_event("noise_recorded", {"index": index})
    evidence_path.write_text(json.dumps(evidence_items, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    full_state = repo.load_state(include_events=True)
    control_slice = ContextBroker(repo).control_slice(recent_events_limit=5, budget_bytes=4_000)

    assert "evidence" not in control_slice
    assert control_slice["counts"]["evidence"] == 201
    assert len(control_slice["recent_events"]) == 5
    assert _json_size(control_slice) <= 4_000
    assert _json_size(control_slice) < _json_size(full_state) / 10


def test_claim_context_uses_linked_evidence_index_not_bulk_noise(tmp_path):
    repo = TruthRepo(tmp_path / "truth_repo")
    repo.write_program(
        objective="Can AI-generated code be copyrighted?",
        subquestions=["What requires human authorship?"],
        stop_conditions={"citation_grounding": 0.9},
    )
    repo.upsert_claim("c001", "Pure AI-generated code needs human authorship.", confidence=0.4)
    repo.add_evidence(
        EvidenceRecord(
            evidence_id="support001",
            source_type="agency_guidance",
            title="Copyright Office AI guidance",
            url="https://www.copyright.gov/ai/",
            excerpt="Human authorship is required.",
            supports_claims=["c001"],
            reliability=0.95,
        )
    )
    repo.add_evidence(
        EvidenceRecord(
            evidence_id="contra001",
            source_type="web_source",
            title="Commentary on AI-assisted works",
            url="https://example.com/ai-assisted",
            excerpt="AI-assisted work may include protectable human choices.",
            contradicts_claims=["c001"],
            reliability=0.7,
        )
    )

    evidence_path = repo.root / "evidence.json"
    evidence_items = json.loads(evidence_path.read_text(encoding="utf-8"))
    for index in range(50):
        evidence_items[f"noise_{index:03d}"] = {
            "evidence_id": f"noise_{index:03d}",
            "source_type": "background_noise",
            "title": f"Archived irrelevant note {index}",
            "url": f"https://example.invalid/{index}",
            "excerpt": "DO_NOT_INCLUDE_STALE_MEMORY",
            "supports_claims": [],
            "contradicts_claims": [],
            "reliability": 0.1,
            "accepted": False,
        }
    evidence_path.write_text(json.dumps(evidence_items, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    claim_context = ContextBroker(repo).claim_context("c001", budget_bytes=3_000)
    rendered = json.dumps(claim_context, sort_keys=True)

    assert claim_context["claim"]["claim_id"] == "c001"
    assert claim_context["provenance"]["raw_evidence_ids"] == ["support001", "contra001"]
    assert "DO_NOT_INCLUDE_STALE_MEMORY" not in rendered
    assert _json_size(claim_context) <= 3_000


def test_parent_agent_can_search_scoped_evidence_without_full_repo_read(tmp_path):
    repo = TruthRepo(tmp_path / "truth_repo")
    repo.write_program(
        objective="Research Japan elderly market sizing.",
        subquestions=["What data supports elderly consumer demand?"],
        stop_conditions={"citation_grounding": 0.9},
    )
    repo.upsert_claim("c001", "Japan elderly demand depends on household spending data.", confidence=0.4)
    repo.add_evidence(
        EvidenceRecord(
            evidence_id="support001",
            source_type="official_material",
            title="Statistics Bureau household expenditure",
            url="https://www.stat.go.jp/english/data/kakei/index.html",
            excerpt="Household spending by category supports elderly consumption estimates.",
            supports_claims=["c001"],
            reliability=0.92,
        )
    )

    result = json.loads(search_truth_repo_evidence_impl(str(repo.root), query="household", claim_id="c001", limit=3))

    assert result["query"] == "household"
    assert result["evidence"][0]["evidence_id"] == "support001"
    assert result["provenance"]["raw_evidence_ids"] == ["support001"]


def _json_size(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))
