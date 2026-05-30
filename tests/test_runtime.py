from __future__ import annotations

import json

from autoresearch_os.cli import main, _format_metrics, _terminal_link
from autoresearch_os.critic import critique_claims
from autoresearch_os.evaluator import evaluate
from autoresearch_os.knowledge import collect_evidence
from autoresearch_os.llm import CentralReasoner, LLMConfigurationError, LLMReasoningError
from autoresearch_os.models import Claim, Evidence, Hypothesis, ResearchProgram, Task
from autoresearch_os.modal_bridge import ModalIntegrationError
from autoresearch_os.retrieval import _extract_search_result_urls, _infer_contradictions, detect_blocked_source, fetch_url_text, retrieve_live_evidence
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
    assert report.startswith("# Legal Research Report")
    assert "## Question Presented" in report
    assert "Can AI-generated code be copyrighted in the United States?" in report
    assert "## Appendix: Research Trace" in report
    html = (tmp_path / "gt_repo" / "final_report.html").read_text(encoding="utf-8")
    assert "<title>AutoResearch OS Legal Research Report</title>" in html
    assert "Question Presented" in html
    assert "Short Answer" in html
    assert "Reasoning and rationale path" in html
    assert "<h3>Convergence Progress</h3>" in html
    assert "<h3>Component Metrics</h3>" in html
    assert "<h3>Agent Tool Loops</h3>" in html
    assert "<h3>Live Retrieval</h3>" in html
    assert 'href="#source_001"' in html
    assert 'id="source_001"' in html
    assert (tmp_path / "gt_repo" / "final_report.pdf").read_bytes().startswith(b"%PDF")


def test_runtime_auto_tunes_params_for_weak_research_state(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=False, use_llm=False)

    runtime.run("Assess a novel unresolved legal question with no provided sources")

    params = json.loads((tmp_path / "gt_repo" / "tuning_params.json").read_text(encoding="utf-8"))
    assert params["min_primary_sources"] > 2


def test_runtime_persists_and_reuses_agent_skills(tmp_path):
    runtime = ResearchRuntime(tmp_path / "gt_repo_1", max_iterations=1, live_retrieval=False, use_llm=False)
    runtime.run("Assess a novel unresolved legal question with no provided sources")

    shared_skills = tmp_path / "agent_skills.json"
    run_skills = tmp_path / "gt_repo_1" / "agent_skills.json"
    assert shared_skills.exists()
    assert run_skills.exists()
    skills = json.loads(shared_skills.read_text(encoding="utf-8"))["skills"]
    assert "hypothesis_refinement_agent" in skills
    assert any("open questions" in item for item in skills["hypothesis_refinement_agent"])

    runtime = ResearchRuntime(tmp_path / "gt_repo_2", max_iterations=1, live_retrieval=False, use_llm=False)
    runtime.run("Can AI-generated code be copyrighted in the United States?")
    second_run_skills = json.loads((tmp_path / "gt_repo_2" / "agent_skills.json").read_text(encoding="utf-8"))["skills"]
    assert any("open questions" in item for item in second_run_skills["hypothesis_refinement_agent"])


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


def test_inner_feedback_loop_refines_hypotheses(tmp_path, monkeypatch):
    import autoresearch_os.runtime as runtime_module

    calls = {"knowledge": 0, "refine": 0}

    def fake_knowledge(tasks, hypotheses, seed_texts, live_retrieval, source_urls, reasoner, use_modal, agent_skills=None):
        calls["knowledge"] += 1
        from autoresearch_os.models import Evidence

        return (
            [
                Evidence(
                    source_id="source_001",
                    title="Primary source",
                    url="https://example.test/primary",
                    source_type="agency_guidance",
                    excerpt="Human authorship is required.",
                    supports=["h001"],
                    reliability=0.95,
                )
            ],
            {
                "enabled": False,
                "attempted_urls": 0,
                "successful_urls": 0,
                "failed_urls": 0,
                "retrieved_urls": [],
                "errors": {},
                "fallback_used": True,
                "modal_enabled": False,
            },
            runtime_module.AgentTrace("knowledge_agent_pool", "fake", ["collect_evidence"]),
        )

    def fake_critic(claims, reasoner, agent_skills=None):
        from autoresearch_os.models import Contradiction

        return (
            [Contradiction(claim=claims[0].claim, supporting_sources=["source_001"], contradicting_sources=["source_002"])],
            ["Needs scoped hypothesis."],
            runtime_module.AgentTrace("critic_agent", "fake", ["critique_claims"]),
        )

    def fake_refine(program, hypotheses, claims, contradictions, criticisms, open_questions, reasoner, agent_skills=None):
        calls["refine"] += 1
        return hypotheses, runtime_module.AgentTrace("hypothesis_refinement_agent", "fake", [])

    monkeypatch.setattr(runtime_module, "run_knowledge_agent", fake_knowledge)
    monkeypatch.setattr(runtime_module, "run_critic_agent", fake_critic)
    monkeypatch.setattr(runtime_module, "run_hypothesis_refinement_agent", fake_refine)

    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=False, use_llm=False, feedback_rounds=2)
    runtime.run("Can AI-generated code be copyrighted in the United States?")

    assert calls == {"knowledge": 2, "refine": 1}


