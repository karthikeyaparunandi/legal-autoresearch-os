from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .critic import critique_claims
from .hypotheses import generate_hypotheses
from .knowledge import collect_evidence
from .models import Claim, Contradiction, Evidence, Hypothesis, ResearchProgram, Task
from .llm import CentralReasoner


@dataclass
class AgentTrace:
    name: str
    goal: str
    tools: list[str]
    steps: list[str] = field(default_factory=list)
    used_llm: bool = False
    llm_model: str | None = None
    output_count: int = 0


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]


class ResearchAgent:
    def __init__(self, name: str, goal: str, tools: list[Tool], reasoner: CentralReasoner, skills: list[str] | None = None) -> None:
        self.name = name
        self.goal = goal
        self.tools = {tool.name: tool for tool in tools}
        self.reasoner = reasoner
        self.skills = skills or []
        self.trace = AgentTrace(
            name=name,
            goal=goal,
            tools=list(self.tools),
            used_llm=reasoner.enabled,
            llm_model=reasoner.model if reasoner.enabled else None,
        )

    def tool(self, name: str, *args, **kwargs):
        self.trace.steps.append(f"tool:{name}")
        return self.tools[name].fn(*args, **kwargs)

    def reason_json(self, instruction: str, payload: dict) -> dict | None:
        self.trace.steps.append("llm_reasoning" if self.reasoner.enabled else "deterministic_fallback")
        return self.reasoner.reason_json(self.name, instruction, {"learned_skills": self.skills, **payload})


def run_hypothesis_agent(program: ResearchProgram, reasoner: CentralReasoner, agent_skills: dict[str, list[str]] | None = None) -> tuple[list[Hypothesis], AgentTrace]:
    agent = ResearchAgent(
        "hypothesis_agent",
        "Generate and refine candidate legal theories.",
        [Tool("generate_baseline_hypotheses", generate_hypotheses)],
        reasoner,
        (agent_skills or {}).get("hypothesis_agent", []),
    )
    hypotheses = agent.tool("generate_baseline_hypotheses", program)
    revised = agent.reason_json(
        "Refine these legal research hypotheses. Preserve IDs if possible. Return {\"hypotheses\":[{\"statement\":\"...\",\"rationale\":\"...\"}]}",
        {"objective": program.objective, "baseline_hypotheses": [h.__dict__ for h in hypotheses]},
    )
    if revised and isinstance(revised.get("hypotheses"), list):
        hypotheses = _hypotheses_from_llm(revised["hypotheses"], hypotheses)
    agent.trace.output_count = len(hypotheses)
    return hypotheses, agent.trace


def run_hypothesis_refinement_agent(
    program: ResearchProgram,
    hypotheses: list[Hypothesis],
    claims: list[Claim],
    contradictions: list[Contradiction],
    criticisms: list[str],
    open_questions: list[str],
    reasoner: CentralReasoner,
    agent_skills: dict[str, list[str]] | None = None,
) -> tuple[list[Hypothesis], AgentTrace]:
    agent = ResearchAgent(
        "hypothesis_refinement_agent",
        "Revise hypotheses from critic, evidence, and knowledge-gap feedback.",
        [],
        reasoner,
        (agent_skills or {}).get("hypothesis_refinement_agent", []),
    )
    revised = agent.reason_json(
        (
            "Revise or preserve these legal hypotheses using critic feedback and open questions. "
            "Prefer scoped hypotheses over unresolved contradictions. Preserve IDs when the theory is still valid. "
            "Return {\"hypotheses\":[{\"hypothesis_id\":\"h001\",\"statement\":\"...\",\"rationale\":\"...\"}]}"
        ),
        {
            "objective": program.objective,
            "hypotheses": [h.__dict__ for h in hypotheses],
            "claims": [claim.__dict__ for claim in claims],
            "contradictions": [contradiction.__dict__ for contradiction in contradictions],
            "criticisms": criticisms[:6],
            "open_questions": open_questions[:6],
        },
    )
    if revised and isinstance(revised.get("hypotheses"), list):
        hypotheses = _hypotheses_from_llm(revised["hypotheses"], hypotheses)
    else:
        hypotheses = _deterministic_refine_hypotheses(hypotheses, contradictions, open_questions)
    agent.trace.output_count = len(hypotheses)
    return hypotheses, agent.trace


