from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
import os
import time


class RaindropConfigurationError(RuntimeError):
    pass


class RaindropTracer:
    def __init__(self, enabled: bool = False, workspace: Path | None = None) -> None:
        self.enabled = enabled
        self.model_name = "none"
        self._raindrop = None
        self._interaction = None
        self._workspace = workspace
        if enabled:
            self._init_sdk()

    def _init_sdk(self) -> None:
        try:
            import raindrop.analytics as raindrop
        except ImportError as exc:
            raise RaindropConfigurationError(
                "Install Raindrop tracing with `pip install -e \".[raindrop]\"`, then run with --raindrop."
            ) from exc

        write_key = os.environ.get("RAINDROP_WRITE_KEY")
        local_debugger = os.environ.get("RAINDROP_LOCAL_DEBUGGER")
        if not write_key and not local_debugger:
            raise RaindropConfigurationError(
                "Run `raindrop workshop setup` or set RAINDROP_WRITE_KEY before using --raindrop."
            )

        local_workshop_url = local_debugger or None
        endpoint = local_workshop_url if local_workshop_url else None
        # In local Workshop mode the SDK needs tracing enabled for tool spans, but the
        # normal OTEL exporter targets the cloud path. Direct tool spans keep the demo
        # self-contained and mirror the phase spans to the local daemon.
        raindrop.init(
            write_key or "local-workshop",
            tracing_enabled=True,
            auto_instrument=False,
            bypass_otel_for_tools=bool(local_workshop_url),
            endpoint=endpoint,
            local_workshop_url=local_workshop_url,
        )
        self._raindrop = raindrop
        self.model_name = "raindrop-workshop" if local_debugger else "raindrop-cloud"

    def begin_run(self, goal: str, properties: dict[str, Any]) -> None:
        if not self.enabled or not self._raindrop:
            return
        self._interaction = self._raindrop.begin(
            user_id="local-autoresearch",
            event="autoresearch_run",
            input=goal,
            properties=properties,
        )

    @contextmanager
    def span(
        self,
        name: str,
        input_data: Any | None = None,
        properties: dict[str, Any] | None = None,
    ) -> Iterator["RaindropSpan"]:
        span = RaindropSpan(self, name, input_data=input_data, properties=properties or {})
        try:
            yield span
        except Exception as exc:
            span.finish(error=exc)
            raise
        else:
            span.finish()

    def finish_run(self, output: str, properties: dict[str, Any] | None = None) -> None:
        if not self.enabled or not self._raindrop or not self._interaction:
            return
        self._interaction.finish(output=output, properties=properties or {})
        self._raindrop.flush()
        self._raindrop.shutdown()

    def track_tool(
        self,
        name: str,
        input_data: Any,
        output_data: Any,
        duration_ms: float,
        properties: dict[str, Any],
        error: BaseException | str | None = None,
    ) -> None:
        if not self.enabled or not self._interaction:
            return
        self._interaction.track_tool(
            name=name,
            input=input_data,
            output=output_data,
            duration_ms=round(duration_ms, 3),
            properties=properties,
            error=error,
        )


class RaindropSpan:
    def __init__(
        self,
        tracer: RaindropTracer,
        name: str,
        input_data: Any | None,
        properties: dict[str, Any],
    ) -> None:
        self._tracer = tracer
        self._name = name
        self._input = input_data
        self._properties = properties
        self._output: Any = None
        self._started_at = time.perf_counter()
        self._finished = False

    def record_output(self, output_data: Any) -> None:
        self._output = output_data

    def set_properties(self, properties: dict[str, Any]) -> None:
        self._properties.update(properties)

    def finish(self, error: BaseException | str | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        duration_ms = (time.perf_counter() - self._started_at) * 1000
        self._tracer.track_tool(
            name=self._name,
            input_data=self._input,
            output_data=self._output,
            duration_ms=duration_ms,
            properties=self._properties,
            error=error,
        )
