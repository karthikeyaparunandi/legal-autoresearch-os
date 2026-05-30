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

import json

try:
    import modal
except ImportError:  # Keeps the local repo dependency-free.
    modal = None


if modal:
    app = modal.App("autoresearch-os")
    image = (
        modal.Image.debian_slim(python_version="3.12")
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
