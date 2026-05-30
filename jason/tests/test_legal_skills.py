from __future__ import annotations

from jason.harness import run_offline
from jason.legal_skills import is_legal_goal, legal_skill_names, match_legal_skills
from jason.memory import TruthRepo
from jason.program import build_program_seed


AI_COPYRIGHT_GOAL = (
    "Can AI-generated code be copyrighted in the United States, "
    "and what legal risks would a startup face?"
)


def test_legal_skill_catalog_classifies_practice_area_triggers():
    skill_names = legal_skill_names("Review this NDA and DPA for a SaaS vendor agreement.")

    assert is_legal_goal("Review this NDA and DPA for a SaaS vendor agreement.")
    assert "commercial_legal" in skill_names
    assert "privacy_legal" in skill_names
    assert [skill.name for skill in match_legal_skills("Prepare deposition questions for litigation.")] == [
        "litigation_legal"
    ]


def test_legal_program_seed_uses_jurisdiction_authority_and_human_review():
    seed = build_program_seed(AI_COPYRIGHT_GOAL)
    subquestions = "\n".join(seed.subquestions).lower()
    claims = "\n".join(claim.claim for claim in seed.claims).lower()

    assert "jurisdiction" in subquestions
    assert "primary legal authorit" in subquestions
    assert "human authorship" in claims
    assert "startup" in claims
    assert any("specialist review" in contradiction.note for contradiction in seed.contradictions)


def test_legal_offline_run_uses_primary_authorities_and_legal_report_sections(tmp_path):
    repo_dir = tmp_path / "truth_repo"
    run_offline(AI_COPYRIGHT_GOAL, repo_dir, max_iterations=2)

    state = TruthRepo(repo_dir).load_state(include_events=False)
    evidence = list(state["evidence"].values())
    report = (repo_dir / "final_report.md").read_text(encoding="utf-8")

    assert any("Copyright Office" in item["title"] for item in evidence)
    assert any(item["source_type"] == "case_law" for item in evidence)
    assert any(item["source_type"] == "statute" for item in evidence)
    assert "## Legal Analysis Framework" in report
    assert "## Risk And Human Review" in report
    assert "not legal advice" in report
