from __future__ import annotations

from dataclasses import asdict
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .models import Evidence, Hypothesis, Task
from .retrieval import RetrievalStats


class ModalIntegrationError(RuntimeError):
    pass


def retrieve_live_evidence_with_modal(
    urls: list[str],
    tasks: list[Task],
    hypotheses: list[Hypothesis],
    start_index: int,
    timeout_seconds: float,
) -> tuple[list[Evidence], RetrievalStats]:
    modal_app = _load_modal_app()
    if not getattr(modal_app, "modal", None):
        raise ModalIntegrationError("Install Modal with `pip install modal`, then run again with --modal.")

    payloads = [
        {
            "url": url,
            "source_id": f"source_{start_index + index:03d}",
            "tasks": [asdict(task) for task in tasks],
            "hypotheses": [asdict(hypothesis) for hypothesis in hypotheses],
            "timeout_seconds": timeout_seconds,
        }
        for index, url in enumerate(urls)
    ]
    stats = RetrievalStats(attempted_urls=len(payloads), retrieved_urls=[], errors={})
    evidence: list[Evidence] = []

    try:
        with modal_app.app.run():
            results = list(modal_app.collect_url_evidence.map(payloads, order_outputs=False, return_exceptions=True))
    except Exception as exc:
        raise ModalIntegrationError(f"Modal retrieval failed: {exc}") from exc

    for result in results:
        if isinstance(result, Exception):
            stats.failed_urls += 1
            stats.errors[f"modal_exception_{stats.failed_urls}"] = result.__class__.__name__
            continue
        if not isinstance(result, dict):
            stats.failed_urls += 1
            stats.errors[f"modal_result_{stats.failed_urls}"] = "invalid_result"
            continue
        if result.get("status") != "ok":
            stats.failed_urls += 1
            stats.errors[str(result.get("url", "unknown_url"))] = str(result.get("error", "unknown_error"))
            continue
        stats.successful_urls += 1
        stats.retrieved_urls.append(result["url"])
        evidence.append(
            Evidence(
                source_id=result["source_id"],
                title=result["title"],
                url=result["url"],
                source_type=result["source_type"],
                excerpt=result["excerpt"],
                supports=result["supports"],
                contradicts=result["contradicts"],
                reliability=result["reliability"],
            )
        )

    evidence.sort(key=lambda item: item.source_id)
    return evidence, stats


def _load_modal_app():
    repo_root = Path(__file__).resolve().parents[2]
    modal_app_path = repo_root / "modal" / "app.py"
    spec = spec_from_file_location("autoresearch_modal_app", modal_app_path)
    if spec is None or spec.loader is None:
        raise ModalIntegrationError(f"Could not load Modal app from {modal_app_path}.")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
