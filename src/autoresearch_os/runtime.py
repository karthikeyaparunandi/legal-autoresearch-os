from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time

from .agents import AgentTrace, run_critic_agent, run_hypothesis_agent, run_hypothesis_refinement_agent, run_knowledge_agent
from .evaluator import evaluate, stop_conditions_met
from .gaps import detect_gaps
from .html import write_research_html
from .knowledge import claims_from_hypotheses
from .llm import CentralReasoner
from .models import Evaluation, RunMetrics, write_json
from .pdf import write_pdf
from .planner import plan_tasks
from .program import generate_program, program_to_markdown
from .raindrop_feedback import build_raindrop_feedback
from .raindrop_tracing import RaindropTracer
from .report import build_report
from .skills import load_agent_skills, skills_path_for, update_agent_skills
from .tuning import load_tuning_params, tune_params


BASE_AGENT_BREAKDOWN = {
    "program_generator": 1,
    "planner_orchestrator": 1,
    "hypothesis_agent": 1,
    "hypothesis_refinement_agent": 0,
    "web_search_agent": 1,
    "academic_agent": 1,
    "legal_agent": 1,
    "company_intelligence_agent": 1,
    "social_signal_agent": 1,
    "extraction_agent": 1,
    "critic_agent": 1,
    "evaluator_agent": 1,
    "knowledge_gap_detector": 1,
    "auto_tuner": 1,
    "raindrop_feedback_agent": 1,
    "report_generator": 1,
}


