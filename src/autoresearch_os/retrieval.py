from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import re

from .models import Evidence, Hypothesis, Task


DEFAULT_LEGAL_SOURCE_URLS = [
    "https://www.federalregister.gov/documents/2023/03/16/2023-05321/copyright-registration-guidance-works-containing-material-generated-by-artificial-intelligence",
    "https://www.copyright.gov/ai/",
    "https://www.law.cornell.edu/uscode/text/17/102",
]


@dataclass
class RetrievalStats:
    attempted_urls: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    blocked_urls: list[str] | None = None
    block_reasons: dict[str, str] | None = None
    retrieved_urls: list[str] | None = None
    errors: dict[str, str] | None = None

    def as_dict(self) -> dict:
        return {
            "attempted_urls": self.attempted_urls,
            "successful_urls": self.successful_urls,
            "failed_urls": self.failed_urls,
            "blocked_sources": len(self.blocked_urls or []),
            "blocked_urls": self.blocked_urls or [],
            "block_reasons": self.block_reasons or {},
            "retrieved_urls": self.retrieved_urls or [],
            "errors": self.errors or {},
        }


def retrieve_live_evidence(
    tasks: list[Task],
    hypotheses: list[Hypothesis],
    source_urls: Iterable[str] = (),
    start_index: int = 1,
    timeout_seconds: float = 8.0,
    use_modal: bool = False,
) -> tuple[list[Evidence], RetrievalStats]:
    urls = list(dict.fromkeys([*DEFAULT_LEGAL_SOURCE_URLS, *source_urls]))
    if use_modal:
        from .modal_bridge import retrieve_live_evidence_with_modal

        return retrieve_live_evidence_with_modal(urls, tasks, hypotheses, start_index, timeout_seconds)

    stats = RetrievalStats(attempted_urls=len(urls), blocked_urls=[], block_reasons={}, retrieved_urls=[], errors={})
    evidence: list[Evidence] = []
    task_text = " ".join(task.question for task in tasks)

    for url in urls:
        try:
            title, text = fetch_url_text(url, timeout_seconds=timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            stats.failed_urls += 1
            stats.errors[url] = exc.__class__.__name__
            continue

        if not text:
            stats.failed_urls += 1
            stats.errors[url] = "empty_response"
            continue
        block_reason = detect_blocked_source(text)
        if block_reason:
            stats.failed_urls += 1
            stats.blocked_urls.append(url)
            stats.block_reasons[url] = block_reason
            stats.errors[url] = block_reason
            continue
        if _is_low_signal_retrieval(text):
            stats.failed_urls += 1
            stats.errors[url] = "low_signal_response"
            continue

        stats.successful_urls += 1
        stats.retrieved_urls.append(url)
        source_id = f"source_{start_index + len(evidence):03d}"
        evidence.append(
            Evidence(
                source_id=source_id,
                title=title or _fallback_title(url),
                url=url,
                source_type=_classify_source(url, text),
                excerpt=_best_excerpt(text, task_text),
                supports=_infer_supports(url, text, hypotheses),
                contradicts=_infer_contradictions(url, text, hypotheses),
                reliability=_source_reliability(url),
            )
        )

    return evidence, stats


def fetch_url_text(url: str, timeout_seconds: float = 8.0) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "AutoResearchOS/0.1 legal research prototype",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(1_500_000)
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return _fallback_title(url), "PDF source retrieved. Text extraction is not available in the dependency-free prototype."
    decoded = raw.decode("utf-8", errors="replace")
    parser = _TextExtractor()
    parser.feed(decoded)
    text = _normalize(parser.text())
    title = _normalize(parser.title) or _fallback_title(url)
    return title, text


def detect_blocked_source(text: str) -> str | None:
    lower = _normalize(text).lower()
    blocked_patterns = {
        "captcha_detected": [
            "captcha",
            "recaptcha",
            "hcaptcha",
            "verify you are human",
            "prove you are human",
            "human verification",
            "security check",
        ],
        "access_denied": [
            "access denied",
            "request blocked",
            "you have been blocked",
            "temporarily blocked",
            "forbidden",
            "403 forbidden",
        ],
        "login_required": [
            "sign in to continue",
            "log in to continue",
            "login required",
            "authentication required",
        ],
    }
    for reason, patterns in blocked_patterns.items():
        if any(pattern in lower for pattern in patterns):
            return reason
    return None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(self._parts)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fallback_title(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    return slug.replace("-", " ").replace("_", " ").title()


def _classify_source(url: str, text: str) -> str:
    host = urlparse(url).netloc.lower()
    lower = f"{url} {text[:1000]}".lower()
    if "law.cornell.edu/uscode" in lower or "/uscode/" in lower:
        return "statute"
    if "federalregister.gov" in host or "copyright.gov" in host:
        return "agency_guidance"
    if "court" in lower or "v." in lower or "opinion" in lower:
        return "case_law"
    if "edu" in host:
        return "academic"
    return "web_source"


def _source_reliability(url: str) -> float:
    host = urlparse(url).netloc.lower()
    if "law.cornell.edu" in host:
        return 0.92
    if "copyright.gov" in host or "federalregister.gov" in host:
        return 0.95
    if host.endswith(".gov"):
        return 0.9
    if host.endswith(".edu"):
        return 0.8
    return 0.65


def _best_excerpt(text: str, task_text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    keywords = [word for word in re.findall(r"[a-zA-Z]{5,}", task_text.lower()) if word not in {"which", "would", "could"}]
    for sentence in sentences:
        if _is_low_signal_sentence(sentence):
            continue
        lower = sentence.lower()
        if any(keyword in lower for keyword in ["authorship", "copyright", "artificial intelligence", "generated"]):
            return sentence[:550]
        if keywords and sum(1 for keyword in keywords if keyword in lower) >= 2:
            return sentence[:550]
    return text[:550]


def _infer_supports(url: str, text: str, hypotheses: list[Hypothesis]) -> list[str]:
    lower = f"{url} {text}".lower()
    supports: set[str] = set()
    for hypothesis in hypotheses:
        statement = hypothesis.statement.lower()
        if "pure ai-generated" in statement and any(term in lower for term in ["human authorship", "copyright office", "authorship"]):
            supports.add(hypothesis.hypothesis_id)
        if "ai-assisted" in statement and any(term in lower for term in ["human", "selection", "arrangement", "authorship"]):
            supports.add(hypothesis.hypothesis_id)
        if "prompting" in statement and any(term in lower for term in ["prompt", "human", "authorship", "generated"]):
            supports.add(hypothesis.hypothesis_id)
        if "startups" in statement and any(term in lower for term in ["license", "risk", "infringement", "software"]):
            supports.add(hypothesis.hypothesis_id)
    if not supports and hypotheses:
        supports.add(hypotheses[0].hypothesis_id)
    return sorted(supports)


def _infer_contradictions(url: str, text: str, hypotheses: list[Hypothesis]) -> list[str]:
    lower = f"{url} {text}".lower()
    contradicts: set[str] = set()
    if any(term in lower for term in ["ai-generated works are copyrightable without human authorship", "non-human author can own copyright"]):
        for hypothesis in hypotheses:
            if "pure ai-generated" in hypothesis.statement.lower():
                contradicts.add(hypothesis.hypothesis_id)
    return sorted(contradicts)


def _is_low_signal_retrieval(text: str) -> bool:
    lower = text[:1200].lower()
    return any(
        marker in lower
        for marker in [
            "please complete the captcha",
            "request access",
            "enable javascript",
            "access denied",
        ]
    )


def _is_low_signal_sentence(sentence: str) -> bool:
    cleaned = sentence.strip()
    if len(cleaned) < 40:
        return True
    lower = cleaned.lower()
    return lower in {"support us!", "main content", "navigation"} or "skip to" in lower
