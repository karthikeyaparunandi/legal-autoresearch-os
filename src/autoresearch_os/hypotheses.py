from __future__ import annotations

from .models import Hypothesis, ResearchProgram


def generate_hypotheses(program: ResearchProgram) -> list[Hypothesis]:
    goal = program.objective.lower()
    if any(term in goal for term in ["contract template", "legal template", "legal forms"]):
        statements = [
            (
                "A startup can usually offer generic AI-generated contract templates, but applying law to a customer's specific facts can create unauthorized-practice-of-law risk.",
                "The key distinction is generic self-help information versus individualized legal advice or document customization.",
            ),
            (
                "Customer-facing AI contract templates can create warranty, misrepresentation, consumer-protection, and negligence-style liability if marketed as reliable legal outputs.",
                "Risk turns on representations, disclaimers, review workflows, and whether the template fails for the customer's transaction or jurisdiction.",
            ),
            (
                "A decision-grade answer must identify target jurisdictions and customer type because UPL and contract-enforceability rules vary by state and context.",
                "U.S. law is not a single national contract-template rule; state law and professional conduct rules control much of the risk.",
            ),
        ]
    elif "ai-generated code" in goal and "copyright" in goal:
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
