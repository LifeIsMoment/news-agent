#!/usr/bin/env python3
"""Daily AI finance, tax, and accounting monitoring.

The collector uses only Python's standard library. It gathers public RSS/API
metadata, applies deterministic relevance gates, keeps a local deduplication
and snapshot state, and writes a detailed Markdown report plus a compact
GitHub issue body.

This is a discovery and prioritisation system. It is not financial, accounting,
tax, or legal advice. RSS snippets and automated scores must be checked against
primary sources before operational use.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
USER_AGENT = (
    "LifeIsMoment-AI-Finance-Tax-Accounting-Monitor/1.0 "
    "(+https://github.com/LifeIsMoment/news-agent)"
)

AI_TERMS = {
    "ai", "인공지능", "생성형 ai", "생성형ai", "artificial intelligence",
    "large language model", "llm", "agentic", "에이전틱", "copilot",
    "에이전트", "agent", "mcp", "model context protocol", "rag",
}
DOMAIN_TERMS = {
    "재무", "세무", "세법", "조세", "회계", "감사", "공시", "법인세",
    "부가가치세", "원천징수", "세액공제", "이전가격", "tax", "taxation",
    "vat", "accounting", "audit", "finance", "financial", "fp&a", "cfo",
    "bookkeeping", "ledger", "invoice", "accounts payable", "accounts receivable",
    "financial reporting", "xbrl", "ifrs", "gaap", "revenue recognition",
}
RELEASE_TERMS = {
    "출시", "공개", "정식 제공", "업데이트", "릴리스", "도입", "파트너십",
    "launch", "launched", "release", "released", "general availability", "ga",
    "introduces", "unveils", "announces", "partnership", "beta", "preview",
}
REGULATORY_TERMS = {
    "법률", "법안", "시행령", "고시", "지침", "가이드라인", "개정", "공포",
    "시행", "감리", "제재", "조사", "의견수렴", "rule", "regulation",
    "guidance", "guideline", "consultation", "enforcement", "amendment",
    "standard", "standard-setting", "inspection", "sanction", "effective date",
}
RISK_TERMS = {
    "오류", "허위", "환각", "부정", "위반", "과징금", "벌금", "중단",
    "breach", "fraud", "hallucination", "misstatement", "penalty", "fine",
    "material weakness", "restatement", "outage", "vulnerability",
}
BENCHMARK_TERMS = {
    "benchmark", "벤치마크", "evaluation", "평가", "dataset", "데이터셋",
    "leaderboard", "정확도", "accuracy", "exact match", "reasoning",
}

CATEGORY_TERMS: list[tuple[str, set[str]]] = [
    ("세무 AI·조세기술", {"세무", "세법", "조세", "법인세", "부가가치세", "원천징수", "tax", "taxation", "vat", "transfer pricing"}),
    ("회계 자동화·결산", {"회계", "기장", "전표", "원장", "결산", "accounting", "bookkeeping", "ledger", "close", "reconciliation"}),
    ("감사·내부통제·부정탐지", {"감사", "감리", "내부통제", "부정", "audit", "assurance", "internal control", "fraud", "sox", "grc"}),
    ("재무분석·FP&A·CFO", {"재무", "예산", "현금흐름", "재무분석", "finance", "financial", "fp&a", "cfo", "treasury", "forecast", "planning"}),
    ("AP·AR·인보이스", {"매입", "매출채권", "지급", "수금", "인보이스", "invoice", "accounts payable", "accounts receivable", "billing", "collections"}),
    ("문서 AI·OCR·XBRL", {"ocr", "문서 ai", "document ai", "document intelligence", "xbrl", "pdf", "영수증", "receipt", "table extraction"}),
    ("공공 데이터·API", {"api", "공공데이터", "open data", "opendart", "dart", "ecos", "kosis", "xbrl taxonomy", "developer guide"}),
    ("AI 규제·거버넌스", {"거버넌스", "책임", "개인정보", "보안", "ai act", "governance", "privacy", "security", "human-in-the-loop", "audit trail"}),
    ("오픈소스·도구", {"github", "open source", "오픈소스", "pypi", "repository", "package", "framework"}),
    ("논문·벤치마크", {"arxiv", "paper", "논문", "benchmark", "벤치마크", "dataset", "데이터셋", "evaluation"}),
]

DEFAULT_SECTION_ORDER = [
    "TAXiA·CLOA 직접 관련",
    "상용 서비스·기업 업데이트",
    "오픈소스 프로젝트",
    "논문·벤치마크",
    "공공 데이터·API",
    "법·제도·감사",
]


@dataclasses.dataclass
class Item:
    uid: str
    title: str
    url: str
    source: str
    published_at: str
    jurisdiction: str
    track: str
    category: str
    kind: str
    summary: str
    priority: str
    score: int
    status: str
    confidence: str
    source_type: str
    evidence: str
    impact: str
    query_names: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        allowed = {field.name for field in dataclasses.fields(cls)}
        cleaned = {key: value for key, value in data.items() if key in allowed}
        cleaned.setdefault("query_names", [])
        return cls(**cleaned)


@dataclasses.dataclass
class Health:
    source: str
    group: str
    ok: bool
    count: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class HttpClient:
    def __init__(self, token: str | None = None, timeout: int = 22) -> None:
        self.token = token
        self.timeout = timeout

    def get_bytes(self, url: str, *, accept: str | None = None) -> bytes:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        }
        if accept:
            headers["Accept"] = accept
        if self.token and "api.github.com" in url:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_text(self, url: str) -> str:
        return self.get_bytes(url).decode("utf-8", errors="replace")

    def get_json(self, url: str) -> Any:
        return json.loads(self.get_bytes(url, accept="application/vnd.github+json").decode("utf-8"))


def now_utc() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def parse_datetime(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        result = value
    else:
        text = str(value).strip()
        if not text:
            return None
        result = None
        try:
            result = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = email.utils.parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                try:
                    result = dt.datetime.strptime(text[:10], "%Y-%m-%d")
                except ValueError:
                    return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def isoformat(value: dt.datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def strip_html(value: str, max_len: int = 1000) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣一-龥ぁ-ゟァ-ヿ]+", "", value.lower())


def contains_term(text: str, term: str) -> bool:
    lowered = text.lower()
    token = term.lower().strip()
    if not token:
        return False
    if re.fullmatch(r"[a-z0-9+#.&/-]{1,5}", token):
        return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered) is not None
    return token in lowered


def contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(contains_term(text, str(term)) for term in terms)


def canonical_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        query = [
            (key, val)
            for key, val in query
            if not key.lower().startswith("utm_")
            and key.lower() not in {"gclid", "fbclid", "ref", "source", "campaign"}
        ]
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), "")
        )
    except ValueError:
        return value


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower().split(":", 1)[0].removeprefix("www.")
    except ValueError:
        return ""


def domain_matches(url: str, domains: Iterable[str]) -> bool:
    host = host_of(url)
    return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in domains)


def make_uid(title: str, url: str, published_at: str, kind: str) -> str:
    base = canonical_url(url)
    event_kinds = {
        "github_metadata", "github_release", "github_commit", "github_issue",
        "pypi_release", "official_rule", "page_snapshot",
    }
    if kind in event_kinds:
        base = f"{base}|{normalize_text(title)}|{published_at}|{kind}"
    elif "news.google.com/rss/articles/" in base or not base:
        base = f"{normalize_text(title)}|{published_at[:10]}|{kind}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def classify_category(text: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    lowered = text.lower()
    best = ("기타", 0)
    for category, terms in CATEGORY_TERMS:
        score = sum(1 for term in terms if contains_term(lowered, term))
        if score > best[1]:
            best = (category, score)
    return best[0]


def default_impact(category: str, track: str) -> str:
    mapping = {
        "세무 AI·조세기술": "법령·예규 검색, 신고 검증, 세액 계산, 전문가 승인 구조의 경쟁·설계 변화로 검토",
        "회계 자동화·결산": "거래 분류, 전표·원장 검증, 월말결산과 세무조정 연계 기능의 참고 대상으로 검토",
        "감사·내부통제·부정탐지": "에이전트 권한, 증적, 내부통제, 이상거래 탐지와 감사 추적 설계에 반영",
        "재무분석·FP&A·CFO": "CLOA의 재무분석·예측·경영지원 확장성과 정량 검증 체계에 영향",
        "AP·AR·인보이스": "증빙 수집, 필드 계보, 매입·매출 검증과 지급·수금 워크플로에 적용 가능",
        "문서 AI·OCR·XBRL": "세금계산서·영수증·공시 문서의 구조화, 좌표 추적, 표·주석 추출 성능을 비교",
        "공공 데이터·API": "공식 데이터 수집기, 스키마 버전, 정정 이력, 시행일·귀속연도 관리에 즉시 영향",
        "AI 규제·거버넌스": "고객 데이터 격리, 모델·도구 권한, 책임자 승인, 비용·로그 관리 요구사항에 반영",
        "오픈소스·도구": "도입 가능성보다 라이선스·유지보수·재현성·한국 세무 현지화 비용을 우선 평가",
        "논문·벤치마크": "완전정답률, 인용 정확도, 계산 일치율, 시행일 정확도 등 TAXiA/CLOA 평가체계와 비교",
    }
    if track == "TAXiA·CLOA 직접 관련":
        return "TAXiA·CLOA의 코드, 배포, 문서, 평판 또는 제품 방향을 직접 확인해야 함"
    return mapping.get(category, "TAXiA/CLOA의 제품·데이터·통제 구조에 미치는 영향은 원문 검토 후 판단")


def passes_gate(text: str, source_url: str, rule: dict[str, Any]) -> bool:
    lowered = text.lower()
    exclusions = [str(term).lower() for term in rule.get("exclude_any", [])]
    if contains_any(lowered, exclusions):
        return False

    required_any = [str(term).lower() for term in rule.get("required_any", [])]
    if required_any and not contains_any(lowered, required_any):
        return False

    for group in rule.get("required_all_groups", []):
        normalized_group = [str(term).lower() for term in group]
        if normalized_group and not contains_any(lowered, normalized_group):
            return False

    title_required = [str(term).lower() for term in rule.get("title_required_any", [])]
    title = str(rule.get("_title", "")).lower()
    if title_required and not contains_any(title, title_required):
        return False

    allowlist = rule.get("domain_allowlist", [])
    if allowlist and not domain_matches(source_url, allowlist):
        return False

    min_hits = int(rule.get("min_term_hits", 0))
    terms = [str(term).lower() for term in rule.get("scoring_terms", [])]
    if min_hits and sum(1 for term in terms if contains_term(lowered, term)) < min_hits:
        return False
    return True


def confidence_for(source_type: str) -> str:
    if source_type in {"official_primary", "repository_primary", "paper_primary", "package_primary"}:
        return "높음"
    if source_type == "vendor_primary":
        return "중간~높음"
    if source_type == "repository_discovery":
        return "중간"
    return "낮음~중간"


def score_item(
    text: str,
    *,
    source_type: str,
    category: str,
    kind: str,
    direct: bool = False,
    score_boost: int = 0,
) -> tuple[int, str]:
    lowered = text.lower()
    score = 12
    score += {
        "official_primary": 26,
        "repository_primary": 22,
        "paper_primary": 22,
        "package_primary": 20,
        "vendor_primary": 16,
        "repository_discovery": 10,
        "secondary_index": 2,
    }.get(source_type, 0)
    if category in {"세무 AI·조세기술", "회계 자동화·결산", "감사·내부통제·부정탐지", "공공 데이터·API"}:
        score += 8
    if contains_any(lowered, RELEASE_TERMS):
        score += 12
    if contains_any(lowered, REGULATORY_TERMS):
        score += 14
    if contains_any(lowered, RISK_TERMS):
        score += 10
    if contains_any(lowered, BENCHMARK_TERMS):
        score += 8
    if contains_any(lowered, AI_TERMS) and contains_any(lowered, DOMAIN_TERMS):
        score += 7
    if direct:
        score += 28
    if kind in {"github_release", "pypi_release", "official_rule"}:
        score += 8
    score += score_boost
    score = max(0, min(score, 100))
    if score >= 75:
        priority = "P0"
    elif score >= 55:
        priority = "P1"
    elif score >= 35:
        priority = "P2"
    else:
        priority = "P3"
    return score, priority


def google_locale_params(locale: str) -> dict[str, str]:
    if locale == "ja":
        return {"hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    if locale == "zh":
        return {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    if locale == "en-gb":
        return {"hl": "en-GB", "gl": "GB", "ceid": "GB:en"}
    if locale == "en":
        return {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    return {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}


def source_type_for_news(source_url: str, row: dict[str, Any], config: dict[str, Any]) -> str:
    if domain_matches(source_url, config.get("official_domains", [])):
        return "official_primary"
    if domain_matches(source_url, config.get("vendor_domains", [])):
        return "vendor_primary"
    return row.get("source_type", "secondary_index")


def fetch_google_news(
    client: HttpClient,
    *,
    row: dict[str, Any],
    since: dt.datetime,
    config: dict[str, Any],
) -> list[Item]:
    params = {"q": f"{row['query']} when:4d", **google_locale_params(row.get("locale", "ko"))}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    root = ET.fromstring(client.get_bytes(url))
    items: list[Item] = []
    for node in root.findall("./channel/item"):
        title = strip_html(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        published = parse_datetime(node.findtext("pubDate"))
        if published is None or published < since:
            continue
        source_node = node.find("source")
        source = strip_html(source_node.text if source_node is not None and source_node.text else "Google News")
        source_url = source_node.attrib.get("url", "") if source_node is not None else ""
        description = strip_html(node.findtext("description") or "")
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        combined = f"{title} {description} {source} {source_url}"
        gate = dict(row)
        gate["_title"] = title
        if not passes_gate(combined, source_url, gate):
            continue
        category = classify_category(combined, row.get("category"))
        source_type = source_type_for_news(source_url, row, config)
        direct = bool(row.get("direct", False))
        score, priority = score_item(
            combined,
            source_type=source_type,
            category=category,
            kind="news",
            direct=direct,
            score_boost=int(row.get("score_boost", 0)),
        )
        published_at = isoformat(published)
        status = {
            "official_primary": "공식기관 원문 색인",
            "vendor_primary": "기업 공식 발표 색인",
        }.get(source_type, "뉴스/RSS 색인·원문 확인 필요")
        impact = row.get("impact") or default_impact(category, row["track"])
        evidence = (
            "Google News RSS가 제공한 제목·요약·발표 출처. 원문 발표일, 기능 범위, 수치와 시행일을 재확인해야 함."
            if source_type == "secondary_index"
            else "Google News RSS에서 공식 출처 도메인을 확인. 세부 내용은 연결된 1차 원문 검토 필요."
        )
        items.append(Item(
            uid=make_uid(title, link, published_at, "news"),
            title=title,
            url=link,
            source=source,
            published_at=published_at,
            jurisdiction=row.get("jurisdiction", "글로벌"),
            track=row["track"],
            category=category,
            kind="news",
            summary=description or "RSS 제목만 수집됨. 원문 확인 필요.",
            priority=priority,
            score=score,
            status=status,
            confidence=confidence_for(source_type),
            source_type=source_type,
            evidence=evidence,
            impact=impact,
            query_names=[row["name"]],
        ))
    return items


def fetch_arxiv(client: HttpClient, row: dict[str, Any], since: dt.datetime) -> list[Item]:
    params = {
        "search_query": row["query"],
        "start": 0,
        "max_results": int(row.get("max_results", 50)),
        "sortBy": "lastUpdatedDate",
        "sortOrder": "descending",
    }
    raw = client.get_bytes("https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params))
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    result: list[Item] = []
    for entry in root.findall("a:entry", ns):
        title = strip_html(entry.findtext("a:title", default="", namespaces=ns))
        summary = strip_html(entry.findtext("a:summary", default="", namespaces=ns), max_len=1400)
        updated = parse_datetime(entry.findtext("a:updated", default="", namespaces=ns))
        published = parse_datetime(entry.findtext("a:published", default="", namespaces=ns))
        event_time = updated or published
        if event_time is None or event_time < since:
            continue
        authors = [
            strip_html(author.findtext("a:name", default="", namespaces=ns))
            for author in entry.findall("a:author", ns)
        ]
        entry_id = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        combined = f"{title} {summary} {' '.join(authors)}"
        gate = dict(row)
        gate["_title"] = title
        if not passes_gate(combined, entry_id, gate):
            continue
        category = classify_category(combined, row.get("category", "논문·벤치마크"))
        score, priority = score_item(
            combined,
            source_type="paper_primary",
            category=category,
            kind="arxiv_paper",
            score_boost=int(row.get("score_boost", 0)),
        )
        author_text = ", ".join(authors[:8])
        if len(authors) > 8:
            author_text += " 외"
        result.append(Item(
            uid=make_uid(title, entry_id, isoformat(event_time), "arxiv_paper"),
            title=title,
            url=entry_id,
            source="arXiv API",
            published_at=isoformat(event_time),
            jurisdiction="글로벌",
            track=row.get("track", "논문·벤치마크"),
            category=category,
            kind="arxiv_paper",
            summary=f"저자: {author_text or '미표시'}. {summary}",
            priority=priority,
            score=score,
            status="사전공개 논문 메타데이터",
            confidence="높음(존재·메타데이터) / 성능 주장은 별도 검증",
            source_type="paper_primary",
            evidence="arXiv 공식 Atom API의 제목·초록·저자·업데이트 시각",
            impact=row.get("impact") or default_impact(category, "논문·벤치마크"),
            query_names=[row["name"]],
        ))
    return result


def repo_item(
    *,
    asset: dict[str, Any],
    title: str,
    url: str,
    published: dt.datetime,
    kind: str,
    summary: str,
    status: str,
) -> Item:
    direct = bool(asset.get("direct", False))
    category = asset.get("category", "오픈소스·도구")
    score, priority = score_item(
        f"{title} {summary}",
        source_type="repository_primary",
        category=category,
        kind=kind,
        direct=direct,
        score_boost=int(asset.get("score_boost", 0)),
    )
    return Item(
        uid=make_uid(title, url, isoformat(published), kind),
        title=title,
        url=url,
        source="GitHub REST API",
        published_at=isoformat(published),
        jurisdiction="제품 생태계",
        track=asset.get("track", "오픈소스 프로젝트"),
        category=category,
        kind=kind,
        summary=summary,
        priority=priority,
        score=score,
        status=status,
        confidence="높음",
        source_type="repository_primary",
        evidence="GitHub 공식 REST API의 저장소·릴리스·커밋·이슈 메타데이터",
        impact=asset.get("impact") or default_impact(category, asset.get("track", "오픈소스 프로젝트")),
        query_names=[asset["repo"]],
    )


def fetch_github_repo(
    client: HttpClient,
    asset: dict[str, Any],
    since: dt.datetime,
    state: dict[str, Any],
) -> tuple[list[Item], dict[str, Any]]:
    repo = asset["repo"]
    encoded = urllib.parse.quote(repo, safe="/")
    base = f"https://api.github.com/repos/{encoded}"
    metadata = client.get_json(base)
    snapshot_key = f"finance:github:{repo}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {
        "updated_at": metadata.get("updated_at"),
        "pushed_at": metadata.get("pushed_at"),
        "default_branch": metadata.get("default_branch"),
        "stargazers_count": metadata.get("stargazers_count"),
        "forks_count": metadata.get("forks_count"),
        "open_issues_count": metadata.get("open_issues_count"),
        "archived": metadata.get("archived"),
    }
    items: list[Item] = []
    baseline = previous is None
    if baseline or snapshot != previous:
        title = f"{repo} 저장소 {'기준선 등록' if baseline else '메타데이터 변경'}"
        summary = (
            f"최근 push {snapshot.get('pushed_at')}; stars {snapshot.get('stargazers_count')}; "
            f"forks {snapshot.get('forks_count')}; open issues {snapshot.get('open_issues_count')}; "
            f"archived {snapshot.get('archived')}."
        )
        event_time = parse_datetime(snapshot.get("updated_at")) or now_utc()
        items.append(repo_item(
            asset=asset,
            title=title,
            url=metadata.get("html_url", f"https://github.com/{repo}"),
            published=event_time,
            kind="github_metadata",
            summary=summary,
            status="공식 저장소 기준선" if baseline else "공식 저장소 변경",
        ))

    releases = client.get_json(base + "/releases?per_page=30")
    for index, release in enumerate(releases if isinstance(releases, list) else []):
        published = parse_datetime(release.get("published_at") or release.get("created_at"))
        if published is None:
            continue
        if baseline and index > int(asset.get("baseline_releases", 0)):
            break
        if not baseline and published < since:
            continue
        tag = release.get("tag_name") or release.get("name") or "untagged"
        title = f"{repo} 릴리스 {tag}"
        summary = strip_html(release.get("body") or "릴리스 설명 없음", max_len=1400)
        items.append(repo_item(
            asset=asset,
            title=title,
            url=release.get("html_url", f"https://github.com/{repo}/releases"),
            published=published,
            kind="github_release",
            summary=summary,
            status="공식 GitHub 릴리스",
        ))

    commit_params: dict[str, Any] = {"per_page": int(asset.get("baseline_commits", 3)) if baseline else 100}
    if not baseline:
        commit_params["since"] = isoformat(since)
    commits = client.get_json(base + "/commits?" + urllib.parse.urlencode(commit_params))
    for commit in commits if isinstance(commits, list) else []:
        commit_data = commit.get("commit", {})
        event_time = parse_datetime(
            commit_data.get("committer", {}).get("date") or commit_data.get("author", {}).get("date")
        )
        if event_time is None:
            continue
        message = (commit_data.get("message") or "").splitlines()[0].strip()
        sha = (commit.get("sha") or "")[:10]
        items.append(repo_item(
            asset=asset,
            title=f"{repo} 커밋 {sha}: {message}",
            url=commit.get("html_url", f"https://github.com/{repo}/commits"),
            published=event_time,
            kind="github_commit",
            summary=message or "커밋 메시지 없음",
            status="공식 코드 변경",
        ))

    if asset.get("monitor_issues", False):
        issue_params: dict[str, Any] = {
            "state": "all", "per_page": 100, "sort": "updated", "direction": "desc"
        }
        if not baseline:
            issue_params["since"] = isoformat(since)
        issues = client.get_json(base + "/issues?" + urllib.parse.urlencode(issue_params))
        if baseline and isinstance(issues, list):
            issues = issues[: int(asset.get("baseline_issues", 5))]
        for issue in issues if isinstance(issues, list) else []:
            event_time = parse_datetime(issue.get("updated_at"))
            if event_time is None:
                continue
            is_pr = "pull_request" in issue
            type_name = "PR" if is_pr else "이슈"
            title = f"{repo} {type_name} #{issue.get('number')}: {issue.get('title', '').strip()}"
            summary = strip_html(issue.get("body") or f"상태: {issue.get('state')}", max_len=1200)
            items.append(repo_item(
                asset=asset,
                title=title,
                url=issue.get("html_url", f"https://github.com/{repo}/issues"),
                published=event_time,
                kind="github_issue",
                summary=summary,
                status=f"공식 {type_name} 활동",
            ))
    return items, {snapshot_key: snapshot}


def fetch_github_discovery(client: HttpClient, row: dict[str, Any], since: dt.datetime) -> list[Item]:
    params = {"q": row["query"], "sort": "updated", "order": "desc", "per_page": 50}
    payload = client.get_json("https://api.github.com/search/repositories?" + urllib.parse.urlencode(params))
    result: list[Item] = []
    for repo in payload.get("items", []):
        updated = parse_datetime(repo.get("updated_at") or repo.get("pushed_at"))
        if updated is None or updated < since:
            continue
        title = f"신규·변경 GitHub 저장소: {repo.get('full_name')}"
        summary = strip_html(repo.get("description") or "설명 없음")
        combined = f"{title} {summary} {' '.join(repo.get('topics') or [])}"
        gate = dict(row)
        gate["_title"] = title
        if not passes_gate(combined, repo.get("html_url", ""), gate):
            continue
        category = classify_category(combined, row.get("category", "오픈소스·도구"))
        score, priority = score_item(
            combined,
            source_type="repository_discovery",
            category=category,
            kind="github_discovery",
            score_boost=int(row.get("score_boost", 0)),
        )
        result.append(Item(
            uid=make_uid(title, repo.get("html_url", ""), isoformat(updated), "github_discovery"),
            title=title,
            url=repo.get("html_url", ""),
            source="GitHub Search API",
            published_at=isoformat(updated),
            jurisdiction="제품 생태계",
            track="오픈소스 프로젝트",
            category=category,
            kind="github_discovery",
            summary=(
                f"{summary} | stars {repo.get('stargazers_count')}; forks {repo.get('forks_count')}; "
                f"language {repo.get('language')}; archived {repo.get('archived')}."
            ),
            priority=priority,
            score=score,
            status="공개 저장소 발견·품질 확인 필요",
            confidence="중간",
            source_type="repository_discovery",
            evidence="GitHub 공개 Repository Search API. 동명이인, 포크, 유지보수 상태와 라이선스 확인 필요.",
            impact=row.get("impact") or default_impact(category, "오픈소스 프로젝트"),
            query_names=[row["name"]],
        ))
    return result


def fetch_pypi(
    client: HttpClient,
    asset: dict[str, Any],
    since: dt.datetime,
    state: dict[str, Any],
) -> tuple[list[Item], dict[str, Any]]:
    package = asset["package"]
    payload = client.get_json(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
    info = payload.get("info", {})
    latest = info.get("version")
    snapshot_key = f"finance:pypi:{package}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {
        "version": latest,
        "requires_python": info.get("requires_python"),
        "project_url": info.get("project_url") or info.get("package_url"),
    }
    result: list[Item] = []
    for version, files in payload.get("releases", {}).items():
        timestamps = [
            parse_datetime(file.get("upload_time_iso_8601") or file.get("upload_time"))
            for file in files
        ]
        timestamps = [stamp for stamp in timestamps if stamp is not None]
        if not timestamps:
            continue
        published = max(timestamps)
        if previous is None and version != latest:
            continue
        if previous is not None and published < since:
            continue
        title = f"PyPI {package} {version} 릴리스"
        summary = (
            f"최신 버전 {latest}; Python 요구사항 {info.get('requires_python') or '미표시'}; "
            f"배포 파일 {len(files)}개."
        )
        category = asset.get("category", "오픈소스·도구")
        score, priority = score_item(
            title + " " + summary,
            source_type="package_primary",
            category=category,
            kind="pypi_release",
            direct=bool(asset.get("direct", False)),
            score_boost=int(asset.get("score_boost", 0)),
        )
        url = info.get("package_url") or f"https://pypi.org/project/{package}/{version}/"
        result.append(Item(
            uid=make_uid(title, f"{url}#{version}", isoformat(published), "pypi_release"),
            title=title,
            url=url,
            source="PyPI JSON API",
            published_at=isoformat(published),
            jurisdiction="제품 생태계",
            track=asset.get("track", "오픈소스 프로젝트"),
            category=category,
            kind="pypi_release",
            summary=summary,
            priority=priority,
            score=score,
            status="공식 패키지 릴리스",
            confidence="높음",
            source_type="package_primary",
            evidence="PyPI 공식 JSON API의 버전·파일·업로드 시각",
            impact=asset.get("impact") or default_impact(category, asset.get("track", "오픈소스 프로젝트")),
            query_names=[package],
        ))
    return result, {snapshot_key: snapshot}


def fetch_federal_register(client: HttpClient, row: dict[str, Any], since: dt.datetime) -> list[Item]:
    params = {"per_page": 100, "order": "newest"}
    payload = client.get_json(
        "https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(params)
    )
    result: list[Item] = []
    for document in payload.get("results", []):
        published = parse_datetime(document.get("publication_date"))
        if published is None or published < since - dt.timedelta(hours=24):
            continue
        title = strip_html(document.get("title") or "")
        abstract = strip_html(document.get("abstract") or "", max_len=1400)
        agencies = document.get("agencies", [])
        agency_names = " ".join(
            str(agency.get("name") or agency.get("raw_name") or "") if isinstance(agency, dict) else str(agency)
            for agency in agencies
        )
        combined = f"{title} {abstract} {agency_names}"
        gate = dict(row)
        gate["_title"] = title
        url = document.get("html_url") or document.get("pdf_url") or ""
        if not passes_gate(combined, url, gate):
            continue
        category = classify_category(combined, row.get("category", "AI 규제·거버넌스"))
        score, priority = score_item(
            combined,
            source_type="official_primary",
            category=category,
            kind="official_rule",
            score_boost=int(row.get("score_boost", 0)),
        )
        result.append(Item(
            uid=make_uid(title, url, isoformat(published), "official_rule"),
            title=title,
            url=url,
            source="U.S. Federal Register API",
            published_at=isoformat(published),
            jurisdiction="미국",
            track=row.get("track", "법·제도·감사"),
            category=category,
            kind="official_rule",
            summary=abstract or f"문서 유형: {document.get('type') or '미표시'}; 기관: {agency_names}",
            priority=priority,
            score=score,
            status="미국 연방 공식 문서",
            confidence="높음",
            source_type="official_primary",
            evidence="Federal Register 공식 API의 문서 메타데이터와 초록",
            impact=row.get("impact") or default_impact(category, "법·제도·감사"),
            query_names=[row["name"]],
        ))
    return result


def normalized_page_hash(raw: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|svg).*?>.*?</\1>", " ", raw)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r">\s+<", "><", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def fetch_snapshot(
    client: HttpClient,
    asset: dict[str, Any],
    state: dict[str, Any],
) -> tuple[list[Item], dict[str, Any]]:
    url = asset["url"]
    raw = client.get_text(url)
    digest = normalized_page_hash(raw)
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    page_title = strip_html(title_match.group(1) if title_match else asset.get("name", url))
    snapshot_key = f"finance:web:{canonical_url(url)}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {"sha256": digest, "title": page_title}
    if previous is not None and previous.get("sha256") == digest:
        return [], {snapshot_key: snapshot}
    baseline = previous is None
    title = f"{asset.get('name', page_title)} {'기준선 등록' if baseline else '페이지 내용 변경'}"
    category = asset.get("category", "공공 데이터·API")
    score, priority = score_item(
        title,
        source_type="official_primary" if asset.get("official", True) else "vendor_primary",
        category=category,
        kind="page_snapshot",
        score_boost=int(asset.get("score_boost", 0)),
    )
    item = Item(
        uid=make_uid(title, url + "#" + digest[:12], isoformat(now_utc()), "page_snapshot"),
        title=title,
        url=url,
        source=host_of(url),
        published_at=isoformat(now_utc()),
        jurisdiction=asset.get("jurisdiction", "글로벌"),
        track=asset.get("track", "공공 데이터·API"),
        category=category,
        kind="page_snapshot",
        summary=f"정규화 페이지 해시 {digest[:16]}. {'초기 기준선' if baseline else '이전 기준선과 상이'}. 변경 내용은 원문 대조 필요.",
        priority=priority,
        score=score,
        status="공식 페이지 기준선" if baseline else "공식 페이지 변경 탐지",
        confidence="높음(변경 존재) / 변경 의미는 원문 확인",
        source_type="official_primary" if asset.get("official", True) else "vendor_primary",
        evidence="공개 페이지의 스크립트·스타일 제거 후 정규화 해시 비교",
        impact=asset.get("impact") or default_impact(category, asset.get("track", "공공 데이터·API")),
        query_names=[asset.get("name", host_of(url))],
    )
    return [item], {snapshot_key: snapshot}


def merge_duplicate_items(items: Iterable[Item]) -> list[Item]:
    merged: dict[str, Item] = {}
    title_index: dict[str, str] = {}
    for item in items:
        title_key = normalize_text(item.title)
        key = item.uid
        if title_key and title_key in title_index:
            key = title_index[title_key]
        existing = merged.get(key)
        if existing is None:
            merged[key] = item
            if title_key:
                title_index[title_key] = key
            continue
        combined_queries = sorted(set(existing.query_names + item.query_names))
        if item.score > existing.score:
            item.query_names = combined_queries
            merged[key] = item
            if title_key:
                title_index[title_key] = key
        else:
            existing.query_names = combined_queries
            if len(item.summary) > len(existing.summary):
                existing.summary = item.summary
    return list(merged.values())


def item_sort_key(item: Item) -> tuple[Any, ...]:
    published = parse_datetime(item.published_at) or dt.datetime.min.replace(tzinfo=UTC)
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return (priority_order.get(item.priority, 9), -item.score, -published.timestamp(), item.title.lower())


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def markdown_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def local_date_time(value: str, timezone: ZoneInfo) -> str:
    parsed = parse_datetime(value)
    if parsed is None:
        return "일시 불명"
    return parsed.astimezone(timezone).strftime("%Y-%m-%d %H:%M")


def render_item(item: Item, timezone: ZoneInfo, number: int) -> str:
    summary = item.summary.strip() or "요약 없음"
    if len(summary) > 1400:
        summary = summary[:1399] + "…"
    queries = ", ".join(item.query_names[:8]) or "직접 API"
    return "\n".join([
        f"### {number}. [{item.title}]({item.url})",
        "",
        f"- **우선순위:** {item.priority} ({item.score}/100, 규칙 기반)",
        f"- **발표·업데이트:** {local_date_time(item.published_at, timezone)} KST",
        f"- **관할·분류:** {item.jurisdiction} · {item.category}",
        f"- **출처:** {item.source} · `{item.source_type}` · 신뢰도 {item.confidence}",
        f"- **상태:** {item.status}",
        f"- **TAXiA/CLOA 시사점:** {item.impact}",
        f"- **수집 근거:** {item.evidence}",
        f"- **검색·추적 경로:** {queries}",
        "",
        summary,
        "",
    ])


def render_report(
    *,
    report_date: dt.date,
    run_at: dt.datetime,
    since: dt.datetime,
    items: list[Item],
    health: list[Health],
    timezone: ZoneInfo,
    repository: str,
    config: dict[str, Any],
) -> str:
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for item in items:
        counts[item.priority] = counts.get(item.priority, 0) + 1
    title = config.get("report_title", "AI 재무·세무·회계 자동 모니터링")
    lines = [
        f"# {title} — {report_date.isoformat()}",
        "",
        f"- **실행 시각:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST",
        f"- **신규 수집 기준:** {since.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST 이후",
        f"- **당일 누적 항목:** {len(items)}개 (P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']} · P3 {counts['P3']})",
        f"- **저장소:** https://github.com/{repository}",
        "",
        "> 공개 RSS·API·공식 저장소 기반 자동 탐지 보고서입니다. 공급업체 성능 수치, RSS 요약, 사전공개 논문은 독립 검증 결과가 아닙니다. 원문 발표일·적용범위·시행일·라이선스·예외를 다시 확인해야 합니다.",
        "",
        "## 오늘의 핵심 판단",
        "",
    ]
    sorted_items = sorted(items, key=item_sort_key)
    meaningful = [item for item in sorted_items if item.priority in {"P0", "P1"}]
    if not items:
        lines.extend([
            "**새롭거나 의미 있는 변화를 확인하지 못했습니다.** 이는 변화가 없다는 확정 결론이 아니라, 설정된 공개 소스에서 신규 항목을 찾지 못했다는 뜻입니다.",
            "",
        ])
    elif meaningful:
        for item in meaningful[:8]:
            lines.append(
                f"- **{item.priority}** · [{item.title}]({item.url}) — {item.impact}"
            )
        lines.append("")
    else:
        lines.extend([
            "신규 항목은 있으나 P0·P1 기준을 충족한 변화는 없습니다. P2·P3 항목은 아래 원문 검토 목록에 보존했습니다.",
            "",
        ])

    section_order = config.get("section_order", DEFAULT_SECTION_ORDER)
    grouped: dict[str, list[Item]] = {section: [] for section in section_order}
    for item in sorted_items[: int(config.get("max_report_items", 200))]:
        grouped.setdefault(item.track, []).append(item)

    number = 1
    for section in section_order:
        section_items = grouped.get(section, [])
        lines.extend([f"## {section}", ""])
        if not section_items:
            lines.extend(["해당 섹션의 신규 항목 없음.", ""])
            continue
        for item in section_items:
            lines.append(render_item(item, timezone, number))
            number += 1

    extra_sections = [key for key in grouped if key not in section_order]
    for section in extra_sections:
        lines.extend([f"## {section}", ""])
        for item in grouped[section]:
            lines.append(render_item(item, timezone, number))
            number += 1

    lines.extend([
        "## 수집 소스 상태",
        "",
        "| 그룹 | 소스 | 상태 | 수집 건수 | 비고 |",
        "|---|---|---:|---:|---|",
    ])
    for row in sorted(health, key=lambda value: (not value.ok, value.group, value.source.lower())):
        lines.append(
            f"| {markdown_escape(row.group)} | {markdown_escape(row.source)} | "
            f"{'정상' if row.ok else '실패'} | {row.count} | {markdown_escape(row.detail)} |"
        )

    failed = [row for row in health if not row.ok]
    lines.extend([
        "",
        "## 한계와 검토 원칙",
        "",
        "- 공개 웹, RSS, 공개 API, 공개 GitHub·PyPI·arXiv에 노출되지 않은 자료는 수집할 수 없습니다.",
        "- 로그인·유료 데이터베이스, 검색 미색인 자료, 동적 페이지, 이미지·스캔 PDF만 제공되는 자료는 누락될 수 있습니다.",
        "- `AI`와 `재무·세무·회계` 맥락을 동시에 요구하는 엄격한 필터 때문에 경계 사례를 놓칠 수 있습니다.",
        "- 기업 발표의 생산성·정확도 수치는 공급업체 주장일 수 있으며 독립 검증 여부를 별도로 표시해야 합니다.",
        "- 오픈소스는 이름이나 별 개수만으로 채택하지 말고 라이선스, 최근 커밋, 보안, 테스트, 데이터 반출 구조를 확인해야 합니다.",
        "- 중요도·분류·TAXiA/CLOA 시사점은 규칙 기반 1차 판정이며 최종 세무·회계·법률 판단이 아닙니다.",
    ])
    if failed:
        lines.append(f"- 이번 실행에서 실패한 소스가 {len(failed)}개 있습니다. 상태표와 diagnostics artifact를 확인해야 합니다.")
    lines.append("")
    return "\n".join(lines)


def render_issue_body(
    *,
    report_date: dt.date,
    run_at: dt.datetime,
    items: list[Item],
    health: list[Health],
    timezone: ZoneInfo,
    repository: str,
    report_path: str,
    config: dict[str, Any],
) -> str:
    sorted_items = sorted(items, key=item_sort_key)
    report_url = f"https://github.com/{repository}/blob/main/{report_path}"
    lines = [
        f"# {report_date.isoformat()} AI 재무·세무·회계 자동 모니터링",
        "",
        f"**실행:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST  ",
        f"**당일 누적:** {len(sorted_items)}개  ",
        f"**전체 상세 보고서:** [{report_path}]({report_url})",
        "",
    ]
    if not sorted_items:
        lines.extend([
            "설정된 공개 소스에서 새롭거나 의미 있는 변화를 확인하지 못했습니다. 이는 변화가 없다는 확정 결론은 아닙니다.",
            "",
        ])
    else:
        lines.extend(["## 우선 검토", ""])
        issue_items = [item for item in sorted_items if item.priority in {"P0", "P1"}]
        if not issue_items:
            issue_items = sorted_items[:5]
        for item in issue_items[: int(config.get("max_issue_items", 40))]:
            lines.extend([
                f"- **{item.priority}** · **{item.track}/{item.category}** · [{item.title}]({item.url})",
                f"  - 발표·업데이트: {local_date_time(item.published_at, timezone)} KST",
                f"  - TAXiA/CLOA: {item.impact}",
                f"  - 출처: {item.source} · 신뢰도 {item.confidence} · 상태 {item.status}",
            ])
        lines.append("")
    failed = [row for row in health if not row.ok]
    lines.extend([
        "## 수집 상태",
        "",
        f"정상 {len(health) - len(failed)}개 / 실패 {len(failed)}개",
    ])
    for row in failed[:20]:
        lines.append(f"- 실패 · **{row.group}/{row.source}** — {row.detail}")
    lines.extend([
        "",
        "> 공개 소스 자동 수집·규칙 기반 분류입니다. 원문, 수치, 시행일, 적용범위, 라이선스와 법적 효력은 별도 검토해야 합니다.",
        "",
    ])
    body = "\n".join(lines)
    if len(body) > 62000:
        body = body[:61500] + f"\n\n본문이 길어 잘렸습니다. [전체 보고서]({report_url})를 확인하십시오.\n"
    return body


def collect(
    config: dict[str, Any],
    state: dict[str, Any],
    since: dt.datetime,
    client: HttpClient,
) -> tuple[list[Item], list[Health], dict[str, Any]]:
    """Collect all configured sources concurrently with per-source isolation.

    Public monitoring is I/O-bound and may involve more than 80 HTTP requests.
    Running each source sequentially makes a single timeout dominate the whole
    workflow. Each configured source therefore executes in an isolated worker;
    aggregation remains single-threaded so state and diagnostics are deterministic.
    """
    tasks: list[tuple[str, str, Any]] = []

    for row in config.get("news_queries", []):
        tasks.append((
            "뉴스·공식기관",
            row["name"],
            lambda row=row: fetch_google_news(client, row=row, since=since, config=config),
        ))

    for row in config.get("arxiv_queries", []):
        tasks.append(("논문", row["name"], lambda row=row: fetch_arxiv(client, row, since)))

    for asset in config.get("github_repositories", []):
        tasks.append((
            "GitHub 고정 추적",
            asset["repo"],
            lambda asset=asset: fetch_github_repo(client, asset, since, state),
        ))

    for row in config.get("github_discovery_queries", []):
        tasks.append((
            "GitHub 신규 발견",
            row["name"],
            lambda row=row: fetch_github_discovery(client, row, since),
        ))

    for asset in config.get("pypi_packages", []):
        tasks.append((
            "PyPI",
            asset["package"],
            lambda asset=asset: fetch_pypi(client, asset, since, state),
        ))

    for asset in config.get("web_snapshots", []):
        tasks.append((
            "공식 페이지 변경",
            asset["name"],
            lambda asset=asset: fetch_snapshot(client, asset, state),
        ))

    federal = config.get("federal_register")
    if federal:
        tasks.append((
            "공식 규정 API",
            federal["name"],
            lambda federal=federal: fetch_federal_register(client, federal, since),
        ))

    items: list[Item] = []
    health: list[Health] = []
    snapshot_updates: dict[str, Any] = {}
    workers = max(1, min(int(config.get("max_workers", 8)), 16, len(tasks) or 1))

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="finance-monitor") as pool:
        future_map = {
            pool.submit(callback): (group, name)
            for group, name, callback in tasks
        }
        for future in concurrent.futures.as_completed(future_map):
            group, name = future_map[future]
            try:
                produced = future.result()
                if isinstance(produced, tuple):
                    local_items, local_snapshots = produced
                else:
                    local_items, local_snapshots = produced, {}
                items.extend(local_items)
                snapshot_updates.update(local_snapshots)
                health.append(Health(name, group, True, len(local_items)))
            except Exception as exc:  # source isolation is intentional
                health.append(Health(name, group, False, 0, f"{type(exc).__name__}: {str(exc)[:300]}"))

    minimum_score = int(config.get("min_report_score", 28))
    accepted = [item for item in merge_duplicate_items(items) if item.score >= minimum_score]
    return accepted, health, snapshot_updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI finance/tax/accounting daily monitor")
    parser.add_argument("--config", default="config/finance_sources.json")
    parser.add_argument("--state-file", default=".monitor/finance-tax-ai-state.json")
    parser.add_argument("--output-dir", default="reports-finance-tax-ai")
    parser.add_argument("--work-dir", default="out-finance-tax-ai")
    parser.add_argument("--lookback-hours", type=int, default=40)
    parser.add_argument("--now", help="ISO-8601 UTC timestamp for deterministic tests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = Path.cwd()
    config = load_json(root / args.config, {})
    if not config:
        print(f"Configuration not found or invalid: {args.config}", file=sys.stderr)
        return 2

    timezone = ZoneInfo(config.get("timezone", "Asia/Seoul"))
    run_at = parse_datetime(args.now) if args.now else now_utc()
    assert run_at is not None
    state_path = root / args.state_file
    state = load_json(
        state_path,
        {"schema_version": 2, "monitor_id": config.get("monitor_id"), "last_success_at": None, "seen": {}, "snapshots": {}},
    )
    last_success = parse_datetime(state.get("last_success_at"))
    overlap = dt.timedelta(hours=int(config.get("overlap_hours", 8)))
    lookback = run_at - dt.timedelta(hours=max(1, args.lookback_hours))
    since = max(lookback, last_success - overlap) if last_success else lookback

    client = HttpClient(token=os.environ.get("GITHUB_TOKEN"))
    collected, health, snapshot_updates = collect(config, state, since, client)

    seen: dict[str, str] = dict(state.get("seen", {}))
    new_items = [item for item in collected if item.uid not in seen]
    for item in collected:
        seen[item.uid] = isoformat(run_at)

    cutoff = run_at - dt.timedelta(days=int(config.get("dedup_days", 180)))
    seen = {
        uid: stamp
        for uid, stamp in seen.items()
        if (parse_datetime(stamp) or run_at) >= cutoff
    }

    report_date = run_at.astimezone(timezone).date()
    relative_dir = Path(str(report_date.year)) / f"{report_date.month:02d}"
    report_rel_path = Path(args.output_dir) / relative_dir / f"{report_date.isoformat()}.md"
    data_rel_path = Path(args.output_dir) / relative_dir / f"{report_date.isoformat()}.json"
    existing_payload = load_json(root / data_rel_path, {"items": []})
    existing_items = [
        Item.from_dict(row)
        for row in existing_payload.get("items", [])
        if isinstance(row, dict)
    ]
    daily_items = merge_duplicate_items(existing_items + new_items)
    daily_items = sorted(daily_items, key=item_sort_key)[: int(config.get("max_report_items", 200))]

    repository = os.environ.get("GITHUB_REPOSITORY", "LifeIsMoment/news-agent")
    report_text = render_report(
        report_date=report_date,
        run_at=run_at,
        since=since,
        items=daily_items,
        health=health,
        timezone=timezone,
        repository=repository,
        config=config,
    )
    issue_prefix = config.get("issue_title_prefix", "[AI 재무·세무·회계]")
    issue_title = f"{issue_prefix} {report_date.isoformat()} 자동 모니터링"
    issue_body = render_issue_body(
        report_date=report_date,
        run_at=run_at,
        items=daily_items,
        health=health,
        timezone=timezone,
        repository=repository,
        report_path=report_rel_path.as_posix(),
        config=config,
    )

    work_dir = root / args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "issue_title.txt").write_text(issue_title + "\n", encoding="utf-8")
    (work_dir / "issue_body.md").write_text(issue_body, encoding="utf-8")
    (work_dir / "summary.md").write_text(report_text[:60000], encoding="utf-8")
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for item in daily_items:
        counts[item.priority] = counts.get(item.priority, 0) + 1
    save_json(work_dir / "metadata.json", {
        "monitor_id": config.get("monitor_id"),
        "date": report_date.isoformat(),
        "new_items": len(new_items),
        "daily_items": len(daily_items),
        "priority_counts": counts,
        "health_ok": len([row for row in health if row.ok]),
        "health_failed": len([row for row in health if not row.ok]),
        "report_path": report_rel_path.as_posix(),
    })

    if not args.dry_run:
        (root / report_rel_path).parent.mkdir(parents=True, exist_ok=True)
        (root / report_rel_path).write_text(report_text, encoding="utf-8")
        save_json(root / data_rel_path, {
            "schema_version": 2,
            "monitor_id": config.get("monitor_id"),
            "date": report_date.isoformat(),
            "generated_at": isoformat(run_at),
            "items": [item.to_dict() for item in daily_items],
            "health": [row.to_dict() for row in health],
        })
        snapshots = dict(state.get("snapshots", {}))
        snapshots.update(snapshot_updates)
        save_json(state_path, {
            "schema_version": 2,
            "monitor_id": config.get("monitor_id"),
            "last_success_at": isoformat(run_at),
            "seen": seen,
            "snapshots": snapshots,
        })

    print(json.dumps({
        "monitor_id": config.get("monitor_id"),
        "run_at": isoformat(run_at),
        "since": isoformat(since),
        "new_items": len(new_items),
        "daily_items": len(daily_items),
        "priority_counts": counts,
        "sources_ok": len([row for row in health if row.ok]),
        "sources_failed": len([row for row in health if not row.ok]),
        "report": report_rel_path.as_posix(),
    }, ensure_ascii=False))

    healthy = len([row for row in health if row.ok])
    min_healthy = int(config.get("min_healthy_sources", 8))
    critical_groups = set(config.get("critical_source_groups", []))
    healthy_groups = {row.group for row in health if row.ok}
    if healthy < min_healthy or not critical_groups.issubset(healthy_groups):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
