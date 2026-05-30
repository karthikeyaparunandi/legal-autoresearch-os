"""Modal sketch for scaling the evidence agent pool.

Install Modal separately and adapt this file when deploying the knowledge agents:

    pip install modal
    modal run modal/app.py
"""

from __future__ import annotations

try:
    import modal
except ImportError:  # Keeps the local repo dependency-free.
    modal = None


if modal:
    app = modal.App("autoresearch-os")
    image = modal.Image.debian_slim().pip_install("httpx")

    @app.function(image=image)
    def collect_source(task: dict, source_kind: str) -> dict:
        return {
            "task_id": task["task_id"],
            "source_kind": source_kind,
            "status": "placeholder",
            "note": "Replace with web, legal, academic, or company-intelligence retrieval.",
        }
