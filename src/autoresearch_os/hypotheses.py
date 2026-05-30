from __future__ import annotations

from .models import Hypothesis, ResearchProgram


def generate_hypotheses(program: ResearchProgram) -> list[Hypothesis]:
    goal = program.objective.lower()
    if "ai-generated code" in goal and "copyright" in goal:
        statements = [
            ("Pure AI-generated code is unlikely to be copyrightable without human authorship.", "Copyright law centers human authorship."),
            ("AI-assisted code may be copyrightable when humans select, arrange, modify, or contribute expression.", "Human creative contribution can remain protectable."),
            ("The determining issue is the boundary between prompting and expressive human control.", "Prompting alone may be too abstract, while detailed expressive control may matter."),
            ("Startups face ownership uncertainty, license compliance, and infringement risks.", "Code provenance affects fundraising, acquisition diligence, and product risk."),
        ]
    else:
        statements = [
            ("The strongest answer will depend on source quality rather than source volume.", "Research confidence needs authoritative evidence."),
            ("Contradictions are likely to expose the most important follow-up questions.", "Unresolved conflicts drive the next research tasks."),
            ("A sufficient answer must identify limits and uncertainty, not only a conclusion.", "Research reports should be decision-grade."),
        ]

    return [
        Hypothesis(hypothesis_id=f"h{index:03d}", statement=statement, rationale=rationale)
        for index, (statement, rationale) in enumerate(statements, start=1)
    ]