def test_modal_fans_out_url_retrieval_inside_runtime(tmp_path, monkeypatch):
    import autoresearch_os.runtime as runtime_module

    calls = {"knowledge": 0, "use_modal": None}

    def fake_knowledge(tasks, hypotheses, seed_texts, live_retrieval, source_urls, reasoner, use_modal, agent_skills=None):
        calls["knowledge"] += 1
        calls["use_modal"] = use_modal
        from autoresearch_os.models import Evidence

        evidence = [
            Evidence(
                source_id=f"source_{index:03d}",
                title=f"Evidence {index}",
                url=f"https://example.test/{index}",
                source_type="agency_guidance",
                excerpt="Human authorship is required.",
                supports=[hypothesis.hypothesis_id],
                reliability=0.95,
            )
            for index, hypothesis in enumerate(hypotheses, start=1)
        ]
        return (
            evidence,
            {
                "enabled": True,
                "modal_enabled": True,
                "modal_url_fetch_agents": len(hypotheses),
                "attempted_urls": len(hypotheses),
                "successful_urls": len(hypotheses),
                "failed_urls": 0,
                "retrieved_urls": [],
                "errors": {},
                "fallback_used": False,
            },
            runtime_module.AgentTrace("knowledge_agent_pool", "fake", ["collect_evidence"]),
        )

    monkeypatch.setattr(runtime_module, "run_knowledge_agent", fake_knowledge)
    runtime = ResearchRuntime(tmp_path / "gt_repo", max_iterations=1, live_retrieval=True, use_llm=False, use_modal=True)
    runtime.run("Can AI-generated code be copyrighted in the United States?")

    metrics = json.loads((tmp_path / "gt_repo" / "metrics.json").read_text(encoding="utf-8"))
    assert calls == {"knowledge": 1, "use_modal": True}
    assert metrics["retrieval_metrics"]["modal_enabled"] is True
    assert metrics["retrieval_metrics"]["modal_url_fetch_agents"] == 4
    assert metrics["agent_breakdown"]["modal_url_fetch_agent"] == 4
    trace = next(trace for trace in metrics["agent_traces"] if trace["name"] == "knowledge_agent_pool")
    assert trace["tools"] == ["collect_evidence"]


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
    import autoresearch_os.runtime as runtime_module

    def fail_modal(*args, **kwargs):
        raise ModalIntegrationError("Modal is unavailable")

    monkeypatch.setattr(runtime_module, "run_knowledge_agent", fail_modal)

    exit_code = main(["demo", "--no-llm", "--modal", "--out", str(tmp_path / "gt_repo")])

    assert exit_code == 3


def test_cli_raindrop_error_is_clear(tmp_path, monkeypatch):
    import autoresearch_os.raindrop_tracing as tracing

    def fail_raindrop(self):
        raise tracing.RaindropConfigurationError("Raindrop is unavailable")

    monkeypatch.setattr(tracing.RaindropTracer, "_init_sdk", fail_raindrop)

    exit_code = main(["demo", "--offline", "--no-llm", "--raindrop", "--out", str(tmp_path / "gt_repo")])

    assert exit_code == 4


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
            "raindrop_tracing_enabled": False,
            "raindrop_target": None,
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
    assert "Raindrop tracing" in output
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


def test_search_result_urls_extract_duckduckgo_redirects():
    html = (
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.americanbar.org%2Fgroups%2Fdelivery_legal_services%2F">'
        "ABA</a>"
        '<a href="https://duckduckgo.com/y.js">tracking</a>'
        '<a href="https://www.law.cornell.edu/uscode/text/17/102">Cornell</a>'
    )

    urls = _extract_search_result_urls(html)

    assert urls == [
        "https://www.americanbar.org/groups/delivery_legal_services/",
        "https://www.law.cornell.edu/uscode/text/17/102",
    ]


