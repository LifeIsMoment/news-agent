#!/usr/bin/env python3
"""Daily TAXiA/CLOA and AI tax/legal monitoring.

The collector intentionally uses only Python's standard library so the scheduled
workflow does not depend on third-party package availability. It gathers public
metadata and RSS/API results, performs deterministic classification, preserves a
local audit trail, and writes a full Markdown report plus a compact GitHub issue.

This is a discovery system, not a legal database or a substitute for professional
review. Feed snippets and automated classifications are labelled accordingly.
"""

from __future__ import annotations

import argparse
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

USER_AGENT = (
    "LifeIsMoment-AI-Tax-Legal-Monitor/1.0 "
    "(+https://github.com/LifeIsMoment/news-agent)"
)
UTC = dt.timezone.utc

OFFICIAL_DOMAINS = {
    "nts.go.kr", "moef.go.kr", "pipc.go.kr", "law.go.kr", "assembly.go.kr",
    "likms.assembly.go.kr", "scourt.go.kr", "ccourt.go.kr", "ftc.go.kr",
    "fsc.go.kr", "fss.or.kr", "mcst.go.kr", "copyright.or.kr", "moel.go.kr",
    "kisa.or.kr", "digital-strategy.ec.europa.eu", "commission.europa.eu",
    "edpb.europa.eu", "competition-policy.ec.europa.eu",
    "digital-markets-act.ec.europa.eu", "taxation-customs.ec.europa.eu",
    "curia.europa.eu", "federalregister.gov", "ftc.gov", "justice.gov",
    "irs.gov", "treasury.gov", "copyright.gov", "uspto.gov", "sec.gov",
    "gov.uk", "ico.org.uk", "cma.gov.uk", "ppc.go.jp", "meti.go.jp",
    "digital.go.jp", "cac.gov.cn", "samr.gov.cn", "chinatax.gov.cn",
    "oecd.org", "wipo.int", "github.com", "api.github.com", "pypi.org",
    "huggingface.co", "xaikorea.github.io"
}

URGENT_TERMS = {
    "시행", "발효", "공포", "확정", "판결", "과징금", "제재", "처분", "마감",
    "의무", "위반", "긴급", "effective", "enters into force", "enforcement",
    "penalty", "fine", "judgment", "deadline", "mandatory", "binding",
    "regulation", "final rule", "injunction", "sanction", "breach"
}

HIGH_TERMS = {
    "법률", "법안", "시행령", "고시", "지침", "가이드라인", "유권해석", "예규",
    "입법예고", "행정예고", "조사", "감사", "개정", "결정", "guideline", "guidance",
    "rule", "bill", "act", "consultation", "decision", "investigation", "amendment",
    "code of practice", "policy", "framework"
}

CATEGORY_TERMS: list[tuple[str, set[str]]] = [
    ("TAXiA·CLOA", {"taxia", "택시아", "taxia-core", "xaikorea", "엑스에이아이코리아", "cloa 엔진", "cloa engine"}),
    ("세무·조세", {"세무", "세법", "조세", "법인세", "부가가치세", "원천징수", "세액공제", "이전가격", "tax", "vat", "irs", "treasury", "taxation", "customs"}),
    ("개인정보·데이터", {"개인정보", "데이터 보호", "국외이전", "gdpr", "privacy", "personal data", "data protection", "automated decision"}),
    ("저작권·지식재산", {"저작권", "특허", "상표", "학습데이터", "copyright", "patent", "trademark", "intellectual property", "training data"}),
    ("경쟁·플랫폼", {"공정거래", "경쟁법", "플랫폼", "dma", "독점", "competition", "antitrust", "gatekeeper"}),
    ("노동·채용", {"노동", "근로자", "채용", "평가", "고용", "employment", "worker", "hiring", "workplace"}),
    ("금융·소비자", {"금융", "핀테크", "신용", "소비자", "finance", "financial", "credit", "consumer", "sec"}),
    ("보안·책임", {"보안", "사이버", "침해", "제품책임", "손해배상", "security", "cyber", "liability", "safety", "incident"}),
    ("AI 규제·거버넌스", {"인공지능", "생성형ai", "ai act", "artificial intelligence", "algorithm", "알고리즘", "agentic", "에이전틱"}),
]

JURISDICTION_ORDER = {
    "대한민국": 0, "EU": 1, "미국": 2, "영국": 3, "일본": 4,
    "중국": 5, "국제": 6, "글로벌": 7, "제품 생태계": 8, "시장": 9,
}


@dataclasses.dataclass
class Item:
    uid: str
    title: str
    url: str
    source: str
    published_at: str
    jurisdiction: str
    category: str
    kind: str
    summary: str
    importance: str
    score: int
    status: str
    evidence: str
    relevance: str
    query_names: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        allowed = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclasses.dataclass
class Health:
    source: str
    ok: bool
    count: int
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class HttpClient:
    def __init__(self, token: str | None = None, timeout: int = 25) -> None:
        self.token = token
        self.timeout = timeout

    def get_bytes(self, url: str, *, accept: str | None = None) -> bytes:
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
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
                    time.sleep(1.5 * (attempt + 1))
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


def strip_html(value: str, max_len: int = 700) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def normalize_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣一-龥ぁ-ゟァ-ヿ]+", "", value.lower())


def canonical_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        query = [
            (k, v) for k, v in query
            if not k.lower().startswith("utm_")
            and k.lower() not in {"gclid", "fbclid", "ref", "source"}
        ]
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), ""))
    except ValueError:
        return value


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).netloc.lower().split(":", 1)[0].removeprefix("www.")
    except ValueError:
        return ""


