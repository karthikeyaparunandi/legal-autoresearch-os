# Jason AutoResearch Agent

Jason is a separate implementation of AutoResearch OS built around the OpenAI Agents SDK.

The design goal is not "multiple named prompts." The design goal is observable causality:

```text
measured state weakness
-> parent decision
-> targeted worker task
-> Truth Repo update
-> evaluator score change
-> continue or stop
```

## Architecture

```text
User Goal
  |
  v
Parent Research Agent
  |
  +-- initialize_research_program()
  +-- evaluate_truth_repo()
  +-- schedule_targeted_workers()
  +-- run_pending_workers()
  +-- write_final_report()
  |
  v
Truth Maintenance Repo
  |
  +-- events.jsonl          append-only memory
  +-- agent_runs.jsonl      worker trace
  +-- program.md/json       research program
  +-- tasks.json            executable worker tasks
  +-- claims.json           current claims
  +-- evidence.json         accepted evidence
  +-- contradictions.json   unresolved/resolved conflicts
  +-- evals.json            convergence history
```

## Run Offline

The offline path proves the harness without an API call:

```bash
PYTHONPATH=. python -m jason.main --offline --repo jason/truth_repo/demo
```

## Run Benchmark

The benchmark is deterministic and does not require an API key:

```bash
PYTHONPATH=. python jason/benchmarks/run_benchmark.py
```

It writes:

```text
jason/benchmarks/results/latest.json
jason/benchmarks/results/latest.md
```

The benchmark tracks two things:

- Research quality: final evaluator score, required spawned agents, parent decisions, final report creation.
- Truth-repo scalability: full repo read bytes, projected-state read bytes, a small control-slice byte estimate, and the full/control ratio.

The `large_truth_repo_context_pressure` case intentionally injects synthetic stale evidence and events after a normal run. It reports the legacy full-state read, projected state read, and managed control-slice size. Jason's parent agent now uses a Context Broker (`read_control_slice`, `read_claim_context`, `read_contradiction_context`, `read_task_context`) so model context scales with the active claim/task neighborhood rather than the full Truth Repo.

## Legal Specialization

Jason includes a Claude-style legal skill catalog in `jason/legal_skills.py`. Legal goals trigger practice-area skill paths for commercial, corporate, employment, privacy, product, regulatory, AI governance, IP, litigation, or general legal research. The program seed then scopes jurisdiction, authority hierarchy, date sensitivity, missing facts, primary authority needs, business risk, and human-review gates before the scheduler spawns workers.

The offline harness is deterministic: legal workers prefer statutes, case law, regulations, agency guidance, and official materials, and the final report adds legal analysis, authority discipline, evidence requirements, and a clear "not legal advice" review gate.

## Run DeepResearch Bench Adapter

DeepResearch Bench is an external report-quality benchmark. Jason writes its reports in the raw format DRB expects:

```bash
PYTHONPATH=. python jason/benchmarks/deepresearch_bench.py \
  --drb-root /path/to/deep_research_bench \
  --only-en \
  --limit 1 \
  --copy-to-drb
```

To generate the DRB article with the current flagship model and web search, use:

```bash
PYTHONPATH=. python jason/benchmarks/deepresearch_bench.py \
  --drb-root /path/to/deep_research_bench \
  --only-en \
  --limit 1 \
  --generator latest-model \
  --model gpt-5.5 \
  --model-name jason-autoresearch-latest \
  --copy-to-drb
```

The adapter writes:

```text
jason/benchmarks/results/deepresearch_bench/jason-autoresearch.jsonl
jason/benchmarks/results/deepresearch_bench/latest.json
jason/benchmarks/results/deepresearch_bench/latest.md
```

To attach an official RACE score after running DRB's evaluator, pass the generated result file back in:

```bash
PYTHONPATH=. python jason/benchmarks/deepresearch_bench.py \
  --drb-root /path/to/deep_research_bench \
  --only-en \
  --limit 1 \
  --reuse-output \
  --race-result /path/to/deep_research_bench/results/race/jason-autoresearch/race_result.txt
```

Interpretation:

- `generation_accuracy` means Jason produced a DRB-formatted article for each selected task.
- `official_scores.race.overall_score` is the external RACE report-quality score.
- A high Jason internal score with a low RACE score means the current internal evaluator is too narrow for general deep research tasks.

## Run With Agents SDK

The API-backed path uses `OPENAI_API_KEY` from the environment or `.env.local`:

```bash
cd jason
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..
PYTHONPATH=. python -m jason.main --repo jason/truth_repo/sdk-demo
```

## What To Demo

Open `jason/truth_repo/<run>/events.jsonl` and show:

```text
eval_completed
parent_decision
task_created
agent_run_completed
evidence_added
eval_completed
```

That trace is the core claim: the system chooses work from measured research state, not from a fixed pipeline.
