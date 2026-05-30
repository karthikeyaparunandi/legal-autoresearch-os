# AutoResearch OS

AutoResearch OS is a legal autoresearch runtime for the Modal Autoresearch Systems Hackathon. It turns a user goal into an executable research program, runs specialized agents through an iterative control loop, maintains a persistent truth repository, evaluates convergence, and emits a grounded report with citations, metrics, and a reasoning trace.

The prototype is intentionally narrowed to legal research. Each run records legal metadata such as jurisdiction, practice area, authority hierarchy, required source types, citation policy, risk posture, and uncertainty policy.

## The Idea

AutoResearch OS is not just an agent with memory. It is a research control system that keeps improving a structured research state until measurable objectives are satisfied.

```text
Research
-> Truth Maintenance
-> Self Evaluation
-> Knowledge Gap Detection
-> New Research Tasks
-> Research Again
```

The final output is not only an answer. It is a report backed by claims, evidence, contradictions, confidence scores, source links, agent traces, and stop-condition metrics.

## What Makes It Different

- A central OpenAI Agents SDK reasoning layer coordinates the legal research process by default.
- Role agents are explicit tool-using workers, not anonymous programming threads.
- A truth-maintenance repo stores claims, evidence, contradictions, confidence, open questions, and tuning parameters.
- The evaluator scores objective completion, citation grounding, evidence coverage, contradiction resolution, source diversity, and open questions.
- A knowledge-gap detector converts weak research states into new tasks.
- Tuning parameters adapt over time when the evaluator finds weak evidence, unresolved contradictions, or insufficient primary authority.

## Quickstart

Install the project:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the built-in legal demo with OpenAI Agents SDK reasoning:

```bash
export OPENAI_API_KEY="..."
autoresearch demo --out demo_gt_repo
```

`OPEN_API_KEY` is also accepted for local experiments. OpenAI Agents SDK reasoning is the default; if no key is available, the CLI fails loudly instead of silently falling back.

Run without installing:

```bash
export OPENAI_API_KEY="..."
PYTHONPATH=src python -m autoresearch_os.cli demo --out demo_gt_repo
```

Run deterministic fallback mode for offline tests or no-key demos:

```bash
PYTHONPATH=src python -m autoresearch_os.cli demo --offline --no-llm --out demo_gt_repo
```

Control the inner hypothesis/knowledge/critic feedback loop:

```bash
PYTHONPATH=src python -m autoresearch_os.cli demo --feedback-rounds 2 --out demo_gt_repo
```

Run your own legal question:

```bash
autoresearch run \
  "Can AI-generated code be copyrighted in the United States, and what legal risks would a startup face if it relies heavily on AI-generated software?" \
  --out gt_repo \
  --max-iterations 4
```

Add extra sources:

```bash
autoresearch run \
  "Can AI-generated code be copyrighted in the United States?" \
  --source-url https://www.example.com/legal-source \
  --out gt_repo
```

Run live retrieval on Modal for faster source fan-out:

```bash
pip install -e ".[dev,modal]"
modal setup
export OPENAI_API_KEY="..."
autoresearch demo --modal --out demo_gt_repo
```

For a fast retrieval-only smoke test:

```bash
modal run modal/app.py
```

## Architecture

### High-Level Loop

```mermaid
flowchart LR
    goal["User Goal"] --> program["Research Program<br/>(program.md)"]
    program --> runtime["Research Runtime<br/>Hypothesize · Critique · Retrieve"]
    runtime --> truth["Truth Maintenance Repo<br/>Claims · Evidence · Contradictions"]
    truth --> eval["Self Evaluation<br/>Objectives · Citations · Contradictions"]
    eval --> gaps["Knowledge Gap Detector"]
    gaps --> converged{"Research State<br/>Converged?"}
    converged -- "No: new tasks" --> runtime
    converged -- "Yes" --> report["Grounded Report<br/>HTML · PDF · Markdown"]
```

### Runtime Detail

