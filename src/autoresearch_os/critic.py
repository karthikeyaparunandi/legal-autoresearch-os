from __future__ import annotations

from .models import Claim, Contradiction


def critique_claims(claims: list[Claim]) -> tuple[list[Contradiction], list[str]]:
    contradictions: list[Contradiction] = []
    criticisms: list[str] = []

    for claim in claims:
        if not claim.supporting_sources:
            criticisms.append(f"{claim.claim_id}: no supporting evidence yet.")
        if claim.contradicting_sources:
            claim_lower = claim.claim.lower()
            can_scope = bool(
                claim.supporting_sources
                and ("pure ai" in claim_lower or "solely by an ai" in claim_lower or "without meaningful human" in claim_lower)
            )
            contradictions.append(
                Contradiction(
                    claim=claim.claim,
                    supporting_sources=claim.supporting_sources,
                    contradicting_sources=claim.contradicting_sources,
                    resolution_status="resolved" if can_scope else "unresolved",
                    note=(
                        "Scoped distinction: pure AI output lacks human authorship, while AI-assisted output may include protectable human expression."
                        if can_scope
                        else "Needs synthesis explaining when both positions can be true."
                    ),
                )
            )
        if claim.confidence < 0.7:
            criticisms.append(f"{claim.claim_id}: confidence below support threshold ({claim.confidence:.0%}).")

    return contradictions, criticisms
