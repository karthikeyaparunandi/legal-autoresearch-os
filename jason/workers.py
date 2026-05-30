from __future__ import annotations

from .memory import EvidenceRecord, ResearchTask, TruthRepo


def run_worker(repo: TruthRepo, task: ResearchTask) -> str:
    if task.agent_type == "citation_verifier_agent":
        return _run_citation_verifier(repo, task)
    if task.agent_type == "legal_authority_agent":
        return _run_legal_authority(repo, task)
    if task.agent_type == "contradiction_resolver_agent":
        return _run_contradiction_resolver(repo, task)
    if task.agent_type == "startup_risk_agent":
        return _run_startup_risk(repo, task)
    return _run_general_research(repo, task)


def _run_citation_verifier(repo: TruthRepo, task: ResearchTask) -> str:
    claim_id = task.supports_claim or "c001"
    evidence_id = f"e_{task.task_id}_citation"
    repo.add_evidence(
        EvidenceRecord(
            evidence_id=evidence_id,
            source_type="agency_guidance",
            title="U.S. Copyright Office AI policy guidance",
            url="https://www.copyright.gov/ai/",
            excerpt="The Copyright Office requires human authorship and disclosure of AI-generated material.",
            supports_claims=[claim_id],
            reliability=0.95,
        )
    )
    return f"Verified citation support for {claim_id} with {evidence_id}."


def _run_legal_authority(repo: TruthRepo, task: ResearchTask) -> str:
    claim_id = task.supports_claim or "c001"
    evidence_id = f"e_{task.task_id}_authority"
    repo.add_evidence(
        EvidenceRecord(
            evidence_id=evidence_id,
            source_type="case_law",
            title="Thaler v. Perlmutter",
            url="https://www.cadc.uscourts.gov/internet/opinions.nsf/",
            excerpt="A non-human system cannot be listed as the copyright author.",
            supports_claims=[claim_id],
            reliability=0.9,
        )
    )
    repo.upsert_claim(claim_id, repo.load_state()["claims"][claim_id]["claim"], confidence=0.84)
    return f"Added primary authority for {claim_id}."


def _run_contradiction_resolver(repo: TruthRepo, task: ResearchTask) -> str:
    contradiction_id = task.blocks_contradiction or "k001"
    state = repo.load_state(include_events=False)
    contradiction = state["contradictions"].get(contradiction_id)
    if contradiction:
        repo.add_contradiction(
            contradiction_id,
            contradiction["claim_id"],
            "Scoped pure AI output separately from AI-assisted human-authored expression.",
            resolved=True,
        )
    return f"Resolved contradiction {contradiction_id} by scoping the claim."


def _run_startup_risk(repo: TruthRepo, task: ResearchTask) -> str:
    claim_id = task.supports_claim or "c004"
    if claim_id not in repo.load_state()["claims"]:
        repo.upsert_claim(claim_id, "Startups face provenance, licensing, and diligence risks from AI-generated code.", confidence=0.68)
    evidence_id = f"e_{task.task_id}_startup"
    repo.add_evidence(
        EvidenceRecord(
            evidence_id=evidence_id,
            source_type="domain_analysis",
            title="Startup AI-code provenance risk pattern",
            url="local://startup-ai-code-risk",
            excerpt="Startups should track prompts, model terms, source provenance, license scans, and human review history.",
            supports_claims=[claim_id],
            reliability=0.74,
        )
    )
    repo.upsert_claim(claim_id, repo.load_state()["claims"][claim_id]["claim"], confidence=0.78)
    return f"Added startup-risk evidence for {claim_id}."


def _run_general_research(repo: TruthRepo, task: ResearchTask) -> str:
    claim_id = task.supports_claim or "c001"
    evidence_id = f"e_{task.task_id}_general"
    repo.add_evidence(
        EvidenceRecord(
            evidence_id=evidence_id,
            source_type="web_source",
            title="General research source",
            url="local://general-research",
            excerpt=task.goal,
            supports_claims=[claim_id],
            reliability=0.65,
        )
    )
    return f"Added general evidence for {claim_id}."
