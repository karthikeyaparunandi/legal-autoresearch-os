from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
import re

from .models import Evidence, Hypothesis, Task


DEFAULT_LEGAL_SOURCE_URLS = [
    "https://www.federalregister.gov/documents/2023/03/16/2023-05321/copyright-registration-guidance-works-containing-material-generated-by-artificial-intelligence",
    "https://www.copyright.gov/ai/",
    "https://www.law.cornell.edu/uscode/text/17/102",
]

_FETCH_CACHE: dict[str, tuple[str, str]] = {}
_BAD_URL_CACHE: dict[str, str] = {}
_SEARCH_CACHE: dict[str, list[str]] = {}


@dataclass
class RetrievalStats:
    attempted_urls: int = 0
    successful_urls: int = 0
    failed_urls: int = 0
    blocked_urls: list[str] | None = None
    block_reasons: dict[str, str] | None = None
    retrieved_urls: list[str] | None = None
    errors: dict[str, str] | None = None
    search_enabled: bool = False
    search_queries: list[str] | None = None
    discovered_urls: list[str] | None = None
    source_scores: dict[str, float] | None = None

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
            "search_enabled": self.search_enabled,
            "search_queries": self.search_queries or [],
            "discovered_urls": self.discovered_urls or [],
            "source_scores": self.source_scores or {},
        }


def retrieve_live_evidence(
    tasks: list[Task],
    hypotheses: list[Hypothesis],
    source_urls: Iterable[str] = (),
    start_index: int = 1,
    timeout_seconds: float = 8.0,
    use_modal: bool = False,
    use_web_search: bool = True,
) -> tuple[list[Evidence], RetrievalStats]:
    task_text = " ".join(task.question for task in tasks)
    explicit_urls = list(source_urls)
    default_urls = _default_urls_for_context(task_text)
    search_queries = _build_search_queries(tasks, hypotheses) if use_web_search and not _only_local_urls(explicit_urls) else []
    discovered_urls, search_errors = _discover_urls(search_queries, timeout_seconds=timeout_seconds) if search_queries else ([], {})
    urls = _rank_candidate_urls([*default_urls, *explicit_urls, *discovered_urls], task_text, hypotheses)
    if use_modal:
        from .modal_bridge import retrieve_live_evidence_with_modal

        evidence, stats = retrieve_live_evidence_with_modal(urls, tasks, hypotheses, start_index, timeout_seconds)
        stats.search_enabled = bool(search_queries)
        stats.search_queries = search_queries
        stats.discovered_urls = discovered_urls
        stats.errors = {**search_errors, **(stats.errors or {})}
        stats.source_scores = stats.source_scores or {}
        return evidence, stats

    stats = RetrievalStats(
        attempted_urls=len(urls),
        blocked_urls=[],
        block_reasons={},
        retrieved_urls=[],
        errors=search_errors,
        search_enabled=bool(search_queries),
        search_queries=search_queries,
        discovered_urls=discovered_urls,
        source_scores={},
    )
    evidence: list[Evidence] = []

    for url in urls:
        if url in _BAD_URL_CACHE:
            stats.failed_urls += 1
            stats.errors[url] = _BAD_URL_CACHE[url]
            continue
        try:
            title, text = fetch_url_text(url, timeout_seconds=min(timeout_seconds, 3.0))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            stats.failed_urls += 1
            error = exc.__class__.__name__
            stats.errors[url] = error
            _BAD_URL_CACHE[url] = error
            continue

        if not text:
            stats.failed_urls += 1
            stats.errors[url] = "empty_response"
            _BAD_URL_CACHE[url] = "empty_response"
            continue
        block_reason = detect_blocked_source(text)
        if block_reason:
            stats.failed_urls += 1
            stats.blocked_urls.append(url)
            stats.block_reasons[url] = block_reason
            stats.errors[url] = block_reason
            _BAD_URL_CACHE[url] = block_reason
            continue
        if _is_low_signal_retrieval(text):
            stats.failed_urls += 1
            stats.errors[url] = "low_signal_response"
            _BAD_URL_CACHE[url] = "low_signal_response"
            continue

        stats.successful_urls += 1
        stats.retrieved_urls.append(url)
        source_id = f"source_{start_index + len(evidence):03d}"
        reliability = _source_reliability(url)
        relevance = _relevance_score(text, task_text, hypotheses)
        source_score = _relative_source_score(url, text, task_text, hypotheses)
        stats.source_scores[url] = source_score
        evidence.append(
            Evidence(
                source_id=source_id,
                title=title or _fallback_title(url),
                url=url,
                source_type=_classify_source(url, text),
                excerpt=_best_excerpt(text, task_text),
                supports=_infer_supports(url, text, hypotheses),
                contradicts=_infer_contradictions(url, text, hypotheses),
                reliability=round(min(0.99, reliability * 0.62 + relevance * 0.38), 2),
            )
        )

    return evidence, stats


