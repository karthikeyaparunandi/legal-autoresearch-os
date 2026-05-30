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
