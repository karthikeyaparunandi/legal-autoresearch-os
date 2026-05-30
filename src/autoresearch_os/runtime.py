from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time

from .agents import AgentTrace, run_critic_agent, run_hypothesis_agent, run_knowledge_agent
from .evaluator import evaluate, stop_conditions_met
from .gaps import detect_gaps
from .html import write_research_html
from .knowledge import claims_from_hypotheses
from .llm import CentralReasoner
from .models import Evaluation, RunMetrics, write_json
from .pdf import write_pdf
from .planner import plan_tasks
from .program import generate_program, program_to_markdown
from .report import build_report
from .tuning import load_tuning_params, tune_params


BASE_AGENT_BREAKDOWN = {
    "program_generator": 1,
    "planner_orchestrator": 1,
    "hypothesis_agent": 1,
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
    ) -> None:
        self.out_dir = out_dir
        self.max_iterations = max_iterations
        self.live_retrieval = live_retrieval
        self.source_urls = source_urls or []
        self.use_llm = use_llm

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
            "report_generation": 0.0,
        }
        seed_texts = seed_texts or []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "evidence").mkdir(exist_ok=True)
        (self.out_dir / "evals").mkdir(exist_ok=True)

        tuning_params = load_tuning_params(self.out_dir)
        reasoner = CentralReasoner(workspace=self.out_dir.parent, required=True) if self.use_llm else CentralReasoner(api_key="")
        agent_traces: list[AgentTrace] = []
        timer = time.perf_counter()
        program = generate_program(goal)
        component_seconds["program_generation"] += time.perf_counter() - timer
        timer = time.perf_counter()
        tasks = plan_tasks(program)
        component_seconds["planning"] += time.perf_counter() - timer
        timer = time.perf_counter()
        hypotheses, trace = run_hypothesis_agent(program, reasoner)
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
            "retrieved_urls": [],
            "errors": {},
            "fallback_used": False,
        }

        self._write_program_state(program, tasks, hypotheses)

        for iteration in range(1, self.max_iterations + 1):
            iterations_completed = iteration
            timer = time.perf_counter()
            evidence, retrieval_metrics, trace = run_knowledge_agent(
                tasks,
                hypotheses,
                seed_texts,
                self.live_retrieval,
                self.source_urls,
                reasoner,
            )
            agent_traces.append(trace)
            component_seconds["evidence_collection"] += time.perf_counter() - timer
            timer = time.perf_counter()
            claims = claims_from_hypotheses(hypotheses, evidence, tuning_params)
            component_seconds["claim_synthesis"] += time.perf_counter() - timer
            timer = time.perf_counter()
            contradictions, criticisms, trace = run_critic_agent(claims, reasoner)
            agent_traces.append(trace)
            component_seconds["critique"] += time.perf_counter() - timer
            timer = time.perf_counter()
            open_questions = detect_gaps(program, claims, contradictions, criticisms, tuning_params)
            component_seconds["gap_detection"] += time.perf_counter() - timer
            timer = time.perf_counter()
            evaluation = evaluate(
                iteration,
                program,
                claims,
                evidence,
                contradictions,
                open_questions,
                tuning_params,
                previous_evaluation,
            )
            component_seconds["evaluation"] += time.perf_counter() - timer
            timer = time.perf_counter()
            did_stop = stop_conditions_met(program, evaluation)
            iteration_history.append(_iteration_snapshot(iteration, evaluation, evidence, contradictions, open_questions, did_stop))
            next_tuning_params = tuning_params if did_stop else tune_params(tuning_params, evaluation)
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

            previous_evaluation = evaluation
            tuning_params = next_tuning_params
            timer = time.perf_counter()
            tasks = self._append_gap_tasks(tasks, open_questions)
            component_seconds["planning"] += time.perf_counter() - timer

        if evaluation is None:
            raise RuntimeError("Research loop did not produce an evaluation.")

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
        )
        timer = time.perf_counter()
        self._write_final_outputs(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
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
        )
        write_json(self.out_dir / "metrics.json", metrics)
        self._write_final_outputs(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
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
        write_pdf(self.out_dir / "final_report.pdf", "AutoResearch OS Grounded Legal Research Report", report)

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
    ) -> RunMetrics:
        one_shot_agents = {"program_generator", "planner_orchestrator", "hypothesis_agent", "report_generator"}
        agent_breakdown = {
            name: count if name in one_shot_agents else count * iterations_completed
            for name, count in BASE_AGENT_BREAKDOWN.items()
        }
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
            ),
            "claim_synthesis": agent_breakdown["extraction_agent"],
            "critique": agent_breakdown["critic_agent"],
            "gap_detection": agent_breakdown["knowledge_gap_detector"],
            "evaluation": agent_breakdown["evaluator_agent"],
            "auto_tuning": agent_breakdown["auto_tuner"],
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
        "confidence_cap": evaluation.confidence_cap,
        "contradiction_resolution": evaluation.contradiction_resolution,
        "source_diversity": evaluation.source_diversity,
        "evidence_count": len(evidence),
        "contradictions": len(contradictions),
        "open_questions": len(open_questions),
        "status": "Converged" if did_stop else "Continue",
        "stop_conditions_met": did_stop,
    }
