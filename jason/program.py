from __future__ import annotations

from dataclasses import dataclass

from .legal_skills import (
    is_legal_goal,
    legal_claims_for_goal,
    legal_contradiction_note,
    legal_evidence_requirements_for_goal,
    legal_skill_names,
    legal_subquestions_for_goal,
)

@dataclass(frozen=True)
class ClaimSeed:
    claim_id: str
    claim: str
    confidence: float


@dataclass(frozen=True)
class ContradictionSeed:
    contradiction_id: str
    claim_id: str
    note: str


@dataclass(frozen=True)
class ProgramSeed:
    objective: str
    subquestions: list[str]
    stop_conditions: dict[str, float | int]
    claims: list[ClaimSeed]
    contradictions: list[ContradictionSeed]


DEFAULT_STOP_CONDITIONS = {
    "objective_coverage": 0.9,
    "citation_grounding": 0.9,
    "primary_source_coverage": 0.75,
    "contradiction_resolution": 0.8,
    "open_critical_questions": 1,
}


def build_program_seed(goal: str) -> ProgramSeed:
    lower = goal.lower()
    if is_legal_goal(goal):
        claims = legal_claims_for_goal(goal)
        skill_names = ", ".join(legal_skill_names(goal)) or "general_legal_research"
        return ProgramSeed(
            objective=goal,
            subquestions=[
                *legal_subquestions_for_goal(goal),
                *legal_evidence_requirements_for_goal(goal),
            ],
            stop_conditions=DEFAULT_STOP_CONDITIONS,
            claims=[
                ClaimSeed("c001", claims[0], 0.36),
                ClaimSeed("c002", claims[1], 0.34),
                ClaimSeed("c003", claims[2], 0.32),
                ClaimSeed("c004", claims[3], 0.32),
            ],
            contradictions=[
                ContradictionSeed("k001", "c003", legal_contradiction_note(goal)),
                ContradictionSeed(
                    "k002",
                    "c004",
                    f"The selected Claude-style legal skill path ({skill_names}) may require specialist review before acting.",
                ),
            ],
        )
    if "japan" in lower and ("elderly" in lower or "65" in lower):
        return ProgramSeed(
            objective=goal,
            subquestions=[
                "How large is Japan's 65+ population in 2020, 2030, 2040, and 2050?",
                "Which household spending categories matter most for elderly consumers?",
                "How should clothing, food, housing, and transportation demand be sized?",
                "Which demographic, income, inflation, and behavior assumptions drive uncertainty?",
            ],
            stop_conditions=DEFAULT_STOP_CONDITIONS,
            claims=[
                ClaimSeed("c001", "Japan's elderly population is a large and growing 65+ cohort through 2050, even as total population declines.", 0.36),
                ClaimSeed("c002", "Elderly consumption potential should be estimated from population projections, household spending, income, assets, and care needs.", 0.34),
                ClaimSeed("c003", "Food, housing, healthcare-adjacent services, and mobility/transportation are the most defensible market-sizing segments for Japan's elderly demographic.", 0.34),
                ClaimSeed("c004", "The market-size forecast must carry uncertainty for inflation, healthy-life expectancy, regional depopulation, and changing elderly consumer preferences.", 0.32),
            ],
            contradictions=[
                ContradictionSeed("k001", "c001", "A rising elderly share can coexist with a shrinking absolute population in some forecast windows."),
            ],
        )
    if any(name in lower for name in ["buffett", "munger", "duan yongping"]):
        return ProgramSeed(
            objective=goal,
            subquestions=[
                "What principles define each investor's philosophy?",
                "Where do the philosophies overlap and diverge?",
                "Which primary writings or shareholder communications support the comparison?",
                "How should the ideas translate into practical investment behavior?",
            ],
            stop_conditions=DEFAULT_STOP_CONDITIONS,
            claims=[
                ClaimSeed("c001", "Buffett emphasizes durable business quality, capable management, margin of safety, and long holding periods.", 0.38),
                ClaimSeed("c002", "Munger adds multidisciplinary thinking, incentives, patience, and avoiding obvious mistakes as central investment disciplines.", 0.36),
                ClaimSeed("c003", "Duan Yongping's philosophy overlaps with Buffett and Munger through business quality, consumer franchise strength, and owner-like thinking.", 0.34),
                ClaimSeed("c004", "A useful comparison should separate shared value-investing principles from differences in operating background, market context, and communication style.", 0.32),
            ],
            contradictions=[
                ContradictionSeed("k001", "c004", "Shared principles can obscure differences in market, geography, and operating experience."),
            ],
        )
    if "government" in lower and "invest" in lower:
        return ProgramSeed(
            objective=goal,
            subquestions=[
                "Which governments or public investment institutions control the largest pools of investable assets?",
                "How do sovereign wealth funds, pension funds, and reserve managers differ?",
                "What asset allocation patterns are visible from official disclosures?",
                "What risks and governance constraints shape public-sector investment decisions?",
            ],
            stop_conditions=DEFAULT_STOP_CONDITIONS,
            claims=[
                ClaimSeed("c001", "The largest public investors include sovereign wealth funds, public pension funds, and reserve managers rather than a single uniform government balance sheet.", 0.36),
                ClaimSeed("c002", "Norway's Government Pension Fund Global is a transparent anchor case for equity-heavy sovereign investment at global scale.", 0.35),
                ClaimSeed("c003", "Public investors balance return, liquidity, currency, domestic-policy, and governance constraints differently by mandate.", 0.34),
                ClaimSeed("c004", "A credible ranking or comparison must distinguish assets under management, fiscal reserves, central-bank reserves, and pension liabilities.", 0.32),
            ],
            contradictions=[
                ContradictionSeed("k001", "c004", "Different definitions of government wealth can produce different rankings of the world's wealthiest governments."),
            ],
        )
    topic = _compact_topic(goal)
    return ProgramSeed(
        objective=goal,
        subquestions=[
            f"What are the core facts and definitions needed to answer {topic}?",
            "Which authoritative sources support the answer?",
            "Where are the main uncertainties, tradeoffs, or competing interpretations?",
            "What practical implications follow from the evidence?",
        ],
        stop_conditions=DEFAULT_STOP_CONDITIONS,
        claims=[
            ClaimSeed("c001", f"The research answer should define the scope and baseline facts for {topic}.", 0.34),
            ClaimSeed("c002", f"Authoritative sources are needed to quantify or substantiate {topic}.", 0.32),
            ClaimSeed("c003", f"The report should compare competing interpretations and expose uncertainty around {topic}.", 0.32),
            ClaimSeed("c004", f"The final synthesis should translate the evidence on {topic} into practical implications.", 0.32),
        ],
        contradictions=[
            ContradictionSeed("k001", "c003", "The initial research state has not yet reconciled competing interpretations or uncertainty."),
        ],
    )


def _compact_topic(goal: str) -> str:
    words = [word.strip(" ,.?;:()[]{}").lower() for word in goal.split()]
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "what", "how", "please"}
    keywords = [word for word in words if word and word not in stop]
    return " ".join(keywords[:8]) or "the research question"