def is_official(url: str) -> bool:
    host = host_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)


def make_uid(title: str, url: str, published_at: str, kind: str) -> str:
    base = canonical_url(url)
    event_kinds = {
        "official_snapshot", "github_activity", "github_release",
        "pypi_release", "huggingface_update", "official_rule",
    }
    if kind in event_kinds:
        base = f"{base}|{normalize_text(title)}|{published_at}|{kind}"
    elif "news.google.com/rss/articles/" in base or not base:
        base = f"{normalize_text(title)}|{published_at[:10]}|{kind}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def classify_category(text: str) -> str:
    lowered = text.lower()
    best = ("기타", 0)
    for category, terms in CATEGORY_TERMS:
        score = sum(1 for term in terms if term in lowered)
        if score > best[1]:
            best = (category, score)
    return best[0]


def brand_relevant(text: str, url: str, brand_cfg: dict[str, Any]) -> bool:
    lowered = f"{text} {url}".lower()
    exclusions = [x.lower() for x in brand_cfg.get("exclude_terms", [])]
    contexts = [x.lower() for x in brand_cfg.get("context_terms", [])]

    high_precision = (
        "taxia-core" in lowered
        or "xaikorea/taxia" in lowered
        or "xaikorea.github.io/taxia" in lowered
        or "cloa 엔진" in lowered
        or "cloa engine" in lowered
    )
    has_context = any(term in lowered for term in contexts)
    has_exclusion = any(term in lowered for term in exclusions)

    if high_precision:
        return True
    if has_exclusion and not ("세무" in lowered or "taxia" in lowered or "택시아" in lowered):
        return False
    if "택시아" in lowered:
        return has_context
    if re.search(r"\btaxia\b", lowered, flags=re.IGNORECASE):
        return has_context
    if "xaikorea" in lowered or "엑스에이아이코리아" in lowered:
        return has_context and not has_exclusion
    if re.search(r"\bcloa\b", lowered, flags=re.IGNORECASE) or "클로아" in lowered:
        return has_context and any(x in lowered for x in ("taxia", "택시아", "xaikorea", "엑스에이아이코리아", "세무", "회계", "세법"))
    return False


def calculate_importance(
    text: str,
    *,
    url: str,
    kind: str,
    category: str,
    brand_match: bool = False,
) -> tuple[int, str]:
    lowered = text.lower()
    score = 10
    if is_official(url):
        score += 18
    if kind in {"github_release", "pypi_release", "huggingface_update", "official_snapshot"}:
        score += 18
    if kind in {"brand_news", "github_release", "pypi_release"} or brand_match:
        score += 30
    if category == "세무·조세":
        score += 7
    if any(term.lower() in lowered for term in URGENT_TERMS):
        score += 24
    if any(term.lower() in lowered for term in HIGH_TERMS):
        score += 12
    if any(term in lowered for term in ("과징금", "벌금", "criminal", "penalty", "fine", "sanction", "injunction")):
        score += 12
    if any(term in lowered for term in ("시행일", "effective date", "deadline", "마감", "발효")):
        score += 10
    if kind == "market_news":
        score -= 5
    score = max(0, min(score, 100))
    if score >= 75:
        label = "긴급"
    elif score >= 55:
        label = "높음"
    elif score >= 35:
        label = "보통"
    else:
        label = "낮음"
    return score, label


def status_for(text: str, url: str, kind: str) -> str:
    lowered = text.lower()
    if kind in {"github_release", "pypi_release", "huggingface_update", "official_snapshot", "github_activity"}:
        return "공식 자산 변경"
    if is_official(url) and any(term.lower() in lowered for term in URGENT_TERMS | HIGH_TERMS):
        return "공식 공표·자동 판독"
    if kind in {"brand_news", "market_news", "regulatory_news"}:
        return "RSS 색인·원문 확인 필요"
    return "자동 수집"


def relevance_for(text: str, category: str, kind: str, brand_match: bool) -> str:
    lowered = text.lower()
    if brand_match:
        return "TAXiA·CLOA·XAIKOREA의 제품, 평판, 기술자산 또는 사업환경에 직접 관련"
    if kind == "market_news":
        return "세무·회계·리걸테크 경쟁환경과 제품 포지셔닝에 관련"
    mapping = {
        "세무·조세": "TAXiA의 세법 지식·답변·증빙 범위에 영향을 줄 수 있음",
        "개인정보·데이터": "CLOA/TAXiA의 데이터 수집·학습·로그·국외이전 통제에 영향을 줄 수 있음",
        "저작권·지식재산": "학습데이터, 생성물, 소프트웨어·브랜드 권리관계에 영향을 줄 수 있음",
        "경쟁·플랫폼": "AI 서비스의 시장접근, 제휴, 플랫폼 의존성과 경쟁전략에 영향을 줄 수 있음",
        "노동·채용": "AI 업무보조·평가 기능의 노동법 및 조직 운영 리스크에 관련",
        "금융·소비자": "전문가용 AI의 설명·광고·소비자보호·금융규제 리스크에 관련",
        "보안·책임": "전문가용 AI의 보안, 오류책임, 감사추적과 사고대응에 관련",
        "AI 규제·거버넌스": "AI 제공자·배포자 의무와 거버넌스 설계에 영향을 줄 수 있음",
    }
    return mapping.get(category, "세무·법률 AI 사업과의 관련성은 원문 검토가 필요")


