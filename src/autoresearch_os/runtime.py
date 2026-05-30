from __future__ import annotations

from pathlib import Path

from .critic import critique_claims
from .evaluator import evaluate, stop_conditions_met
from .gaps import detect_gaps
from .hypotheses import generate_hypotheses
from .knowledge import claims_from_hypotheses, collect_evidence
from .models import Evaluation, write_json
from .planner import plan_tasks
from .program import generate_program, program_to_markdown
from .report import build_report


class ResearchRuntime:
    def __init__(self, out_dir: Path, max_iterations: int = 4) -> None:
        self.out_dir = out_dir
        self.max_iterations = max_iterations

    def run(self, goal: str, seed_texts: list[str] | None = None) -> Evaluation:
        seed_texts = seed_texts or []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "evidence").mkdir(exist_ok=True)
        (self.out_dir / "evals").mkdir(exist_ok=True)

        program = generate_program(goal)
        tasks = plan_tasks(program)
        hypotheses = generate_hypotheses(program)
        evidence = []
        claims = []
        contradictions = []
        open_questions = ["Initial research state has not been evaluated."]
        criticisms = []
        evaluation: Evaluation | None = None

        self._write_program_state(program, tasks, hypotheses)

        for iteration in range(1, self.max_iterations + 1):
            evidence = collect_evidence(tasks, hypotheses, seed_texts)
            claims = claims_from_hypotheses(hypotheses, evidence)
            contradictions, criticisms = critique_claims(claims)
            open_questions = detect_gaps(program, claims, contradictions, criticisms)
            evaluation = evaluate(iteration, program, claims, evidence, contradictions, open_questions)

            self._write_iteration_state(iteration, evidence, claims, contradictions, criticisms, open_questions, evaluation)
            if stop_conditions_met(program, evaluation):
                break

            tasks = self._append_gap_tasks(tasks, open_questions)

        if evaluation is None:
            raise RuntimeError("Research loop did not produce an evaluation.")

        report = build_report(program, claims, evidence, contradictions, open_questions, evaluation)
        (self.out_dir / "final_report.md").write_text(report, encoding="utf-8")
        return evaluation

    def _write_program_state(self, program, tasks, hypotheses) -> None:
        (self.out_dir / "program.md").write_text(program_to_markdown(program), encoding="utf-8")
        write_json(self.out_dir / "tasks.json", tasks)
        write_json(self.out_dir / "hypotheses.json", hypotheses)
        write_json(self.out_dir / "entities.json", {"entities": _extract_entities(program.objective)})

    def _write_iteration_state(self, iteration, evidence, claims, contradictions, criticisms, open_questions, evaluation) -> None:
        write_json(self.out_dir / "evidence" / f"iteration_{iteration:03d}.json", evidence)
        write_json(self.out_dir / "claims.json", claims)
        write_json(self.out_dir / "contradictions.json", contradictions)
        write_json(self.out_dir / "criticisms.json", criticisms)
        write_json(self.out_dir / "open_questions.json", {"open_questions": open_questions})
        write_json(self.out_dir / "confidence_scores.json", evaluation)
        write_json(self.out_dir / "evals" / f"iteration_{iteration:03d}.json", evaluation)

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
