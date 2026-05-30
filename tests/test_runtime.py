from __future__ import annotations

import json

from autoresearch_os.cli import main, _format_metrics, _terminal_link
from autoresearch_os.critic import critique_claims
from autoresearch_os.knowledge import collect_evidence
from autoresearch_os.llm import CentralReasoner, LLMConfigurationError, LLMReasoningError
from autoresearch_os.models import Claim, Hypothesis, Task
from autoresearch_os.modal_bridge import ModalIntegrationError
from autoresearch_os.retrieval import _infer_contradictions, fetch_url_text
from autoresearch_os.runtime import ResearchRuntime


def test_runtime_writes_truth_maintenance_repo(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=2, live_retrieval=False, use_llm=False)

    evaluation = runtime.run("Can AI-generated code be copyrighted in the United States?")

    assert evaluation.primary_authority_coverage >= 0.75
    assert evaluation.mean_claim_confidence > 0
    assert evaluation.overall_confidence < 1.0
    program = (tmp_path / "gt_repo" / "program.md").read_text(encoding="utf-8")
    assert "## Legal Metadata" in program
    assert "## Legal Authority Hierarchy" in program
    assert (tmp_path / "gt_repo" / "legal_metadata.json").exists()
    assert (tmp_path / "gt_repo" / "tuning_params.json").exists()
    metrics = json.loads((tmp_path / "gt_repo" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["agents_spun_off"] >= 14
    assert metrics["hypotheses_count"] == 4
    assert metrics["total_runtime_seconds"] >= 0
    assert metrics["component_metrics"]["evidence_collection"]["agents"] > 0
    assert metrics["iteration_history"]
    assert "primary_authority_coverage" in metrics["iteration_history"][-1]
    assert "mean_claim_confidence" in metrics["iteration_history"][-1]
    assert metrics["iteration_history"][-1]["status"] in {"Continue", "Converged"}
    assert metrics["retrieval_metrics"]["enabled"] is False
    assert metrics["llm_reasoning_enabled"] is False
    assert metrics["agent_traces"]
    assert metrics["agent_traces"][0]["tools"]
    assert (tmp_path / "gt_repo" / "claims.json").exists()
    assert (tmp_path / "gt_repo" / "evidence" / "iteration_001.json").exists()
    report = (tmp_path / "gt_repo" / "final_report.md").read_text(encoding="utf-8")
    assert report.startswith("# Grounded Research Report")
    assert "## Run Metrics" in report
    html = (tmp_path / "gt_repo" / "final_report.html").read_text(encoding="utf-8")
    assert "<title>AutoResearch OS Grounded Legal Research Report</title>" in html
    assert "Reasoning and rationale path" in html
    assert "<h2>Convergence Progress</h2>" in html
    assert "<h2>Component Metrics</h2>" in html
    assert "<h2>Agent Tool Loops</h2>" in html
    assert "<h2>Live Retrieval</h2>" in html
    assert 'href="#source_001"' in html
    assert 'id="source_001"' in html
    assert (tmp_path / "gt_repo" / "final_report.pdf").read_bytes().startswith(b"%PDF")


def test_runtime_auto_tunes_params_for_weak_research_state(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=False, use_llm=False)

    runtime.run("Assess a novel unresolved legal question with no provided sources")

    params = json.loads((tmp_path / "gt_repo" / "tuning_params.json").read_text(encoding="utf-8"))
    assert params["min_primary_sources"] > 2


def test_human_selection_counterpoint_scopes_rather_than_contradicts():
    hypotheses = [
        Hypothesis(
            hypothesis_id="h001",
            statement="Pure AI-generated code without meaningful human creative contribution is unlikely to be copyrightable.",
            rationale="Human authorship is required.",
        )
    ]

    contradictions = _infer_contradictions(
        "local://human-control-counterpoint",
        "Some AI-assisted outputs may include protectable human expression when a person controls selection and arrangement.",
        hypotheses,
    )

    assert contradictions == []


def test_critic_resolves_scoped_ai_authorship_contradiction():
    contradictions, criticisms = critique_claims(
        [
            Claim(
                claim_id="c001",
                claim="Code generated solely by an AI, without meaningful human creative contribution, is unlikely to be copyrightable.",
                supporting_sources=["source_001"],
                contradicting_sources=["source_002"],
                confidence=0.72,
                status="supported",
            )
        ]
    )

    assert contradictions[0].resolution_status == "resolved"
    assert not criticisms


def test_demo_fallback_evidence_does_not_create_false_contradiction():
    tasks = [Task(task_id="t001", title="AI copyright", question="Can AI-generated code be copyrighted?")]
    hypotheses = [
        Hypothesis(
            hypothesis_id="h001",
            statement="Code generated solely by an AI, without meaningful human creative contribution, is unlikely to be copyrightable.",
            rationale="Human authorship is required.",
        ),
        Hypothesis(
            hypothesis_id="h002",
            statement="AI-assisted code with human selection and arrangement can be copyrightable.",
            rationale="Human expression can still matter.",
        ),
    ]

    evidence, _stats = collect_evidence(tasks, hypotheses, live_retrieval=False)

    assert not any("h001" in item.contradicts for item in evidence)


def test_runtime_requires_llm_key_when_llm_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_API_KEY", raising=False)
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=False, use_llm=True)

    try:
        runtime.run("Can AI-generated code be copyrighted?")
    except LLMConfigurationError as exc:
        assert "OPENAI_API_KEY or OPEN_API_KEY" in str(exc)
    else:
        raise AssertionError("Expected LLMConfigurationError")


def test_reasoner_accepts_open_api_key_alias(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_API_KEY", "test-key")

    reasoner = CentralReasoner()

    assert reasoner.enabled is True


def test_reasoner_uses_agents_sdk_path(monkeypatch):
    monkeypatch.setattr(
        CentralReasoner,
        "_run_agents_sdk",
        lambda self, agent_name, instruction, payload, timeout_seconds: '{"ok": true}',
    )
    reasoner = CentralReasoner(api_key="test-key", required=True)

    assert reasoner.reason_json("test_agent", "Return ok.", {}) == {"ok": True}


def test_reasoner_wraps_agents_sdk_failures(monkeypatch):
    def fail_sdk(self, agent_name, instruction, payload, timeout_seconds):
        raise RuntimeError("sdk unavailable")

    monkeypatch.setattr(CentralReasoner, "_run_agents_sdk", fail_sdk)
    reasoner = CentralReasoner(api_key="test-key", required=True)

    try:
        reasoner.reason_json("test_agent", "Return ok.", {})
    except LLMReasoningError as exc:
        assert "OpenAI Agents SDK reasoning failed" in str(exc)
    else:
        raise AssertionError("Expected LLMReasoningError")


def test_cli_defaults_to_llm_and_requires_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_API_KEY", raising=False)

    exit_code = main(["demo", "--offline", "--out", str(tmp_path / "gt_repo")])

    assert exit_code == 2
    assert not (tmp_path / "gt_repo" / "metrics.json").exists()


def test_cli_no_llm_uses_deterministic_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPEN_API_KEY", raising=False)

    exit_code = main(["demo", "--offline", "--no-llm", "--out", str(tmp_path / "gt_repo")])

    assert exit_code == 0
    metrics = json.loads((tmp_path / "gt_repo" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["llm_reasoning_enabled"] is False


def test_cli_modal_error_is_clear(tmp_path, monkeypatch):
    import autoresearch_os.knowledge as knowledge

    def fail_modal(*args, **kwargs):
        raise ModalIntegrationError("Modal is unavailable")

    monkeypatch.setattr(knowledge, "retrieve_live_evidence", fail_modal)

    exit_code = main(["demo", "--no-llm", "--modal", "--out", str(tmp_path / "gt_repo")])

    assert exit_code == 3


def test_cli_metrics_formatter_shows_full_summary():
    output = _format_metrics(
        {
            "generated_at": "2026-05-30T00:00:00+00:00",
            "total_runtime_seconds": 1.23,
            "iterations_completed": 2,
            "agents_spun_off": 24,
            "tasks_count": 5,
            "hypotheses_count": 4,
            "evidence_count": 8,
            "source_type_count": 3,
            "claims_count": 4,
            "supported_claims_count": 3,
            "contradictions_count": 1,
            "resolved_contradictions_count": 1,
            "open_questions_count": 0,
            "final_confidence": 0.87,
            "stop_conditions_met": True,
            "llm_reasoning_enabled": False,
            "llm_model": None,
            "agent_traces": [
                {
                    "name": "hypothesis_agent",
                    "goal": "Generate hypotheses",
                    "tools": ["generate_baseline_hypotheses"],
                    "steps": ["tool:generate_baseline_hypotheses", "deterministic_fallback"],
                    "used_llm": False,
                    "llm_model": None,
                    "output_count": 4,
                }
            ],
            "retrieval_metrics": {
                "enabled": True,
                "modal_enabled": True,
                "attempted_urls": 3,
                "successful_urls": 2,
                "failed_urls": 1,
                "fallback_used": False,
                "retrieved_urls": ["https://example.test"],
                "errors": {},
            },
            "iteration_history": [
                {
                    "iteration": 1,
                    "overall_confidence": 0.54,
                    "objective_completion": 0.5,
                    "citation_grounding": 0.9,
                    "open_questions": 3,
                    "status": "Continue",
                },
                {
                    "iteration": 2,
                    "overall_confidence": 0.87,
                    "objective_completion": 0.9,
                    "citation_grounding": 1.0,
                    "open_questions": 0,
                    "status": "Converged",
                },
            ],
            "agent_breakdown": {"legal_agent": 2, "critic_agent": 2},
        }
    )

    assert "Final Metrics" in output
    assert "Agent Breakdown" in output
    assert "Agent Tool Loops" in output
    assert "Convergence Progress" in output
    assert "Live Retrieval" in output
    assert "Agents spun off" in output
    assert "24" in output
    assert "Hypotheses" in output
    assert "1.230s" in output
    assert "legal_agent" in output


def test_terminal_link_points_to_file(tmp_path):
    path = tmp_path / "final_report.html"
    link = _terminal_link(path, str(path))

    assert path.as_uri() in link
    assert "final_report.html" in link


def test_fetch_url_text_extracts_local_html(tmp_path):
    html = tmp_path / "source.html"
    html.write_text(
        "<html><head><title>Legal Source</title><style>bad</style></head>"
        "<body><h1>Copyright authorship</h1><p>Human authorship matters.</p></body></html>",
        encoding="utf-8",
    )

    title, text = fetch_url_text(html.as_uri())

    assert title == "Legal Source"
    assert "Human authorship matters." in text
    assert "bad" not in text