def google_locale_params(locale: str) -> dict[str, str]:
    if locale == "ja":
        return {"hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    if locale == "zh":
        return {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    if locale == "en":
        return {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    return {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}


def fetch_google_news(
    client: HttpClient,
    *,
    query: str,
    name: str,
    jurisdiction: str,
    locale: str,
    since: dt.datetime,
    kind: str,
    brand_cfg: dict[str, Any],
) -> list[Item]:
    params = {"q": f"{query} when:4d", **google_locale_params(locale)}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    raw = client.get_bytes(url)
    root = ET.fromstring(raw)
    result: list[Item] = []
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
        is_brand = brand_relevant(combined, link + " " + source_url, brand_cfg)
        if kind == "brand_news" and not is_brand:
            continue
        category = "TAXiA·CLOA" if is_brand else classify_category(combined)
        # AUTO-QUALITY: regulatory-misc-filter-v1
        # Search-engine sidebars can match the query even when the actual document
        # has no tax, legal, data, security, labour, financial or AI relevance.
        if kind == "regulatory_news" and category == "기타" and not is_brand:
            continue
        score, importance = calculate_importance(
            combined,
            url=source_url or link,
            kind=kind,
            category=category,
            brand_match=is_brand,
        )
        published_str = isoformat(published)
        result.append(Item(
            uid=make_uid(title, link, published_str, kind),
            title=title,
            url=link,
            source=source,
            published_at=published_str,
            jurisdiction=jurisdiction,
            category=category,
            kind=kind,
            summary=description or "RSS 제목만 수집됨. 원문 확인 필요.",
            importance=importance,
            score=score,
            status=status_for(combined, source_url or link, kind),
            evidence="Google News RSS 색인. 링크의 원문·발표기관·시행일을 확인해야 함.",
            relevance=relevance_for(combined, category, kind, is_brand),
            query_names=[name],
        ))
    return result


def fetch_github_repo(
    client: HttpClient,
    repo: str,
    since: dt.datetime,
    state: dict[str, Any],
) -> tuple[list[Item], dict[str, Any]]:
    encoded_repo = urllib.parse.quote(repo, safe="/")
    base = f"https://api.github.com/repos/{encoded_repo}"
    metadata = client.get_json(base)
    snapshot_key = f"github_repo:{repo}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {
        "pushed_at": metadata.get("pushed_at"),
        "updated_at": metadata.get("updated_at"),
        "stargazers_count": metadata.get("stargazers_count"),
        "forks_count": metadata.get("forks_count"),
        "open_issues_count": metadata.get("open_issues_count"),
        "default_branch": metadata.get("default_branch"),
    }
    items: list[Item] = []
    if previous is None or snapshot != previous:
        baseline = previous is None
        title = f"{repo} GitHub 저장소 {'기준선 등록' if baseline else '메타데이터 변경'}"
        summary = (
            f"최근 push {snapshot.get('pushed_at')}; stars {snapshot.get('stargazers_count')}; "
            f"forks {snapshot.get('forks_count')}; open issues {snapshot.get('open_issues_count')}."
        )
        score, importance = calculate_importance(
            title + " " + summary, url=metadata.get("html_url", ""), kind="github_activity",
            category="TAXiA·CLOA", brand_match=True,
        )
        items.append(Item(
            uid=make_uid(title, metadata.get("html_url", ""), snapshot.get("updated_at") or "", "github_activity"),
            title=title,
            url=metadata.get("html_url", f"https://github.com/{repo}"),
            source="GitHub API",
            published_at=isoformat(parse_datetime(snapshot.get("updated_at")) or now_utc()),
            jurisdiction="제품 생태계",
            category="TAXiA·CLOA",
            kind="github_activity",
            summary=summary,
            importance=importance,
            score=score,
            status="공식 자산 변경" if not baseline else "공식 자산 기준선",
            evidence="GitHub 공식 REST API 메타데이터",
            relevance="TAXiA 공개 저장소의 개발활동·관심도·이슈 변화를 직접 추적",
            query_names=[repo],
        ))

    releases = client.get_json(base + "/releases?per_page=30")
    for index, release in enumerate(releases):
        published = parse_datetime(release.get("published_at") or release.get("created_at"))
        if published is None:
            continue
        if previous is not None and published < since:
            continue
        if previous is None and index > 1:
            break
        title = f"{repo} 릴리스 {release.get('tag_name') or release.get('name') or ''}".strip()
        summary = strip_html(release.get("body") or "릴리스 설명 없음")
        score, importance = calculate_importance(title + " " + summary, url=release.get("html_url", ""), kind="github_release", category="TAXiA·CLOA", brand_match=True)
        items.append(Item(
            uid=make_uid(title, release.get("html_url", ""), isoformat(published), "github_release"),
            title=title,
            url=release.get("html_url", f"https://github.com/{repo}/releases"),
            source="GitHub Releases",
            published_at=isoformat(published),
            jurisdiction="제품 생태계",
            category="TAXiA·CLOA",
            kind="github_release",
            summary=summary,
            importance=importance,
            score=score,
            status="공식 릴리스",
            evidence="GitHub 공식 Releases API",
            relevance="TAXiA 코드·기능·의존성·배포 변경을 직접 반영",
            query_names=[repo],
        ))

    commit_params = {"per_page": 5} if previous is None else {"since": isoformat(since), "per_page": 100}
    commits_url = base + "/commits?" + urllib.parse.urlencode(commit_params)
    commits = client.get_json(commits_url)
    if previous is None:
        commits = commits[:5]
    for commit in commits:
        commit_data = commit.get("commit", {})
        commit_date = parse_datetime(commit_data.get("committer", {}).get("date") or commit_data.get("author", {}).get("date"))
        if commit_date is None:
            continue
        message = (commit_data.get("message") or "").splitlines()[0].strip()
        sha = (commit.get("sha") or "")[:10]
        title = f"{repo} 커밋 {sha}: {message}"
        score, importance = calculate_importance(title, url=commit.get("html_url", ""), kind="github_activity", category="TAXiA·CLOA", brand_match=True)
        items.append(Item(
            uid=make_uid(title, commit.get("html_url", ""), isoformat(commit_date), "github_activity"),
            title=title,
            url=commit.get("html_url", f"https://github.com/{repo}/commits"),
            source="GitHub Commits",
            published_at=isoformat(commit_date),
            jurisdiction="제품 생태계",
            category="TAXiA·CLOA",
            kind="github_activity",
            summary=message or "커밋 메시지 없음",
            importance=importance,
            score=score,
            status="공식 코드 변경",
            evidence="GitHub 공식 Commits API",
            relevance="TAXiA 소스코드와 문서의 변경을 직접 추적",
            query_names=[repo],
        ))

    issue_params: dict[str, Any] = {"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"}
    if previous is not None:
        issue_params["since"] = isoformat(since)
    issues_url = base + "/issues?" + urllib.parse.urlencode(issue_params)
    issues = client.get_json(issues_url)
    if previous is None:
        issues = issues[:10]
    for issue in issues:
        updated = parse_datetime(issue.get("updated_at"))
        if updated is None:
            continue
        is_pr = "pull_request" in issue
        type_name = "PR" if is_pr else "이슈"
        title = f"{repo} {type_name} #{issue.get('number')}: {issue.get('title', '').strip()}"
        summary = strip_html(issue.get("body") or f"상태: {issue.get('state')}")
        score, importance = calculate_importance(title + " " + summary, url=issue.get("html_url", ""), kind="github_activity", category="TAXiA·CLOA", brand_match=True)
        items.append(Item(
            uid=make_uid(title, issue.get("html_url", ""), isoformat(updated), "github_activity"),
            title=title,
            url=issue.get("html_url", f"https://github.com/{repo}/issues"),
            source="GitHub Issues/PRs",
            published_at=isoformat(updated),
            jurisdiction="제품 생태계",
            category="TAXiA·CLOA",
            kind="github_activity",
            summary=summary,
            importance=importance,
            score=score,
            status=f"공식 {type_name} 활동",
            evidence="GitHub 공식 Issues API",
            relevance="버그·요구사항·기능개발·외부 기여 흐름을 직접 추적",
            query_names=[repo],
        ))
    return items, {snapshot_key: snapshot}


def fetch_github_global(client: HttpClient, since: dt.datetime, brand_cfg: dict[str, Any]) -> list[Item]:
    queries = [
        ("repositories", 'TAXiA OR taxia-core OR XAIKOREA in:name,description,readme'),
        ("issues", '"taxia-core" OR "XAIKOREA" OR "TAXiA"'),
    ]
    result: list[Item] = []
    for endpoint, query in queries:
        params = {"q": query, "sort": "updated", "order": "desc", "per_page": 50}
        payload = client.get_json(f"https://api.github.com/search/{endpoint}?" + urllib.parse.urlencode(params))
        for row in payload.get("items", []):
            updated = parse_datetime(row.get("updated_at") or row.get("pushed_at"))
            if updated is None or updated < since:
                continue
            if endpoint == "repositories":
                title = f"GitHub 저장소: {row.get('full_name')}"
                summary = strip_html(row.get("description") or "설명 없음")
                url = row.get("html_url", "")
            else:
                repo_url = row.get("repository_url", "").replace("https://api.github.com/repos/", "")
                title = f"GitHub {repo_url} #{row.get('number')}: {row.get('title', '')}"
                summary = strip_html(row.get("body") or "본문 없음")
                url = row.get("html_url", "")
            combined = f"{title} {summary} {url}"
            # AUTO-QUALITY: strict-global-brand-filter-v1
            # Generic TaxIA/CLOA homonyms are common. Global GitHub discovery must
            # contain a high-precision TAXiA/XAIKOREA signal before it is reported.
            precise_global_signal = any(
                token in combined.lower()
                for token in (
                    "xaikorea", "taxia-core", "xaikorea0", "korean tax",
                    "한국 세법", "graph-rag", "xaikorea.github.io/taxia",
                )
            )
            if not precise_global_signal:
                continue
            if "lifeismoment/news-agent" in combined.lower():
                continue
            if not brand_relevant(combined, url, brand_cfg):
                continue
            score, importance = calculate_importance(combined, url=url, kind="github_activity", category="TAXiA·CLOA", brand_match=True)
            result.append(Item(
                uid=make_uid(title, url, isoformat(updated), "github_activity"),
                title=title,
                url=url,
                source="GitHub Search API",
                published_at=isoformat(updated),
                jurisdiction="제품 생태계",
                category="TAXiA·CLOA",
                kind="github_activity",
                summary=summary,
                importance=importance,
                score=score,
                status="공개 GitHub 언급·자동 판독",
                evidence="GitHub 공개 검색 API. 동명이인·포크 여부 확인 필요.",
                relevance="TAXiA·CLOA 관련 외부 저장소·이슈·통합 흔적을 탐지",
                query_names=[f"github:{endpoint}"],
            ))
    return result


def fetch_pypi(client: HttpClient, package: str, since: dt.datetime, state: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]:
    payload = client.get_json(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
    info = payload.get("info", {})
    latest = info.get("version")
    snapshot_key = f"pypi:{package}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {"version": latest, "requires_python": info.get("requires_python"), "project_url": info.get("project_url")}
    items: list[Item] = []
    for version, files in payload.get("releases", {}).items():
        dates = [parse_datetime(file.get("upload_time_iso_8601") or file.get("upload_time")) for file in files]
        dates = [x for x in dates if x is not None]
        if not dates:
            continue
        published = max(dates)
        if previous is not None and published < since and version == previous.get("version"):
            continue
        if previous is not None and published < since:
            continue
        if previous is None and version != latest:
            continue
        title = f"PyPI {package} {version} 릴리스"
        summary = f"최신 버전 {latest}; Python 요구사항 {info.get('requires_python') or '미표시'}; 파일 {len(files)}개."
        url = info.get("package_url") or f"https://pypi.org/project/{package}/{version}/"
        score, importance = calculate_importance(title + " " + summary, url=url, kind="pypi_release", category="TAXiA·CLOA", brand_match=True)
        items.append(Item(
            uid=make_uid(title, f"{url}#{version}", isoformat(published), "pypi_release"),
            title=title,
            url=url,
            source="PyPI JSON API",
            published_at=isoformat(published),
            jurisdiction="제품 생태계",
            category="TAXiA·CLOA",
            kind="pypi_release",
            summary=summary,
            importance=importance,
            score=score,
            status="공식 패키지 릴리스",
            evidence="PyPI 공식 JSON API",
            relevance="TAXiA 배포 버전·호환성·패키지 변경을 직접 추적",
            query_names=[package],
        ))
    return items, {snapshot_key: snapshot}


def fetch_huggingface(client: HttpClient, author: str, since: dt.datetime, state: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]:
    items: list[Item] = []
    snapshots: dict[str, Any] = {}
    for resource, singular in (("models", "model"), ("datasets", "dataset"), ("spaces", "space")):
        params = {"author": author, "limit": 100, "full": "true"}
        payload = client.get_json(f"https://huggingface.co/api/{resource}?" + urllib.parse.urlencode(params))
        if not isinstance(payload, list):
            continue
        for row in payload:
            rid = row.get("id") or row.get("modelId") or row.get("name")
            if not rid:
                continue
            modified = parse_datetime(row.get("lastModified") or row.get("last_modified") or row.get("createdAt"))
            snapshot_key = f"hf:{singular}:{rid}"
            snapshot = {
                "lastModified": isoformat(modified),
                "downloads": row.get("downloads"),
                "likes": row.get("likes"),
                "sha": row.get("sha"),
            }
            previous = state.get("snapshots", {}).get(snapshot_key)
            snapshots[snapshot_key] = snapshot
            if previous is not None and snapshot == previous:
                continue
            if previous is not None and modified is not None and modified < since:
                continue
            title = f"Hugging Face {singular}: {rid} {'기준선 등록' if previous is None else '업데이트'}"
            url = f"https://huggingface.co/{'datasets/' if singular == 'dataset' else 'spaces/' if singular == 'space' else ''}{rid}"
            summary = f"lastModified {snapshot['lastModified'] or '미표시'}; downloads {snapshot.get('downloads')}; likes {snapshot.get('likes')}; sha {str(snapshot.get('sha') or '')[:12]}."
            score, importance = calculate_importance(title + " " + summary, url=url, kind="huggingface_update", category="TAXiA·CLOA", brand_match=True)
            items.append(Item(
                uid=make_uid(title, url, snapshot["lastModified"], "huggingface_update"),
                title=title,
                url=url,
                source="Hugging Face Hub API",
                published_at=snapshot["lastModified"] or isoformat(now_utc()),
                jurisdiction="제품 생태계",
                category="TAXiA·CLOA",
                kind="huggingface_update",
                summary=summary,
                importance=importance,
                score=score,
                status="공식 Hub 자산 변경" if previous is not None else "공식 Hub 자산 기준선",
                evidence="Hugging Face Hub 공개 API",
                relevance="TAXiA 관련 모델·데이터셋·Space 배포와 사용량 변화를 직접 추적",
                query_names=[author],
            ))
    return items, snapshots


def normalized_page_hash(raw: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def fetch_snapshot(client: HttpClient, url: str, state: dict[str, Any]) -> tuple[list[Item], dict[str, Any]]:
    raw = client.get_text(url)
    hash_value = normalized_page_hash(raw)
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    page_title = strip_html(title_match.group(1) if title_match else url)
    snapshot_key = f"web:{canonical_url(url)}"
    previous = state.get("snapshots", {}).get(snapshot_key)
    snapshot = {"sha256": hash_value, "title": page_title}
    if previous is not None and previous.get("sha256") == hash_value:
        return [], {snapshot_key: snapshot}
    baseline = previous is None
    title = f"공식 페이지 {'기준선 등록' if baseline else '내용 변경'}: {page_title}"
    score, importance = calculate_importance(title, url=url, kind="official_snapshot", category="TAXiA·CLOA", brand_match=True)
    item = Item(
        uid=make_uid(title, url + "#" + hash_value[:12], isoformat(now_utc()), "official_snapshot"),
        title=title,
        url=url,
        source=host_of(url),
        published_at=isoformat(now_utc()),
        jurisdiction="제품 생태계",
        category="TAXiA·CLOA",
        kind="official_snapshot",
        summary=f"정규화된 페이지 해시 {hash_value[:16]}. {'초기 기준선' if baseline else '이전 기준선과 상이'}.",
        importance=importance,
        score=score,
        status="공식 페이지 기준선" if baseline else "공식 페이지 변경 탐지",
        evidence="공개 웹페이지의 정규화 해시 비교. 변경 내용은 원문 대조 필요.",
        relevance="TAXiA 공식 문서·소개 페이지의 비정형 변경을 탐지",
        query_names=[url],
    )
    return [item], {snapshot_key: snapshot}


def fetch_federal_register(client: HttpClient, since: dt.datetime) -> list[Item]:
    params = {
        "conditions[term]": "artificial intelligence",
        "conditions[publication_date][gte]": since.date().isoformat(),
        "order": "newest",
        "per_page": 100,
    }
    payload = client.get_json("https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(params))
    result: list[Item] = []
    for row in payload.get("results", []):
        published = parse_datetime(row.get("publication_date"))
        if published is None or published < since - dt.timedelta(hours=24):
            continue
        title = strip_html(row.get("title") or "")
        abstract = strip_html(row.get("abstract") or "")
        agencies = row.get("agencies", [])
        agency_names = " ".join(
            str(a.get("name") or a.get("raw_name") or "") if isinstance(a, dict) else str(a)
            for a in agencies
        ) if isinstance(agencies, list) else str(agencies or "")
        combined = f"{title} {abstract} {agency_names}"
        category = classify_category(combined)
        url = row.get("html_url") or row.get("pdf_url") or ""
        score, importance = calculate_importance(combined, url=url, kind="official_rule", category=category)
        result.append(Item(
            uid=make_uid(title, url, isoformat(published), "official_rule"),
            title=title,
            url=url,
            source="U.S. Federal Register API",
            published_at=isoformat(published),
            jurisdiction="미국",
            category=category,
            kind="official_rule",
            summary=abstract or f"문서 유형: {row.get('type') or '미표시'}",
            importance=importance,
            score=score,
            status="미국 연방 공식 문서",
            evidence="Federal Register 공식 API",
            relevance=relevance_for(combined, category, "official_rule", False),
            query_names=["US-Federal-Register-API"],
        ))
    return result


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
        existing.query_names = sorted(set(existing.query_names + item.query_names))
        if item.score > existing.score:
            item.query_names = existing.query_names
            merged[key] = item
            if title_key:
                title_index[title_key] = key
        elif len(item.summary) > len(existing.summary):
            existing.summary = item.summary
    return list(merged.values())


def item_sort_key(item: Item) -> tuple[Any, ...]:
    published = parse_datetime(item.published_at) or dt.datetime.min.replace(tzinfo=UTC)
    return (-item.score, JURISDICTION_ORDER.get(item.jurisdiction, 99), -published.timestamp(), item.title.lower())


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


def local_date_time(iso: str, timezone: ZoneInfo) -> str:
    value = parse_datetime(iso)
    if value is None:
        return "일시 불명"
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M")


def render_item(item: Item, timezone: ZoneInfo, number: int) -> str:
    summary = item.summary.strip() or "요약 없음"
    if len(summary) > 900:
        summary = summary[:899] + "…"
    query_text = ", ".join(item.query_names[:5])
    return "\n".join([
        f"### {number}. [{item.title}]({item.url})",
        "",
        f"- **중요도:** {item.importance} ({item.score}/100, 자동 산정)",
        f"- **일시:** {local_date_time(item.published_at, timezone)} KST",
        f"- **관할·분야:** {item.jurisdiction} · {item.category}",
        f"- **출처:** {item.source}",
        f"- **상태:** {item.status}",
        f"- **왜 관련되는가:** {item.relevance}",
        f"- **수집 근거:** {item.evidence}",
        f"- **검색 경로:** {query_text or '직접 API'}",
        "",
        summary,
        "",
    ])


def section_for_item(item: Item) -> str:
    if item.category == "TAXiA·CLOA" or item.jurisdiction == "제품 생태계":
        return "TAXiA·CLOA 직접 모니터링"
    if item.kind == "market_news" or item.jurisdiction == "시장":
        return "시장·경쟁 서비스"
    return "세무·법률·AI 규제"


def render_report(
    *,
    report_date: dt.date,
    run_at: dt.datetime,
    since: dt.datetime,
    items: list[Item],
    health: list[Health],
    timezone: ZoneInfo,
    repository: str,
    max_items: int,
) -> str:
    counts = {"긴급": 0, "높음": 0, "보통": 0, "낮음": 0}
    for item in items:
        counts[item.importance] = counts.get(item.importance, 0) + 1
    lines = [
        f"# AI 세무·법률 / TAXiA·CLOA 자동 모니터링 — {report_date.isoformat()}",
        "",
        f"- **실행 시각:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST",
        f"- **신규 수집 기준:** {since.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST 이후",
        f"- **누적 보고 항목:** {len(items)}개 (긴급 {counts['긴급']} · 높음 {counts['높음']} · 보통 {counts['보통']} · 낮음 {counts['낮음']})",
        f"- **저장소:** https://github.com/{repository}",
        "",
        "> 자동 수집·분류 보고서입니다. RSS 요약이나 검색 색인은 원문과 다를 수 있습니다. 사실, 시행일, 적용범위, 예외, 법적 효력은 반드시 1차 자료에서 다시 확인해야 합니다.",
        "",
        "## 오늘의 판단",
        "",
    ]
    if not items:
        lines.extend([
            "**새로 확인된 항목이 없습니다.** 이것은 변화가 없다는 확정 결론이 아니라, 설정된 공개 소스에서 신규 항목을 찾지 못했다는 뜻입니다.",
            "",
        ])
    else:
        top = sorted(items, key=item_sort_key)[:5]
        for item in top:
            lines.append(f"- **{item.importance}** · [{item.title}]({item.url}) — {item.relevance}")
        lines.append("")

    grouped: dict[str, list[Item]] = {
        "TAXiA·CLOA 직접 모니터링": [],
        "세무·법률·AI 규제": [],
        "시장·경쟁 서비스": [],
    }
    for item in sorted(items, key=item_sort_key)[:max_items]:
        grouped[section_for_item(item)].append(item)

    number = 1
    for section, section_items in grouped.items():
        lines.extend([f"## {section}", ""])
        if not section_items:
            lines.extend(["해당 섹션의 신규 항목 없음.", ""])
            continue
        for item in section_items:
            lines.append(render_item(item, timezone, number))
            number += 1

    lines.extend([
        "## 수집 소스 상태",
        "",
        "| 소스 | 상태 | 수집 건수 | 비고 |",
        "|---|---:|---:|---|",
    ])
    for row in sorted(health, key=lambda x: (not x.ok, x.source.lower())):
        lines.append(f"| {markdown_escape(row.source)} | {'정상' if row.ok else '실패'} | {row.count} | {markdown_escape(row.detail)} |")

    failed = [x for x in health if not x.ok]
    lines.extend([
        "",
        "## 한계 및 검토 원칙",
        "",
        "- 공개 웹, RSS, 공개 API에 노출되지 않은 자료는 수집할 수 없습니다.",
        "- 검색엔진 색인 지연, 사이트 차단, 동적 페이지, 삭제·수정된 문서 때문에 누락이 생길 수 있습니다.",
        "- `CLOA`와 `XAIKOREA`에는 동명·유사명 결과가 있어 세무·회계·TAXiA 문맥이 없는 결과는 자동 제외합니다.",
        "- 중요도·분야·관련성은 규칙 기반 자동 분류이며 법적 판단이 아닙니다.",
        "- 이 보고서는 개별 사안에 대한 법률·세무 자문이 아닙니다.",
    ])
    if failed:
        lines.append(f"- 이번 실행에서 실패한 소스가 {len(failed)}개 있습니다. 위 상태표를 확인해야 합니다.")
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
    max_items: int,
) -> str:
    sorted_items = sorted(items, key=item_sort_key)
    report_url = f"https://github.com/{repository}/blob/main/{report_path}"
    lines = [
        f"# {report_date.isoformat()} 자동 모니터링",
        "",
        f"**실행:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST  ",
        f"**누적 항목:** {len(sorted_items)}개  ",
        f"**전체 보고서:** [{report_path}]({report_url})",
        "",
    ]
    if not sorted_items:
        lines.extend([
            "설정된 공개 소스에서 신규 항목을 찾지 못했습니다. 이는 변화가 없다는 확정 결론이 아닙니다.",
            "",
        ])
    else:
        lines.extend(["## 우선 검토", ""])
        for item in sorted_items[:max_items]:
            lines.extend([
                f"- **{item.importance}** · **{item.jurisdiction}/{item.category}** · [{item.title}]({item.url})",
                f"  - {item.relevance}",
                f"  - 상태: {item.status} · 출처: {item.source}",
            ])
        lines.append("")
    failed = [x for x in health if not x.ok]
    lines.extend([
        "## 수집 상태",
        "",
        f"정상 {len(health) - len(failed)}개 / 실패 {len(failed)}개",
    ])
    for row in failed[:15]:
        lines.append(f"- 실패 · **{row.source}** — {row.detail}")
    lines.extend([
        "",
        "> 자동 수집·규칙 기반 분류입니다. 원문, 시행일, 적용범위와 법적 효력은 별도 검토해야 합니다.",
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
    items: list[Item] = []
    health: list[Health] = []
    snapshot_updates: dict[str, Any] = {}
    brand_cfg = config["brand"]

    def run_source(name: str, callback: Any) -> None:
        try:
            produced = callback()
            local_items: list[Item]
            local_snapshots: dict[str, Any]
            if isinstance(produced, tuple):
                local_items, local_snapshots = produced
            else:
                local_items, local_snapshots = produced, {}
            items.extend(local_items)
            snapshot_updates.update(local_snapshots)
            health.append(Health(name, True, len(local_items)))
        except Exception as exc:  # source isolation is intentional
            detail = f"{type(exc).__name__}: {str(exc)[:240]}"
            health.append(Health(name, False, 0, detail))

    for index, query in enumerate(brand_cfg.get("news_queries", []), start=1):
        run_source(
            f"Brand-News-{index}",
            lambda query=query, index=index: fetch_google_news(
                client,
                query=query,
                name=f"Brand-News-{index}",
                jurisdiction="글로벌",
                locale="ko",
                since=since,
                kind="brand_news",
                brand_cfg=brand_cfg,
            ),
        )

    for index, query in enumerate(config.get("market_news_queries", []), start=1):
        run_source(
            f"Market-News-{index}",
            lambda query=query, index=index: fetch_google_news(
                client,
                query=query,
                name=f"Market-News-{index}",
                jurisdiction="시장",
                locale="ko",
                since=since,
                kind="market_news",
                brand_cfg=brand_cfg,
            ),
        )

    for row in config.get("regulatory_news_queries", []):
        run_source(
            row["name"],
            lambda row=row: fetch_google_news(
                client,
                query=row["query"],
                name=row["name"],
                jurisdiction=row["jurisdiction"],
                locale=row.get("locale", "ko"),
                since=since,
                kind="regulatory_news",
                brand_cfg=brand_cfg,
            ),
        )

    for repo in brand_cfg.get("github_repositories", []):
        run_source(f"GitHub-Repo-{repo}", lambda repo=repo: fetch_github_repo(client, repo, since, state))
    run_source("GitHub-Global-Search", lambda: fetch_github_global(client, since, brand_cfg))

    for package in brand_cfg.get("pypi_packages", []):
        run_source(f"PyPI-{package}", lambda package=package: fetch_pypi(client, package, since, state))

    for author in brand_cfg.get("huggingface_authors", []):
        run_source(f"HuggingFace-{author}", lambda author=author: fetch_huggingface(client, author, since, state))

    for url in brand_cfg.get("web_snapshots", []):
        run_source(f"WebSnapshot-{host_of(url)}", lambda url=url: fetch_snapshot(client, url, state))

    run_source("US-Federal-Register-API", lambda: fetch_federal_register(client, since))
    return merge_duplicate_items(items), health, snapshot_updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI tax/legal and TAXiA/CLOA daily monitor")
    parser.add_argument("--config", default="config/sources.json")
    parser.add_argument("--state-file", default=".monitor/state.json")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--work-dir", default="out")
    parser.add_argument("--lookback-hours", type=int, default=36)
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
    state = load_json(state_path, {"schema_version": 1, "last_success_at": None, "seen": {}, "snapshots": {}})
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
        uid: stamp for uid, stamp in seen.items()
        if (parse_datetime(stamp) or run_at) >= cutoff
    }

    report_date = run_at.astimezone(timezone).date()
    rel_dir = Path(str(report_date.year)) / f"{report_date.month:02d}"
    report_rel_path = Path(args.output_dir) / rel_dir / f"{report_date.isoformat()}.md"
    data_rel_path = Path(args.output_dir) / rel_dir / f"{report_date.isoformat()}.json"
    existing_payload = load_json(root / data_rel_path, {"items": []})
    existing_items = [Item.from_dict(row) for row in existing_payload.get("items", []) if isinstance(row, dict)]
    daily_items = merge_duplicate_items(existing_items + new_items)
    daily_items = sorted(daily_items, key=item_sort_key)[: int(config.get("max_report_items", 160))]

    repository = os.environ.get("GITHUB_REPOSITORY", "LifeIsMoment/news-agent")
    report_text = render_report(
        report_date=report_date,
        run_at=run_at,
        since=since,
        items=daily_items,
        health=health,
        timezone=timezone,
        repository=repository,
        max_items=int(config.get("max_report_items", 160)),
    )
    issue_title = f"[AI 세무·법률/TAXiA·CLOA] {report_date.isoformat()} 자동 모니터링"
    issue_body = render_issue_body(
        report_date=report_date,
        run_at=run_at,
        items=daily_items,
        health=health,
        timezone=timezone,
        repository=repository,
        report_path=report_rel_path.as_posix(),
        max_items=int(config.get("max_issue_items", 40)),
    )

    work_dir = root / args.work_dir
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "issue_title.txt").write_text(issue_title + "\n", encoding="utf-8")
    (work_dir / "issue_body.md").write_text(issue_body, encoding="utf-8")
    (work_dir / "summary.md").write_text(report_text[:60000], encoding="utf-8")
    save_json(work_dir / "metadata.json", {
        "date": report_date.isoformat(),
        "new_items": len(new_items),
        "daily_items": len(daily_items),
        "health_ok": len([x for x in health if x.ok]),
        "health_failed": len([x for x in health if not x.ok]),
        "report_path": report_rel_path.as_posix(),
    })

    if not args.dry_run:
        (root / report_rel_path).parent.mkdir(parents=True, exist_ok=True)
        (root / report_rel_path).write_text(report_text, encoding="utf-8")
        save_json(root / data_rel_path, {
            "schema_version": 1,
            "date": report_date.isoformat(),
            "generated_at": isoformat(run_at),
            "items": [item.to_dict() for item in daily_items],
            "health": [row.to_dict() for row in health],
        })
        snapshots = dict(state.get("snapshots", {}))
        snapshots.update(snapshot_updates)
        save_json(state_path, {
            "schema_version": 1,
            "last_success_at": isoformat(run_at),
            "seen": seen,
            "snapshots": snapshots,
        })

    print(json.dumps({
        "run_at": isoformat(run_at),
        "since": isoformat(since),
        "new_items": len(new_items),
        "daily_items": len(daily_items),
        "sources_ok": len([x for x in health if x.ok]),
        "sources_failed": len([x for x in health if not x.ok]),
        "report": report_rel_path.as_posix(),
    }, ensure_ascii=False))

    # A broad monitor should not silently pass when nearly every source is unreachable.
    if len([x for x in health if x.ok]) < 3:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
