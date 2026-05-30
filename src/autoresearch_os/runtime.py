from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import time

from .critic import critique_claims
from .evaluator import evaluate, stop_conditions_met
from .gaps import detect_gaps
from .hypotheses import generate_hypotheses
from .knowledge import claims_from_hypotheses, collect_evidence
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
    def __init__(self, out_dir: Path, max_iterations: int = 4) -> None:
        self.out_dir = out_dir
        self.max_iterations = max_iterations

    def run(self, goal: str, seed_texts: list[str] | None = None) -> Evaluation:
        started_at = time.perf_counter()
        seed_texts = seed_texts or []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "evidence").mkdir(exist_ok=True)
        (self.out_dir / "evals").mkdir(exist_ok=True)

        tuning_params = load_tuning_params(self.out_dir)
        program = generate_program(goal)
        tasks = plan_tasks(program)
        hypotheses = generate_hypotheses(program)
        evidence = []
        claims = []
        contradictions = []
        open_questions = ["Initial research state has not been evaluated."]
        criticisms = []
        evaluation: Evaluation | None = None
        iterations_completed = 0

        self._write_program_state(program, tasks, hypotheses)

        for iteration in range(1, self.max_iterations + 1):
            iterations_completed = iteration
            evidence = collect_evidence(tasks, hypotheses, seed_texts)
            claims = claims_from_hypotheses(hypotheses, evidence, tuning_params)
            contradictions, criticisms = critique_claims(claims)
            open_questions = detect_gaps(program, claims, contradictions, criticisms, tuning_params)
            evaluation = evaluate(iteration, program, claims, evidence, contradictions, open_questions, tuning_params)
            next_tuning_params = tuning_params if stop_conditions_met(program, evaluation) else tune_params(tuning_params, evaluation)

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
            if stop_conditions_met(program, evaluation):
                break

            tuning_params = next_tuning_params
            tasks = self._append_gap_tasks(tasks, open_questions)

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
        )
        write_json(self.out_dir / "metrics.json", metrics)

        report = build_report(program, claims, evidence, contradictions, open_questions, evaluation, metrics)
        (self.out_dir / "final_report.md").write_text(report, encoding="utf-8")
        write_pdf(self.out_dir / "final_report.pdf", "AutoResearch OS Grounded Legal Research Report", report)
        return evaluation

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
    ) -> RunMetrics:
        one_shot_agents = {"program_generator", "planner_orchestrator", "hypothesis_agent", "report_generator"}
        agent_breakdown = {
            name: count if name in one_shot_agents else count * iterations_completed
            for name, count in BASE_AGENT_BREAKDOWN.items()
        }
        return RunMetrics(
            generated_at=datetime.now(UTC).isoformat(),
            total_runtime_seconds=round(elapsed, 3),
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
