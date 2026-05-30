from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
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
        self.api_key = api_key or _load_api_key(workspace)
        self.required = required

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def reason_json(self, agent_name: str, instruction: str, payload: dict, timeout_seconds: float = 30.0) -> dict | None:
        if not self.api_key:
            if self.required:
                raise LLMConfigurationError("Set OPENAI_API_KEY or OPEN_API_KEY, or omit --with-llm.")
            return None
        prompt = (
            "Return only valid JSON. Do not include markdown.\n\n"
            f"Agent: {agent_name}\n"
            f"Instruction: {instruction}\n\n"
            f"Payload:\n{json.dumps(payload, indent=2)}"
        )
        body = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are the central reasoning model for AutoResearch OS, a legal research "
                        "control system. Reason carefully, prefer primary authority, identify uncertainty, "
                        "and output compact JSON that the runtime can consume."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "text": {"format": {"type": "json_object"}},
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if self.required:
                message = exc.read().decode("utf-8", errors="replace")[:500]
                raise LLMReasoningError(f"OpenAI reasoning call failed with HTTP {exc.code}: {message}") from exc
            return None
        except (URLError, TimeoutError, OSError) as exc:
            if self.required:
                raise LLMReasoningError(f"OpenAI reasoning call failed: {exc}") from exc
            return None
        try:
            data = json.loads(raw)
            text = _extract_response_text(data)
            return json.loads(text) if text else None
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            if self.required:
                raise LLMReasoningError("OpenAI reasoning response was not valid JSON.") from exc
            return None


def _load_api_key(workspace: Path | None = None) -> str | None:
    for name in API_KEY_ENV_VARS:
        if os.environ.get(name):
            return os.environ[name]
    candidates = []
    if workspace:
        candidates.extend([workspace / ".env.local", workspace / ".env"])
    candidates.extend([Path(".env.local"), Path(".env")])
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not any(line.startswith(f"{name}=") for name in API_KEY_ENV_VARS):
                continue
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def _extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts)
