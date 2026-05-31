# 1-Minute Hackathon Demo Script

**0:00-0:10 - Benchmark score and impact**
AutoResearch OS takes a legal research prompt about AI-generated code copyright and produces a grounded research report. In our benchmark demo, the system reaches **88% final confidence**, with **6 evidence records**, **4 out of 4 supported claims**, **100% citation grounding**, and **100% primary-authority coverage**. The impact is that a user gets a decision-ready legal memo instead of a fluent but untraceable answer.

**0:10-0:30 - Why the system hits that score**
We hit that score because this is not a single model call. The architecture is a control loop: program generation, planning, hypothesis generation, knowledge-agent retrieval, claim synthesis, critique, gap detection, evaluation, and auto-tuning. Each phase has a specific quality gate. If evidence is missing, citations are weak, contradictions appear, or open questions remain, the evaluator and tuner push the run back into another research pass.

**0:30-0:45 - Walk through the report**
In the report, start at the top-line metrics: **88% confidence**, supported claims, sources, and stop conditions. Then show the key findings and citations. The report also includes open questions, convergence progress, agent tool loops, and live web retrieval status, so users can see both the answer and how the system reasoned its way there.

**0:45-1:00 - Walk through Raindrop**
Raindrop is the operator view. The HTML now shows **Raindrop Workshop: enabled** and the feedback section shows the trace status, verdict, trace focus, and recommended next steps. In Workshop, we can inspect spans like `knowledge_agent_pool`, `evaluator_agent`, `knowledge_gap_detector`, and `auto_tuner`. That is the self-improvement loop: the user sees the report, while the builder uses Raindrop traces to understand why a run scored well or failed, then improves the next run.