```mermaid
flowchart TD
    goal["User Goal"] --> generator["Program Generator Agent"]
    generator --> program["Research Program<br/>program.md"]
    generator --> legalMeta["Legal Metadata<br/>jurisdiction · authority hierarchy · risk posture"]

    program --> planner["Planner / Orchestrator"]
    planner --> tasks["Task DAG"]

    subgraph runtime["Research Runtime"]
        direction TB
        hypotheses["Hypothesis Agent<br/>candidate legal theories"]
        critic["Critic Agent<br/>weaknesses · alternatives · contradictions"]
        knowledge["Knowledge Agent Pool<br/>legal · web · academic · company · social"]
        extraction["Extraction Agent<br/>facts · citations · source metadata"]
        hypotheses --> critic
        critic --> knowledge
        knowledge --> extraction
        extraction -- "evidence updates" --> hypotheses
        critic -- "revise / split / discard" --> hypotheses
    end

    tasks --> hypotheses
    legalMeta --> knowledge

    subgraph truth["Truth Maintenance Repo"]
        direction TB
        repoClaims["claims.json"]
        repoEvidence["evidence/*.json"]
        repoContradictions["contradictions.json"]
        repoConfidence["confidence_scores.json"]
        repoQuestions["open_questions.json"]
        repoTuning["tuning_params.json"]
    end

    hypotheses --> repoClaims
    critic --> repoContradictions
    extraction --> repoEvidence
    repoEvidence --> repoClaims
    repoClaims --> critic
    repoContradictions --> critic
    repoQuestions --> planner
    repoTuning --> planner
    repoTuning --> critic

    subgraph evaluator["Self Evaluation"]
        direction TB
        objective["Objective Completion"]
        coverage["Evidence Coverage"]
        grounding["Citation Grounding"]
        contradictionScore["Contradiction Resolution"]
        diversity["Source Diversity"]
        openQ["Open Questions"]
        confidence["Research Confidence Score"]
        objective --> confidence
        coverage --> confidence
        grounding --> confidence
        contradictionScore --> confidence
        diversity --> confidence
        openQ --> confidence
    end

    truth --> evaluator
    confidence --> repoConfidence
    evaluator --> gaps["Knowledge Gap Detector<br/>missing authority · weak claims · unresolved contradictions"]
    gaps --> repoQuestions
    gaps --> newTasks["New Research Tasks"]
    newTasks --> planner
    evaluator --> tuner["Auto-Tuner<br/>thresholds · source targets · penalty weights"]
    tuner --> repoTuning
    confidence --> converged{"Objectives Satisfied<br/>and Research State Converged?"}
    converged -- "No" --> newTasks
    converged -- "Yes" --> report["Grounded Legal Report<br/>linked citations · reasoning diagram · metrics"]
```

The hypothesis, critic, and knowledge agents form an inner feedback loop. Hypotheses are challenged by the critic, tested by knowledge agents, updated from extracted evidence, and revised before the truth repo is evaluated. `--feedback-rounds` controls how many times that inner loop may run inside a single outer research iteration.

## Agents

The current runtime exposes these agent roles:

- `program_generator`: creates the legal research program and metadata.
- `planner_orchestrator`: turns the program into task structure.
- `hypothesis_agent`: generates and refines candidate legal theories.
- `hypothesis_refinement_agent`: revises hypotheses from critic findings, contradictions, and knowledge gaps.
- `knowledge_agent_pool`: retrieves and structures evidence from live or fallback sources.
- `modal_hypothesis_agent_pool`: when `--modal` is enabled, runs one remote research worker per hypothesis.
- `critic_agent`: attacks claims, finds contradictions, and raises weaknesses.
- `evaluator_agent`: scores the research state against convergence criteria.
- `knowledge_gap_detector`: creates follow-up tasks from weak or missing knowledge.
- `auto_tuner`: adjusts thresholds and source requirements over time.
- `report_generator`: produces Markdown, HTML, and PDF reports.

Each role agent has deterministic tools plus an OpenAI Agents SDK reasoning call. The local runtime owns orchestration and state, while SDK `Agent` instances perform the compact JSON reasoning steps for hypothesis refinement, evidence review, and criticism. Agent traces are written into `metrics.json` and shown in the CLI and HTML report, including tools used, loop steps, output counts, and whether LLM reasoning was used.

