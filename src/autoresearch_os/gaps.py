from __future__ import annotations

from .models import Claim, Contradiction, ResearchProgram


def detect_gaps(program: ResearchProgram, claims: list[Claim], contradictions: list[Contradiction], criticisms: list[str]) -> list[str]:
    questions: list[str] = []

    for claim in claims:
        if claim.status != "supported":
            questions.append(f"What additional authoritative evidence would resolve claim {claim.claim_id}: {claim.claim}")

    for contradiction in contradictions:
        if contradiction.resolution_status != "resolved":
            questions.append(f"Can this contradiction be scoped or resolved: {contradiction.claim}")

    if len(claims) < len(program.subquestions) - 1:
        questions.append("Are all program subquestions represented by explicit claims?")

    for criticism in criticisms[:2]:
        questions.append(f"Critic follow-up: {criticism}")

    return dedupe(questions)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