def test_retrieval_discovers_query_specific_sources(tmp_path, monkeypatch):
    import autoresearch_os.retrieval as retrieval_module

    monkeypatch.setattr(retrieval_module, "DEFAULT_LEGAL_SOURCE_URLS", [])
    state_bar = tmp_path / "state_bar.html"
    state_bar.write_text(
        "<html><head><title>State Bar UPL Opinion</title></head><body>"
        "<p>Unauthorized practice of law risk can arise when a legal document service applies contract law to a customer specific situation.</p>"
        "<p>Disclaimers and attorney supervision may affect liability.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    consumer = tmp_path / "consumer.html"
    consumer.write_text(
        "<html><head><title>Consumer Protection Source</title></head><body>"
        "<p>Contract template providers can face warranty, misrepresentation, and consumer protection liability.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        retrieval_module,
        "_search_web",
        lambda query, timeout_seconds=8.0: [state_bar.as_uri(), consumer.as_uri()],
    )
    tasks = [
        Task(
            task_id="t001",
            title="AI contract templates",
            question="Can a startup use AI-generated contract templates for customers, and what liability risks arise under U.S. law?",
        )
    ]
    hypotheses = [
        Hypothesis(
            hypothesis_id="h001",
            statement="AI-generated contract templates create unauthorized practice of law and liability risks.",
            rationale="Templates can apply law to customer facts.",
        )
    ]

    evidence, stats = retrieve_live_evidence(tasks, hypotheses)

    assert stats.search_enabled is True
    assert stats.search_queries
    assert stats.discovered_urls == [state_bar.as_uri(), consumer.as_uri()]
    assert stats.successful_urls == 2
    assert {item.url for item in evidence} == {state_bar.as_uri(), consumer.as_uri()}
    assert all("h001" in item.supports for item in evidence)
    assert all(item.reliability > 0.45 for item in evidence)
    assert set(stats.source_scores or {}) == {state_bar.as_uri(), consumer.as_uri()}


def test_retrieval_marks_captcha_pages_as_blocked(tmp_path, monkeypatch):
    import autoresearch_os.retrieval as retrieval_module

    monkeypatch.setattr(retrieval_module, "DEFAULT_LEGAL_SOURCE_URLS", [])
    blocked = tmp_path / "blocked.html"
    blocked.write_text(
        "<html><head><title>Blocked</title></head><body>"
        "<h1>Security check</h1><p>Please complete the CAPTCHA to verify you are human.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    tasks = [Task(task_id="t001", title="Blocked source", question="Can AI-generated code be copyrighted?")]
    hypotheses = [Hypothesis(hypothesis_id="h001", statement="Pure AI-generated code is risky.", rationale="Authorship")]

    evidence, stats = retrieve_live_evidence(tasks, hypotheses, source_urls=[blocked.as_uri()])

    assert evidence == []
    assert stats.successful_urls == 0
    assert stats.failed_urls == 1
    assert stats.as_dict()["blocked_sources"] == 1
    assert stats.block_reasons == {blocked.as_uri(): "captcha_detected"}


def test_blocked_source_metrics_lower_confidence():
    program = ResearchProgram(
        objective="Can AI-generated code be copyrighted?",
        subquestions=[
            "What legal standard controls authorship?",
            "Which primary sources apply?",
        ],
        evidence_requirements=[],
        success_metrics=[],
    )
    evidence = [
        Evidence(
            source_id="source_001",
            title="Copyright statute",
            url="https://www.law.cornell.edu/uscode/text/17/102",
            source_type="statute",
            excerpt="Original works of authorship are protected.",
            supports=["h001"],
            reliability=0.92,
        ),
        Evidence(
            source_id="source_002",
            title="Copyright Office guidance",
            url="https://www.copyright.gov/ai/",
            source_type="agency_guidance",
            excerpt="Human authorship matters.",
            supports=["h001"],
            reliability=0.95,
        ),
    ]
    claims = [
        Claim(
            claim_id="c001",
            claim="Pure AI-generated code faces copyright authorship risk.",
            supporting_sources=["source_001", "source_002"],
            confidence=0.9,
            status="supported",
        )
    ]

    clean = evaluate(1, program, claims, evidence, [], [], retrieval_metrics={"blocked_sources": 0})
    blocked = evaluate(1, program, claims, evidence, [], [], retrieval_metrics={"blocked_sources": 2})

    assert blocked.blocked_source_penalty == 0.1
    assert blocked.confidence_cap <= 0.8
    assert blocked.overall_confidence < clean.overall_confidence


def test_detect_blocked_source_variants():
    assert detect_blocked_source("Please verify you are human before continuing.") == "captcha_detected"
    assert detect_blocked_source("Access denied. You have been blocked.") == "access_denied"
    assert detect_blocked_source("Sign in to continue reading this source.") == "login_required"