## Truth-Maintenance Repo

Each run writes a complete research state:

```text
gt_repo/
  program.md
  legal_metadata.json
  tuning_params.json
  tasks.json
  entities.json
  hypotheses.json
  claims.json
  evidence/
  contradictions.json
  confidence_scores.json
  metrics.json
  open_questions.json
  evals/
  final_report.md
  final_report.html
  final_report.pdf
```

The HTML report is the primary demo artifact. It includes paper-style linked citations, a reasoning/rationale diagram, component-level metrics, convergence progress, hypothesis confidence, contradiction analysis, source anchors, and agent tool loops.

## Retrieval

Knowledge agents can fetch real external sources using dependency-free HTTP retrieval. The built-in legal source set includes public authorities such as Federal Register copyright guidance, the U.S. Copyright Office AI page, and 17 U.S.C. Section 102 via Cornell LII.

Every run records retrieval metrics:

- live retrieval enabled or disabled
- URLs attempted and retrieved
- failed URLs and error classes
- fallback evidence usage
- retrieved source URLs

## Evaluation And Convergence

The evaluator tracks:

- objective completion
- evidence coverage
- citation grounding
- contradiction resolution
- source diversity
- open questions
- final confidence

The runtime stops when the research program is satisfied:

```text
Objective Completion >= 90%
Citation Grounding >= 90%
Overall Confidence >= 85%
Critical Open Questions <= 2
Contradiction Resolution >= 80%
```

If the state has not converged, the knowledge-gap detector creates follow-up tasks and the runtime loops again.

## Legal Metadata And Tuning

Legal quality depends on different assumptions than generic web research. AutoResearch OS records those assumptions in `program.md` and `legal_metadata.json`:

- jurisdiction and practice area
- legal authority hierarchy
- required primary source types
- citation style
- risk posture and uncertainty policy

The runtime persists tunable constants in `tuning_params.json`, including:

- `supported_claim_threshold`
- `contradiction_penalty_weight`
- `min_primary_sources`
- `target_source_diversity`
- `gap_task_limit`
- `evaluator_weights`

After each evaluation, the tuner nudges these values when the research state is weak. For example, low citation grounding raises the support threshold and primary-source requirement; low contradiction resolution increases contradiction penalties; too many open questions expands gap-task generation.

## Metrics

The CLI, `metrics.json`, Markdown report, HTML report, and PDF report include:

- agents spun off and agent-by-agent breakdown
- hypotheses, tasks, claims, evidence records, source categories, contradictions, and open questions
- iterations completed
- component runtimes
- retrieval metrics
- agent tool-loop traces
- final confidence
- stop-condition status

## Modal Acceleration

`modal/app.py` defines the remote workers used by `autoresearch demo --modal` and `autoresearch run --modal`. The stronger path is the `modal_hypothesis_agent_pool`: each hypothesis is sent to a separate Modal worker that retrieves evidence, synthesizes a claim, critiques that claim, runs an OpenAI Agents SDK reasoning pass, and returns a scored research bundle to the local orchestrator. URL-level retrieval fan-out is still available as a lower-level tool.

The design follows the same control-plane/data-plane split as [`modal-labs/openai-agents-python-example`](https://github.com/modal-labs/openai-agents-python-example): keep an orchestrator in charge of state, then fan out bounded worker jobs on Modal. In this repo, `ResearchRuntime` is the orchestrator, `modal_hypothesis_agent_pool` is the distributed agent pool, and `modal/app.py` is the remote worker layer.

Modal is optional:

- Default local retrieval stays dependency-free.
- `--modal` requires `pip install -e ".[modal]"` and `modal setup`.
- If Modal is unavailable, the CLI exits with a clear error instead of silently switching paths.

See [docs/modal_agents_reference.md](docs/modal_agents_reference.md) for the mapping between the reference project and this legal research runtime.

## Development

```bash
pytest
```
