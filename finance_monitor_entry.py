#!/usr/bin/env python3
"""Run the finance monitor with a core-first, evidence-weighted policy.

TAXiA/CLOA activity is retained only as a small appendix. The primary report is
reserved for material finance, tax, accounting, audit, public-data, regulatory,
research, benchmark, and open-source signals.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Iterable

CONFIG_PATH = Path("config/finance_sources.json")
APPENDIX_TRACK = "참고: TAXiA·CLOA 직접 관련"
CORE_SECTION_ORDER = [
    "상용 서비스·기업 업데이트",
    "논문·벤치마크",
    "공공 데이터·API",
    "법·제도·감사",
    "오픈소스 프로젝트",
    APPENDIX_TRACK,
]
CORE_IMPACT = {
    "세무 AI·조세기술": "세법 검색, 신고 검증, 결정론적 세액 계산, 전문가 승인 구조에 직접 영향을 준다.",
    "회계 자동화·결산": "거래 분류, 전표·원장 검증, 계정 조정과 월말결산 자동화 수준을 판단하는 핵심 신호다.",
    "감사·내부통제·부정탐지": "감사 증적, 내부통제, 이상거래 탐지, 에이전트 권한과 책임 추적 설계에 중요하다.",
    "재무분석·FP&A·CFO": "재무 분석, 예산·현금흐름·예측, 경영 의사결정 품질과 검증 구조에 영향을 준다.",
    "AP·AR·인보이스": "증빙 수집, 필드 계보, 지급·수금·청구 및 매입·매출 검증 워크플로에 적용할 수 있다.",
    "문서 AI·OCR·XBRL": "세금계산서·영수증·공시 문서의 OCR, 표·주석·좌표 추출과 데이터 계보 품질에 중요하다.",
    "공공 데이터·API": "공식 데이터 수집, 스키마 버전, 정정 이력, 시행일·귀속연도 관리에 직접 영향을 준다.",
    "AI 규제·거버넌스": "데이터 격리, 모델·도구 권한, 사람 승인, 비용·로그·책임 관리 요구사항에 반영해야 한다.",
    "오픈소스·도구": "라이선스, 유지보수, 재현성, 보안, 데이터 반출과 국내 현지화 비용을 기준으로 평가해야 한다.",
    "논문·벤치마크": "완전정답률, 인용 정확도, 수치 계산, 시점 적용, 재현성 등 평가체계 고도화에 중요하다.",
}
GENERIC_COMMIT_TERMS = {
    "readme", "docs", "documentation", "style", "chore", "typo",
    "merge pull request", "bump version", "format", "lint", "emoji",
}
MATERIAL_REPOSITORY_TERMS = {
    "benchmark", "dataset", "evaluation", "tax", "vat", "accounting",
    "audit", "invoice", "ocr", "xbrl", "reconciliation", "fraud",
    "agent", "mcp", "financial statement", "internal control",
}
NOISE_ITEM_TERMS = {
    "채용", "모집", "입찰", "구인", "job opening", "hiring", "recruitment",
    "tender notice", "procurement notice", "webinar registration", "award ceremony",
    "sponsorship announcement",
}
PAPER_DOMAIN_TERMS = {
    "accounting", "financial statement", "financial reporting", "financial question answering",
    "financial reasoning", "finance benchmark", "tax", "taxation", "vat", "transfer pricing",
    "invoice", "receipt", "ledger", "bookkeeping", "audit firm", "external audit",
    "audit report", "assurance", "internal control", "sec filing", "xbrl",
    "회계", "세무", "조세", "재무제표", "감사보고서", "내부통제", "세금계산서",
}
SOURCE_RANK = {
    "official_primary": 0,
    "paper_primary": 1,
    "vendor_primary": 2,
    "package_primary": 3,
    "repository_primary": 4,
    "repository_discovery": 5,
    "secondary_index": 6,
}
TRACK_RANK = {track: index for index, track in enumerate(CORE_SECTION_ORDER)}


def _contains(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(str(term).lower() in lowered for term in terms)


def _priority(score: int) -> str:
    if score >= 75:
        return "P0"
    if score >= 55:
        return "P1"
    if score >= 35:
        return "P2"
    return "P3"


def _parse_time(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def is_taxia_item(item: Any) -> bool:
    haystack = " ".join([
        str(getattr(item, "track", "")),
        str(getattr(item, "title", "")),
        str(getattr(item, "source", "")),
        " ".join(str(value) for value in getattr(item, "query_names", []) or []),
    ]).lower()
    return any(token in haystack for token in (
        "taxia", "택시아", "taxia-core", "xaikorea", "cloa engine", "cloa 엔진",
    ))


def is_baseline_item(item: Any) -> bool:
    text = f"{getattr(item, 'title', '')} {getattr(item, 'status', '')} {getattr(item, 'summary', '')}".lower()
    return "기준선" in text or "baseline" in text


def is_generic_commit(item: Any) -> bool:
    if getattr(item, "kind", "") != "github_commit":
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()
    return _contains(text, GENERIC_COMMIT_TERMS) and not _contains(text, MATERIAL_REPOSITORY_TERMS)


def is_noise_item(item: Any) -> bool:
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()
    return _contains(text, NOISE_ITEM_TERMS)


def is_weak_paper_item(item: Any) -> bool:
    if getattr(item, "source_type", "") != "paper_primary":
        return False
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')}".lower()
    return not _contains(text, PAPER_DOMAIN_TERMS)


def is_core_item(item: Any) -> bool:
    return not any((
        is_taxia_item(item), is_baseline_item(item), is_generic_commit(item),
        is_noise_item(item), is_weak_paper_item(item),
    ))


def apply_core_first_policy(config: dict[str, Any]) -> dict[str, Any]:
    """Apply stable, idempotent policy defaults to the source configuration."""
    config["report_title"] = "AI 재무·세무·회계 핵심 동향 모니터링"
    config["issue_title_prefix"] = "[AI 재무·세무·회계 핵심 동향]"
    config["section_order"] = list(CORE_SECTION_ORDER)
    config["report_hour_kst"] = 7
    config["report_minute_kst"] = 30
    config["watchdog_minute_kst"] = 50
    config["max_issue_items"] = min(int(config.get("max_issue_items", 16)), 16)
    config["max_report_items"] = min(int(config.get("max_report_items", 180)), 180)
    config["min_report_score"] = max(int(config.get("min_report_score", 30)), 30)
    config["max_workers"] = min(int(config.get("max_workers", 4)), 4)
    config["critical_source_groups"] = ["뉴스·공식기관", "GitHub 고정 추적"]
    config.setdefault("core_top_limit", 10)
    config.setdefault("taxia_appendix_limit", 5)
    config["priority_policy_version"] = 3

    for row in config.get("news_queries", []):
        if row.get("name") == "DIRECT-TAXIA-CLOA":
            row["track"] = APPENDIX_TRACK
            row["direct"] = False
            row["score_boost"] = min(int(row.get("score_boost", 0)), -8)
            row["impact"] = "직접 프로젝트 변화는 참고용으로 보존하며 핵심 시장·연구·기관 동향보다 낮게 평가한다."

    for asset in config.get("github_repositories", []):
        if str(asset.get("repo", "")).lower() == "xaikorea/taxia":
            asset["track"] = APPENDIX_TRACK
            asset["direct"] = False
            asset["score_boost"] = min(int(asset.get("score_boost", 0)), -8)
            asset["baseline_commits"] = 0
            asset["baseline_issues"] = min(int(asset.get("baseline_issues", 3)), 3)
            asset["impact"] = "직접 프로젝트 변화는 부록에서만 확인하고 핵심 우선순위에는 포함하지 않는다."

    for asset in config.get("pypi_packages", []):
        if str(asset.get("package", "")).lower() == "taxia-core":
            asset["track"] = APPENDIX_TRACK
            asset["direct"] = False
            asset["score_boost"] = min(int(asset.get("score_boost", 0)), -8)
            asset["impact"] = "직접 패키지 변화는 참고용 부록으로만 보존한다."
    return config


def normalize_item(item: Any, module: Any, now: dt.datetime | None = None) -> Any:
    """Re-score historical and new items under the core-first policy."""
    now = now or dt.datetime.now(dt.timezone.utc)
    published = _parse_time(getattr(item, "published_at", ""))
    age_days = (now - published).total_seconds() / 86400 if published else 10_000
    text = f"{getattr(item, 'title', '')} {getattr(item, 'summary', '')} {getattr(item, 'status', '')}"
    score = int(getattr(item, "score", 0))
    taxia_item = is_taxia_item(item)
    baseline_item = is_baseline_item(item)
    generic_commit = is_generic_commit(item)
    noise_item = is_noise_item(item)
    weak_paper = is_weak_paper_item(item)
    demoted = taxia_item or baseline_item or generic_commit or noise_item or weak_paper

    if taxia_item:
        item.track = APPENDIX_TRACK
        item.impact = "직접 프로젝트 변화는 참고용 부록으로만 보존하며 핵심 우선순위에서는 제외한다."
        score = min(score, 29 if baseline_item or getattr(item, "kind", "") == "github_commit" else 44)
    else:
        item.impact = CORE_IMPACT.get(
            getattr(item, "category", ""),
            "재무·세무·회계 AI의 제품, 데이터, 통제 또는 평가 구조에 미치는 영향을 원문에서 검토해야 한다.",
        )

    if baseline_item or generic_commit or noise_item or weak_paper:
        score = min(score, 29)
    if getattr(item, "source_type", "") == "secondary_index":
        score = min(score, 54)
    if getattr(item, "source_type", "") == "vendor_primary":
        score = min(score, 74)

    category = getattr(item, "category", "")
    source_type = getattr(item, "source_type", "")
    kind = getattr(item, "kind", "")
    recent = age_days <= 14
    if not demoted:
        if recent and source_type == "official_primary" and category in {
            "세무 AI·조세기술", "회계 자동화·결산", "감사·내부통제·부정탐지",
            "공공 데이터·API", "AI 규제·거버넌스",
        } and _contains(text, module.REGULATORY_TERMS | module.RISK_TERMS | module.RELEASE_TERMS):
            score = max(score, 76)
        if recent and source_type == "paper_primary" and _contains(text, module.BENCHMARK_TERMS) and _contains(text, PAPER_DOMAIN_TERMS):
            score = max(score, 62)
        if recent and source_type == "vendor_primary" and _contains(text, module.RELEASE_TERMS) and _contains(text, module.DOMAIN_TERMS):
            score = max(score, 58)
        if recent and source_type in {"repository_primary", "package_primary"} and kind in {"github_release", "pypi_release"} and _contains(text, MATERIAL_REPOSITORY_TERMS):
            score = max(score, 56)

    if age_days > 90 and source_type in {"repository_primary", "package_primary"}:
        score = min(score, 34)

    item.score = max(0, min(score, 100))
    item.priority = _priority(item.score)
    return item


def verification_note(item: Any) -> str:
    source_type = getattr(item, "source_type", "")
    if source_type == "official_primary":
        return "시행일, 적용대상, 예외, 정정 여부를 1차 원문에서 확인한다."
    if source_type == "paper_primary":
        return "사전공개 여부, 데이터 공개성, 평가셋 누수, 재현성 및 독립 검증 여부를 확인한다."
    if source_type == "vendor_primary":
        return "정확도·생산성·ROI 수치는 공급업체 주장일 수 있으므로 독립 검증 자료와 실제 적용범위를 확인한다."
    if source_type in {"repository_primary", "package_primary", "repository_discovery"}:
        return "라이선스, 최근 유지보수, 보안, 테스트, 의존성, 데이터 반출 구조를 확인한다."
    return "RSS 요약이 아닌 원문과 발표기관, 실제 발표일, 수치 근거를 확인한다."


def core_sort_key(item: Any) -> tuple[Any, ...]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    published = _parse_time(getattr(item, "published_at", "")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    appendix_penalty = 1 if is_taxia_item(item) else 0
    noise_penalty = 1 if any((is_baseline_item(item), is_generic_commit(item), is_noise_item(item), is_weak_paper_item(item))) else 0
    return (
        appendix_penalty,
        noise_penalty,
        priority_rank.get(getattr(item, "priority", "P3"), 9),
        SOURCE_RANK.get(getattr(item, "source_type", ""), 9),
        TRACK_RANK.get(getattr(item, "track", ""), 9),
        -int(getattr(item, "score", 0)),
        -published.timestamp(),
        str(getattr(item, "title", "")).lower(),
    )


def _local_time(module: Any, value: str, timezone: Any) -> str:
    return module.local_date_time(value, timezone)


def render_item(module: Any, item: Any, timezone: Any, number: int) -> str:
    summary = (getattr(item, "summary", "") or "요약 없음").strip()
    if len(summary) > 1400:
        summary = summary[:1399] + "…"
    queries = ", ".join((getattr(item, "query_names", []) or [])[:8]) or "직접 API"
    return "\n".join([
        f"### {number}. [{item.title}]({item.url})",
        "",
        f"- **우선순위:** {item.priority} ({item.score}/100, 규칙 기반)",
        f"- **발표·업데이트:** {_local_time(module, item.published_at, timezone)} KST",
        f"- **영역:** {item.track} · {item.category} · {item.jurisdiction}",
        f"- **출처:** {item.source} · `{item.source_type}` · 신뢰도 {item.confidence}",
        f"- **상태:** {item.status}",
        f"- **핵심 시사점:** {item.impact}",
        f"- **검증 포인트:** {verification_note(item)}",
        f"- **수집 근거:** {item.evidence}",
        f"- **검색·추적 경로:** {queries}",
        "",
        summary,
        "",
    ])


def _metric_counts(items: list[Any]) -> dict[str, int]:
    counts = {
        "P0": 0, "P1": 0, "P2": 0, "P3": 0,
        "official": 0, "paper": 0, "vendor": 0, "open_source": 0,
        "core": 0, "appendix": 0,
    }
    for item in items:
        counts[getattr(item, "priority", "P3")] = counts.get(getattr(item, "priority", "P3"), 0) + 1
        source_type = getattr(item, "source_type", "")
        if source_type == "official_primary":
            counts["official"] += 1
        elif source_type == "paper_primary":
            counts["paper"] += 1
        elif source_type == "vendor_primary":
            counts["vendor"] += 1
        elif source_type in {"repository_primary", "package_primary", "repository_discovery"}:
            counts["open_source"] += 1
        if is_core_item(item):
            counts["core"] += 1
        if is_taxia_item(item):
            counts["appendix"] += 1
    return counts


def render_report(module: Any, *, report_date: dt.date, run_at: dt.datetime, since: dt.datetime,
                  items: list[Any], health: list[Any], timezone: Any, repository: str,
                  config: dict[str, Any]) -> str:
    sorted_items = sorted(items, key=core_sort_key)
    counts = _metric_counts(sorted_items)
    healthy = len([row for row in health if row.ok])
    failed = len(health) - healthy
    title = config.get("report_title", "AI 재무·세무·회계 핵심 동향 모니터링")
    lines = [
        f"# {title} — {report_date.isoformat()}",
        "",
        f"- **실행 시각:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST",
        f"- **신규 수집 기준:** {since.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST 이후",
        f"- **당일 누적:** {len(sorted_items)}개 · 핵심 {counts['core']}개 · 참고 부록 {counts['appendix']}개",
        f"- **우선순위:** P0 {counts['P0']} · P1 {counts['P1']} · P2 {counts['P2']} · P3 {counts['P3']}",
        f"- **근거 구성:** 공식기관 {counts['official']} · 논문 {counts['paper']} · 기업 공식 {counts['vendor']} · 오픈소스 {counts['open_source']}",
        f"- **수집 상태:** 정상 {healthy} · 실패 {failed}",
        f"- **저장소:** https://github.com/{repository}",
        "",
        "> 핵심 시장·연구·기관·데이터·법제도 변화를 우선합니다. 특정 내부 프로젝트 활동은 참고 부록으로만 보존합니다. 공급업체 수치와 사전공개 논문은 독립 검증 결과가 아닙니다.",
        "",
        "## 오늘의 핵심 변화",
        "",
    ]
    top = [item for item in sorted_items if is_core_item(item) and item.priority in {"P0", "P1"}]
    if not sorted_items:
        lines.extend([
            "**새롭거나 의미 있는 변화를 확인하지 못했습니다.** 이는 변화가 없다는 확정 결론이 아니라 설정된 공개 소스에서 신규 핵심 항목을 찾지 못했다는 뜻입니다.",
            "",
        ])
    elif top:
        for item in top[: int(config.get("core_top_limit", 10))]:
            lines.append(f"- **{item.priority}** · [{item.title}]({item.url}) — {item.impact}")
        lines.append("")
    else:
        lines.extend([
            "신규 항목은 있으나 P0·P1 핵심 기준을 충족한 변화는 없습니다. P2·P3 자료는 아래에 근거 보존용으로 정리했습니다.",
            "",
        ])

    section_order = config.get("section_order", CORE_SECTION_ORDER)
    grouped: dict[str, list[Any]] = {section: [] for section in section_order}
    for item in sorted_items[: int(config.get("max_report_items", 180))]:
        grouped.setdefault(getattr(item, "track", "기타"), []).append(item)

    number = 1
    for section in section_order:
        section_items = grouped.get(section, [])
        if section == APPENDIX_TRACK:
            section_items = section_items[: int(config.get("taxia_appendix_limit", 5))]
        lines.extend([f"## {section}", ""])
        if not section_items:
            lines.extend(["해당 섹션의 신규 핵심 항목 없음.", ""])
            continue
        for item in section_items:
            lines.append(render_item(module, item, timezone, number))
            number += 1

    extra_sections = [key for key in grouped if key not in section_order]
    for section in extra_sections:
        lines.extend([f"## {section}", ""])
        for item in grouped[section]:
            lines.append(render_item(module, item, timezone, number))
            number += 1

    lines.extend([
        "## 수집 소스 상태",
        "",
        "| 그룹 | 소스 | 상태 | 수집 건수 | 비고 |",
        "|---|---|---:|---:|---|",
    ])
    for row in sorted(health, key=lambda value: (not value.ok, value.group, value.source.lower())):
        lines.append(
            f"| {module.markdown_escape(row.group)} | {module.markdown_escape(row.source)} | "
            f"{'정상' if row.ok else '실패'} | {row.count} | {module.markdown_escape(row.detail)} |"
        )
    lines.extend([
        "",
        "## 한계와 검토 원칙",
        "",
        "- 공개 웹·RSS·API·GitHub·PyPI·arXiv에 노출되지 않은 자료는 누락될 수 있습니다.",
        "- 공급업체 성능·생산성·ROI 수치는 독립 평가가 아니라 자체 주장일 수 있습니다.",
        "- 논문은 평가셋 공개성, 재현성, 데이터 누수와 후속 검증 여부를 확인해야 합니다.",
        "- 오픈소스는 라이선스, 보안, 유지보수, 테스트, 데이터 반출 구조를 별도로 확인해야 합니다.",
        "- 자동 분류와 우선순위는 탐지용이며 최종 재무·세무·회계·법률 판단이 아닙니다.",
        "",
    ])
    return "\n".join(lines)


def render_issue_body(module: Any, *, report_date: dt.date, run_at: dt.datetime, items: list[Any],
                      health: list[Any], timezone: Any, repository: str, report_path: str,
                      config: dict[str, Any]) -> str:
    sorted_items = sorted(items, key=core_sort_key)
    counts = _metric_counts(sorted_items)
    report_url = f"https://github.com/{repository}/blob/main/{report_path}"
    lines = [
        f"# {report_date.isoformat()} AI 재무·세무·회계 핵심 동향",
        "",
        f"**실행:** {run_at.astimezone(timezone).strftime('%Y-%m-%d %H:%M:%S')} KST  ",
        f"**핵심/전체:** {counts['core']} / {len(sorted_items)}개  ",
        f"**근거:** 공식 {counts['official']} · 논문 {counts['paper']} · 기업 공식 {counts['vendor']} · 오픈소스 {counts['open_source']}  ",
        f"**전체 보고서:** [{report_path}]({report_url})",
        "",
        "## 우선 검토",
        "",
    ]
    issue_items = [item for item in sorted_items if is_core_item(item) and item.priority in {"P0", "P1"}]
    if not issue_items:
        issue_items = [item for item in sorted_items if is_core_item(item)][:5]
    if not issue_items:
        lines.extend(["새롭거나 의미 있는 핵심 변화가 확인되지 않았습니다.", ""])
    else:
        for item in issue_items[: int(config.get("max_issue_items", 16))]:
            lines.extend([
                f"- **{item.priority}** · **{item.track}/{item.category}** · [{item.title}]({item.url})",
                f"  - 발표·업데이트: {_local_time(module, item.published_at, timezone)} KST",
                f"  - 핵심 시사점: {item.impact}",
                f"  - 출처: {item.source} · 신뢰도 {item.confidence} · 상태 {item.status}",
                f"  - 검증: {verification_note(item)}",
            ])
    failed = [row for row in health if not row.ok]
    lines.extend([
        "",
        "## 수집 상태",
        "",
        f"정상 {len(health) - len(failed)}개 / 실패 {len(failed)}개",
    ])
    for row in failed[:20]:
        lines.append(f"- 실패 · **{row.group}/{row.source}** — {row.detail}")
    lines.extend([
        "",
        "> 특정 프로젝트 활동은 핵심 목록에서 제외하고 참고 부록으로만 보존합니다. 수치·시행일·라이선스·적용범위는 원문 검토가 필요합니다.",
        "",
    ])
    body = "\n".join(lines)
    if len(body) > 62000:
        body = body[:61500] + f"\n\n본문이 길어 잘렸습니다. [전체 보고서]({report_url})를 확인하십시오.\n"
    return body


def tune_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    original = path.read_text(encoding="utf-8")
    config = json.loads(original)
    tuned = apply_core_first_policy(config)
    rendered = json.dumps(tuned, ensure_ascii=False, indent=2) + "\n"
    if original != rendered:
        path.write_text(rendered, encoding="utf-8")
        print("Applied core-first monitoring policy.")
    else:
        print("Core-first monitoring policy already applied.")
    return tuned


def patch_monitor(module: Any) -> None:
    original_merge = module.merge_duplicate_items

    def normalized_merge(items: Iterable[Any]) -> list[Any]:
        merged = original_merge(items)
        return [normalize_item(item, module) for item in merged]

    module.merge_duplicate_items = normalized_merge
    module.item_sort_key = core_sort_key
    module.render_item = lambda item, timezone, number: render_item(module, item, timezone, number)
    module.render_report = lambda **kwargs: render_report(module, **kwargs)
    module.render_issue_body = lambda **kwargs: render_issue_body(module, **kwargs)


def main() -> int:
    tune_config()
    import finance_monitor
    patch_monitor(finance_monitor)
    return finance_monitor.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
