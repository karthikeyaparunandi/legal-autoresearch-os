from __future__ import annotations

from .models import ResearchProgram, Task


def plan_tasks(program: ResearchProgram) -> list[Task]:
    tasks = [
        Task(
            task_id=f"t{index:03d}",
            title=question.split("?")[0][:80],
            question=question,
            depends_on=[] if index == 1 else ["t001"],
        )
        for index, question in enumerate(program.subquestions, start=1)
    ]
    tasks.append(
        Task(
            task_id=f"t{len(tasks) + 1:03d}",
            title="Synthesize grounded answer",
            question="Which answer is best supported once claims, evidence, and contradictions are considered?",
            depends_on=[task.task_id for task in tasks],
        )
    )
    return tasks