def fetch_url_text(url: str, timeout_seconds: float = 8.0) -> tuple[str, str]:
    if url in _FETCH_CACHE:
        return _FETCH_CACHE[url]
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
    result = (title, text)
    _FETCH_CACHE[url] = result
    return result


def _default_urls_for_context(task_text: str) -> list[str]:
    lower = task_text.lower()
    if "copyright" in lower or "authorship" in lower or "ai-generated code" in lower:
        return DEFAULT_LEGAL_SOURCE_URLS
    return []


def _only_local_urls(urls: list[str]) -> bool:
    return bool(urls) and all(url.startswith(("file:", "local:")) for url in urls)


def _build_search_queries(tasks: list[Task], hypotheses: list[Hypothesis], limit: int = 4) -> list[str]:
    task_text = " ".join(task.question for task in tasks)
    hypothesis_text = " ".join(hypothesis.statement for hypothesis in hypotheses)
    lower = f"{task_text} {hypothesis_text}".lower()
    queries: list[str] = []

    if any(term in lower for term in ["contract template", "legal template", "legal forms", "upl", "unauthorized practice"]):
        queries.extend(
            [
                "AI generated contract templates unauthorized practice of law state bar ethics",
                "online legal forms unauthorized practice of law state bar opinion",
                "legal document automation unauthorized practice of law liability",
                "contract template provider warranty misrepresentation consumer protection liability",
            ]
        )
    if "copyright" in lower or "authorship" in lower:
        queries.extend(
            [
                "site:copyright.gov artificial intelligence copyright registration guidance human authorship",
                "AI generated works copyright human authorship case law",
            ]
        )
    if not queries:
        cleaned = " ".join(_keywords(task_text)[:12])
        if cleaned:
            queries.append(f"{cleaned} statute case law agency guidance")
            queries.append(f"{cleaned} legal liability primary authority")

    deduped = list(dict.fromkeys(queries))
    return deduped[:limit]


def _discover_urls(search_queries: list[str], timeout_seconds: float = 8.0, per_query: int = 5) -> tuple[list[str], dict[str, str]]:
    discovered: list[str] = []
    errors: dict[str, str] = {}
    for query in search_queries:
        try:
            result_urls = _search_web(query, timeout_seconds=min(timeout_seconds, 1.5))[:per_query]
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors[f"search:{query}"] = exc.__class__.__name__
            result_urls = []
        if not result_urls:
            result_urls = _fallback_search_urls(query)
        for url in result_urls:
            if url not in discovered and _is_probably_useful_url(url):
                discovered.append(url)
    return discovered, errors


