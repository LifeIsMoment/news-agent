#!/usr/bin/env python3
"""Evaluate and safely tune the AI finance/tax/accounting monitor.

The optimizer is deliberately bounded. It may tune documented configuration
knobs and one workflow timeout, but it never invents arbitrary code patches.
Every proposed change is written to a branch and validated before merge.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

UTC = dt.timezone.utc
PRIMARY_TYPES = {"official_primary", "paper_primary", "vendor_primary", "repository_primary", "package_primary"}
OPEN_SOURCE_TYPES = {"repository_primary", "package_primary", "repository_discovery"}
APPENDIX_TRACK = "참고: TAXiA·CLOA 직접 관련"
NOISE_MARKERS = {
    "채용", "모집", "입찰", "webinar", "conference", "award", "sponsorship",
    "sports", "football", "baseball", "casino", "crypto price", "stock price",
    "cosmetic", "skincare", "dating", "ai companion",
}
GENERIC_COMMIT_MARKERS = {"readme", "docs", "style", "chore", "typo", "merge pull request", "bump version", "lint", "format"}
MATERIAL_MARKERS = {"benchmark", "dataset", "tax", "vat", "accounting", "audit", "invoice", "ocr", "xbrl", "agent", "mcp", "internal control"}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_taxia(item: dict[str, Any]) -> bool:
    text = " ".join([
        str(item.get("track", "")), str(item.get("title", "")), str(item.get("source", "")),
        " ".join(str(v) for v in item.get("query_names", []) or []),
    ]).lower()
    return any(token in text for token in ("taxia", "택시아", "taxia-core", "xaikorea", "cloa engine", "cloa 엔진"))


def is_baseline(item: dict[str, Any]) -> bool:
    text = f"{item.get('title', '')} {item.get('status', '')} {item.get('summary', '')}".lower()
    return "기준선" in text or "baseline" in text


def is_generic_commit(item: dict[str, Any]) -> bool:
    if item.get("kind") != "github_commit":
        return False
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(term in text for term in GENERIC_COMMIT_MARKERS) and not any(term in text for term in MATERIAL_MARKERS)


def is_noise(item: dict[str, Any]) -> bool:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    return any(term in text for term in NOISE_MARKERS) or is_generic_commit(item)


def is_core(item: dict[str, Any]) -> bool:
    return not is_taxia(item) and not is_baseline(item) and not is_noise(item)


def item_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    priority = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(item.get("priority"), 9)
    source = {
        "official_primary": 0, "paper_primary": 1, "vendor_primary": 2,
        "package_primary": 3, "repository_primary": 4,
        "repository_discovery": 5, "secondary_index": 6,
    }.get(item.get("source_type"), 9)
    published = parse_time(item.get("published_at")) or dt.datetime.min.replace(tzinfo=UTC)
    return (1 if is_taxia(item) else 0, 1 if is_baseline(item) else 0, priority, source, -int(item.get("score", 0)), -published.timestamp())


def recent_report_paths(root: Path, days: int) -> list[Path]:
    files = sorted(root.glob("*/*/*.json"))
    return files[-max(1, days):]


def load_reports(root: Path, days: int) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in recent_report_paths(root, days):
        payload = load_json(path, {})
        if payload:
            reports.append(payload)
    return reports


def ratio(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


@dataclasses.dataclass
class QualityMetrics:
    reports: int
    items: int
    top_count: int
    top_core_purity: float
    primary_evidence_share: float
    official_or_paper_share: float
    taxia_top_share: float
    baseline_top_share: float
    noise_top_share: float
    health_rate: float
    category_coverage: int
    actionable_core_items: int
    official_items: int
    paper_items: int
    vendor_items: int
    open_source_items: int
    secondary_items: int
    quality_score: int
    pipeline_success_rate: float
    pipeline_average_minutes: float
    pipeline_timed_out: int

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def pipeline_metrics(payload: dict[str, Any]) -> tuple[float, float, int]:
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    runs = [row for row in runs if row.get("conclusion")]
    if not runs:
        return 1.0, 0.0, 0
    success = sum(1 for row in runs if row.get("conclusion") == "success")
    durations: list[float] = []
    for row in runs:
        start = parse_time(row.get("run_started_at") or row.get("created_at"))
        end = parse_time(row.get("updated_at"))
        if start and end and end >= start:
            durations.append((end - start).total_seconds() / 60)
    timed_out = sum(1 for row in runs if row.get("conclusion") == "timed_out")
    return round(success / len(runs), 4), round(sum(durations) / len(durations), 2) if durations else 0.0, timed_out


def calculate_metrics(reports: list[dict[str, Any]], workflow_runs: dict[str, Any]) -> QualityMetrics:
    all_items: list[dict[str, Any]] = []
    health_rows: list[dict[str, Any]] = []
    for report in reports:
        all_items.extend(row for row in report.get("items", []) if isinstance(row, dict))
        health_rows.extend(row for row in report.get("health", []) if isinstance(row, dict))
    latest_items = [row for row in (reports[-1].get("items", []) if reports else []) if isinstance(row, dict)]
    top = sorted(latest_items, key=item_sort_key)[:20]
    core_top = [item for item in top if is_core(item)]
    primary_top = [item for item in top if item.get("source_type") in PRIMARY_TYPES]
    official_paper_top = [item for item in top if item.get("source_type") in {"official_primary", "paper_primary"}]
    categories = {item.get("category") for item in core_top if item.get("category")}
    actionable = [item for item in latest_items if is_core(item) and item.get("priority") in {"P0", "P1"}]
    source_counts = Counter(item.get("source_type") for item in all_items)
    health_ok = sum(1 for row in health_rows if row.get("ok") is True)
    pipeline_success, pipeline_minutes, timed_out = pipeline_metrics(workflow_runs)

    top_count = len(top)
    purity = ratio(len(core_top), top_count)
    primary_share = ratio(len(primary_top), top_count)
    official_paper_share = ratio(len(official_paper_top), top_count)
    taxia_share = ratio(sum(1 for item in top if is_taxia(item)), top_count)
    baseline_share = ratio(sum(1 for item in top if is_baseline(item)), top_count)
    noise_share = ratio(sum(1 for item in top if is_noise(item)), top_count)
    health_rate = ratio(health_ok, len(health_rows)) if health_rows else 1.0

    score = 0
    score += round(purity * 30)
    score += round(primary_share * 20)
    score += round(official_paper_share * 15)
    score += round(health_rate * 15)
    score += min(len(categories), 6) * 2
    score += min(len(actionable), 8)
    score -= round(taxia_share * 15)
    score -= round(baseline_share * 10)
    score -= round(noise_share * 15)
    score = max(0, min(score, 100))

    return QualityMetrics(
        reports=len(reports), items=len(latest_items), top_count=top_count,
        top_core_purity=purity, primary_evidence_share=primary_share,
        official_or_paper_share=official_paper_share, taxia_top_share=taxia_share,
        baseline_top_share=baseline_share, noise_top_share=noise_share,
        health_rate=health_rate, category_coverage=len(categories),
        actionable_core_items=len(actionable),
        official_items=source_counts.get("official_primary", 0),
        paper_items=source_counts.get("paper_primary", 0),
        vendor_items=source_counts.get("vendor_primary", 0),
        open_source_items=sum(source_counts.get(key, 0) for key in OPEN_SOURCE_TYPES),
        secondary_items=source_counts.get("secondary_index", 0),
        quality_score=score, pipeline_success_rate=pipeline_success,
        pipeline_average_minutes=pipeline_minutes, pipeline_timed_out=timed_out,
    )


def find_safe_noise_by_query(items: list[dict[str, Any]], safe_terms: Iterable[str]) -> dict[str, set[str]]:
    low_hits: dict[str, Counter[str]] = defaultdict(Counter)
    high_hits: dict[str, set[str]] = defaultdict(set)
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        queries = [str(value) for value in item.get("query_names", []) or []]
        for term in safe_terms:
            token = str(term).lower()
            if token not in text:
                continue
            for query in queries:
                if is_core(item) and item.get("priority") in {"P0", "P1"}:
                    high_hits[query].add(token)
                elif item.get("priority") in {"P2", "P3"}:
                    low_hits[query][token] += 1
    additions: dict[str, set[str]] = defaultdict(set)
    for query, counter in low_hits.items():
        for term, count in counter.items():
            if count >= 2 and term not in high_hits.get(query, set()):
                additions[query].add(term)
    return additions


def set_if_changed(obj: dict[str, Any], key: str, value: Any, changes: list[str]) -> None:
    if obj.get(key) != value:
        changes.append(f"{key}: {obj.get(key)!r} → {value!r}")
        obj[key] = value


def propose_config(config: dict[str, Any], policy: dict[str, Any], metrics: QualityMetrics,
                   latest_items: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    proposed = copy.deepcopy(config)
    changes: list[str] = []
    thresholds = policy.get("thresholds", {})

    target_issue_items = max(10, min(16, metrics.actionable_core_items + 4))
    set_if_changed(proposed, "max_issue_items", target_issue_items, changes)
    set_if_changed(proposed, "max_report_items", 180, changes)

    current_min = int(proposed.get("min_report_score", 30))
    if metrics.top_core_purity < float(thresholds.get("min_top_core_purity", 0.85)) or metrics.noise_top_share > float(thresholds.get("max_noise_top_share", 0.05)):
        target_min = min(40, current_min + 2)
    elif metrics.top_core_purity >= 0.95 and metrics.actionable_core_items < 4:
        target_min = max(30, current_min - 1)
    else:
        target_min = max(30, current_min)
    set_if_changed(proposed, "min_report_score", target_min, changes)

    workers = int(proposed.get("max_workers", 8))
    if metrics.health_rate < float(thresholds.get("min_health_rate", 0.90)) or metrics.pipeline_success_rate < 0.80:
        set_if_changed(proposed, "max_workers", max(4, workers - 1), changes)

    set_if_changed(proposed, "core_top_limit", 10, changes)
    set_if_changed(proposed, "taxia_appendix_limit", 5, changes)
    set_if_changed(proposed, "priority_policy_version", 2, changes)

    for row in proposed.get("news_queries", []):
        if row.get("name") == "DIRECT-TAXIA-CLOA":
            set_if_changed(row, "track", APPENDIX_TRACK, changes)
            set_if_changed(row, "direct", False, changes)
            set_if_changed(row, "score_boost", min(int(row.get("score_boost", 0)), -8), changes)

    for asset in proposed.get("github_repositories", []):
        if str(asset.get("repo", "")).lower() == "xaikorea/taxia":
            set_if_changed(asset, "track", APPENDIX_TRACK, changes)
            set_if_changed(asset, "direct", False, changes)
            set_if_changed(asset, "score_boost", min(int(asset.get("score_boost", 0)), -8), changes)
            set_if_changed(asset, "baseline_commits", 0, changes)
            set_if_changed(asset, "baseline_issues", min(int(asset.get("baseline_issues", 3)), 3), changes)

    safe_terms = policy.get("safe_noise_terms", sorted(NOISE_MARKERS))
    additions = find_safe_noise_by_query(latest_items, safe_terms)
    for row in proposed.get("news_queries", []):
        name = row.get("name")
        if name not in additions:
            continue
        existing = {str(value).lower() for value in row.get("exclude_any", [])}
        new_terms = sorted(term for term in additions[name] if term not in existing)
        if new_terms:
            row["exclude_any"] = sorted(set(row.get("exclude_any", [])) | set(new_terms), key=str.lower)
            changes.append(f"{name}.exclude_any += {new_terms}")
            old_boost = int(row.get("score_boost", 0))
            new_boost = max(-8, old_boost - 1)
            if new_boost != old_boost:
                row["score_boost"] = new_boost
                changes.append(f"{name}.score_boost: {old_boost} → {new_boost}")
    return proposed, changes


def propose_workflow(workflow_text: str, metrics: QualityMetrics) -> tuple[str, list[str]]:
    changes: list[str] = []
    proposed = workflow_text
    match = re.search(r"(?m)^(\s*timeout-minutes:\s*)(\d+)\s*$", workflow_text)
    if match and metrics.pipeline_timed_out >= 2:
        current = int(match.group(2))
        target = min(60, current + 5)
        if target != current:
            proposed = workflow_text[:match.start(2)] + str(target) + workflow_text[match.end(2):]
            changes.append(f"workflow timeout-minutes: {current} → {target}")
    return proposed, changes


def render_quality_report(date: str, metrics: QualityMetrics, config_changes: list[str],
                          workflow_changes: list[str], recommendations: list[str]) -> str:
    lines = [
        f"# AI 재무·세무·회계 모니터 품질 분석 — {date}", "",
        f"- **종합 품질점수:** {metrics.quality_score}/100",
        f"- **상위 20개 핵심 순도:** {metrics.top_core_purity:.1%}",
        f"- **상위 20개 1차 근거 비율:** {metrics.primary_evidence_share:.1%}",
        f"- **상위 20개 공식기관·논문 비율:** {metrics.official_or_paper_share:.1%}",
        f"- **상위 20개 특정 프로젝트 비율:** {metrics.taxia_top_share:.1%}",
        f"- **상위 20개 기준선·노이즈 비율:** {metrics.baseline_top_share:.1%} / {metrics.noise_top_share:.1%}",
        f"- **소스 건강도:** {metrics.health_rate:.1%}",
        f"- **파이프라인 성공률·평균 실행시간:** {metrics.pipeline_success_rate:.1%} · {metrics.pipeline_average_minutes:.1f}분",
        f"- **핵심 카테고리 커버리지:** {metrics.category_coverage}개",
        "", "## 자동 변경안", "",
    ]
    changes = config_changes + workflow_changes
    if changes:
        lines.extend(f"- {change}" for change in changes)
    else:
        lines.append("- 안전 범위 내 자동 변경 필요 없음")
    lines.extend(["", "## 개선 권고", ""])
    lines.extend(f"- {item}" for item in recommendations)
    lines.extend([
        "", "## 안전 경계", "",
        "- 자동 병합은 설정값, 노이즈 제외어, 작업자 수, 보고서 한도와 워크플로 timeout의 제한된 변경에만 허용합니다.",
        "- 수집기 알고리즘, 출처 삭제, 법적 판단 로직, 임의 코드 생성은 자동 병합하지 않습니다.",
        "- 변경 전 Python 구문, JSON, 전체 재무 모니터 단위 테스트를 통과해야 합니다.",
        "",
    ])
    return "\n".join(lines)


def recommendations_for(metrics: QualityMetrics, policy: dict[str, Any]) -> list[str]:
    threshold = policy.get("thresholds", {})
    result: list[str] = []
    if metrics.top_core_purity < float(threshold.get("min_top_core_purity", 0.85)):
        result.append("상위 항목의 핵심 순도가 낮다. 검색군별 오탐 제목과 저품질 커밋을 추가 분석한다.")
    if metrics.official_or_paper_share < float(threshold.get("min_official_or_paper_share", 0.25)):
        result.append("공식기관·논문 근거 비중이 낮다. 기관별 RSS·API와 학술 검색군을 확장한다.")
    if metrics.paper_items == 0:
        result.append("최근 분석기간에 논문·벤치마크가 없다. arXiv 검색식과 신규 벤치마크 저장소를 검토한다.")
    if metrics.category_coverage < int(threshold.get("min_category_coverage", 4)):
        result.append("핵심 업무군 커버리지가 좁다. 세무, 회계, 감사, 재무, 문서 AI, 공공 API 검색 균형을 점검한다.")
    if metrics.health_rate < float(threshold.get("min_health_rate", 0.9)):
        result.append("수집 소스 건강도가 낮다. 실패 소스의 응답코드·타임아웃·대체 출처를 점검한다.")
    if metrics.pipeline_success_rate < 0.9:
        result.append("최근 Actions 성공률이 낮다. 실패 로그와 push 충돌, API 한도, 실행시간을 확인한다.")
    if not result:
        result.append("현재 핵심 순도와 파이프라인 상태가 정책 기준을 충족한다. 신규 출처 발견과 장기 회귀만 계속한다.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finance monitor quality and safe auto-tuning")
    parser.add_argument("--reports-dir", default="reports-finance-tax-ai")
    parser.add_argument("--config", default="config/finance_sources.json")
    parser.add_argument("--policy", default="config/finance_quality_policy.json")
    parser.add_argument("--workflow-file", default=".github/workflows/daily-finance-tax-ai-monitor.yml")
    parser.add_argument("--workflow-runs", default="out-finance-quality/workflow-runs.json")
    parser.add_argument("--state-file", default=".monitor/finance-quality-state.json")
    parser.add_argument("--quality-report-dir", default="quality-reports-finance-tax-ai")
    parser.add_argument("--output-dir", default="out-finance-quality")
    parser.add_argument("--now", help="ISO timestamp for deterministic tests")
    args = parser.parse_args(argv)

    now = parse_time(args.now) if args.now else dt.datetime.now(UTC)
    assert now is not None
    policy = load_json(Path(args.policy), {})
    reports = load_reports(Path(args.reports_dir), int(policy.get("lookback_days", 7)))
    workflow_runs = load_json(Path(args.workflow_runs), {})
    metrics = calculate_metrics(reports, workflow_runs)
    config = load_json(Path(args.config), {})
    latest_items = [row for row in (reports[-1].get("items", []) if reports else []) if isinstance(row, dict)]
    proposed_config, config_changes = propose_config(config, policy, metrics, latest_items)
    workflow_text = Path(args.workflow_file).read_text(encoding="utf-8")
    proposed_workflow, workflow_changes = propose_workflow(workflow_text, metrics)
    recommendations = recommendations_for(metrics, policy)

    date = now.date().isoformat()
    report_text = render_quality_report(date, metrics, config_changes, workflow_changes, recommendations)
    quality_path = Path(args.quality_report_dir) / str(now.year) / f"{now.month:02d}" / f"{date}.md"
    quality_path.parent.mkdir(parents=True, exist_ok=True)
    quality_path.write_text(report_text, encoding="utf-8")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "metrics.json", metrics.to_dict())
    save_json(out / "proposed-config.json", proposed_config)
    (out / "proposed-workflow.yml").write_text(proposed_workflow, encoding="utf-8")

    changed_config = proposed_config != config
    changed_workflow = proposed_workflow != workflow_text
    max_changes = int(policy.get("auto_merge", {}).get("max_changes", 14))
    critical = metrics.health_rate < 0.70 or metrics.pipeline_success_rate < 0.50
    auto_merge = bool(policy.get("auto_merge", {}).get("enabled", True)) and not critical and len(config_changes + workflow_changes) <= max_changes
    decision = {
        "date": date, "changed": changed_config or changed_workflow,
        "changed_config": changed_config, "changed_workflow": changed_workflow,
        "auto_merge_eligible": auto_merge,
        "quality_score": metrics.quality_score,
        "config_changes": config_changes, "workflow_changes": workflow_changes,
        "quality_report_path": quality_path.as_posix(),
    }
    save_json(out / "decision.json", decision)

    pr_lines = [
        f"## AI 재무·세무·회계 모니터 자동 품질 개선 — {date}", "",
        f"- 품질점수: **{metrics.quality_score}/100**",
        f"- 상위 핵심 순도: **{metrics.top_core_purity:.1%}**",
        f"- 소스 건강도: **{metrics.health_rate:.1%}**", "",
        "### 변경", "",
    ]
    pr_lines.extend(f"- {change}" for change in (config_changes + workflow_changes) or ["변경 없음"])
    pr_lines.extend(["", "### 검증", "", "- Python 구문 검사", "- JSON 설정 검사", "- `test_finance*.py` 전체 단위 테스트", "- 변경 파일 allowlist 및 변경 개수 제한", ""])
    (out / "pr_body.md").write_text("\n".join(pr_lines), encoding="utf-8")
    (out / "issue_title.txt").write_text(f"[AI 재무·세무·회계 품질] {date}\n", encoding="utf-8")
    (out / "issue_body.md").write_text(report_text[:60000], encoding="utf-8")
    (out / "summary.md").write_text(report_text[:60000], encoding="utf-8")

    state_path = Path(args.state_file)
    state = load_json(state_path, {"history": []})
    history = list(state.get("history", []))
    history.append({"date": date, **metrics.to_dict(), "changed": decision["changed"]})
    state["history"] = history[-30:]
    state["last_run_at"] = now.isoformat().replace("+00:00", "Z")
    state["last_quality_score"] = metrics.quality_score
    save_json(state_path, state)

    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
