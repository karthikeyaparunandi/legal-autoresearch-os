from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from .models import Contradiction, Evaluation


DEFAULT_AGENT_SKILLS: dict[str, list[str]] = {
    "hypothesis_agent": [
        "Separate pure AI output from AI-assisted human expression.",
        "State legal hypotheses with jurisdiction, authority level, and uncertainty boundaries.",
    ],
    "knowledge_agent_pool": [
        "Prefer statutes, cases, agency guidance, and official materials over secondary commentary.",
        "Treat CAPTCHA, access-denied, navigation-only, and empty pages as blocked retrieval, not evidence.",
    ],
    "critic_agent": [
        "Scope apparent contradictions before marking them unresolved.",
        "Criticize claims for missing primary authority, weak source diversity, or unsupported practical-risk assertions.",
    ],
    "hypothesis_refinement_agent": [
        "Turn repeated open questions into narrower, testable hypotheses.",
        "Preserve valid hypothesis IDs when refining scope rather than replacing the whole theory.",
    ],
    "modal_hypothesis_agent": [
        "Evaluate one hypothesis end-to-end: retrieve evidence, synthesize one claim, critique it, and return concise gaps.",
    ],
}


def skills_path_for(out_dir: Path) -> Path:
    return out_dir.parent / "agent_skills.json"


def load_agent_skills(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {agent: list(skills) for agent, skills in DEFAULT_AGENT_SKILLS.items()}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {agent: list(skills) for agent, skills in DEFAULT_AGENT_SKILLS.items()}
    skills = {agent: list(items) for agent, items in DEFAULT_AGENT_SKILLS.items()}
    for agent, items in loaded.get("skills", {}).items():
        if isinstance(items, list):
            skills.setdefault(agent, [])
            for item in items:
                _add_skill(skills, agent, str(item))
    return skills


def update_agent_skills(
    path: Path,
    skills: dict[str, list[str]],
    evaluation: Evaluation,
    retrieval_metrics: dict[str, Any],
    contradictions: list[Contradiction],
    open_questions: list[str],
) -> dict[str, list[str]]:
    updated = {agent: list(items) for agent, items in skills.items()}
    if retrieval_metrics.get("blocked_sources") or retrieval_metrics.get("failed_urls"):
        _add_skill(
            updated,
            "knowledge_agent_pool",
            "When retrieval is blocked or low-signal, replace the source with an accessible primary authority before evaluating confidence.",
        )
        _add_skill(
            updated,
            "modal_hypothesis_agent",
            "Return blocked retrieval reasons separately from evidence so the orchestrator can avoid false citation grounding.",
        )
    if evaluation.citation_grounding < 0.9:
        _add_skill(
            updated,
            "knowledge_agent_pool",
            "Do not mark a claim citation-grounded unless it has enough supporting sources and at least one primary authority.",
        )
    if evaluation.objective_completion < 0.9 or open_questions:
        _add_skill(
            updated,
            "hypothesis_refinement_agent",
            "Map unresolved open questions back to the exact claim or hypothesis they can repair.",
        )
    if any(item.resolution_status != "resolved" for item in contradictions):
        _add_skill(
            updated,
            "critic_agent",
            "Resolve contradictions by distinguishing legal categories, factual assumptions, and source authority before escalating.",
        )
    if evaluation.overall_confidence >= 0.85 and not open_questions:
        _add_skill(
            updated,
            "critic_agent",
            "When all material claims are supported and no critical questions remain, avoid inventing extra follow-up questions.",
        )

    payload = {"version": 1, "skills": updated}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return updated


def _add_skill(skills: dict[str, list[str]], agent: str, skill: str) -> None:
    skills.setdefault(agent, [])
    if skill not in skills[agent]:
        skills[agent].append(skill)
