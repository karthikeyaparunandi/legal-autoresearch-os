from __future__ import annotations

from pathlib import Path
import json
import os


DEFAULT_REASONING_MODEL = "gpt-5-mini"
API_KEY_ENV_VARS = ("OPENAI_API_KEY", "OPEN_API_KEY")


class LLMConfigurationError(RuntimeError):
    pass


class LLMReasoningError(RuntimeError):
    pass


class CentralReasoner:
    """Optional central LLM used by all research agents for reasoning."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        workspace: Path | None = None,
        required: bool = False,
    ) -> None:
        self.model = model or os.environ.get("AUTORESEARCH_MODEL", DEFAULT_REASONING_MODEL)
        self.api_key = _load_api_key(workspace) if api_key is None else api_key
        self.required = required

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def reason_json(self, agent_name: str, instruction: str, payload: dict, timeout_seconds: float = 30.0) -> dict | None:
        if not self.api_key:
            if self.required:
                raise LLMConfigurationError("Set OPENAI_API_KEY or OPEN_API_KEY, or run with --no-llm.")
            return None
        try:
            text = self._run_agents_sdk(agent_name, instruction, payload, timeout_seconds)
            return json.loads(text) if text else None
        except (ImportError, RuntimeError, json.JSONDecodeError, TypeError) as exc:
            if self.required:
                raise LLMReasoningError(f"OpenAI Agents SDK reasoning failed: {exc}") from exc
            return None

    def _run_agents_sdk(self, agent_name: str, instruction: str, payload: dict, timeout_seconds: float) -> str:
        try:
            from agents import Agent, Runner
        except ImportError as exc:
            raise ImportError("Install the OpenAI Agents SDK with `pip install -e .` or `pip install openai-agents`.") from exc

        if self.api_key:
            os.environ["OPENAI_API_KEY"] = self.api_key
        prompt = (
            "Return only valid JSON. Do not include markdown.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Payload:\n{json.dumps(payload, indent=2)}"
        )
        agent = Agent(
            name=agent_name,
            model=self.model,
            instructions=(
                "You are an OpenAI Agents SDK role agent inside Legal AutoResearch OS, a legal "
                "research control system. Reason carefully, prefer primary authority, "
                "identify uncertainty, and output compact JSON that the runtime can consume."
            ),
        )
        result = Runner.run_sync(agent, prompt, max_turns=1)
        output = getattr(result, "final_output", result)
        if not isinstance(output, str):
            output = str(output)
        return output.strip()


def _load_api_key(workspace: Path | None = None) -> str | None:
    for name in API_KEY_ENV_VARS:
        if os.environ.get(name):
            return os.environ[name]
    if workspace:
        candidates = [workspace / ".env.local", workspace / ".env"]
    else:
        candidates = [Path(".env.local"), Path(".env")]
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not any(line.startswith(f"{name}=") for name in API_KEY_ENV_VARS):
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None
