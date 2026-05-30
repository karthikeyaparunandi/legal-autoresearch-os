# AutoResearch OS — C4 Model & Sequence Diagrams

This document describes the architecture of **AutoResearch OS** using the
[C4 model](https://c4model.com/) (Context → Container → Component → Code) plus a
runtime **sequence diagram** of the research control loop.

All diagrams are Mermaid and render in GitHub and in VS Code's Markdown preview
(with the **Markdown Preview Mermaid Support** extension). The C4 levels use
standard `flowchart` syntax — color-coded by C4 element type — rather than
Mermaid's experimental `C4Context`/`C4Container` diagrams, which the bundled
renderer leaves blank.

> Mapping note: every component below corresponds to a real module under
> `src/autoresearch_os/`. The runtime is fully deterministic and offline today —
> "knowledge agents" read a built-in legal fixture (`knowledge.py`) plus optional
> seed text; the external search/LLM systems shown dashed are the documented
> swap-in points, not current dependencies.

---

## Level 1 — System Context

Who uses the system and what it talks to.

```mermaid
flowchart TB
    researcher["👤 Researcher / Startup Decision-Maker<br/><i>[Person]</i><br/>Has a legal research goal; wants a grounded,<br/>cited answer with explicit uncertainty"]

    autoresearch["AutoResearch OS<br/><i>[Software System]</i><br/>Self-evaluating autonomous research runtime<br/>with a truth-maintenance repo. Drives a research<br/>state to measurable convergence and emits a cited report."]

    modal["Modal Workers<br/><i>[External System]</i><br/>Optional parallel evidence-collection<br/>fan-out (sketch in modal/app.py)"]
    search["Web / Legal / Academic Search<br/><i>[External System]</i><br/>Planned swap-in for the<br/>deterministic knowledge agents"]
    llm["LLM / Model APIs<br/><i>[External System]</i><br/>Planned swap-in for hypothesis,<br/>critic &amp; extraction reasoning"]

    researcher -->|"Submits a goal; reads cited report + metrics<br/>(CLI: autoresearch run / demo)"| autoresearch
    autoresearch -.->|"May fan out evidence collection"| modal
    autoresearch -.->|"Would retrieve evidence (HTTP, future)"| search
    autoresearch -.->|"Would generate / critique / extract (HTTP, future)"| llm

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef system fill:#1168bd,stroke:#0b4884,color:#fff
    classDef external fill:#999,stroke:#6b6b6b,color:#fff,stroke-dasharray:4 3
    class researcher person
    class autoresearch system
    class modal,search,llm external
```

---

## Level 2 — Containers

The high-level building blocks inside AutoResearch OS and the shared
truth-maintenance repository they all read from / write to.

```mermaid
flowchart TB
    researcher["👤 Researcher<br/><i>[Person]</i>"]

    subgraph aros["AutoResearch OS"]
        direction TB
        cli["CLI<br/><i>[Container: Python · argparse · cli.py]</i><br/>Parses run / demo, invokes the runtime,<br/>prints metrics, convergence &amp; agent tables"]
        runtime["Research Runtime<br/><i>[Container: Python · runtime.py]</i><br/>Orchestrates the control loop: hypothesize →<br/>retrieve → synthesize → critique → detect gaps →<br/>evaluate → tune → repeat until convergence"]
        repo[("Truth-Maintenance Repo<br/><i>[Filesystem · JSON + Markdown · gt_repo/]</i><br/>Durable research state: program, tasks, hypotheses,<br/>claims, evidence/, contradictions, confidence_scores,<br/>open_questions, tuning_params, evals/, metrics")]
        reporters["Report Generators<br/><i>[Container: report.py · html.py · pdf.py]</i><br/>Render the final grounded report<br/>as Markdown, HTML &amp; PDF"]
    end

    modal["Modal Workers<br/><i>[External System]</i>"]

    researcher -->|"autoresearch run &quot;&lt;goal&gt;&quot;"| cli
    cli -->|"ResearchRuntime(out_dir).run(goal, seed_texts)"| runtime
    runtime -->|"Writes every artifact each iteration;<br/>reads tuning_params on start"| repo
    runtime -->|"build_report / write_research_html / write_pdf"| reporters
    reporters -->|"final_report.{md,html,pdf}"| repo
    cli -->|"Reads metrics.json to print summary"| repo
    runtime -.->|"Optional evidence fan-out (future)"| modal

    classDef person fill:#08427b,stroke:#052e56,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    classDef store fill:#438dd5,stroke:#2e6295,color:#fff
    classDef external fill:#999,stroke:#6b6b6b,color:#fff,stroke-dasharray:4 3
    class researcher person
    class cli,runtime,reporters container
    class repo store
    class modal external
```

---

## Level 3 — Components (inside the Research Runtime)

Each component is one module. Arrows show the data-flow of a single iteration of
the control loop. The runtime (`runtime.py`) is the orchestrator that calls each
component in order and persists the result.

```mermaid
flowchart TB
    repo[("Truth-Maintenance Repo<br/><i>[JSON + Markdown]</i>")]
    reporters["Report Generators<br/><i>[report/html/pdf]</i>"]

    subgraph rt["Research Runtime — runtime.py"]
        direction TB
        orchestrator["Orchestrator / Control Loop<br/><i>[ResearchRuntime.run]</i><br/>Sequences components, times each stage,<br/>persists state, checks stop conditions"]
        program["Program Generator<br/><i>[program.py]</i>"]
        planner["Planner<br/><i>[planner.py]</i>"]
        hypo["Hypothesis Agent<br/><i>[hypotheses.py]</i>"]
        knowledge["Knowledge Agent Pool<br/><i>[knowledge.collect_evidence]</i>"]
        extract["Claim Synthesizer<br/><i>[knowledge.claims_from_hypotheses]</i>"]
        critic["Critic Agent<br/><i>[critic.py]</i>"]
        gaps["Knowledge Gap Detector<br/><i>[gaps.py]</i>"]
        eval["Evaluator<br/><i>[evaluator.py]</i>"]
        tuner["Auto-Tuner<br/><i>[tuning.py]</i>"]
    end

    orchestrator -->|"generate_program(goal)"| program
    orchestrator -->|"plan_tasks(program)"| planner
    orchestrator -->|"generate_hypotheses(program)"| hypo
    orchestrator -->|"collect_evidence(...)"| knowledge
    orchestrator -->|"claims_from_hypotheses(...)"| extract
    orchestrator -->|"critique_claims(claims)"| critic
    orchestrator -->|"detect_gaps(...)"| gaps
    orchestrator -->|"evaluate(...)"| eval
    orchestrator -->|"tune_params(params, eval)"| tuner
    orchestrator -->|"build_report / html / pdf"| reporters

    orchestrator -->|"write_json each stage"| repo
    tuner -->|"tuning_params.json"| repo
    eval -->|"confidence_scores.json / evals/"| repo

    classDef component fill:#85bbf0,stroke:#5d82a8,color:#000
    classDef store fill:#438dd5,stroke:#2e6295,color:#fff
    classDef container fill:#438dd5,stroke:#2e6295,color:#fff
    class orchestrator,program,planner,hypo,knowledge,extract,critic,gaps,eval,tuner component
    class repo store
    class reporters container
```

### Component responsibilities & control-flow feedback

```mermaid
flowchart LR
    program["Program Generator<br/>program.py"] --> planner["Planner<br/>planner.py"]
    program --> hypo["Hypothesis Agent<br/>hypotheses.py"]
    planner --> knowledge
    hypo --> knowledge["Knowledge Pool<br/>collect_evidence"]
    knowledge --> extract["Claim Synthesizer<br/>claims_from_hypotheses"]
    extract --> critic["Critic<br/>critic.py"]
    critic --> gaps["Gap Detector<br/>gaps.py"]
    gaps --> eval["Evaluator<br/>evaluator.py"]
    eval --> stop{"stop_conditions_met?"}
    stop -- "No" --> tuner["Auto-Tuner<br/>tuning.py"]
    tuner -- "nudged params" --> extract
    gaps -- "new gap tasks" --> knowledge
    stop -- "Yes" --> report["Report Generators<br/>report/html/pdf"]
```

---

## Level 4 — Code (key types)

The contracts passed between components live in `models.py` (dataclasses).

```mermaid
classDiagram
    class ResearchProgram {
        +str objective
        +list~str~ subquestions
        +list~str~ evidence_requirements
        +list~str~ success_metrics
        +StopConditions stop_conditions
        +LegalMetadata legal_metadata
    }
    class Task {
        +str task_id
        +str title
        +str question
        +list~str~ depends_on
        +str status
    }
    class Hypothesis {
        +str hypothesis_id
        +str statement
        +str rationale
        +str status
    }
    class Evidence {
        +str source_id
        +str source_type
        +list~str~ supports
        +list~str~ contradicts
        +float reliability
    }
    class Claim {
        +str claim_id
        +list~str~ supporting_sources
        +list~str~ contradicting_sources
        +float confidence
        +str status
    }
    class Contradiction {
        +str claim
        +str resolution_status
        +str note
    }
    class Evaluation {
        +int iteration
        +float objective_completion
        +float citation_grounding
        +float contradiction_resolution
        +float overall_confidence
    }
    class TuningParams {
        +float supported_claim_threshold
        +int min_primary_sources
        +int target_source_diversity
        +dict evaluator_weights
        +float learning_rate
    }

    ResearchProgram --> StopConditions
    ResearchProgram --> LegalMetadata
    Hypothesis ..> Claim : synthesized into
    Evidence ..> Claim : supports / contradicts
    Claim ..> Contradiction : conflict detected
    Claim ..> Evaluation : scored by
    Evaluation ..> TuningParams : drives tuning
```

---

## Sequence Diagram — One Research Run

End-to-end flow for `autoresearch run "<goal>"`, including the iterative loop and
its convergence check. The loop body matches `ResearchRuntime.run` in
`runtime.py`.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as CLI<br/>(cli.py)
    participant RT as Research Runtime<br/>(runtime.py)
    participant PG as Program Generator
    participant PL as Planner
    participant HY as Hypothesis Agent
    participant KN as Knowledge Pool
    participant EX as Claim Synthesizer
    participant CR as Critic
    participant GP as Gap Detector
    participant EV as Evaluator
    participant TU as Auto-Tuner
    participant Repo as Truth-Maintenance Repo
    participant RP as Report Generators

    User->>CLI: autoresearch run "<goal>"
    CLI->>RT: ResearchRuntime(out_dir).run(goal, seed_texts)

    RT->>Repo: load tuning_params.json (or defaults)
    RT->>PG: generate_program(goal)
    PG-->>RT: ResearchProgram (+ legal metadata)
    RT->>PL: plan_tasks(program)
    PL-->>RT: tasks (DAG)
    RT->>HY: generate_hypotheses(program)
    HY-->>RT: hypotheses
    RT->>Repo: write program.md, tasks, hypotheses, legal_metadata, entities

    loop iteration 1..max_iterations
        RT->>KN: collect_evidence(tasks, hypotheses, seed_texts)
        KN-->>RT: evidence[]
        RT->>EX: claims_from_hypotheses(hypotheses, evidence, params)
        EX-->>RT: claims[] (confidence, status)
        RT->>CR: critique_claims(claims)
        CR-->>RT: contradictions[], criticisms[]
        RT->>GP: detect_gaps(program, claims, contradictions, criticisms, params)
        GP-->>RT: open_questions[]
        RT->>EV: evaluate(iteration, ...)
        EV-->>RT: Evaluation (overall_confidence, grounding, ...)
        RT->>RT: stop_conditions_met(program, evaluation)
        RT->>Repo: write evidence/, claims, contradictions, open_questions,<br/>confidence_scores, evals/, snapshot to iteration_history

        alt converged (stop conditions met)
            Note over RT: break loop
        else not converged
            RT->>TU: tune_params(params, evaluation)
            TU-->>RT: nudged TuningParams
            RT->>RT: append gap tasks from open_questions
            RT->>Repo: write tuning_params.json, tasks.json
        end
    end

    RT->>RP: build_report / write_research_html / write_pdf
    RP->>Repo: final_report.md / .html / .pdf
    RT->>Repo: write metrics.json
    RT-->>CLI: Evaluation
    CLI->>Repo: read metrics.json
    CLI-->>User: "Research complete" + report links<br/>+ metrics / convergence / agent tables
```

### Convergence stop conditions

The loop breaks early when **all four** hard gates pass — see
`stop_conditions_met` in `evaluator.py` against `StopConditions` in `models.py`:

| Gate | Threshold |
|------|-----------|
| Overall confidence | ≥ 85% |
| Citation grounding | ≥ 90% |
| Objective completion | ≥ 90% |
| Open questions | ≤ 2 |

> Note: contradiction resolution (≥ 80%, mentioned in the README) is **not** a
> hard stop gate in the code. It is one of the weighted inputs the evaluator
> folds into `overall_confidence`, so it influences convergence indirectly
> rather than blocking it directly.

If the gates are not met, the gap detector's open questions become new tasks, the
auto-tuner nudges thresholds, and the runtime loops again (up to
`--max-iterations`).
