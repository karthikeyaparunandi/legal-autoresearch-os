from __future__ import annotations

from dataclasses import asdict
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .models import Claim, Contradiction, Evidence, Hypothesis, Task, TuningParams
from .retrieval import RetrievalStats


class ModalIntegrationError(RuntimeError):
    pass


def evaluate_hypotheses_with_modal(
    tasks: list[Task],
    hypotheses: list[Hypothesis],
    seed_texts: list[str],
    live_retrieval: bool,
    source_urls: list[str],
    tuning_params: TuningParams,
    api_key: str | None = None,
    llm_model: str | None = None,
) -> tuple[list[Evidence], list[Claim], list[Contradiction], list[str], dict]:
    modal_app = _load_modal_app()
    if not getattr(modal_app, "modal", None):
        raise ModalIntegrationError("Install Modal with `pip install modal`, then run again with --modal.")

    payloads = [
        {
            "tasks": [asdict(task) for task in tasks],
            "hypothesis": asdict(hypothesis),
            "seed_texts": seed_texts,
            "live_retrieval": live_retrieval,
            "source_urls": source_urls,
            "tuning_params": asdict(tuning_params),
            "api_key": api_key,
            "llm_model": llm_model,
        }
        for hypothesis in hypotheses
    ]
    try:
        with modal_app.app.run():
            results = list(modal_app.evaluate_hypothesis_agent.map(payloads, order_outputs=False, return_exceptions=True))
    except Exception as exc:
        raise ModalIntegrationError(f"Modal hypothesis agents failed: {exc}") from exc

    evidence: list[Evidence] = []
    claims: list[Claim] = []
    contradictions: list[Contradiction] = []
    criticisms: list[str] = []
    retrieval_metrics = _empty_retrieval_metrics(live_retrieval, modal_enabled=True)

    evidence_index = 1
    for result in results:
        if isinstance(result, Exception):
            retrieval_metrics["failed_urls"] += 1
            retrieval_metrics["errors"][f"modal_hypothesis_exception_{retrieval_metrics['failed_urls']}"] = result.__class__.__name__
            continue
        if not isinstance(result, dict):
            retrieval_metrics["errors"][f"modal_hypothesis_result_{len(retrieval_metrics['errors']) + 1}"] = "invalid_result"
            continue
        if result.get("status") != "ok":
            retrieval_metrics["errors"][str(result.get("hypothesis_id", "unknown_hypothesis"))] = str(result.get("error", "unknown_error"))
            continue

        id_map: dict[str, str] = {}
        for item in result.get("evidence", []):
            old_id = item["source_id"]
            new_id = f"source_{evidence_index:03d}"
            evidence_index += 1
            id_map[old_id] = new_id
            evidence.append(
                Evidence(
                    source_id=new_id,
                    title=item["title"],
                    url=item["url"],
                    source_type=item["source_type"],
                    excerpt=item["excerpt"],
                    supports=item.get("supports", []),
                    contradicts=item.get("contradicts", []),
                    reliability=item.get("reliability", 0.7),
                )
            )

        for item in result.get("claims", []):
            claims.append(
                Claim(
                    claim_id=f"c{len(claims) + 1:03d}",
                    claim=item["claim"],
                    supporting_sources=[id_map.get(source_id, source_id) for source_id in item.get("supporting_sources", [])],
                    contradicting_sources=[id_map.get(source_id, source_id) for source_id in item.get("contradicting_sources", [])],
                    confidence=item.get("confidence", 0.0),
                    status=item.get("status", "untested"),
                    objective_refs=item.get("objective_refs", []),
                )
            )

        for item in result.get("contradictions", []):
            contradictions.append(
                Contradiction(
                    claim=item["claim"],
                    supporting_sources=[id_map.get(source_id, source_id) for source_id in item.get("supporting_sources", [])],
                    contradicting_sources=[id_map.get(source_id, source_id) for source_id in item.get("contradicting_sources", [])],
                    resolution_status=item.get("resolution_status", "unresolved"),
                    note=item.get("note", ""),
                )
            )
        criticisms.extend(result.get("criticisms", []))
        if result.get("used_llm"):
            retrieval_metrics["modal_agent_llm_calls"] = int(retrieval_metrics.get("modal_agent_llm_calls", 0)) + 1
            retrieval_metrics["modal_agent_llm_model"] = result.get("llm_model")
        _merge_retrieval_metrics(retrieval_metrics, result.get("retrieval_metrics", {}))

    return evidence, claims, contradictions, criticisms, retrieval_metrics


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
        if result.get("status") == "blocked":
            url = str(result.get("url", "unknown_url"))
            stats.failed_urls += 1
            if stats.blocked_urls is None:
                stats.blocked_urls = []
            if stats.block_reasons is None:
                stats.block_reasons = {}
            if stats.errors is None:
                stats.errors = {}
            stats.blocked_urls.append(url)
            stats.block_reasons[url] = str(result.get("error", "blocked_source"))
            stats.errors[url] = str(result.get("error", "blocked_source"))
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


def _empty_retrieval_metrics(live_retrieval: bool, modal_enabled: bool) -> dict:
    return {
        "enabled": live_retrieval,
        "modal_enabled": modal_enabled,
        "attempted_urls": 0,
        "successful_urls": 0,
        "failed_urls": 0,
        "retrieved_urls": [],
        "errors": {},
        "fallback_used": False,
        "modal_hypothesis_agents": True,
        "modal_agent_llm_calls": 0,
        "modal_agent_llm_model": None,
    }


def _merge_retrieval_metrics(target: dict, source: dict) -> None:
    target["attempted_urls"] += int(source.get("attempted_urls", 0))
    target["successful_urls"] += int(source.get("successful_urls", 0))
    target["failed_urls"] += int(source.get("failed_urls", 0))
    target["fallback_used"] = bool(target.get("fallback_used") or source.get("fallback_used"))
    for url in source.get("retrieved_urls", []):
        if url not in target["retrieved_urls"]:
            target["retrieved_urls"].append(url)
    target["errors"].update(source.get("errors", {}))



def _load_modal_app():
    repo_root = Path(__file__).resolve().parents[2]
    modal_app_path = repo_root / "modal" / "app.py"
    spec = spec_from_file_location("autoresearch_modal_app", modal_app_path)
    if spec is None or spec.loader is None:
        raise ModalIntegrationError(f"Could not load Modal app from {modal_app_path}.")
    module = module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ModalIntegrationError(f"Could not initialize Modal app: {exc}") from exc
    return module
