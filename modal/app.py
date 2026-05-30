"""Modal acceleration for AutoResearch OS live retrieval.

Install and authenticate Modal separately:

    pip install modal
    modal setup

Use it from the main CLI:

    autoresearch demo --modal --out demo_gt_repo

Or smoke-test the remote retrieval function directly:

    modal run modal/app.py
"""

from __future__ import annotations

from dataclasses import asdict
import json

try:
    import modal
except ImportError:  # Keeps the local repo dependency-free.
    modal = None


if modal:
    app = modal.App("autoresearch-os")
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("openai-agents>=0.3.0")
        .env({"PYTHONPATH": "/root"})
        .add_local_dir("src/autoresearch_os", "/root/autoresearch_os")
    )

    @app.function(image=image, timeout=45)
    def collect_url_evidence(payload: dict) -> dict:
        from urllib.error import HTTPError, URLError

        from autoresearch_os.models import Hypothesis, Task
        from autoresearch_os.retrieval import (
            _best_excerpt,
            _classify_source,
            detect_blocked_source,
            _infer_contradictions,
            _infer_supports,
            _source_reliability,
            fetch_url_text,
        )

        url = payload["url"]
        try:
            tasks = [Task(**task) for task in payload["tasks"]]
            hypotheses = [Hypothesis(**hypothesis) for hypothesis in payload["hypotheses"]]
            task_text = " ".join(task.question for task in tasks)
            title, text = fetch_url_text(url, timeout_seconds=payload.get("timeout_seconds", 8.0))
            if not text:
                return {"status": "error", "url": url, "error": "empty_response"}
            block_reason = detect_blocked_source(text)
            if block_reason:
                return {"status": "blocked", "url": url, "error": block_reason}
            return {
                "status": "ok",
                "source_id": payload["source_id"],
                "title": title,
                "url": url,
                "source_type": _classify_source(url, text),
                "excerpt": _best_excerpt(text, task_text),
                "supports": _infer_supports(url, text, hypotheses),
                "contradicts": _infer_contradictions(url, text, hypotheses),
                "reliability": _source_reliability(url),
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            return {"status": "error", "url": url, "error": exc.__class__.__name__}

    @app.function(image=image, timeout=90)
    def evaluate_hypothesis_agent(payload: dict) -> dict:
        from autoresearch_os.critic import critique_claims
        from autoresearch_os.knowledge import claims_from_hypotheses, collect_evidence
        from autoresearch_os.llm import CentralReasoner
        from autoresearch_os.models import Hypothesis, Task, TuningParams

        hypothesis = Hypothesis(**payload["hypothesis"])
        tasks = [Task(**task) for task in payload["tasks"]]
        params = TuningParams(**payload.get("tuning_params", {}))
        try:
            evidence, retrieval_metrics = collect_evidence(
                tasks,
                [hypothesis],
                seed_texts=payload.get("seed_texts", []),
                live_retrieval=payload.get("live_retrieval", True),
                source_urls=payload.get("source_urls", []),
                use_modal=False,
            )
            claims = claims_from_hypotheses([hypothesis], evidence, params)
            contradictions, criticisms = critique_claims(claims)
            reasoner = CentralReasoner(
                model=payload.get("llm_model"),
                api_key=payload.get("api_key"),
                required=False,
            )
            reasoning = reasoner.reason_json(
                "modal_hypothesis_agent",
                (
                    "Review this single-hypothesis legal research bundle. Return "
                    "{\"criticisms\":[\"...\"],\"notes\":[\"...\"]}. Keep it concise."
                ),
                {
                    "learned_skills": payload.get("agent_skills", []),
                    "hypothesis": asdict(hypothesis),
                    "evidence": [asdict(item) for item in evidence[:8]],
                    "claims": [asdict(item) for item in claims],
                    "contradictions": [asdict(item) for item in contradictions],
                    "baseline_criticisms": criticisms,
                },
            )
            if reasoning and isinstance(reasoning.get("criticisms"), list):
                criticisms = [*criticisms, *[str(item) for item in reasoning["criticisms"][:3]]]
            return {
                "status": "ok",
                "hypothesis_id": hypothesis.hypothesis_id,
                "evidence": [asdict(item) for item in evidence],
                "claims": [asdict(item) for item in claims],
                "contradictions": [asdict(item) for item in contradictions],
                "criticisms": criticisms,
                "retrieval_metrics": retrieval_metrics,
                "used_llm": bool(reasoning),
                "llm_model": reasoner.model if reasoning else None,
            }
        except Exception as exc:
            return {
                "status": "error",
                "hypothesis_id": hypothesis.hypothesis_id,
                "error": exc.__class__.__name__,
            }

    @app.local_entrypoint()
    def main(url: str = "https://www.law.cornell.edu/uscode/text/17/102"):
        payload = {
            "url": url,
            "source_id": "source_001",
            "tasks": [
                {
                    "task_id": "t001",
                    "title": "Smoke test legal retrieval",
                    "question": "Can AI-generated code be copyrighted in the United States?",
                    "depends_on": [],
                    "status": "pending",
                }
            ],
            "hypotheses": [
                {
                    "hypothesis_id": "h001",
                    "statement": "Pure AI-generated code faces copyright authorship risk.",
                    "rationale": "U.S. copyright law requires authorship.",
                    "status": "open",
                }
            ],
            "timeout_seconds": 8.0,
        }
        print(json.dumps(collect_url_evidence.remote(payload), indent=2))
else:
    app = None