def _search_web(query: str, timeout_seconds: float = 8.0) -> list[str]:
    if query in _SEARCH_CACHE:
        return _SEARCH_CACHE[query]
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    request = Request(
        url,
        headers={
            "User-Agent": "AutoResearchOS/0.1 legal research prototype",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read(800_000)
    html = raw.decode("utf-8", errors="replace")
    if detect_blocked_source(html) or "anomaly-modal" in html or "bots use duckduckgo" in html.lower():
        _SEARCH_CACHE[query] = []
        raise ValueError("search_challenge_detected")
    urls = _extract_search_result_urls(html)
    _SEARCH_CACHE[query] = urls
    return urls


def _fallback_search_urls(query: str) -> list[str]:
    lower = query.lower()
    urls: list[str] = []
    if any(term in lower for term in ["unauthorized practice", "legal forms", "document automation", "contract template"]):
        urls.extend(
            [
                "https://www.law.cornell.edu/wex/unauthorized_practice_of_law",
                "https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_5_5_unauthorized_practice_of_law_multijurisdictional_practice_of_law/",
                "https://www.law.cornell.edu/wex/practice_of_law",
            ]
        )
    if any(term in lower for term in ["warranty", "misrepresentation", "consumer protection", "liability"]):
        urls.extend(
            [
                "https://www.law.cornell.edu/wex/warranty",
                "https://www.law.cornell.edu/wex/misrepresentation",
                "https://www.law.cornell.edu/wex/consumer_protection",
                "https://www.law.cornell.edu/ucc/2/2-313",
            ]
        )
    return list(dict.fromkeys(urls))


def _extract_search_result_urls(html: str) -> list[str]:
    urls: list[str] = []
    for raw_href in re.findall(r'href=["\']([^"\']+)["\']', html):
        href = raw_href.replace("&amp;", "&")
        parsed = urlparse(href)
        if parsed.path.startswith("/l/") and parsed.query:
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            href = unquote(target)
        if href.startswith("//"):
            href = f"https:{href}"
        if href.startswith("http") and "duckduckgo.com" not in urlparse(href).netloc.lower():
            urls.append(href)
    return list(dict.fromkeys(urls))


def _rank_candidate_urls(urls: list[str], task_text: str, hypotheses: list[Hypothesis], limit: int = 12) -> list[str]:
    deduped = list(dict.fromkeys(_canonicalize_url(url) for url in urls if url))
    return sorted(deduped, key=lambda url: _url_priority(url, task_text, hypotheses), reverse=True)[:limit]


def _canonicalize_url(url: str) -> str:
    if url.startswith(("file:", "local:")):
        return url
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def _is_probably_useful_url(url: str) -> bool:
    if url.startswith("file:"):
        return True
    host = urlparse(url).netloc.lower()
    if not host:
        return False
    blocked_hosts = {"facebook.com", "x.com", "twitter.com", "linkedin.com", "youtube.com", "reddit.com"}
    return not any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_hosts)


def _url_priority(url: str, task_text: str, hypotheses: list[Hypothesis]) -> float:
    host_path = f"{urlparse(url).netloc} {urlparse(url).path}".lower()
    reliability = _source_reliability(url)
    url_relevance = _keyword_overlap(host_path, f"{task_text} {' '.join(h.statement for h in hypotheses)}")
    return reliability + min(0.25, url_relevance * 0.04)


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
    if "law.cornell.edu/ucc" in lower or "/ucc/" in lower:
        return "uniform_code"
    if "regulation" in lower or "code of regulations" in lower or "/cfr/" in lower:
        return "regulation"
    if "federalregister.gov" in host or "copyright.gov" in host:
        return "agency_guidance"
    if "statebar" in host or "bar.ca.gov" in host or "americanbar.org" in host or "ethics opinion" in lower:
        return "bar_ethics"
    if "court" in lower or "v." in lower or "opinion" in lower or "caselaw" in lower:
        return "case_law"
    if any(term in lower for term in ["consumer protection", "unfair or deceptive", "warranty", "misrepresentation"]):
        return "liability_authority"
    if "law.cornell.edu/wex" in lower:
        return "legal_reference"
    if "edu" in host:
        return "academic"
    return "web_source"


def _source_reliability(url: str) -> float:
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "law.cornell.edu" in host:
        return 0.92
    if "copyright.gov" in host or "federalregister.gov" in host:
        return 0.95
    if "supreme.justia.com" in host or "law.justia.com" in host:
        return 0.84
    if "courtlistener.com" in host:
        return 0.82
    if "americanbar.org" in host or "statebar" in host or "bar.ca.gov" in host:
        return 0.82
    if "uniformlaws.org" in host:
        return 0.82
    if host.endswith(".gov"):
        return 0.9
    if host.endswith(".us") and any(term in path for term in ["statute", "code", "law", "bar", "court"]):
        return 0.84
    if host.endswith(".edu"):
        return 0.8
    if any(term in host for term in ["findlaw", "nolo", "lexisnexis", "westlaw", "bloomberglaw"]):
        return 0.72
    return 0.65


def _best_excerpt(text: str, task_text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    keywords = _keywords(task_text)
    ranked = sorted(sentences[:160], key=lambda sentence: _sentence_score(sentence, keywords), reverse=True)
    for sentence in ranked:
        if _is_low_signal_sentence(sentence):
            continue
        if _sentence_score(sentence, keywords) > 0:
            return sentence[:550]
    return text[:550]


def _keywords(text: str) -> list[str]:
    stopwords = {
        "about",
        "after",
        "arise",
        "could",
        "customer",
        "customers",
        "does",
        "from",
        "have",
        "into",
        "legal",
        "likely",
        "should",
        "that",
        "their",
        "there",
        "under",
        "which",
        "would",
        "what",
        "with",
    }
    words = re.findall(r"[a-zA-Z][a-zA-Z-]{3,}", text.lower())
    return list(dict.fromkeys(word.strip("-") for word in words if word not in stopwords))


def _sentence_score(sentence: str, keywords: list[str]) -> int:
    lower = sentence.lower()
    priority_terms = [
        "unauthorized practice",
        "state bar",
        "ethics opinion",
        "contract",
        "template",
        "warranty",
        "misrepresentation",
        "consumer protection",
        "liability",
        "statute",
        "case law",
        "regulation",
        "authorship",
        "copyright",
    ]
    score = sum(3 for term in priority_terms if term in lower)
    score += sum(1 for keyword in keywords if keyword in lower)
    return score


def _keyword_overlap(text: str, query_text: str) -> int:
    lower = text.lower()
    return sum(1 for keyword in _keywords(query_text) if keyword in lower)


def _relevance_score(text: str, task_text: str, hypotheses: list[Hypothesis]) -> float:
    query_text = f"{task_text} {' '.join(hypothesis.statement for hypothesis in hypotheses)}"
    keywords = _keywords(query_text)
    if not keywords:
        return 0.5
    overlap = _keyword_overlap(text[:8000], query_text)
    return min(1.0, overlap / max(4, min(14, len(keywords))))


def _relative_source_score(url: str, text: str, task_text: str, hypotheses: list[Hypothesis]) -> float:
    reliability = _source_reliability(url)
    relevance = _relevance_score(text, task_text, hypotheses)
    source_type_bonus = {
        "statute": 0.08,
        "uniform_code": 0.08,
        "regulation": 0.08,
        "agency_guidance": 0.07,
        "case_law": 0.07,
        "bar_ethics": 0.06,
        "liability_authority": 0.04,
        "legal_reference": 0.02,
        "academic": 0.02,
    }.get(_classify_source(url, text), 0.0)
    return round(min(0.99, reliability * 0.65 + relevance * 0.30 + source_type_bonus), 2)


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
        if any(term in statement for term in ["unauthorized-practice-of-law", "unauthorized practice", "upl"]):
            if any(term in lower for term in ["unauthorized practice of law", "practice of law", "rule 5.5", "legal advice"]):
                supports.add(hypothesis.hypothesis_id)
        if any(term in statement for term in ["warranty", "misrepresentation", "consumer-protection", "consumer protection", "negligence", "liability"]):
            if any(term in lower for term in ["warranty", "misrepresentation", "consumer protection", "deceptive", "liability", "affirmation of fact"]):
                supports.add(hypothesis.hypothesis_id)
        if any(term in statement for term in ["jurisdiction", "state", "vary"]):
            if any(term in lower for term in ["state", "jurisdiction", "unauthorized practice of law", "rule 5.5", "consumer protection"]):
                supports.add(hypothesis.hypothesis_id)
        hypothesis_keywords = _keywords(hypothesis.statement)
        if _keyword_overlap(lower[:5000], " ".join(hypothesis_keywords)) >= max(2, min(5, len(hypothesis_keywords) // 4)):
            supports.add(hypothesis.hypothesis_id)
    if not supports and hypotheses:
        task_terms = ["unauthorized practice", "contract", "template", "liability", "warranty", "consumer protection", "state bar"]
        if any(term in lower for term in task_terms):
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
