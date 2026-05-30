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
- `hypothesis_agent`, `critic_agent`, and `knowledge_agent_pool` are the role agents. They have explicit goals, tools, loop steps, traces, and OpenAI Agents SDK reasoning calls.
- `modal/app.py` is the Modal worker layer. It fetches one legal source URL per remote function call and converts it into a structured evidence record.
- `src/autoresearch_os/modal_bridge.py` is the local pool bridge. It dispatches source payloads to Modal concurrently with `collect_url_evidence.map(...)`.
- `legal_metadata.json` and `tuning_params.json` play the role of domain-specific operating context for the workers.

## Why This Is Fast

Live source retrieval is often the slowest part of a research run. Without Modal, URLs are fetched sequentially in the local process. With `--modal`, the retrieval queue is fanned out across Modal workers:

```text
ResearchRuntime
-> Knowledge Agent Pool
-> Modal Bridge
-> collect_url_evidence(url_1)
-> collect_url_evidence(url_2)
-> collect_url_evidence(url_3)
-> merged Evidence[]
-> Truth Maintenance Repo
```

This keeps the central control loop local and deterministic while moving high-latency retrieval work into parallel cloud functions.

## Current Scope

The current integration uses OpenAI Agents SDK agents for role reasoning and Modal functions for evidence retrieval. The next natural extension is to give selected SDK agents Modal sandbox sessions for longer-lived legal research experiments.
