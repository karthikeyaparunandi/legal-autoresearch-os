"""LegalBench task registry for the AutoResearch OS experiment.

Each task knows: its HF config name, its allowed label set, which row fields hold
the input, how to phrase the research `goal` (what we ask the agent), and how to
build the `seed_text` (the raw legal text we feed the agent as evidence).

This is a thin adapter layer only — it does NOT modify the agent. See
run_benchmark.py for how the agent is driven and how its report is scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + " ..."


@dataclass
class LegalBenchTask:
    config: str
    labels: list[str]
    text_field: str
    description: str
    # build the research goal shown to the agent (drives hypotheses/critic)
    build_goal: Callable[[dict], str]
    question_field: str | None = None
    # how to phrase the constrained answer for the adapter / scoring
    answer_noun: str = "label"
    aliases: dict[str, str] = field(default_factory=dict)  # lowercased synonym -> canonical label

    def seed_text(self, row: dict) -> str:
        return " ".join((row.get(self.text_field) or "").split())

    def label_instruction(self) -> str:
        return " / ".join(self.labels)


def _abercrombie_goal(row: dict) -> str:
    mark = _clip(row.get("text", ""), 400)
    return (
        "Under U.S. trademark law, classify the distinctiveness of the following mark "
        "into exactly one Abercrombie category: generic, descriptive, suggestive, "
        "arbitrary, or fanciful. Explain which category applies and why.\n\n"
        f"Mark: {mark}"
    )


def _cuad_anti_assignment_goal(row: dict) -> str:
    clause = _clip(row.get("text", ""), 1500)
    return (
        "Analyze the following contract clause. Does it contain an anti-assignment "
        "provision — i.e., a restriction requiring consent for (or prohibiting) the "
        "assignment or transfer of the agreement or rights/obligations under it? "
        "Decide Yes or No and explain.\n\n"
        f"Clause: {clause}"
    )


def _privacy_policy_qa_goal(row: dict) -> str:
    question = _clip(row.get("question", ""), 300)
    clause = _clip(row.get("text", ""), 1500)
    return (
        "A user asked a question about a privacy policy. Determine whether the policy "
        "excerpt below is RELEVANT to answering that question (i.e., it addresses the "
        "subject of the question), or IRRELEVANT. Decide Relevant or Irrelevant and "
        "explain.\n\n"
        f"User question: {question}\n\n"
        f"Privacy policy excerpt: {clause}"
    )


def _hearsay_goal(row: dict) -> str:
    evidence = _clip(row.get("text", ""), 600)
    return (
        "Determine whether the following piece of evidence would be considered HEARSAY "
        "under the U.S. Federal Rules of Evidence — i.e., an out-of-court statement "
        "offered to prove the truth of the matter asserted. Note common non-hearsay "
        "situations (non-assertive conduct, statements offered for a non-truth purpose, "
        "effect on the listener, etc.). Decide Yes (it is hearsay) or No (not hearsay) "
        "and explain.\n\n"
        f"Evidence: {evidence}"
    )


def _learned_hands_consumer_goal(row: dict) -> str:
    post = _clip(row.get("text", ""), 1800)
    return (
        "The following is a post from a member of the public seeking legal help. "
        "Determine whether the post raises an issue of CONSUMER law — for example "
        "debts, collections, credit, purchases, warranties, contracts with businesses, "
        "fraud, or consumer protection. Decide Yes or No and explain.\n\n"
        f"Post: {post}"
    )


TASKS: dict[str, LegalBenchTask] = {
    "abercrombie": LegalBenchTask(
        config="abercrombie",
        labels=["generic", "descriptive", "suggestive", "arbitrary", "fanciful"],
        text_field="text",
        description="Trademark distinctiveness (5-way Abercrombie spectrum).",
        build_goal=_abercrombie_goal,
        answer_noun="Abercrombie category",
    ),
    "cuad_anti-assignment": LegalBenchTask(
        config="cuad_anti-assignment",
        labels=["Yes", "No"],
        text_field="text",
        description="Does a contract clause contain an anti-assignment provision? (Yes/No)",
        build_goal=_cuad_anti_assignment_goal,
        answer_noun="Yes/No answer",
    ),
    "privacy_policy_qa": LegalBenchTask(
        config="privacy_policy_qa",
        labels=["Relevant", "Irrelevant"],
        text_field="text",
        question_field="question",
        description="Is a privacy-policy excerpt relevant to a user question? (Relevant/Irrelevant)",
        build_goal=_privacy_policy_qa_goal,
        answer_noun="Relevant/Irrelevant answer",
    ),
    "hearsay": LegalBenchTask(
        config="hearsay",
        labels=["Yes", "No"],
        text_field="text",
        description="Is the described evidence hearsay under the FRE? (Yes/No)",
        build_goal=_hearsay_goal,
        answer_noun="Yes/No hearsay answer",
    ),
    "learned_hands_consumer": LegalBenchTask(
        config="learned_hands_consumer",
        labels=["Yes", "No"],
        text_field="text",
        description="Does a legal-help post raise a consumer-law issue? (Yes/No)",
        build_goal=_learned_hands_consumer_goal,
        answer_noun="Yes/No answer",
    ),
}