def run_critic_agent(claims: list[Claim], reasoner: CentralReasoner, agent_skills: dict[str, list[str]] | None = None) -> tuple[list, list[str], AgentTrace]:
    agent = ResearchAgent(
        "critic_agent",
        "Attack claims, find gaps, and surface contradictions.",
        [Tool("critique_claims", critique_claims)],
        reasoner,
        (agent_skills or {}).get("critic_agent", []),
    )
    contradictions, criticisms = agent.tool("critique_claims", claims)
    critique = agent.reason_json(
        "Add concise legal research criticisms. Return {\"criticisms\":[\"...\"]}.",
        {"claims": [claim.__dict__ for claim in claims], "baseline_criticisms": criticisms},
    )
    if critique and isinstance(critique.get("criticisms"), list):
        criticisms = [*criticisms, *[str(item) for item in critique["criticisms"][:4]]]
    agent.trace.output_count = len(contradictions) + len(criticisms)
    return contradictions, criticisms, agent.trace


def run_knowledge_agent(
    tasks: list[Task],
    hypotheses: list[Hypothesis],
    seed_texts: list[str],
    live_retrieval: bool,
    source_urls: list[str],
    reasoner: CentralReasoner,
    use_modal: bool,
    agent_skills: dict[str, list[str]] | None = None,
) -> tuple[list[Evidence], dict, AgentTrace]:
    agent = ResearchAgent(
        "knowledge_agent_pool",
        "Retrieve real sources and extract structured evidence.",
        [Tool("collect_evidence", collect_evidence)],
        reasoner,
        (agent_skills or {}).get("knowledge_agent_pool", []),
    )
    evidence, retrieval_metrics = agent.tool(
        "collect_evidence",
        tasks,
        hypotheses,
        seed_texts,
        live_retrieval=live_retrieval,
        source_urls=source_urls,
        use_modal=use_modal,
    )
    agent.reason_json(
        "Review retrieved evidence quality. Return {\"notes\":[\"...\"]}.",
        {
            "tasks": [task.__dict__ for task in tasks[:8]],
            "evidence": [item.__dict__ for item in evidence[:8]],
            "retrieval_metrics": retrieval_metrics,
        },
    )
    agent.trace.output_count = len(evidence)
    return evidence, retrieval_metrics, agent.trace


def _hypotheses_from_llm(items: list, fallback: list[Hypothesis]) -> list[Hypothesis]:
    if not items:
        return fallback
    hypotheses: list[Hypothesis] = []
    for index, item in enumerate(items[:6], start=1):
        if not isinstance(item, dict) or not item.get("statement"):
            continue
        hypotheses.append(
            Hypothesis(
                hypothesis_id=str(item.get("hypothesis_id") or f"h{index:03d}"),
                statement=str(item["statement"]),
                rationale=str(item.get("rationale", "LLM-refined hypothesis.")),
            )
        )
    return hypotheses or fallback


def _deterministic_refine_hypotheses(
    hypotheses: list[Hypothesis],
    contradictions: list[Contradiction],
    open_questions: list[str],
) -> list[Hypothesis]:
    if not contradictions and not open_questions:
        return hypotheses
    refined: list[Hypothesis] = []
    for hypothesis in hypotheses:
        statement = hypothesis.statement
        rationale = hypothesis.rationale
        lower = statement.lower()
        if "pure ai" in lower or "solely by an ai" in lower:
            statement = "Pure AI-generated code remains unlikely to be copyrightable, while AI-assisted code must be separately evaluated for human authorship."
            rationale = "Critic feedback scoped the apparent conflict: pure autonomous output and human-controlled AI assistance are distinct legal categories."
        refined.append(
            Hypothesis(
                hypothesis_id=hypothesis.hypothesis_id,
                statement=statement,
                rationale=rationale,
                status=hypothesis.status,
            )
        )
    return refined
