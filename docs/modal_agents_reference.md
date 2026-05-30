# Modal Agents Reference

AutoResearch OS uses the same high-level scaling idea as `modal-labs/openai-agents-python-example`: keep one orchestrator in charge of the research state, then fan out bounded worker jobs on Modal.

## Reference Pattern

The Modal example is a general-purpose coding-agent harness with:

- an orchestrator agent that owns the user interaction and session memory
- subagents exposed as tools
- a subagent pool that runs workers concurrently
- Modal-backed sandboxes for isolated long-running work
- skills that give workers domain-specific guidance

## AutoResearch OS Adaptation

AutoResearch OS applies that pattern to legal research:

- `ResearchRuntime` is the orchestrator. It owns `program.md`, task planning, truth-maintenance state, evaluation, tuning, and reporting.
- `hypothesis_agent`, `critic_agent`, and `knowledge_agent_pool` are the local role agents. They have explicit goals, tools, loop steps, traces, and OpenAI Agents SDK reasoning calls.
- `modal_hypothesis_agent_pool` is the distributed Modal agent pool. It runs one remote worker per hypothesis.
- `modal/app.py` is the Modal worker layer. A worker retrieves evidence, synthesizes a claim, critiques that claim, runs an OpenAI Agents SDK reasoning pass, and returns a scored bundle for one hypothesis.
- `src/autoresearch_os/modal_bridge.py` is the local pool bridge. It dispatches hypothesis payloads to Modal concurrently with `evaluate_hypothesis_agent.map(...)`.
- `legal_metadata.json` and `tuning_params.json` play the role of domain-specific operating context for the workers.

## Why This Is Fast

Live source retrieval and per-hypothesis critique are often the slowest parts of a research run. Without Modal, the local runtime walks through the role modules in process. With `--modal`, the hypothesis set is fanned out across Modal workers:

```text
ResearchRuntime
-> Hypothesis Set
-> Modal Bridge
-> evaluate_hypothesis_agent(h001)
-> evaluate_hypothesis_agent(h002)
-> evaluate_hypothesis_agent(h003)
-> evaluate_hypothesis_agent(h004)
-> merged Evidence[] + Claims[] + Contradictions[]
-> Truth Maintenance Repo
```

This keeps the central control loop local and deterministic while moving bounded research-agent work into parallel cloud functions.

## Current Scope

The current integration uses OpenAI Agents SDK agents for role reasoning and Modal functions for distributed hypothesis workers. The next natural extension is to give selected SDK agents Modal sandbox sessions for longer-lived legal research experiments.
