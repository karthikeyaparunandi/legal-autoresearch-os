# LegalBench benchmarking harness

Drive AutoResearch OS (and a direct-model baseline) over [LegalBench](https://huggingface.co/datasets/nguha/legalbench)
tasks and score them. Dependency-free data download (HF datasets-server JSON API);
runs use the project's OpenAI Agents SDK reasoner.

## Setup

```bash
# from repo root
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"        # installs the package + openai-agents

# your OWN OpenAI key (this file is gitignored — never commit it)
echo 'OPENAI_API_KEY=sk-...your key...' > .env.local
```

The runtime/baseline default to model `gpt-5-mini`; override with `--model` (e.g.
`gpt-5.5`, `gpt-5`). Confirm your key can call the model you pick.

## 1. Download task data (label-balanced sample)

```bash
# a 10-example balanced sample per task (the original 4-task mix)
PYTHONPATH=src .venv/bin/python scripts/legalbench/download.py --per-task 10

# or the full hearsay test set (94 items)
PYTHONPATH=src .venv/bin/python scripts/legalbench/download.py --only hearsay --per-task 94
```

Saves to `legalbench_data/<config>.json` (gitignored).

## 2a. Single-shot benchmark (no research — one model call per question)

Fast; this is the clean "model, no agent" number.

```bash
PYTHONPATH=src .venv/bin/python scripts/legalbench/single_shot.py \
    --task hearsay --model gpt-5.5 --concurrency 24
```
→ `legalbench_runs/single_shot/summary_<task>.json` + `findings_<task>.md`

## 2b. With-research comparison (AutoResearch OS vs direct baseline)

Runs BOTH conditions per item and scores them head-to-head. The agent makes
several sequential model calls per item, so it is much slower/costlier than 2a —
keep `--feedback-rounds`/`--max-iterations` low and use `--limit` to sample.

```bash
PYTHONPATH=src .venv/bin/python scripts/legalbench/compare_hearsay.py \
    --task hearsay --model gpt-5.5 --concurrency 24 \
    --max-iterations 1 --feedback-rounds 1 --limit 30
```
→ `legalbench_runs/compare/summary_<task>.json` + `findings_<task>.md`

## 3. Consolidated final report

```bash
PYTHONPATH=src .venv/bin/python scripts/legalbench/final_report.py --task hearsay
```
→ prints + writes `legalbench_runs/FINAL_REPORT_<task>.md` (no-research vs with-research, Δ, agreement, cost).

## Files

| File | Role |
|------|------|
| `tasks.py` | Task registry: labels, goal/seed templates per LegalBench task |
| `download.py` | Balanced sampler via HF datasets-server (no `datasets` lib) |
| `single_shot.py` | One model call per question → label (no-research benchmark) |
| `compare_hearsay.py` | AutoResearch OS + adapter vs direct baseline, paired per item |
| `run_benchmark.py` | Full-agent run over the 4-task mix (adapter scoring) |
| `final_report.py` | Merge single-shot + compare summaries into one report |

## Notes

- `legalbench_data/` and `legalbench_runs/` are gitignored (data + outputs).
- The agent's internal `overall_confidence` reads ~0 here by design: it's a
  citation/primary-authority grounding score, and these runs are offline with a
  single seed snippet — so the **adapter** produces the label from the agent's
  report. Judge by accuracy, not that confidence number.
- Findings so far (GPT-5.5, hearsay): no-research single-shot ≈ 0.81; with-research
  agrees ~97% of the time → ~no accuracy gain for ~20× the cost.