class ResearchRuntime:
    def __init__(
        self,
        out_dir: Path,
        max_iterations: int = 4,
        live_retrieval: bool = True,
        source_urls: list[str] | None = None,
        use_llm: bool = True,
        use_modal: bool = False,
        feedback_rounds: int = 2,
        use_raindrop: bool = False,
    ) -> None:
        self.out_dir = out_dir
        self.max_iterations = max_iterations
        self.live_retrieval = live_retrieval
        self.source_urls = source_urls or []
        self.use_llm = use_llm
        self.use_modal = use_modal
        self.feedback_rounds = max(1, feedback_rounds)
        self.use_raindrop = use_raindrop

    def run(self, goal: str, seed_texts: list[str] | None = None) -> Evaluation:
        started_at = time.perf_counter()
        component_seconds: dict[str, float] = {
            "program_generation": 0.0,
            "planning": 0.0,
            "hypothesis_generation": 0.0,
            "evidence_collection": 0.0,
            "claim_synthesis": 0.0,
            "critique": 0.0,
            "gap_detection": 0.0,
            "evaluation": 0.0,
            "auto_tuning": 0.0,
            "raindrop_feedback": 0.0,
            "report_generation": 0.0,
        }
        seed_texts = seed_texts or []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "evidence").mkdir(exist_ok=True)
        (self.out_dir / "evals").mkdir(exist_ok=True)
        tracer = RaindropTracer(enabled=self.use_raindrop, workspace=self.out_dir.parent)
        tracer.begin_run(
            goal,
            {
                "max_iterations": self.max_iterations,
                "live_retrieval": self.live_retrieval,
                "modal": self.use_modal,
                "llm": self.use_llm,
                "feedback_rounds": self.feedback_rounds,
            },
        )

        tuning_params = load_tuning_params(self.out_dir)
        skills_path = skills_path_for(self.out_dir)
        agent_skills = load_agent_skills(skills_path)
        reasoner = CentralReasoner(workspace=self.out_dir.parent, required=True) if self.use_llm else CentralReasoner(api_key="")
        agent_traces: list[AgentTrace] = []
        timer = time.perf_counter()
        with tracer.span("program_generator", {"goal": goal}) as span:
            program = generate_program(goal)
            span.record_output({"subquestions": len(program.subquestions), "domain": program.legal_metadata.domain})
        component_seconds["program_generation"] += time.perf_counter() - timer
        timer = time.perf_counter()
        with tracer.span("planner_orchestrator", {"subquestions": program.subquestions}) as span:
            tasks = plan_tasks(program)
            span.record_output({"tasks": len(tasks)})
        component_seconds["planning"] += time.perf_counter() - timer
        timer = time.perf_counter()
        with tracer.span("hypothesis_agent", {"objective": program.objective}) as span:
            hypotheses, trace = run_hypothesis_agent(program, reasoner, agent_skills)
            span.record_output({"hypotheses": len(hypotheses), "used_llm": trace.used_llm})
        agent_traces.append(trace)
        component_seconds["hypothesis_generation"] += time.perf_counter() - timer
        evidence = []
        claims = []
        contradictions = []
        open_questions = ["Initial research state has not been evaluated."]
        criticisms = []
        evaluation: Evaluation | None = None
        previous_evaluation: Evaluation | None = None
        iterations_completed = 0
        iteration_history: list[dict[str, float | int | str | bool]] = []
        retrieval_metrics = {
            "enabled": self.live_retrieval,
            "attempted_urls": 0,
            "successful_urls": 0,
            "failed_urls": 0,
            "blocked_sources": 0,
            "blocked_urls": [],
            "block_reasons": {},
            "retrieved_urls": [],
            "errors": {},
            "fallback_used": False,
        }

        self._write_program_state(program, tasks, hypotheses)

        for iteration in range(1, self.max_iterations + 1):
            iterations_completed = iteration
            for feedback_round in range(1, self.feedback_rounds + 1):
                timer = time.perf_counter()
                with tracer.span(
                    "knowledge_agent_pool",
                    {
                        "iteration": iteration,
                        "feedback_round": feedback_round,
                        "task_count": len(tasks),
                        "hypotheses": len(hypotheses),
                    },
                ) as span:
                    evidence, retrieval_metrics, trace = run_knowledge_agent(
                        tasks,
                        hypotheses,
                        seed_texts,
                        self.live_retrieval,
                        self.source_urls,
                        reasoner,
                        self.use_modal,
                        agent_skills,
                    )
                    span.record_output(
                        {
                            "evidence": len(evidence),
                            "urls_attempted": retrieval_metrics.get("attempted_urls", 0),
                            "urls_retrieved": retrieval_metrics.get("successful_urls", 0),
                            "blocked_sources": retrieval_metrics.get("blocked_sources", 0),
                            "fallback_used": retrieval_metrics.get("fallback_used", False),
                        }
                    )
                agent_traces.append(trace)
                component_seconds["evidence_collection"] += time.perf_counter() - timer
                timer = time.perf_counter()
                with tracer.span("claim_synthesis", {"hypotheses": len(hypotheses), "evidence": len(evidence)}) as span:
                    claims = claims_from_hypotheses(hypotheses, evidence, tuning_params)
                    span.record_output({"claims": len(claims), "supported": sum(1 for claim in claims if claim.status == "supported")})
                component_seconds["claim_synthesis"] += time.perf_counter() - timer
                timer = time.perf_counter()
                with tracer.span("critic_agent", {"claims": len(claims)}) as span:
                    contradictions, criticisms, trace = run_critic_agent(claims, reasoner, agent_skills)
                    span.record_output({"contradictions": len(contradictions), "criticisms": len(criticisms), "used_llm": trace.used_llm})
                agent_traces.append(trace)
                component_seconds["critique"] += time.perf_counter() - timer
                timer = time.perf_counter()
                with tracer.span("knowledge_gap_detector", {"claims": len(claims), "contradictions": len(contradictions)}) as span:
                    open_questions = detect_gaps(program, claims, contradictions, criticisms, tuning_params)
                    span.record_output({"open_questions": len(open_questions)})
                component_seconds["gap_detection"] += time.perf_counter() - timer
                if feedback_round >= self.feedback_rounds or not contradictions:
                    break
                timer = time.perf_counter()
                with tracer.span("hypothesis_refinement_agent", {"open_questions": len(open_questions), "contradictions": len(contradictions)}) as span:
                    hypotheses, trace = run_hypothesis_refinement_agent(
                        program,
                        hypotheses,
                        claims,
                        contradictions,
                        criticisms,
                        open_questions,
                        reasoner,
                        agent_skills,
                    )
                    span.record_output({"hypotheses": len(hypotheses), "used_llm": trace.used_llm})
                agent_traces.append(trace)
                component_seconds["hypothesis_generation"] += time.perf_counter() - timer
            timer = time.perf_counter()
            with tracer.span("evaluator_agent", {"iteration": iteration, "claims": len(claims), "evidence": len(evidence)}) as span:
                evaluation = evaluate(
                    iteration,
                    program,
                    claims,
                    evidence,
                    contradictions,
                    open_questions,
                    tuning_params,
                    previous_evaluation,
                    retrieval_metrics,
                    reasoner,
                )
                span.record_output(
                    {
                        "overall_confidence": evaluation.overall_confidence,
                        "deterministic_confidence": evaluation.deterministic_confidence,
                        "llm_score_adjustment": evaluation.llm_score_adjustment,
                        "citation_grounding": evaluation.citation_grounding,
                        "primary_authority_coverage": evaluation.primary_authority_coverage,
                        "blocked_source_penalty": evaluation.blocked_source_penalty,
                        "confidence_cap": evaluation.confidence_cap,
                    }
                )
            component_seconds["evaluation"] += time.perf_counter() - timer
            timer = time.perf_counter()
            with tracer.span("auto_tuner", {"overall_confidence": evaluation.overall_confidence}) as span:
                did_stop = stop_conditions_met(program, evaluation)
                next_tuning_params = tuning_params if did_stop else tune_params(tuning_params, evaluation)
                span.record_output({"stop_conditions_met": did_stop, "gap_task_limit": next_tuning_params.gap_task_limit})
            iteration_history.append(_iteration_snapshot(iteration, evaluation, evidence, contradictions, open_questions, did_stop))
            component_seconds["auto_tuning"] += time.perf_counter() - timer

            self._write_iteration_state(
                iteration,
                evidence,
                claims,
                contradictions,
                criticisms,
                open_questions,
                evaluation,
                tuning_params,
                next_tuning_params,
            )
            if did_stop:
                break
            if _research_plateaued(iteration_history):
                iteration_history[-1]["status"] = "Plateau"
                break

            previous_evaluation = evaluation
            tuning_params = next_tuning_params
            timer = time.perf_counter()
            tasks = self._append_gap_tasks(tasks, open_questions)
            component_seconds["planning"] += time.perf_counter() - timer

        if evaluation is None:
            raise RuntimeError("Research loop did not produce an evaluation.")

        agent_skills = update_agent_skills(skills_path, agent_skills, evaluation, retrieval_metrics, contradictions, open_questions)
        write_json(self.out_dir / "agent_skills.json", {"skills": agent_skills})

        elapsed = time.perf_counter() - started_at
        final_artifacts = [
            "program.md",
            "legal_metadata.json",
            "tuning_params.json",
            "tasks.json",
            "hypotheses.json",
            "claims.json",
            "evidence/",
            "contradictions.json",
            "confidence_scores.json",
            "open_questions.json",
            "metrics.json",
            "agent_skills.json",
            "raindrop_feedback.json",
            "final_report.md",
            "final_report.html",
            "final_report.pdf",
        ]
        metrics = self._build_metrics(
            elapsed,
            iterations_completed,
            tasks,
            hypotheses,
            evidence,
            claims,
            contradictions,
            open_questions,
            evaluation,
            stop_conditions_met(program, evaluation),
            final_artifacts,
            component_seconds,
            iteration_history,
            retrieval_metrics,
            agent_traces,
            reasoner.enabled,
            reasoner.model,
            tracer.enabled,
            tracer.model_name if tracer.enabled else None,
        )
        timer = time.perf_counter()
        with tracer.span(
            "raindrop_feedback_agent",
            {
                "overall_confidence": metrics.final_confidence,
                "open_questions": metrics.open_questions_count,
                "stop_conditions_met": metrics.stop_conditions_met,
            },
        ) as span:
            raindrop_feedback = build_raindrop_feedback(metrics)
            write_json(self.out_dir / "raindrop_feedback.json", raindrop_feedback)
            span.record_output(
                {
                    "verdict": raindrop_feedback["verdict"],
                    "recommendations": len(raindrop_feedback["recommendations"]),
                    "trace_focus": raindrop_feedback["trace_focus"],
                }
            )
        component_seconds["raindrop_feedback"] += time.perf_counter() - timer

        elapsed = time.perf_counter() - started_at
        metrics = self._build_metrics(
            elapsed,
            iterations_completed,
            tasks,
            hypotheses,
            evidence,
            claims,
            contradictions,
            open_questions,
            evaluation,
            stop_conditions_met(program, evaluation),
            final_artifacts,
            component_seconds,
            iteration_history,
            retrieval_metrics,
            agent_traces,
            reasoner.enabled,
            reasoner.model,
            tracer.enabled,
            tracer.model_name if tracer.enabled else None,
            raindrop_feedback,
        )
        timer = time.perf_counter()
        with tracer.span("report_generator", {"artifacts": final_artifacts}) as span:
            self._write_final_outputs(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
            span.record_output({"markdown": "final_report.md", "html": "final_report.html", "pdf": "final_report.pdf"})
        component_seconds["report_generation"] += time.perf_counter() - timer

        elapsed = time.perf_counter() - started_at
        metrics = self._build_metrics(
            elapsed,
            iterations_completed,
            tasks,
            hypotheses,
            evidence,
            claims,
            contradictions,
            open_questions,
            evaluation,
            stop_conditions_met(program, evaluation),
            final_artifacts,
            component_seconds,
            iteration_history,
            retrieval_metrics,
            agent_traces,
            reasoner.enabled,
            reasoner.model,
            tracer.enabled,
            tracer.model_name if tracer.enabled else None,
            raindrop_feedback,
        )
        write_json(self.out_dir / "metrics.json", metrics)
        self._write_final_outputs(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
        tracer.finish_run(
            f"Research complete with {evaluation.overall_confidence:.0%} confidence.",
            {
                "overall_confidence": evaluation.overall_confidence,
                "iterations_completed": iterations_completed,
                "stop_conditions_met": stop_conditions_met(program, evaluation),
                "blocked_sources": retrieval_metrics.get("blocked_sources", 0),
            },
        )
        return evaluation

    def _write_final_outputs(self, program, claims, evidence, contradictions, open_questions, evaluation, metrics) -> None:
        report = build_report(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
        (self.out_dir / "final_report.md").write_text(report, encoding="utf-8")
        write_research_html(
            self.out_dir / "final_report.html",
            program,
            claims,
            evidence,
            contradictions,
            open_questions,
            evaluation,
            metrics,
        )
        write_pdf(self.out_dir / "final_report.pdf", "AutoResearch OS Legal Research Report", report)

    def _write_program_state(self, program, tasks, hypotheses) -> None:
        (self.out_dir / "program.md").write_text(program_to_markdown(program), encoding="utf-8")
        write_json(self.out_dir / "tasks.json", tasks)
        write_json(self.out_dir / "hypotheses.json", hypotheses)
        write_json(self.out_dir / "entities.json", {"entities": _extract_entities(program.objective)})
        write_json(self.out_dir / "legal_metadata.json", program.legal_metadata)

    def _write_iteration_state(
        self,
        iteration,
        evidence,
        claims,
        contradictions,
        criticisms,
        open_questions,
        evaluation,
        tuning_params,
        next_tuning_params,
    ) -> None:
        write_json(self.out_dir / "evidence" / f"iteration_{iteration:03d}.json", evidence)
        write_json(self.out_dir / "claims.json", claims)
        write_json(self.out_dir / "contradictions.json", contradictions)
        write_json(self.out_dir / "criticisms.json", criticisms)
        write_json(self.out_dir / "open_questions.json", {"open_questions": open_questions})
        write_json(self.out_dir / "confidence_scores.json", evaluation)
        write_json(self.out_dir / "tuning_params.json", next_tuning_params)
        write_json(self.out_dir / "evals" / f"iteration_{iteration:03d}.json", evaluation)
        write_json(self.out_dir / "evals" / f"tuning_params_{iteration:03d}.json", tuning_params)
        write_json(self.out_dir / "evals" / f"next_tuning_params_{iteration:03d}.json", next_tuning_params)

    def _build_metrics(
        self,
        elapsed: float,
        iterations_completed,
        tasks,
        hypotheses,
        evidence,
        claims,
        contradictions,
        open_questions,
        evaluation,
        did_stop,
        final_artifacts,
        component_seconds,
        iteration_history,
        retrieval_metrics,
        agent_traces,
        llm_enabled,
        llm_model,
        raindrop_enabled,
        raindrop_target,
        raindrop_feedback=None,
    ) -> RunMetrics:
        one_shot_agents = {"program_generator", "planner_orchestrator", "hypothesis_agent", "raindrop_feedback_agent", "report_generator"}
        agent_breakdown = {
            name: count if name in one_shot_agents else count * iterations_completed
            for name, count in BASE_AGENT_BREAKDOWN.items()
        }
        for trace in agent_traces:
            if trace.name == "modal_hypothesis_agent_pool":
                agent_breakdown["modal_hypothesis_agent"] = agent_breakdown.get("modal_hypothesis_agent", 0) + trace.output_count
            elif trace.name == "hypothesis_refinement_agent":
                agent_breakdown["hypothesis_refinement_agent"] = agent_breakdown.get("hypothesis_refinement_agent", 0) + 1
        if retrieval_metrics.get("modal_enabled"):
            agent_breakdown["modal_url_fetch_agent"] = int(retrieval_metrics.get("modal_url_fetch_agents", 0))
        component_agents = {
            "program_generation": agent_breakdown["program_generator"],
            "planning": agent_breakdown["planner_orchestrator"] + agent_breakdown["knowledge_gap_detector"],
            "hypothesis_generation": agent_breakdown["hypothesis_agent"],
            "evidence_collection": (
                agent_breakdown["web_search_agent"]
                + agent_breakdown["academic_agent"]
                + agent_breakdown["legal_agent"]
                + agent_breakdown["company_intelligence_agent"]
                + agent_breakdown["social_signal_agent"]
                + agent_breakdown["extraction_agent"]
                + agent_breakdown.get("modal_url_fetch_agent", 0)
            ),
            "claim_synthesis": agent_breakdown["extraction_agent"],
            "critique": agent_breakdown["critic_agent"],
            "gap_detection": agent_breakdown["knowledge_gap_detector"],
            "evaluation": agent_breakdown["evaluator_agent"],
            "auto_tuning": agent_breakdown["auto_tuner"],
            "raindrop_feedback": agent_breakdown["raindrop_feedback_agent"],
            "report_generation": agent_breakdown["report_generator"],
        }
        component_metrics = {
            name: {
                "seconds": round(component_seconds.get(name, 0.0), 4),
                "agents": component_agents.get(name, 0),
            }
            for name in component_seconds
        }
        return RunMetrics(
            generated_at=datetime.now(UTC).isoformat(),
            total_runtime_seconds=round(elapsed, 3),
            component_metrics=component_metrics,
            iteration_history=iteration_history,
            retrieval_metrics=retrieval_metrics,
            agent_traces=[trace.__dict__ for trace in agent_traces],
            llm_reasoning_enabled=llm_enabled,
            llm_model=llm_model if llm_enabled else None,
            raindrop_tracing_enabled=raindrop_enabled,
            raindrop_target=raindrop_target,
            iterations_completed=iterations_completed,
            agents_spun_off=sum(agent_breakdown.values()),
            agent_breakdown=agent_breakdown,
            tasks_count=len(tasks),
            hypotheses_count=len(hypotheses),
            evidence_count=len(evidence),
            source_type_count=len({item.source_type for item in evidence}),
            claims_count=len(claims),
            supported_claims_count=sum(1 for claim in claims if claim.status == "supported"),
            contradictions_count=len(contradictions),
            resolved_contradictions_count=sum(1 for contradiction in contradictions if contradiction.resolution_status == "resolved"),
            open_questions_count=len(open_questions),
            final_confidence=evaluation.overall_confidence,
            stop_conditions_met=did_stop,
            generated_artifacts=final_artifacts,
            raindrop_feedback=raindrop_feedback or {},
            deterministic_confidence=evaluation.deterministic_confidence,
            llm_scoring_enabled=evaluation.llm_scoring_enabled,
            llm_score_adjustment=evaluation.llm_score_adjustment,
        )

    def _append_gap_tasks(self, tasks, open_questions):
        existing = {task.question for task in tasks}
        next_id = len(tasks) + 1
        for question in open_questions:
            if question in existing:
                continue
            from .models import Task

            tasks.append(Task(task_id=f"t{next_id:03d}", title="Resolve knowledge gap", question=question))
            next_id += 1
        write_json(self.out_dir / "tasks.json", tasks)
        return tasks


def _extract_entities(text: str) -> list[str]:
    candidates = []
    for token in text.replace("?", "").replace(",", "").split():
        if token[:1].isupper() or token.upper() in {"AI", "US", "U.S."}:
            candidates.append(token)
    return sorted(set(candidates))


def _iteration_snapshot(iteration: int, evaluation: Evaluation, evidence, contradictions, open_questions, did_stop: bool) -> dict[str, float | int | str | bool]:
    return {
        "iteration": iteration,
        "overall_confidence": evaluation.overall_confidence,
        "objective_completion": evaluation.objective_completion,
        "evidence_coverage": evaluation.evidence_coverage,
        "citation_grounding": evaluation.citation_grounding,
        "primary_authority_coverage": evaluation.primary_authority_coverage,
        "mean_claim_confidence": evaluation.mean_claim_confidence,
        "weakest_claim_confidence": evaluation.weakest_claim_confidence,
        "confidence_stability": evaluation.confidence_stability,
        "open_question_penalty": evaluation.open_question_penalty,
        "blocked_source_penalty": evaluation.blocked_source_penalty,
        "confidence_cap": evaluation.confidence_cap,
        "contradiction_resolution": evaluation.contradiction_resolution,
        "source_diversity": evaluation.source_diversity,
        "evidence_count": len(evidence),
        "contradictions": len(contradictions),
        "open_questions": len(open_questions),
        "status": "Converged" if did_stop else "Continue",
        "stop_conditions_met": did_stop,
    }


def _research_plateaued(history: list[dict[str, float | int | str | bool]]) -> bool:
    if len(history) < 2:
        return False
    recent = history[-2:]
    confidence_delta = max(float(item["overall_confidence"]) for item in recent) - min(float(item["overall_confidence"]) for item in recent)
    evidence_delta = int(recent[-1]["evidence_count"]) - int(recent[0]["evidence_count"])
    open_questions_delta = int(recent[0]["open_questions"]) - int(recent[-1]["open_questions"])
    return confidence_delta < 0.01 and evidence_delta <= 0 and open_questions_delta <= 0
